"""Subpaquete de plataformas concretas de redes sociales."""

from __future__ import annotations

from .facebook import FacebookContent, FacebookPlatform
from .instagram import InstagramContent, InstagramPlatform
from .linkedin import LinkedInContent, LinkedInPlatform
from .tiktok import TikTokContent, TikTokPlatform
from .twitter_x import XTwitterContent, XTwitterPlatform
from .youtube import YouTubeContent, YouTubePlatform

__all__ = [
    "FacebookContent",
    "FacebookPlatform",
    "InstagramContent",
    "InstagramPlatform",
    "LinkedInContent",
    "LinkedInPlatform",
    "TikTokContent",
    "TikTokPlatform",
    "XTwitterContent",
    "XTwitterPlatform",
    "YouTubeContent",
    "YouTubePlatform",
]
