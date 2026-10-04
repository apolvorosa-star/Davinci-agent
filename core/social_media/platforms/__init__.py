"""Subpaquete de plataformas concretas de redes sociales."""
from __future__ import annotations

from .youtube import YouTubeContent, YouTubePlatform
from .instagram import InstagramContent, InstagramPlatform
from .tiktok import TikTokContent, TikTokPlatform
from .twitter_x import XTwitterContent, XTwitterPlatform
from .facebook import FacebookContent, FacebookPlatform
from .linkedin import LinkedInContent, LinkedInPlatform


__all__ = [
    "YouTubeContent", "YouTubePlatform",
    "InstagramContent", "InstagramPlatform",
    "TikTokContent", "TikTokPlatform",
    "XTwitterContent", "XTwitterPlatform",
    "FacebookContent", "FacebookPlatform",
    "LinkedInContent", "LinkedInPlatform",
]
