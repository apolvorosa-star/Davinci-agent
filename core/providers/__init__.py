"""Paquete de proveedores de IA multi-proveedor para DaVinci Agent / Da Vinci Studio.

Este paquete implementa la **arquitectura híbrida** de producción:

1. **N múltiples proveedores** — Ollama (local), OpenAI, Anthropic, Google,
   OpenRouter, Mistral, y cualquier API compatible con formato OpenAI
   (LM Studio, Groq, Together, Perplexity…).
2. **Cadena de respaldo automática (fallback chain)** — si el proveedor
   principal falla, se prueba el siguiente sin interrumpir al usuario.
3. **Expansión de variables de entorno** — las API Keys NUNCA se escriben en
   el yaml; se cargan desde ``${VAR}`` / ``${VAR:-default}``.
4. **Compatibilidad 100% hacia atrás** — todas las clases antiguas siguen
   existiendo (incluso con nombres legacy como ``CustomOpenAIProvider``).

Uso rápido::

    from core.providers import (
        ProviderFactory, FallbackChainExecutor, build_provider,
        BaseProvider, ProviderResponse, expand_env_vars,
        OllamaProvider, OpenAIProvider, OpenAICompatibleProvider, ...
    )

    factory = ProviderFactory()
    ollama = factory.build("ollama", ollama_cfg, ai_root_cfg)
    print(ollama.health_check())
"""

from __future__ import annotations

from .anthropic import AnthropicProvider

# ---------------------------------------------------------------------------
# base (tipos / interfaz común)
# ---------------------------------------------------------------------------
from .base import (
    BaseProvider,
    ProviderConfig,
    ProviderResponse,
    RateLimitError,
    parse_retry_after,
)

# ---------------------------------------------------------------------------
# env_loader
# ---------------------------------------------------------------------------
from .env_loader import expand_env_vars

# ---------------------------------------------------------------------------
# factory (ProviderFactory + FallbackChainExecutor + helper build_provider)
# ---------------------------------------------------------------------------
from .factory import (
    FallbackChainExecutor,
    ProviderFactory,
    build_provider,
)
from .google import GoogleGeminiProvider

# ---------------------------------------------------------------------------
# Proveedores concretos
# ---------------------------------------------------------------------------
from .ollama import OllamaProvider
from .openai_compatible import (
    MistralProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OpenRouterProvider,
)

# Aliases de compatibilidad hacia atrás: las clases antiguas siguen existiendo
# con los mismos nombres, aunque el fichero del yaml y la registry ahora usen
# "openai_compatible" como nombre preferente.
CustomOpenAIProvider = OpenAICompatibleProvider


# ---------------------------------------------------------------------------
# PROVIDER_REGISTRY: mapa legacy de nombre_yaml -> clase (backward compat
# para quien todavía acceda directamente a este atributo en vez de usar
# ProviderFactory). Se construye a partir del factory para no duplicar datos.
# ---------------------------------------------------------------------------
_PROVIDER_FACTORY_SINGLETON: ProviderFactory | None = None


def _ensure_provider_registry() -> dict[str, type[BaseProvider]]:
    global _PROVIDER_FACTORY_SINGLETON
    if _PROVIDER_FACTORY_SINGLETON is None:
        _PROVIDER_FACTORY_SINGLETON = ProviderFactory()
    return dict(_PROVIDER_FACTORY_SINGLETON._registry)


PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = _ensure_provider_registry()


__all__ = [
    # env_loader
    "expand_env_vars",
    # base
    "BaseProvider",
    "ProviderConfig",
    "ProviderResponse",
    "RateLimitError",
    "parse_retry_after",
    # factory
    "ProviderFactory",
    "FallbackChainExecutor",
    "build_provider",
    # registro legacy (no recomendado para código nuevo, pero sigue vivo)
    "PROVIDER_REGISTRY",
    # proveedores concretos
    "OllamaProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "GoogleGeminiProvider",
    "OpenRouterProvider",
    "MistralProvider",
    "OpenAICompatibleProvider",
    # alias legacy
    "CustomOpenAIProvider",
]
