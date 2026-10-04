"""Orquestador de IA multi-proveedor — fachada pública del sistema.

``AIEngine`` es la única clase que usa el resto de Da Vinci Studio para
interactuar con los modelos de IA. **Su API pública permanece exactamente
igual** que en versiones anteriores (compatibilidad 100% hacia atrás).

Internamente delega todo el ciclo de vida:

* Construcción de providers  →  :class:`core.providers.factory.ProviderFactory`
* Ejecución con fallback     →  :class:`core.providers.factory.FallbackChainExecutor`
* Parseo final JSON/YouTube  →  lógica local idéntica a siempre (extracción
  robusta de JSON con balanceo de llaves, soporte markdown `` ```json ``).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import yaml

from .providers import (
    BaseProvider,
    FallbackChainExecutor,
    ProviderFactory,
    ProviderResponse,
)


_LOG = logging.getLogger(__name__)


# Valores seguros usados como último recurso si el yaml no existe o está
# irrecuperablemente corrupto.
_DEFAULT_AI_CFG: dict[str, Any] = {
    "default_provider": "ollama",
    "timeout": 600,
    "max_retries": 3,
    "temperature": 0.2,
    "fallback_chain": ["ollama"],
    "providers": {
        "ollama": {
            "enabled": True,
            "url": "http://localhost:11434",
            "model": "llama3",
            "system_prompt": (
                "Eres un experto en SEO para YouTube especializado en "
                "contenido de habla hispana. Responde en español, con "
                "precisión y creatividad sin inventar datos."
            ),
        },
    },
}


class AIEngine:
    """Fachada IA pública (multi-proveedor + fallback chain, 100% compatible).

    Atributos legacy (no rompen código viejo):
        base_url  – URL del proveedor *por defecto* (para ``ai.base_url``).
        model     – Nombre del modelo del proveedor por defecto.
        settings  – YAML entero cargado (tal cual).

    Métodos públicos (fijos):
        generate(prompt, system=None) -> str
        generate_youtube_metadata(transcript, filename=None) -> dict
        available_providers() -> list[str]
        provider_status() -> dict
    """

    # ------------------------------------------------------------------
    # Constructor (COMPATIBLE HACIA ATRÁS — FIRMA FIJA)
    # ------------------------------------------------------------------
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        config_path: str | Path | None = None,
    ) -> None:
        # ``base_url`` y ``model`` son los parámetros legacy. Si se pasan,
        # se aplican como overrides **al proveedor ollama** (es el que usaba
        # el sistema antiguo) para no romper código que escribía:
        #     ai = AIEngine("http://mi-ollama:11434", "llama3.1:8b")
        self._legacy_overrides: dict[str, Any] = {}
        if base_url is not None:
            self._legacy_overrides["url"] = base_url
            self._legacy_overrides["base_url"] = base_url
        if model is not None:
            self._legacy_overrides["model"] = model

        # --- Carga YAML --------------------------------------------------
        if config_path is None:
            root = Path(__file__).resolve().parents[1]
            user_cfg = root / "config" / "settings.user.yaml"
            config_path = user_cfg if user_cfg.exists() else root / "config" / "settings.yaml"
        self._config_path = Path(config_path)
        self._settings: dict[str, Any] = self._load_settings(self._config_path)

        # --- Construcción bloque ``ai:`` ---------------------------------
        ai_cfg = (
            self._settings.get("ai")
            or self._settings.get("models", {}).get("ollama")
            or {}
        )
        # Si el yaml venía en formato viejo (sólo ``models.ollama.*``), lo
        # migramos automáticamente al nuevo esquema ``ai.providers.ollama.*``
        if "providers" not in ai_cfg:
            ai_cfg = self._merge_legacy_ai_cfg(ai_cfg)
        self.ai_cfg: dict[str, Any] = ai_cfg or dict(_DEFAULT_AI_CFG)

        # --- Construcción providers via ProviderFactory -----------------
        self._factory: ProviderFactory = ProviderFactory()
        self._providers: dict[str, BaseProvider] = {}
        self._provider_errors: dict[str, str] = {}
        self._build_providers()

        # --- FallbackChainExecutor (orquesta + fallback) ----------------
        default_name = str(
            self.ai_cfg.get("default_provider") or "ollama"
        ).strip().lower()
        fallback = self.ai_cfg.get("fallback_chain") or []
        fallback_list = (
            list(fallback) if isinstance(fallback, (list, tuple)) else [fallback]
        )
        self._executor: FallbackChainExecutor = FallbackChainExecutor(
            providers=self._providers,
            default_provider_name=default_name,
            fallback_chain=[str(x).strip() for x in fallback_list],
            logger=_LOG,
        )

        # --- Atributos legacy públicos (compatibilidad) -----------------
        default_provider = self._providers.get(default_name) or (
            next(iter(self._providers.values())) if self._providers else None
        )
        if default_provider is not None:
            cfg = default_provider.config
            self.base_url = cfg.base_url or cfg.url or ""
            self.model = cfg.model
        else:
            self.base_url = base_url or ""
            self.model = model or ""
        self.settings = self._settings

    # ------------------------------------------------------------------
    # Carga YAML
    # ------------------------------------------------------------------
    @staticmethod
    def _load_settings(config_path: str | Path) -> dict[str, Any]:
        config_path = Path(config_path)
        if not config_path.exists():
            _LOG.warning(
                "AIEngine: no existe %s; usando defaults internos (sólo Ollama).",
                config_path,
            )
            return {"ai": dict(_DEFAULT_AI_CFG)}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if not isinstance(loaded, dict):
                raise ValueError("settings.yaml debe contener un diccionario en su raíz.")
            return loaded
        except (OSError, yaml.YAMLError, ValueError) as exc:
            _LOG.error(
                "AIEngine: no se pudo leer %s (%s: %s). Usando defaults.",
                config_path.name,
                type(exc).__name__,
                exc,
            )
            return {"ai": dict(_DEFAULT_AI_CFG)}

    def _merge_legacy_ai_cfg(self, legacy: dict[str, Any]) -> dict[str, Any]:
        """Migración automática del formato YAML antiguo al actual."""
        merged: dict[str, Any] = {
            "default_provider": "ollama",
            "timeout": self._settings.get("ai", {}).get(
                "timeout",
                self._settings.get("ai", {}).get("request_timeout", 600),
            ),
            "max_retries": self._settings.get("ai", {}).get("max_retries", 3),
            "temperature": self._settings.get("ai", {}).get("temperature", 0.2),
            "fallback_chain": ["ollama"],
            "providers": {
                "ollama": {
                    "enabled": True,
                    "url": legacy.get("url", "http://localhost:11434"),
                    "model": legacy.get("model", "llama3"),
                    "system_prompt": _DEFAULT_AI_CFG["providers"]["ollama"][
                        "system_prompt"
                    ],
                },
            },
        }
        if self._legacy_overrides:
            merged["providers"]["ollama"].update(self._legacy_overrides)
        return merged

    # ------------------------------------------------------------------
    # Build de providers
    # ------------------------------------------------------------------
    def _build_providers(self) -> None:
        """Construye el ``default_provider`` y la ``fallback_chain``.

        No hace expansión de variables hasta el momento de construir cada
        provider (``ProviderConfig.from_dict`` lo hace individualmente).
        Así es seguro tener providers ``enabled:false`` referenciando
        ``${API_KEY}`` sin que la falta de esa variable rompa el arranque.
        """
        ai_cfg = self.ai_cfg or {}
        providers_cfg: dict[str, Any] = ai_cfg.get("providers") or {}
        default_name = str(
            ai_cfg.get("default_provider") or "ollama"
        ).strip().lower()
        fallback = ai_cfg.get("fallback_chain") or []
        if not isinstance(fallback, (list, tuple)):
            fallback = [fallback]

        desired_names: list[str] = []
        if default_name:
            desired_names.append(default_name)
        for name in fallback:
            sname = str(name).strip().lower()
            if sname and sname not in desired_names:
                desired_names.append(sname)

        # Aplica overrides legacy (si vinieron) al provider "ollama"
        if self._legacy_overrides and "ollama" in providers_cfg:
            providers_cfg["ollama"] = {
                **providers_cfg["ollama"],
                **self._legacy_overrides,
            }

        for name in desired_names:
            raw_cfg = providers_cfg.get(name)
            if not isinstance(raw_cfg, dict):
                self._provider_errors[name] = (
                    f"No existe ai.providers.{name} en settings.yaml."
                )
                continue
            try:
                self._providers[name] = self._factory.build(
                    name, raw_cfg, ai_root_cfg=ai_cfg
                )
                _LOG.info(
                    "AIEngine: inicializado provider [%s] modelo=%s",
                    name,
                    self._providers[name].model,
                )
            except Exception as exc:  # noqa: BLE001
                self._provider_errors[name] = f"{type(exc).__name__}: {exc}"
                _LOG.warning(
                    "AIEngine: no se pudo inicializar provider [%s]: %s",
                    name,
                    exc,
                )

    # ------------------------------------------------------------------
    # API PÚBLICA (fija, NO CAMBIAR las firmas)
    # ------------------------------------------------------------------
    def available_providers(self) -> list[str]:
        """Lista de nombres de providers construidos y operativos."""
        return sorted(self._providers.keys())

    def provider_status(self) -> dict[str, Any]:
        """Resumen para logs/UI: disponibles, default, fallback, errores."""
        return {
            "available": self.available_providers(),
            "default_provider": self.ai_cfg.get("default_provider"),
            "fallback_chain": self.ai_cfg.get("fallback_chain"),
            "errors": dict(self._provider_errors),
        }

    def generate(self, prompt: str, system: str | None = None) -> str:
        """Envía un prompt, con fallback automático.

        Compatibilidad: **exactamente la misma firma** histórica (``prompt``
        y opcionalmente ``system``). Devuelve un ``str`` con texto plano.

        Eleva ``RuntimeError`` si TODOS los providers fallaron (con histórico).
        """
        resp: ProviderResponse = self._executor.execute(
            prompt=prompt, system_prompt=system, json_mode=False
        )
        self._log_resp(resp)
        return resp.text

    # ------------------------------------------------------------------
    # Pipeline YouTube (extracción + parseo JSON robusto)
    # ------------------------------------------------------------------
    def generate_youtube_metadata(
        self, transcript: str, filename: str | None = None
    ) -> dict[str, Any]:
        """Genera la estructura final de metadatos YouTube a partir de una transcripción.

        Devuelve dict con ``titulo``, ``descripcion``, ``capitulos``,
        ``respuesta_cruda`` y ``generado_en_epoch``.
        """
        prompt = self._build_prompt(transcript, filename=filename)
        raw = self.generate(prompt)
        return self._parse_response(raw)

    def _build_prompt(self, transcript: str, filename: str | None = None) -> str:
        context = (
            f"Nombre del archivo multimedia: {filename}\n" if filename else ""
        )
        temperature_hint = ""
        t = self.ai_cfg.get("temperature")
        if t is not None:
            temperature_hint = (
                f"\n\n[Instrucción de temperatura/creatividad: {float(t):.2f}]\n"
            )
        return (
            "Eres un experto en YouTube SEO. A partir de la siguiente "
            "transcripción y del nombre del archivo, genera un JSON válido "
            "con esta estructura exacta:\n"
            "{\n"
            '  "titulo": "Título atractivo, claro y optimizado para SEO",\n'
            '  "descripcion": "Descripción larga, detallada, con palabras '
            'clave, hashtags y un CTA claro",\n'
            '  "capitulos": [\n'
            '    {"inicio": "0:00", "titulo": "Emoji Título del capítulo"},\n'
            "    ...\n"
            "  ]\n"
            "}\n\n"
            "Reglas estrictas:\n"
            "- Responde ÚNICAMENTE con el objeto JSON. No añadas texto extra.\n"
            "- El título y la descripción deben estar en español.\n"
            "- El título debe reflejar el contenido REAL de la transcripción.\n"
            "- La descripción debe tener al menos 150 palabras, incluir "
            "palabras clave, hashtags (#) y un CTA.\n"
            "- Si la transcripción menciona una canción, artista o tema "
            "conocido, inclúyelo en el título.\n"
            "- Los capítulos deben usar emojis y marcas de tiempo reales "
            "(MM:SS o HH:MM:SS).\n"
            "- No inventes capítulos ni frases que no aparezcan en la "
            "transcripción.\n\n"
            f"{context}{temperature_hint}Transcripción:\n{transcript}"
        )

    # ------------------------------------------------------------------
    # Extracción robusta de JSON + parseo
    # ------------------------------------------------------------------
    def _extract_json(self, raw: str) -> dict[str, Any]:
        """Extrae el primer objeto JSON válido de una respuesta.

        Maneja:
          - Bloques markdown ```json ... ```
          - Llaves ``{...}`` anidadas (incluyendo llaves DENTRO de strings)
          - Respuesta vacía o sin JSON  → devuelve dict vacío
        """
        if not raw:
            return {}

        match = re.search(
            r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE
        )
        candidates: list[str] = []
        if match:
            candidates.append(match.group(1).strip())

        start = raw.find("{")
        if start != -1:
            candidates.append(raw[start:])

        for text in candidates:
            if not text:
                continue
            depth = 0
            start_idx = -1
            in_string = False
            escape = False
            for idx, ch in enumerate(text):
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    if depth == 0:
                        start_idx = idx
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and start_idx != -1:
                        candidate = text[start_idx : idx + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            start_idx = -1
                            continue
        return {}

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Normaliza la respuesta del modelo a la estructura final YouTube."""
        data = self._extract_json(raw)
        chapters = data.get("capitulos") or data.get("chapters") or []
        if not isinstance(chapters, list):
            chapters = []
        return {
            "titulo": str(
                data.get("titulo") or data.get("title") or ""
            ).strip(),
            "descripcion": str(
                data.get("descripcion") or data.get("description") or ""
            ).strip(),
            "capitulos": chapters,
            "respuesta_cruda": raw,
            "generado_en_epoch": int(time.time()),
        }

    # ------------------------------------------------------------------
    # Integración multi-plataforma con redes sociales
    # ------------------------------------------------------------------
    def generate_social_media_bundle(
        self,
        transcript: str,
        filename: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Any:
        """Genera contenido para TODAS las redes sociales habilitadas.

        Devuelve un :class:`GeneratedContentBundle` con el contenido para
        YouTube, Instagram, TikTok, X/Twitter, Facebook y LinkedIn (solo las
        plataformas que estén habilitadas en ``settings.yaml``).
        """
        from .social_media import SocialMediaManager
        manager = SocialMediaManager(settings=settings, ai_engine=self)
        return manager.generate_all(transcript, filename=filename)

    def generate_for_platform(
        self,
        platform_name: str,
        transcript: str,
        filename: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> Any:
        """Genera contenido para UNA sola plataforma por nombre."""
        from .social_media import SocialMediaManager
        manager = SocialMediaManager(settings=settings, ai_engine=self)
        return manager.generate_platform(platform_name, transcript, filename=filename)

    def social_media_status(self, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resumen de plataformas habilitadas y configuración activa."""
        from .social_media import SocialMediaManager
        manager = SocialMediaManager(settings=settings, ai_engine=self)
        return {
            "available_platforms": manager.available_platforms(),
            "default_provider": self.ai_cfg.get("default_provider"),
            "available_ai_providers": self.available_providers(),
            "ai_errors": dict(self._provider_errors),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _log_resp(resp: ProviderResponse) -> None:
        _LOG.info(
            "AIEngine: respuesta OK provider=%s modelo=%s latencia=%dms len=%d",
            resp.provider,
            resp.model,
            resp.latency_ms,
            len(resp.text),
        )
