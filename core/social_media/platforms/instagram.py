"""Plataforma Instagram — feed post, stories (5-10), reels caption y hashtags."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..base import (
    BaseSocialPlatform,
    PlatformContent,
    SocialMediaPlatformError,
)


@dataclass
class InstagramStory:
    texto: str = ""
    sticker_sugerido: str = "encuesta"
    duracion_segundos: int = 15
    imagen_prompt: str = ""
    formato: str = "vertical 9:16"


@dataclass
class InstagramReel:
    caption: str = ""
    hook: str = ""
    hashtags: list[str] = field(default_factory=list)
    audio_sugerido: str = "trending audio"


@dataclass
class InstagramContent(PlatformContent):
    feed_caption: str = ""
    carousel_items: list[str] = field(default_factory=list)
    stories: list[InstagramStory] = field(default_factory=list)
    reel: InstagramReel | None = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(platform="instagram", **{k: v for k, v in kwargs.items() if k in PlatformContent.__dataclass_fields__})
        self.feed_caption = str(kwargs.get("feed_caption") or kwargs.get("body") or "").strip()
        self.carousel_items = list(kwargs.get("carousel_items") or [])
        parsed_stories: list[InstagramStory] = []
        for s in (kwargs.get("stories") or []):
            if isinstance(s, InstagramStory):
                parsed_stories.append(s)
            elif isinstance(s, dict):
                try:
                    dur_raw = s.get("duracion_segundos", 15)
                    dur = int(dur_raw) if isinstance(dur_raw, (int, float, str)) and str(dur_raw).strip() else 15
                except (TypeError, ValueError):
                    dur = 15
                parsed_stories.append(InstagramStory(
                    texto=str(s.get("texto") or s.get("text") or "").strip(),
                    sticker_sugerido=str(s.get("sticker_sugerido") or s.get("sticker") or "encuesta").strip(),
                    duracion_segundos=max(3, min(dur, 15)),
                    imagen_prompt=str(s.get("imagen_prompt") or s.get("visual") or "").strip(),
                    formato=str(s.get("formato") or "vertical 9:16").strip(),
                ))
        self.stories = parsed_stories
        reel = kwargs.get("reel")
        if reel is None:
            self.reel = None
        elif isinstance(reel, InstagramReel):
            self.reel = reel
        elif isinstance(reel, dict):
            self.reel = InstagramReel(
                caption=str(reel.get("caption") or ""),
                hook=str(reel.get("hook") or ""),
                hashtags=list(reel.get("hashtags") or []),
                audio_sugerido=str(reel.get("audio_sugerido") or "trending audio"),
            )
        else:
            self.reel = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["feed_caption"] = self.feed_caption
        d["carousel_items"] = list(self.carousel_items)
        d["stories"] = [
            {"texto": s.texto, "sticker_sugerido": s.sticker_sugerido,
             "duracion_segundos": s.duracion_segundos,
             "imagen_prompt": s.imagen_prompt, "formato": s.formato}
            for s in self.stories
        ]
        d["reel"] = {
            "caption": self.reel.caption,
            "hook": self.reel.hook,
            "hashtags": list(self.reel.hashtags),
            "audio_sugerido": self.reel.audio_sugerido,
        } if self.reel else None
        return d


class InstagramPlatform(BaseSocialPlatform):
    PLATFORM_ID = "instagram"
    DISPLAY_NAME = "Instagram"

    TITLE_CHAR_LIMIT = 125  # caption preview
    BODY_CHAR_LIMIT = 2200  # caption hard limit IG
    MAX_HASHTAGS_DEFAULT = 30

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
            "Eres un Community Manager experto en Instagram en español. Genera "
            "ÚNICAMENTE un JSON con esta estructura EXACTA:\n"
            "{\n"
            '  "title": "Hook/headline corto de la publicación",\n'
            '  "feed_caption": "Caption completo para feed (2200 chars máx.). Usa emojis, estructura: 1) Hook 2-3 líneas. 2) Valor/contenido. 3) CTA. 4) Separador \\n\\n. y hashtags al final (no cuenten en los 30 hashtags del campo hashtags).',
            '  "body": "Alias de feed_caption" (puedes usar este campo también),\n'
            '  "carousel_items": ["Texto slide 1", "slide 2", "slide 3", "..." de 3 a 10 slides cada uno con título + 1-2 frases],\n'
            '  "hashtags": ["hashtag1", "... 25-30 hashtags mezclando: 3 branded, 10 niche, 10 medium, 5 large. Todos en minúsculas sin espacios."],\n'
            '  "cta": "CTA específico de Instagram (guarda, comenta, comparte, DM, link en bio)",\n'
            '  "stories": [\n'
            '    {"texto": "Story 1: hook/encabezado corto, max 20 palabras, texto para sobreponer en vídeo/imagen", "sticker_sugerido": "encuesta|quiz|link|ubicacion|hashtag|mencion", "duracion_segundos": 15, "imagen_prompt": "descripción visual para IA generadora", "formato": "vertical 9:16"}, ... (5 a 10 stories)\n'
            "  ],\n"
            '  "reel": {\n'
            '    "hook": "Hook viral de 3-7 palabras para los primeros 3 segundos del reel",\n'
            '    "caption": "Caption completo del reel (<2200 chars, con emojis y CTA)",\n'
            '    "hashtags": ["reel_hashtag1", "... 10-20 hashtags específicos de reels"],\n'
            '    "audio_sugerido": "Tipo de audio: trending audio | voz en off | efecto sonoro | música épica..."\n'
            "  }\n"
            "}\n\n"
            "Reglas Instagram estrictas:\n"
            "- NADA de links en el caption (excepto link en bio en el CTA).\n"
            "- Usa emojis relevantes con moderación (no más de 1 emoji cada 2-3 líneas).\n"
            "- Las stories deben ser una secuencia narrativa: Hook → Valor → CTA.\n"
            "- El reel.hook debe hacer que la gente PARE de scrollear en 3 seg. (pregunta, contraste, dato sorprendente).\n"
            f"{extra_block}"
            f"{ctx}"
            f"Idioma: {self.config.language} | Tono: {self.config.tone}\n\n"
            "TRANSCRIPCIÓN:\n"
            f"{transcript}"
        )
        system = (
            "Eres Instagram Growth Manager senior especializado en contenido viral "
            "en español. Cumples estrictamente los límites: caption <=2200, hashtags <=30. "
            "Respondes SÓLO con JSON válido."
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
                            return json.loads(text[start_idx: idx + 1])
                        except json.JSONDecodeError:
                            start_idx = -1
        return {}

    def parse_response(self, raw_text: str) -> InstagramContent:
        data = self._extract_json(raw_text)
        caption = str(data.get("feed_caption") or data.get("body") or data.get("caption") or "").strip()
        stories_raw = data.get("stories") or []
        stories: list[InstagramStory] = []
        valid_stickers = {"encuesta", "quiz", "link", "ubicacion", "hashtag", "mencion", "pegatina", "sliders", "pregunta"}
        for s in stories_raw:
            if not isinstance(s, dict):
                continue
            sticker = str(s.get("sticker_sugerido") or s.get("sticker") or "encuesta").lower()
            if sticker not in valid_stickers:
                sticker = "encuesta"
            try:
                dur = int(s.get("duracion_segundos", 15))
            except (TypeError, ValueError):
                dur = 15
            dur = max(3, min(dur, 15))
            stories.append(InstagramStory(
                texto=str(s.get("texto") or s.get("text") or "").strip(),
                sticker_sugerido=sticker,
                duracion_segundos=dur,
                imagen_prompt=str(s.get("imagen_prompt") or s.get("visual") or "").strip(),
                formato=str(s.get("formato") or "vertical 9:16").strip(),
            ))
        reel_raw = data.get("reel")
        reel = None
        if isinstance(reel_raw, dict) and reel_raw:
            reel = InstagramReel(
                caption=str(reel_raw.get("caption") or "").strip(),
                hook=str(reel_raw.get("hook") or "").strip(),
                hashtags=list(reel_raw.get("hashtags") or []),
                audio_sugerido=str(reel_raw.get("audio_sugerido") or "trending audio").strip(),
            )
        content = InstagramContent(
            title=str(data.get("title") or "").strip(),
            body=caption,
            feed_caption=caption,
            cta=str(data.get("cta") or self.config.cta).strip(),
            hashtags=list(data.get("hashtags") or []),
            carousel_items=[str(x).strip() for x in (data.get("carousel_items") or data.get("carousel") or []) if str(x).strip()],
            stories=stories,
            reel=reel,
        )
        return content

    def validate(self, content: PlatformContent) -> InstagramContent:
        if not isinstance(content, InstagramContent):
            content = InstagramContent(
                title=getattr(content, "title", ""),
                body=getattr(content, "body", ""),
                hashtags=list(getattr(content, "hashtags", []) or []),
                cta=getattr(content, "cta", ""),
            )
        warnings = list(content.warnings)

        cap = content.feed_caption or content.body or ""
        cap, w = content.enforce_char_limit(cap, self.BODY_CHAR_LIMIT, "feed_caption")
        content.feed_caption = cap
        content.body = cap
        warnings.extend(w)

        title, w = content.enforce_char_limit(content.title or "", self.TITLE_CHAR_LIMIT, "title")
        content.title = title
        warnings.extend(w)

        cta, w = content.enforce_char_limit(content.cta or "", 200, "cta")
        content.cta = cta
        warnings.extend(w)

        cleaned, w = content.clean_hashtags(content.hashtags or [], self.effective_max_hashtags)
        content.hashtags = cleaned
        warnings.extend(w)

        # Carousel: 3-10 items máximo
        if not content.carousel_items:
            content.carousel_items = [content.title or "Slide 1"]
            warnings.append("Carousel vacío: creado desde el título.")
        if len(content.carousel_items) > 10:
            warnings.append(f"Carousel excedió 10 slides ({len(content.carousel_items)}); se truncó.")
            content.carousel_items = content.carousel_items[:10]
        for i, item in enumerate(content.carousel_items):
            t, _ = content.enforce_char_limit(str(item), 200, f"carousel[{i}]")
            content.carousel_items[i] = t

        # Stories: 5-10
        if len(content.stories) < 3:
            warnings.append(f"Stories insuficientes ({len(content.stories)}); se completaron hasta 5.")
            base_hooks = ["🤯 ¿Sabías que...", "💡 Tip clave", "⚠️ No cometas este error", "✅ Haz esto hoy", "👉 Siguiente paso"]
            while len(content.stories) < 5:
                idx = len(content.stories)
                content.stories.append(InstagramStory(
                    texto=base_hooks[idx % len(base_hooks)] + " " + (content.title or ""),
                    sticker_sugerido="encuesta",
                    duracion_segundos=15,
                ))
        elif len(content.stories) > 15:
            warnings.append(f"Stories excedieron 15 ({len(content.stories)}); se truncaron.")
            content.stories = content.stories[:15]
        for s in content.stories:
            s.texto, _ = content.enforce_char_limit(s.texto, 200, "story.texto")
            s.imagen_prompt, _ = content.enforce_char_limit(s.imagen_prompt, 250, "story.imagen_prompt")

        # Reel: si no existe, crea uno mínimo
        if content.reel is None:
            content.reel = InstagramReel(
                hook=content.title[:50] if content.title else "Mira esto 👉",
                caption=cap[:1500],
                hashtags=list(content.hashtags[:15]),
                audio_sugerido="voz en off",
            )
            warnings.append("Reel vacío: generado automáticamente desde feed.")
        else:
            r = content.reel
            r.hook, _ = content.enforce_char_limit(r.hook, 100, "reel.hook")
            r.caption, _ = content.enforce_char_limit(r.caption, 2200, "reel.caption")
            r.audio_sugerido, _ = content.enforce_char_limit(r.audio_sugerido, 100, "reel.audio_sugerido")
            rh, _ = content.clean_hashtags(r.hashtags, 20)
            r.hashtags = rh
        content.warnings = warnings
        return content
