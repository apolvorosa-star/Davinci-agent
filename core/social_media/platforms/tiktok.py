"""Plataforma TikTok — hooks virales, captions cortos, hashtags y tendencias."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..base import BaseSocialPlatform, PlatformContent


@dataclass
class TikTokContent(PlatformContent):
    hook: str = ""
    caption: str = ""
    trend_suggestion: str = ""
    audio_suggestion: str = ""
    text_overlays: list[str] = field(default_factory=list)
    scene_cuts: list[dict[str, Any]] = field(default_factory=list)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            platform="tiktok",
            **{k: v for k, v in kwargs.items() if k in PlatformContent.__dataclass_fields__},
        )
        self.hook = str(kwargs.get("hook") or kwargs.get("title") or "").strip()
        self.caption = str(kwargs.get("caption") or kwargs.get("body") or "").strip()
        self.trend_suggestion = str(
            kwargs.get("trend_suggestion") or kwargs.get("trend") or ""
        ).strip()
        self.audio_suggestion = str(
            kwargs.get("audio_suggestion") or kwargs.get("audio") or "trending sound"
        ).strip()
        self.text_overlays = [
            str(x).strip() for x in (kwargs.get("text_overlays") or []) if str(x).strip()
        ]
        self.scene_cuts = [dict(s) for s in (kwargs.get("scene_cuts") or []) if isinstance(s, dict)]
        self.title = self.hook
        self.body = self.caption

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["hook"] = self.hook
        d["caption"] = self.caption
        d["trend_suggestion"] = self.trend_suggestion
        d["audio_suggestion"] = self.audio_suggestion
        d["text_overlays"] = list(self.text_overlays)
        d["scene_cuts"] = [dict(s) for s in self.scene_cuts]
        return d


class TikTokPlatform(BaseSocialPlatform):
    PLATFORM_ID = "tiktok"
    DISPLAY_NAME = "TikTok"

    TITLE_CHAR_LIMIT = 55  # caption visible preview
    BODY_CHAR_LIMIT = 2200
    MAX_HASHTAGS_DEFAULT = 8  # TikTok: menos es más; 5-8 ideal

    def build_prompt(
        self,
        transcript: str,
        filename: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str | None]:
        ctx = f"Archivo multimedia: {filename}\n" if filename else ""
        extra = "\n".join(f"- {r}" for r in self.config.extra_rules)
        extra_block = f"\n\nReglas adicionales del proyecto:\n{extra}\n" if extra else ""
        prompt = (
            "Eres un TikTok Creator viral senior con 5M+ seguidores en contenido hispanohablante. "
            "Genera SÓLO un JSON con esta estructura EXACTA:\n"
            "{\n"
            '  "hook": "HOOK VIRAL de 3-8 palabras que sorprenda/pregunte/contraste en los PRIMEROS 3 segundos. Sin spoilers, sí curiosidad. Ejemplos: Nadie te dijo que..., El error que..., Esto es lo que pasa si...",\n'
            '  "caption": "Caption del vídeo TikTok. Estructura: 1) Frase que complemente el hook. 2) Contexto corto. 3) CTA. 4) Hashtags (sólo los embebidos en caption). Total <= 2200 caracteres, PERO idealmente <200 + hashtags.",\n'
            '  "body": "(alias caption, opcional)",\n'
            '  "hashtags": ["hashtag1", "... 5-8 hashtags: 3 trending + 3 niche + 2 branded. SIN hashtag genericos como #fyp #foryou. Usa hashtags de nicho en español."],\n'
            '  "cta": "CTA específico TikTok: sigue, comenta 2 palabras, comparte, guarda, sigue para la parte 2.",\n'
            '  "trend_suggestion": "Formato/tendencia actual que encaje: POV, Storytime, Before/After, Tutorial 5 pasos, Rate my X, Day in the life, X vs Y, etc.",\n'
            '  "audio_suggestion": "Tipo de audio: trending viral audio | voz en off natural | sound effect dramático | música épica lenta | voiceover energético...",\n'
            '  "text_overlays": ["Texto superpuesto segundo 0-2", "texto overlay segundo 3-5", "... 3 a 7 overlays cortos (max 25 chars cada uno)"],\n'
            '  "scene_cuts": [{"segundo": "0-2", "visual": "Descripción visual del plano"}, ... 3 a 6 cortes de ritmo rápido]\n'
            "}\n\n"
            "Reglas TikTok estrictas:\n"
            "- HOOK = LO MÁS IMPORTANTE. Si no frena el scroll en 3 segundos, todo falla.\n"
            "- Caption corto y coloquial; usa lenguaje de calle, emojis estratégicos.\n"
            "- NADA de links directos en caption.\n"
            f"{extra_block}"
            f"{ctx}"
            f"Idioma: {self.config.language} | Tono: {self.config.tone}\n\n"
            "TRANSCRIPCIÓN:\n"
            f"{transcript}"
        )
        system = (
            "Eres experto viral TikTok en español. Cumples límites y enfocas todo a retención: "
            "hook fuerte, ritmo rápido, CTA claro. Respondes SÓLO JSON."
        )
        return prompt, system

    def _extract_json(self, raw: str) -> dict[str, Any]:
        if not raw:
            return {}
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE)
        candidates = [m.group(1)] if m else []
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
                        try:
                            return json.loads(text[start_idx : idx + 1])
                        except json.JSONDecodeError:
                            start_idx = -1
        return {}

    def parse_response(self, raw_text: str) -> TikTokContent:
        data = self._extract_json(raw_text)
        overlays = [str(x).strip() for x in (data.get("text_overlays") or []) if str(x).strip()]
        cuts_raw = data.get("scene_cuts") or []
        cuts: list[dict[str, Any]] = []
        for s in cuts_raw:
            if isinstance(s, dict):
                sec = str(s.get("segundo") or s.get("second") or s.get("time") or "").strip()
                vis = str(s.get("visual") or s.get("description") or "").strip()
                if sec or vis:
                    cuts.append({"segundo": sec, "visual": vis})
        return TikTokContent(
            hook=str(data.get("hook") or data.get("title") or "").strip(),
            caption=str(data.get("caption") or data.get("body") or "").strip(),
            cta=str(data.get("cta") or self.config.cta).strip(),
            hashtags=list(data.get("hashtags") or []),
            trend_suggestion=str(data.get("trend_suggestion") or data.get("trend") or "").strip(),
            audio_suggestion=str(
                data.get("audio_suggestion") or data.get("audio") or "trending sound"
            ).strip(),
            text_overlays=overlays,
            scene_cuts=cuts,
        )

    def validate(self, content: PlatformContent) -> TikTokContent:
        if not isinstance(content, TikTokContent):
            content = TikTokContent(
                hook=getattr(content, "title", ""),
                caption=getattr(content, "body", ""),
                hashtags=list(getattr(content, "hashtags", []) or []),
                cta=getattr(content, "cta", ""),
            )
        warnings = list(content.warnings)

        # Hook: 70 chars max (debe ser corto y potente)
        hook, w = content.enforce_char_limit(content.hook or "", 70, "hook")
        content.hook = hook
        content.title = hook
        warnings.extend(w)
        if not content.hook:
            content.hook = "¡MIRA ESTO HASTA EL FINAL! 👀"
            warnings.append("Hook vacío: añadido hook genérico.")

        cap, w = content.enforce_char_limit(content.caption or "", self.BODY_CHAR_LIMIT, "caption")
        content.caption = cap
        content.body = cap
        warnings.extend(w)

        cta, w = content.enforce_char_limit(content.cta or "", 150, "cta")
        content.cta = cta
        warnings.extend(w)

        cleaned, w = content.clean_hashtags(content.hashtags or [], self.effective_max_hashtags)
        content.hashtags = cleaned
        warnings.extend(w)
        if len(content.hashtags) < 3:
            warnings.append(f"TikTok recomienda 5-8 hashtags; tienes {len(content.hashtags)}.")

        content.trend_suggestion, _ = content.enforce_char_limit(
            content.trend_suggestion, 120, "trend_suggestion"
        )
        content.audio_suggestion, _ = content.enforce_char_limit(
            content.audio_suggestion, 120, "audio_suggestion"
        )

        # Overlays: 3-7 máx, cada uno <40 chars
        if len(content.text_overlays) < 3:
            warnings.append(
                f"Text overlays insuficientes ({len(content.text_overlays)}); completados."
            )
            base = [content.hook, "...", content.cta]
            for t in base:
                if t and t not in content.text_overlays and len(content.text_overlays) < 3:
                    content.text_overlays.append(t)
        for i, o in enumerate(content.text_overlays):
            content.text_overlays[i], _ = content.enforce_char_limit(o, 40, f"overlay[{i}]")
        if len(content.text_overlays) > 10:
            warnings.append("Overlays excedieron 10; se truncaron.")
            content.text_overlays = content.text_overlays[:10]

        # Scene cuts: 3-6
        if len(content.scene_cuts) < 3:
            warnings.append("Scene cuts <3; se crearon cortes básicos.")
            for i in range(max(0, 3 - len(content.scene_cuts))):
                content.scene_cuts.append(
                    {
                        "segundo": f"{i*3}-{(i+1)*3}",
                        "visual": f"Plano {i+1}: ritmo rápido siguiendo el audio viral.",
                    }
                )
        if len(content.scene_cuts) > 10:
            content.scene_cuts = content.scene_cuts[:10]
        for i, c in enumerate(content.scene_cuts):
            c["segundo"] = str(c.get("segundo", ""))[:20]
            vis, _ = content.enforce_char_limit(
                str(c.get("visual", "")), 200, f"scene_cut[{i}].visual"
            )
            c["visual"] = vis
        content.warnings = warnings
        return content
