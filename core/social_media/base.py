"""Interfaz abstracta común y tipos para todas las plataformas de redes sociales.

Cada plataforma concreta (YouTube, Instagram, TikTok…) hereda de
:class:`BaseSocialPlatform` e implementa sus métodos abstractos. Esto permite
tratarlas de forma polimórfica desde :class:`SocialMediaManager`.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional


class SocialMediaPlatformError(RuntimeError):
    """Excepción específica para fallos en generación o validación de contenido."""


# ---------------------------------------------------------------------------
# PlatformConfig  —  configuración normalizada por plataforma
# ---------------------------------------------------------------------------
@dataclass
class PlatformConfig:
    """Configuración estándar que recibe cada plataforma concreta.

    Attributes:
        enabled:       Si ``False``, el manager NO generará contenido para ella.
        max_hashtags:  Número máximo de hashtags permitidos (hard-limit).
        tone:          Tono general para el contenido (profesional, casual, viral…).
        language:      Idioma de destino (ISO 639-1, p.ej. ``"es"``).
        cta:           Call-To-Action por defecto si la IA no sugiere uno.
        extra_rules:   Reglas adicionales específicas del usuario/proyecto.
    """

    enabled: bool = True
    max_hashtags: int = 30
    tone: str = "equilibrado"
    language: str = "es"
    cta: str = "¡Síguenos para más contenido de calidad!"
    extra_rules: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "PlatformConfig":
        raw = raw or {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            max_hashtags=int(raw.get("max_hashtags", 30)),
            tone=str(raw.get("tone", "equilibrado")).strip() or "equilibrado",
            language=str(raw.get("language", "es")).strip() or "es",
            cta=str(raw.get("cta") or "¡Síguenos para más contenido de calidad!").strip(),
            extra_rules=list(raw.get("extra_rules", []) or []),
        )


# ---------------------------------------------------------------------------
# PlatformContent  —  clase base para los resultados de cada plataforma
# ---------------------------------------------------------------------------
@dataclass
class PlatformContent:
    """Contenedor base de datos de contenido generado.

    Cada plataforma define una subclase con sus campos específicos (p.ej.
    :class:`YouTubeContent` añade ``capitulos`` y ``tags``).

    Attributes:
        platform:       Nombre corto de la plataforma (``"youtube"``…).
        title:          Título / cabecera principal.
        body:           Cuerpo / descripción / texto largo.
        hashtags:       Lista de hashtags (sin ``#`` inicial).
        cta:            Call-To-Action final.
        warnings:       Advertencias de post-procesamiento (p.ej. texto truncado).
        generated_at:   ISO-8601 UTC.
        raw_ai_response:Respuesta cruda de la IA (para depuración / auditoría).
    """

    platform: str
    title: str = ""
    body: str = ""
    hashtags: list[str] = field(default_factory=list)
    cta: str = ""
    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    raw_ai_response: str = ""

    # ------------------------------------------------------------------
    # Helpers de normalización (usados por las plataformas hijas)
    # ------------------------------------------------------------------
    @staticmethod
    def clean_hashtags(
        tags: list[str] | Any,
        max_tags: int,
    ) -> tuple[list[str], list[str]]:
        """Normaliza hashtags y aplica el hard-limit.

        Devuelve: ``(hashtags_limpios, warnings)``.
        """
        warnings: list[str] = []
        cleaned: list[str] = []
        seen: set[str] = set()
        if not isinstance(tags, list):
            tags = []
        for raw in tags:
            if raw is None:
                continue
            t = str(raw).strip().lstrip("#").strip()
            if not t:
                continue
            t = re.sub(r"\s+", "_", t)
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            if len(cleaned) >= max_tags:
                warnings.append(
                    f"Hashtags excedieron el límite de {max_tags}; se truncaron."
                )
                break
            cleaned.append(t)
        return cleaned, warnings

    @staticmethod
    def enforce_char_limit(
        text: str,
        limit: int,
        field_name: str,
        ellipsis: str = "…",
    ) -> tuple[str, list[str]]:
        """Trunca ``text`` a ``limit`` caracteres si hace falta.

        Devuelve ``(texto, warnings)``.
        """
        if limit <= 0 or not text or len(text) <= limit:
            return text, []
        safe = max(0, limit - len(ellipsis))
        truncated = text[:safe].rstrip() + ellipsis
        return truncated, [
            f"Campo '{field_name}' excedió {limit} caracteres; se truncó."
        ]

    @staticmethod
    def extract_hashtags_from_text(text: str) -> list[str]:
        """Extrae hashtags embebidos en un texto (``#etiqueta``)."""
        return re.findall(r"#([A-Za-z0-9_ÁÉÍÓÚÜÑáéíóúüñ]+)", text or "")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# BaseSocialPlatform  —  interfaz abstracta
# ---------------------------------------------------------------------------
class BaseSocialPlatform(ABC):
    """Clase base abstracta que toda plataforma concreta debe implementar.

    Ciclo de vida:
        1. :meth:`build_prompt`  -> prompt específico de la plataforma.
        2. llamada a la IA       -> texto crudo (JSON).
        3. :meth:`parse_response`-> convierte el texto en :class:`PlatformContent`.
        4. :meth:`validate`      -> garantiza límites de caracteres, hashtags, etc.
    """

    PLATFORM_ID: str = "base"
    DISPLAY_NAME: str = "Base"

    # Límites por defecto (cada plataforma los sobreescribe).
    TITLE_CHAR_LIMIT: int = 100
    BODY_CHAR_LIMIT: int = 2000
    MAX_HASHTAGS_DEFAULT: int = 30

    def __init__(
        self,
        config: PlatformConfig | None = None,
        ai_callable: Optional[Callable[[str, Optional[str]], str]] = None,
    ) -> None:
        self.config = config or PlatformConfig()
        self._ai_callable = ai_callable

    # ------------------------------------------------------------------
    # Helpers protegidos
    # ------------------------------------------------------------------
    @property
    def effective_max_hashtags(self) -> int:
        return min(self.config.max_hashtags, self.MAX_HASHTAGS_DEFAULT)

    def _ai_generate(self, prompt: str, system: str | None = None) -> str:
        """Delega en el callable de IA (inyectado por el manager)."""
        if self._ai_callable is None:
            raise SocialMediaPlatformError(
                f"[{self.PLATFORM_ID}] No se configuró ningún motor de IA. "
                "Pasa `ai_callable` al constructor o usa SocialMediaManager."
            )
        return self._ai_callable(prompt, system)

    # ------------------------------------------------------------------
    # Métodos abstractos que cada plataforma debe implementar
    # ------------------------------------------------------------------
    @abstractmethod
    def build_prompt(
        self,
        transcript: str,
        filename: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str | None]:
        """Construye (prompt_usuario, prompt_sistema) adaptado a la plataforma.

        El prompt **debe** exigir JSON con una estructura concreta (el manager
        luego validará límites).
        """

    @abstractmethod
    def parse_response(self, raw_text: str) -> PlatformContent:
        """Convierte la respuesta cruda de la IA en un ``PlatformContent``.

        Debe ser robusto: markdown ```json```, llaves parciales, etc.
        """

    @abstractmethod
    def validate(self, content: PlatformContent) -> PlatformContent:
        """Aplica hard-limits y devuelve el contenido corregido + warnings.

        **NUNCA** debe lanzar excepciones: cualquier ajuste se convierte en
        un warning dentro de ``content.warnings``.
        """

    # ------------------------------------------------------------------
    # API de alto nivel (usa el ciclo completo)
    # ------------------------------------------------------------------
    def generate(
        self,
        transcript: str,
        filename: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> PlatformContent:
        """Ciclo completo: prompt → IA → parseo → validación."""
        if not self.config.enabled:
            raise SocialMediaPlatformError(
                f"Plataforma [{self.PLATFORM_ID}] deshabilitada en la configuración."
            )
        prompt, system = self.build_prompt(transcript, filename=filename, context=context)
        raw = self._ai_generate(prompt, system)
        content = self.parse_response(raw)
        content.raw_ai_response = raw
        validated = self.validate(content)
        return validated
