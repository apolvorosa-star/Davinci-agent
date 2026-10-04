"""Plataforma Facebook — publicación para página/grupo, descripción larga y segmentación."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..base import BaseSocialPlatform, PlatformContent


@dataclass
class FacebookContent(PlatformContent):
    caption: str = ""
    headline: str = ""
    link_title: str = ""
    link_description: str = ""
    summary_points: list[str] = field(default_factory=list)
    audience_hints: dict[str, Any] = field(default_factory=dict)
    first_comment: str = ""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(platform="facebook", **{k: v for k, v in kwargs.items() if k in PlatformContent.__dataclass_fields__})
        self.caption = str(kwargs.get("caption") or kwargs.get("body") or kwargs.get("post") or "").strip()
        self.headline = str(kwargs.get("headline") or kwargs.get("title") or "").strip()
        self.link_title = str(kwargs.get("link_title") or "").strip()
        self.link_description = str(kwargs.get("link_description") or "").strip()
        self.summary_points = [str(x).strip() for x in (kwargs.get("summary_points") or kwargs.get("key_points") or []) if str(x).strip()]
        aud = kwargs.get("audience_hints") or kwargs.get("audience") or {}
        self.audience_hints = dict(aud) if isinstance(aud, dict) else {}
        self.first_comment = str(kwargs.get("first_comment") or "").strip()
        self.title = self.headline or self.caption[:120]
        self.body = self.caption

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["caption"] = self.caption
        d["headline"] = self.headline
        d["link_title"] = self.link_title
        d["link_description"] = self.link_description
        d["summary_points"] = list(self.summary_points)
        d["audience_hints"] = dict(self.audience_hints)
        d["first_comment"] = self.first_comment
        return d


class FacebookPlatform(BaseSocialPlatform):
    PLATFORM_ID = "facebook"
    DISPLAY_NAME = "Facebook"

    TITLE_CHAR_LIMIT = 120  # headline visible en link preview
    BODY_CHAR_LIMIT = 63206  # hard limit Facebook (pero >2000 se corta con "ver más")
    MAX_HASHTAGS_DEFAULT = 10  # Facebook: 5-10 óptimos

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
            "Eres Community Manager senior de páginas de Facebook profesionales en español. "
            "Escribe publicaciones con alto alcance orgánico. Genera SÓLO JSON:\n"
            "{\n"
            '  "headline": "Headline/gancho visible (<=120 chars). Frase corta atractiva.",\n'
            '  "title": "(alias headline, opcional)",\n'
            '  "caption": "Publicación principal. Estructura Facebook: 1) HOOK párrafo 1 (2-3 frases cortas). 2) Desarrollo en párrafos cortos separados por \\n\\n. 3) Lista 3-5 bullet points con emojis ▶️✅❌. 4) Párrafo CTA final. Longitud total entre 800 y 1800 palabras. Usa un tono conversacional, cercano y de experto.",\n'
            '  "body": "(alias caption opcional)",\n'
            '  "hashtags": ["hashtag1", "... 5-10 hashtags relevantes en minúsculas. Mezcla marca + nicho + amplio."],\n'
            '  "cta": "CTA final claro: Comenta \'INTERESADO\', haz clic en el link, comparte con alguien que lo necesite, guarda la publicación.",\n'
            '  "link_title": "Título del link adjunto (<=100 chars si hubiera link)",\n'
            '  "link_description": "Descripción breve del link (<=200 chars)",\n'
            '  "summary_points": ["Punto clave resumido 1", "2", "3", "... 3 a 6 bullets cortos para resumen visual del post."],\n'
            '  "first_comment": "Comentario pinneado del propio creador: añade valor extra, link o pregunta para generar engagement.",\n'
            '  "audience_hints": {\n'
            '    "edad_minima": 18, "edad_maxima": 65,\n'
            '    "paises": ["España", "México", "Colombia", "Argentina", "Chile", "Perú"],\n'
            '    "intereses": ["palabra clave 1", "palabra clave 2"],\n'
            '    "objetivo": "engagement | trafico | conversiones | awareness"\n'
            "  }\n"
            "}\n\n"
            "Reglas Facebook estrictas:\n"
            "- Facebook penaliza el clickbait directo. El hook debe prometer valor y entregar valor.\n"
            "- Usa emojis en bullet points; párrafos cortos de 2-3 frases máximo.\n"
            "- La publicación debe dar TANTO valor que la gente sienta que debe compartirla.\n"
            f"{extra_block}"
            f"{ctx}"
            f"Idioma: {self.config.language} | Tono: {self.config.tone}\n\n"
            "TRANSCRIPCIÓN:\n"
            f"{transcript}"
        )
        system = (
            "Eres estratega de contenido certificado en Meta Blueprint. Escribes publicaciones "
            "largas pero bien estructuradas en español, sin clickbait, con valor real. "
            "Sólo respondes con JSON."
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

    def parse_response(self, raw_text: str) -> FacebookContent:
        data = self._extract_json(raw_text)
        aud = data.get("audience_hints") or {}
        if isinstance(aud, dict):
            safe_aud: dict[str, Any] = {}
            for k in ("edad_minima", "edad_maxima"):
                try:
                    v = aud.get(k)
                    if v is not None:
                        safe_aud[k] = int(v)
                except (TypeError, ValueError):
                    pass
            for k_list in ("paises", "intereses"):
                l = aud.get(k_list) or []
                if isinstance(l, list):
                    safe_aud[k_list] = [str(x).strip() for x in l if str(x).strip()][:20]
            obj = str(aud.get("objetivo") or "engagement").strip()
            if obj in {"engagement", "trafico", "conversiones", "awareness", "traffic", "leads"}:
                safe_aud["objetivo"] = obj
            else:
                safe_aud["objetivo"] = "engagement"
        else:
            safe_aud = {"objetivo": "engagement"}
        return FacebookContent(
            headline=str(data.get("headline") or data.get("title") or "").strip(),
            caption=str(data.get("caption") or data.get("body") or data.get("post") or "").strip(),
            cta=str(data.get("cta") or self.config.cta).strip(),
            hashtags=list(data.get("hashtags") or []),
            link_title=str(data.get("link_title") or "").strip(),
            link_description=str(data.get("link_description") or "").strip(),
            summary_points=[str(x).strip() for x in (data.get("summary_points") or data.get("key_points") or []) if str(x).strip()],
            first_comment=str(data.get("first_comment") or "").strip(),
            audience_hints=safe_aud,
        )

    def validate(self, content: PlatformContent) -> FacebookContent:
        if not isinstance(content, FacebookContent):
            content = FacebookContent(
                headline=getattr(content, "title", ""),
                caption=getattr(content, "body", ""),
                hashtags=list(getattr(content, "hashtags", []) or []),
                cta=getattr(content, "cta", ""),
            )
        warnings = list(content.warnings)

        headline, w = content.enforce_char_limit(content.headline or "", 120, "headline")
        content.headline = headline
        content.title = headline
        warnings.extend(w)
        if not content.headline:
            content.headline = "Descubre esto hoy 👉"
            content.title = content.headline
            warnings.append("Headline vacío: generado genérico.")

        caption, w = content.enforce_char_limit(content.caption or "", self.BODY_CHAR_LIMIT, "caption")
        content.caption = caption
        content.body = caption
        warnings.extend(w)
        if len(content.caption) < 200:
            warnings.append(f"Caption Facebook muy corto ({len(content.caption)} chars). Facebook prefiere 800-1800 chars para alcance.")

        cta, w = content.enforce_char_limit(content.cta or "", 300, "cta")
        content.cta = cta
        warnings.extend(w)

        cleaned, w = content.clean_hashtags(content.hashtags or [], self.effective_max_hashtags)
        content.hashtags = cleaned
        warnings.extend(w)

        content.link_title, _ = content.enforce_char_limit(content.link_title, 100, "link_title")
        content.link_description, _ = content.enforce_char_limit(content.link_description, 200, "link_description")
        content.first_comment, _ = content.enforce_char_limit(content.first_comment, 1000, "first_comment")

        # Summary points: 3-6
        if not content.summary_points:
            warnings.append("Summary points vacíos: deducidos desde caption.")
            sentences = re.split(r"[.!?]\s+|\n+", content.caption or "")
            pts = [s.strip() for s in sentences if 20 < len(s.strip()) < 120][:6]
            content.summary_points = pts or ["Resumen 1", "Resumen 2", "Resumen 3"]
        if len(content.summary_points) > 8:
            content.summary_points = content.summary_points[:8]
            warnings.append("Summary points >8; truncados.")
        for i, p in enumerate(content.summary_points):
            content.summary_points[i], _ = content.enforce_char_limit(p, 200, f"summary_point[{i}]")

        # Audience defaults mínimos
        if not content.audience_hints:
            content.audience_hints = {"objetivo": "engagement"}
        content.warnings = warnings
        return content
