"""Sistema profesional multi-plataforma para gestión y generación de contenido en redes sociales.

Este paquete implementa una arquitectura extensible basada en:

1. :class:`BaseSocialPlatform` — interfaz abstracta común para todas las plataformas.
2. Plataformas concretas en :mod:`core.social_media.platforms.*` — YouTube, Instagram,
   TikTok, X/Twitter, Facebook, LinkedIn.
3. :class:`SocialMediaManager` — orquestador de alto nivel que coordina todas las
   plataformas, genera contenido adaptado y agrega resultados.

Uso rápido::

    from core.social_media import SocialMediaManager

    manager = SocialMediaManager(settings=mi_cfg)
    transcripcion = "..."  # texto del audio/vídeo
    resultados = manager.generate_all(transcripcion, filename="mi_video.mp4")

    # Acceso por plataforma
    youtube = resultados["youtube"]
    instagram = resultados["instagram"]  # feed + stories + reels
    print(youtube.titulo)
    for story in instagram.stories:
        print(story.texto)

Características profesionales:
  * **Polimorfismo**: todas las plataformas implementan la misma API básica.
  * **Reglas hard-coded + IA**: cada plataforma define límites (caracteres, hashtags
    máximos, formatos) que la IA NO puede romper.
  * **Validación post-generación**: antes de devolver el resultado, cada plataforma
    ejecuta :meth:`~BaseSocialPlatform.validate` garantizando que no hay overruns.
  * **Modo batch / individual**: genera para todas las plataformas o una sola.
"""

from __future__ import annotations

from .base import (
    BaseSocialPlatform,
    PlatformConfig,
    PlatformContent,
    SocialMediaPlatformError,
)
from .manager import (
    GeneratedContentBundle,
    SocialMediaManager,
    build_social_report,
)
from .platforms.facebook import FacebookContent, FacebookPlatform
from .platforms.instagram import InstagramContent, InstagramPlatform
from .platforms.linkedin import LinkedInContent, LinkedInPlatform
from .platforms.tiktok import TikTokContent, TikTokPlatform
from .platforms.twitter_x import XTwitterContent, XTwitterPlatform
from .platforms.youtube import YouTubeContent, YouTubePlatform

__all__ = [
    # base
    "BaseSocialPlatform",
    "PlatformContent",
    "PlatformConfig",
    "SocialMediaPlatformError",
    # manager
    "SocialMediaManager",
    "GeneratedContentBundle",
    "build_social_report",
    # plataformas concretas (por si se quiere acceso directo)
    "YouTubePlatform",
    "YouTubeContent",
    "InstagramPlatform",
    "InstagramContent",
    "TikTokPlatform",
    "TikTokContent",
    "XTwitterPlatform",
    "XTwitterContent",
    "FacebookPlatform",
    "FacebookContent",
    "LinkedInPlatform",
    "LinkedInContent",
]
