"""Factoría y orquestador de fallback chain multi-proveedor.

Clases
------
:class:`ProviderFactory`
    Registro global de nombres ``yaml -> clase``. Construye y valida cada
    proveedor a partir de la configuración cruda (``enabled=false``, faltan
    credenciales, etc.).

:class:`FallbackChainExecutor`
    Orquesta la cadena de respaldo automática. Prueba el proveedor
    ``default`` y, si falla, recorre la lista ``fallback_chain`` en orden
    hasta que uno responda (o lanza ``RuntimeError`` detallado con el
    histórico de fallos si todos agotan sus reintentos).

Backward compat
---------------
Se re-exporta :func:`build_provider` como helper de nivel módulo — es
equivalente a ``ProviderFactory().build(...)`` y mantiene la misma firma que
tenía antiguamente para no romper importaciones directas.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .base import BaseProvider, ProviderConfig, ProviderResponse
from .ollama import OllamaProvider
from .openai_compatible import (
    MistralProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from .anthropic import AnthropicProvider
from .google import GoogleGeminiProvider


_LOG = logging.getLogger(__name__)


# =====================================================================
# ProviderFactory  -  registro global + build
# =====================================================================
class ProviderFactory:
    """Factoría que instancia el proveedor adecuado según su nombre.

    Ejemplo básico::

        factory = ProviderFactory()
        factory.register("mi_proveedor_custom", MiClaseProvider)

        provider = factory.build(
            "openai",
            raw_cfg={"enabled": True, "api_key": "sk-...", "model": "gpt-4o-mini"},
            ai_root_cfg={"temperature": 0.2, "timeout": 600, "max_retries": 3},
        )
        print(provider.PROVIDER_ID, provider.model)
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseProvider]] = {}
        self._register_defaults()

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------
    def register(self, name: str, provider_cls: type[BaseProvider]) -> None:
        """Registra (o sobreescribe) un nombre de proveedor con su clase."""
        if not name or not isinstance(name, str):
            raise ValueError("ProviderFactory.register: nombre inválido.")
        if not issubclass(provider_cls, BaseProvider):
            raise TypeError(
                "ProviderFactory.register: la clase debe heredar de BaseProvider."
            )
        self._registry[name.strip().lower()] = provider_cls

    def _register_defaults(self) -> None:
        """Registra los 7 proveedores oficiales + aliases antiguos."""
        # Core (según especificación del usuario)
        self.register("ollama", OllamaProvider)
        self.register("openai", OpenAIProvider)
        self.register("anthropic", AnthropicProvider)
        self.register("google", GoogleGeminiProvider)
        self.register("openrouter", OpenRouterProvider)
        self.register("mistral", MistralProvider)
        self.register("openai_compatible", OpenAICompatibleProvider)
        # Backward compat: viejos nombres (custom_openai y el nombre fichero
        # antiguo del módulo compat, por si alguien los tenía en el yaml).
        self.register("custom_openai", OpenAICompatibleProvider)
        self.register("openai_compat", OpenAICompatibleProvider)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def build(
        self,
        provider_name: str,
        provider_raw_cfg: dict[str, Any],
        ai_root_cfg: dict[str, Any] | None = None,
    ) -> BaseProvider:
        """Construye y valida un proveedor a partir del nombre y la cfg YAML.

        Args:
            provider_name: clave del proveedor tal cual aparece en
                ``ai.providers.<clave>`` (case-insensitive).
            provider_raw_cfg: diccionario tal cual sale del yaml (debe
                contener ``enabled``, ``model``, etc.).
            ai_root_cfg: bloque superior ``ai:``, con ``temperature``,
                ``timeout`` y ``max_retries`` globales (se usan como
                defaults por proveedor).

        Returns:
            Instancia de :class:`BaseProvider` lista para usar y validada
            (``validate()`` ya ejecutado).

        Raises:
            ValueError: nombre desconocido, ``enabled:false``, falta algún
                campo obligatorio, o falla ``validate()`` del provider.
        """
        if not isinstance(provider_name, str):
            raise ValueError("provider_name debe ser un string.")
        key = provider_name.strip().lower()

        if key not in self._registry:
            raise ValueError(
                f"Proveedor [{key}] no registrado en ProviderFactory. "
                f"Opciones válidas: {sorted(self._registry)}"
            )
        if not isinstance(provider_raw_cfg, dict) or not provider_raw_cfg:
            raise ValueError(f"Configuración vacía para el proveedor [{key}].")
        if provider_raw_cfg.get("enabled", True) is False:
            raise ValueError(
                f"Proveedor [{key}] marcado como enabled:false en settings.yaml."
            )

        cfg = ProviderConfig.from_dict(
            key, provider_raw_cfg, ai_root_cfg=ai_root_cfg
        )
        provider_cls = self._registry[key]
        provider = provider_cls(cfg)
        provider.validate()
        _LOG.info(
            "ProviderFactory: construido [%s] -> %s modelo=%s",
            key,
            provider_cls.__name__,
            provider.model,
        )
        return provider

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def registered_names(self) -> list[str]:
        return sorted(self._registry.keys())


# =====================================================================
# FallbackChainExecutor  -  cadena de respaldo
# =====================================================================
@dataclass
class FallbackChainExecutor:
    """Orquesta la cadena de fallback multi-proveedor.

    Su método :meth:`execute` es la fachada principal que usa el resto de la
    aplicación (a través de ``AIEngine``). Recorre la secuencia de providers
    en orden y captura **todos** los errores para intentar el siguiente
    sin perder trazabilidad.
    """

    providers: dict[str, BaseProvider]
    default_provider_name: str
    fallback_chain: list[str] = field(default_factory=list)
    logger: logging.Logger = field(default_factory=lambda: _LOG)

    def __post_init__(self) -> None:
        """Normaliza claves a lowercase para lookups deterministas."""
        if not isinstance(self.providers, dict):
            raise ValueError("FallbackChainExecutor.providers debe ser un dict.")
        self.providers = {
            str(k).strip().lower(): v for k, v in self.providers.items()
            if isinstance(k, str)
        }
        if not isinstance(self.default_provider_name, str):
            self.default_provider_name = ""
        self.default_provider_name = self.default_provider_name.strip().lower()
        if isinstance(self.fallback_chain, list):
            self.fallback_chain = [
                str(x).strip().lower()
                for x in self.fallback_chain
                if isinstance(x, str) and str(x).strip()
            ]
        else:
            self.fallback_chain = []

    # ------------------------------------------------------------------
    def execution_order(self) -> list[str]:
        """Devuelve la lista ordenada y deduplicada de proveedores.

        Orden:
        1. ``default_provider_name``
        2. Cada entrada de ``fallback_chain`` (en orden, sin repetir)
        3. Cualquier provider que aún esté en ``self.providers`` y no se
           haya añadido aún (orden alfabético), como último recurso.
        """
        order: list[str] = []

        def _push(name: str) -> None:
            s = str(name).strip().lower()
            if s and s in self.providers and s not in order:
                order.append(s)

        # 1. default
        _push(self.default_provider_name)
        # 2. fallback chain
        for name in self.fallback_chain or []:
            _push(name)
        # 3. restos (alfabéticos)
        for name in sorted(self.providers.keys()):
            _push(name)
        return order

    # ------------------------------------------------------------------
    def execute(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> ProviderResponse:
        """Ejecuta el prompt sobre la cadena de fallback hasta éxito.

        Returns:
            :class:`ProviderResponse` con el texto y metadatos del primer
            proveedor que respondió correctamente.

        Raises:
            RuntimeError: Si **ningún** proveedor responde. El mensaje
                incluye el histórico detallado por proveedor (nombre +
                excepción + trace corto).
        """
        order = self.execution_order()
        if not order:
            raise RuntimeError(
                "FallbackChainExecutor: no hay ningún proveedor registrado "
                "y operativo. Revisa ai.providers.*.enabled en settings.yaml."
            )

        errors: list[tuple[str, str]] = []
        for name in order:
            provider = self.providers.get(name)
            if provider is None:  # pragma: no cover - guard defensivo
                errors.append(
                    (name, f"proveedor '{name}' no encontrado en map de providers.")
                )
                continue
            try:
                resp = provider.generate(
                    prompt, system_prompt=system_prompt, json_mode=json_mode
                )
                self.logger.info(
                    "FallbackChainExecutor: OK con [%s] (model=%s latencia=%dms len=%d)",
                    name,
                    resp.model,
                    resp.latency_ms,
                    len(resp.text),
                )
                return resp
            except Exception as exc:  # noqa: BLE001
                short = f"{type(exc).__name__}: {exc}"
                errors.append((name, short))
                self.logger.warning(
                    "FallbackChainExecutor: falló [%s], pasando al siguiente. %s",
                    name,
                    short,
                )
                continue

        # Todos fallaron: error claro con histórico
        lines = [
            "Fallaron TODOS los proveedores de IA en la fallback chain. "
            "Histórico por proveedor:"
        ]
        lines.extend(f"  - [{n}] {m}" for n, m in errors)
        raise RuntimeError("\n".join(lines))


# =====================================================================
# Backward compat: build_provider helper a nivel módulo (antes vivía en
# __init__.py y ai_engine.py lo importaba).
# =====================================================================
_DEFAULT_FACTORY: ProviderFactory | None = None


def _get_default_factory() -> ProviderFactory:
    global _DEFAULT_FACTORY
    if _DEFAULT_FACTORY is None:
        _DEFAULT_FACTORY = ProviderFactory()
    return _DEFAULT_FACTORY


def build_provider(
    provider_name: str,
    provider_raw_cfg: dict[str, Any],
    ai_root_cfg: dict[str, Any] | None = None,
) -> BaseProvider:
    """Helper de nivel módulo — equivalente a ``ProviderFactory().build(...)``.

    Se mantiene **exclusivamente** por compatibilidad hacia atrás. Nuevo
    código debería instanciar :class:`ProviderFactory` explícitamente.
    """
    return _get_default_factory().build(
        provider_name, provider_raw_cfg, ai_root_cfg=ai_root_cfg
    )
