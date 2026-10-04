"""Orquestador de alto nivel: genera contenido para TODAS las plataformas.

:class:`SocialMediaManager` es el punto de entrada público que debe usar el
resto de la aplicación (UI, CLI, watcher, worker). Coordina:

* Construcción de todas las plataformas habilitadas (desde ``settings.yaml``).
* Inyección del motor de IA (normalmente :class:`core.ai_engine.AIEngine`).
* Generación en paralelo / secuencial de contenido para cada red.
* Validación post-generación y reporting unificado.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from .base import (
    BaseSocialPlatform,
    PlatformConfig,
    PlatformContent,
    SocialMediaPlatformError,
)
from .platforms.facebook import FacebookPlatform
from .platforms.instagram import InstagramPlatform
from .platforms.linkedin import LinkedInPlatform
from .platforms.tiktok import TikTokPlatform
from .platforms.twitter_x import XTwitterPlatform
from .platforms.youtube import YouTubePlatform

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tipos de retorno
# ---------------------------------------------------------------------------
@dataclass
class GeneratedContentBundle:
    """Contenedor de los resultados de TODAS las plataformas habilitadas."""

    youtube: Any | None = None
    instagram: Any | None = None
    tiktok: Any | None = None
    twitter_x: Any | None = None
    facebook: Any | None = None
    linkedin: Any | None = None
    errors: dict[str, str] = field(default_factory=dict)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"generated_at": self.generated_at, "errors": dict(self.errors)}
        for name in ("youtube", "instagram", "tiktok", "twitter_x", "facebook", "linkedin"):
            value = getattr(self, name)
            data[name] = value.to_dict() if hasattr(value, "to_dict") else value
        return data

    def enabled_platforms(self) -> list[str]:
        out = []
        for name in ("youtube", "instagram", "tiktok", "twitter_x", "facebook", "linkedin"):
            if getattr(self, name) is not None:
                out.append(name)
        return out


# ---------------------------------------------------------------------------
# Factoría de plataformas
# ---------------------------------------------------------------------------
_PLATFORM_REGISTRY: dict[str, type[BaseSocialPlatform]] = {
    "youtube": YouTubePlatform,
    "instagram": InstagramPlatform,
    "tiktok": TikTokPlatform,
    "twitter_x": XTwitterPlatform,
    "x": XTwitterPlatform,
    "twitter": XTwitterPlatform,
    "facebook": FacebookPlatform,
    "linkedin": LinkedInPlatform,
}


def _build_platform(
    name: str,
    platform_cfg_block: dict[str, Any] | None,
    global_cfg: dict[str, Any] | None,
    ai_callable: Callable[[str, str | None], str],
) -> BaseSocialPlatform | None:
    """Construye una plataforma concreta aplicando herencia de configuración."""
    cls = _PLATFORM_REGISTRY.get(name.lower())
    if cls is None:
        _LOG.warning("Plataforma desconocida: %s", name)
        return None
    global_cfg = global_cfg or {}
    platform_cfg_block = platform_cfg_block or {}

    # Merge: global settings (social_media.defaults) -> específica plataforma
    base_cfg = {
        "max_hashtags": global_cfg.get("max_hashtags", 30),
        "tone": global_cfg.get("tone", "equilibrado"),
        "language": global_cfg.get("language", "es"),
        "cta": global_cfg.get("cta"),
        "extra_rules": list(global_cfg.get("extra_rules", []) or []),
    }
    for k, v in (platform_cfg_block or {}).items():
        if k == "extra_rules" and isinstance(v, list):
            base_cfg["extra_rules"] = list(base_cfg.get("extra_rules", [])) + list(v)
        else:
            base_cfg[k] = v
    if "enabled" not in base_cfg:
        base_cfg["enabled"] = True
    cfg = PlatformConfig.from_dict(base_cfg)
    if not cfg.enabled:
        _LOG.info("Plataforma [%s] deshabilitada (enabled=false).", name)
        return None
    return cls(config=cfg, ai_callable=ai_callable)


# ---------------------------------------------------------------------------
# SocialMediaManager
# ---------------------------------------------------------------------------
class SocialMediaManager:
    """Orquestador principal del sistema multi-plataforma de redes sociales."""

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        ai_engine: Any = None,
        ai_callable: Callable[[str, str | None], str] | None = None,
    ) -> None:
        self.settings = settings or {}
        social_cfg = (
            (self.settings.get("social_media") or {}) if isinstance(self.settings, dict) else {}
        )
        self._global_defaults = social_cfg.get("defaults", {}) or {}
        self._platforms_cfg = social_cfg.get("platforms", {}) or {}

        # Motor IA: prefiere ai_callable, sino ai_engine.generate
        if ai_callable is not None:
            self._ai_callable = ai_callable
        elif ai_engine is not None and hasattr(ai_engine, "generate"):
            self._ai_callable = ai_engine.generate
        else:
            # Fallback lazy: se construye AIEngine a demanda (evita import cycles)
            self._ai_callable = self._lazy_ai_generate

        self._ai_engine_cache = ai_engine
        self._platforms: dict[str, BaseSocialPlatform] = {}
        self._build_all_platforms()

    # ------------------------------------------------------------------
    def _lazy_ai_generate(self, prompt: str, system: str | None = None) -> str:
        if self._ai_engine_cache is None:
            from core.ai_engine import AIEngine

            self._ai_engine_cache = AIEngine()
        return self._ai_engine_cache.generate(prompt, system)

    def _build_all_platforms(self) -> None:
        for name in ("youtube", "instagram", "tiktok", "twitter_x", "facebook", "linkedin"):
            cfg_block = self._platforms_cfg.get(name)
            plat = _build_platform(
                name,
                cfg_block,
                self._global_defaults,
                self._ai_callable,
            )
            if plat is not None:
                self._platforms[name] = plat

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def available_platforms(self) -> list[str]:
        return sorted(self._platforms.keys())

    def get_platform(self, name: str) -> BaseSocialPlatform:
        key = name.lower().strip()
        if key in self._platforms:
            return self._platforms[key]
        raise SocialMediaPlatformError(
            f"Plataforma '{name}' no disponible. Habilitadas: {self.available_platforms()}"
        )

    def generate_all(
        self,
        transcript: str,
        filename: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> GeneratedContentBundle:
        """Genera contenido para todas las plataformas habilitadas."""
        bundle = GeneratedContentBundle()
        from datetime import datetime

        bundle.generated_at = datetime.now(UTC).isoformat()

        name_to_attr = {
            "youtube": "youtube",
            "instagram": "instagram",
            "tiktok": "tiktok",
            "twitter_x": "twitter_x",
            "facebook": "facebook",
            "linkedin": "linkedin",
        }

        for plat_name, platform in self._platforms.items():
            attr = name_to_attr.get(plat_name)
            if attr is None:
                continue
            try:
                content = platform.generate(transcript, filename=filename, context=context)
                setattr(bundle, attr, content)
                _LOG.info("SocialMediaManager: [%s] OK", plat_name)
            except Exception as exc:
                short = f"{type(exc).__name__}: {exc}"
                bundle.errors[plat_name] = short
                _LOG.warning("SocialMediaManager: [%s] falló -> %s", plat_name, short)
        return bundle

    def generate_platform(
        self,
        platform_name: str,
        transcript: str,
        filename: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> PlatformContent:
        return self.get_platform(platform_name).generate(
            transcript, filename=filename, context=context
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def build_social_report(bundle: GeneratedContentBundle) -> str:
    """Construye un informe TXT legible para humanos con TODO el contenido."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("CONTENIDO MULTI-PLATAFORMA — DaVinci Agent Social Media Suite")
    lines.append(f"Generado: {bundle.generated_at or '-'}")
    lines.append("=" * 72)
    lines.append("")

    sections = [
        ("YOUTUBE", bundle.youtube),
        ("INSTAGRAM", bundle.instagram),
        ("TIKTOK", bundle.tiktok),
        ("X / TWITTER", bundle.twitter_x),
        ("FACEBOOK", bundle.facebook),
        ("LINKEDIN", bundle.linkedin),
    ]
    for title, content in sections:
        lines.append("-" * 72)
        lines.append(f"  {title}")
        lines.append("-" * 72)
        if content is None:
            lines.append("  (plataforma deshabilitada o generación fallida)")
            lines.append("")
            continue
        d = content.to_dict() if hasattr(content, "to_dict") else {}
        _render_section(lines, d)
        lines.append("")

    if bundle.errors:
        lines.append("-" * 72)
        lines.append("  ERRORES POR PLATAFORMA")
        lines.append("-" * 72)
        for plat, err in bundle.errors.items():
            lines.append(f"  [{plat}] {err}")
        lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)


def _render_section(lines: list[str], data: dict[str, Any], indent: str = "  ") -> None:
    """Renderiza recursivamente el contenido de una plataforma en TXT."""
    order = [
        "platform",
        "title",
        "body",
        "description",
        "caption",
        "headline",
        "summary",
        "hashtags",
        "tags",
        "cta",
        "chapters",
        "capitulos",
        "stories",
        "reels",
        "feed_posts",
        "carousel",
        "tweets",
        "thread",
        "hooks",
        "summary_points",
        "highlights",
        "warnings",
    ]
    rendered_keys: set[str] = set()
    for key in order:
        if key not in data:
            continue
        _render_kv(lines, key, data[key], indent)
        rendered_keys.add(key)
    for key, value in data.items():
        if key in rendered_keys or key in {"generated_at", "raw_ai_response"}:
            continue
        _render_kv(lines, key, value, indent)


def _render_kv(lines: list[str], key: str, value: Any, indent: str) -> None:
    key_label = key.replace("_", " ").upper()
    if value is None:
        return
    if isinstance(value, list):
        if not value:
            return
        lines.append(f"{indent}{key_label}:")
        for idx, item in enumerate(value, start=1):
            if isinstance(item, dict):
                lines.append(f"{indent}  [{idx}]")
                _render_section(lines, item, indent=indent + "    ")
            else:
                lines.append(f"{indent}  {idx}. {item}")
    elif isinstance(value, dict):
        if not value:
            return
        lines.append(f"{indent}{key_label}:")
        _render_section(lines, value, indent=indent + "  ")
    else:
        text = str(value).strip()
        if not text:
            return
        lines.append(f"{indent}{key_label}:")
        for subline in text.splitlines():
            lines.append(f"{indent}  {subline}")
