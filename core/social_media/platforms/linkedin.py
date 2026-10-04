"""Plataforma LinkedIn — publicaciones profesionales, artículos y páginas de empresa."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..base import BaseSocialPlatform, PlatformContent


@dataclass
class LinkedInContent(PlatformContent):
    headline: str = ""
    opening: str = ""
    core_story: str = ""
    key_lessons: list[str] = field(default_factory=list)
    closing_cta: str = ""
    tags: list[str] = field(default_factory=list)
    audience: dict[str, Any] = field(default_factory=dict)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(platform="linkedin", **{k: v for k, v in kwargs.items() if k in PlatformContent.__dataclass_fields__})
        self.headline = str(kwargs.get("headline") or kwargs.get("title") or "").strip()
        self.opening = str(kwargs.get("opening") or "").strip()
        self.core_story = str(kwargs.get("core_story") or kwargs.get("body") or kwargs.get("post") or "").strip()
        self.key_lessons = [str(x).strip() for x in (kwargs.get("key_lessons") or kwargs.get("lessons") or kwargs.get("takeaways") or []) if str(x).strip()]
        self.closing_cta = str(kwargs.get("closing_cta") or kwargs.get("cta") or "").strip()
        self.tags = [str(x).strip() for x in (kwargs.get("tags") or kwargs.get("hashtags") or []) if str(x).strip()]
        aud = kwargs.get("audience") or {}
        self.audience = dict(aud) if isinstance(aud, dict) else {}
        self.title = self.headline
        body_parts = [self.opening, self.core_story]
        if self.key_lessons:
            body_parts.append("Lecciones clave:\n" + "\n".join(f"  - {l}" for l in self.key_lessons))
        if self.closing_cta:
            body_parts.append(self.closing_cta)
        self.body = "\n\n".join(p for p in body_parts if p)
        self.hashtags = list(self.tags)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["headline"] = self.headline
        d["opening"] = self.opening
        d["core_story"] = self.core_story
        d["key_lessons"] = list(self.key_lessons)
        d["closing_cta"] = self.closing_cta
        d["tags"] = list(self.tags)
        d["audience"] = dict(self.audience)
        return d


class LinkedInPlatform(BaseSocialPlatform):
    PLATFORM_ID = "linkedin"
    DISPLAY_NAME = "LinkedIn"

    TITLE_CHAR_LIMIT = 200
    BODY_CHAR_LIMIT = 3000  # LinkedIn: 3000 chars ideal; max 12500 (pero "ver más")
    MAX_HASHTAGS_DEFAULT = 8

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
            "Eres Ghostwriter de fundadores y directivos en LinkedIn en español. "
            "Escribes publicaciones de 1500-3000 caracteres que generan comentarios y compartidos. "
            "Genera SÓLO JSON:\n"
            "{\n"
            '  "headline": "Hook / opening line (<=200 chars). Frase corta con promesa clara o pregunta retórica. Sin emojis. Ejemplos: \\"Nadie te enseña esto en la universidad.\\" \\"Trabajé 10 años en consultora y estas son las 3 mentiras que me vendieron.\\" \\"Hace 5 años mi jefe me dijo una frase que me cambió la carrera.\\"",\n'
            '  "title": "(alias headline, opcional)",\n'
            '  "opening": "Párrafo de apertura (2-4 frases). Estructura storytelling: plantear una situación personal, un dolor o una pregunta. NO desvelar el final.",\n'
            '  "core_story": "Historia principal + argumento. 3-5 párrafos cortos. Alterna: 1 párrafo narrativo → 1 párrafo reflexión/clase. Usa detalles concretos (fechas, números, nombres de puestos). Usa la regla del \\"3\\" para estructurar puntos.",\n'
            '  "body": "(alias core_story opcional)",\n'
            '  "key_lessons": ["Lección 1: frase concreta accionable", "Lección 2: ...", "... 3 a 7 lecciones ENUMERADAS y ACCIONABLES. Cada una debe ser una instrucción específica que el lector pueda aplicar HOY."],\n'
            '  "closing_cta": "Párrafo de cierre (<=400 chars): resume el mensaje principal + pregunta ABIERTA para generar comentarios. Las preguntas que más comentarios generan piden OPINION PERSONAL o una EXPERIENCIA concreta del lector. Termina con \\"Me gustaría leer tu opinión en los comentarios 👇\\" o similar.",\n'
            '  "hashtags": ["hashtag1", "... 5-8 hashtags profesionales en minúsculas. Prefiere hashtags medianos (10K-500K seguidores). Evita genericos como #empleo #trabajo si no son el núcleo."],\n'
            '  "tags": "(alias hashtags)",\n'
            '  "cta": "(alias closing_cta)",\n'
            '  "audience": {\n'
            '    "seniority": ["Junior", "Mid", "Senior", "Directivo", "Fundador"], (elige 2-4 segmentos objetivo)\n'
            '    "sectores": ["tecnologia", "finanzas", "marketing", "recursos-humanos", "ventas", "consultoria", "..."],\n'
            '    "objetivo": "engagement | branding_personal | trafico | leads"\n'
            "  }\n"
            "}\n\n"
            "Reglas LinkedIn estrictas:\n"
            "- SIN EMOJIS de más. 1 emoji por sección máximo. LinkedIn prefiere tono sobrio pero humano.\n"
            "- NUNCA pidas like/follow/republique. Pide COMPARTIR IDEA en comentarios.\n"
            "- La estructura story → reflexión → lecciones → pregunta es probada y convertió millones de veces.\n"
            f"{extra_block}"
            f"{ctx}"
            f"Idioma: {self.config.language} | Tono: {self.config.tone}\n\n"
            "TRANSCRIPCIÓN:\n"
            f"{transcript}"
        )
        system = (
            "Eres escritor sénior de contenido B2B y LinkedIn. Cumples límites de caracteres. "
            "Sólo respondes con JSON válido."
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

    def parse_response(self, raw_text: str) -> LinkedInContent:
        data = self._extract_json(raw_text)
        aud = data.get("audience") or {}
        if isinstance(aud, dict):
            safe_aud: dict[str, Any] = {}
            for k_list in ("seniority", "sectores"):
                l = aud.get(k_list) or []
                if isinstance(l, list):
                    safe_aud[k_list] = [str(x).strip() for x in l if str(x).strip()][:15]
            obj = str(aud.get("objetivo") or "engagement").strip()
            if obj in {"engagement", "branding_personal", "trafico", "leads", "branding"}:
                safe_aud["objetivo"] = obj
            else:
                safe_aud["objetivo"] = "engagement"
        else:
            safe_aud = {"objetivo": "engagement"}
        lessons = [str(x).strip() for x in (data.get("key_lessons") or data.get("lessons") or data.get("takeaways") or []) if str(x).strip()]
        cta = str(data.get("closing_cta") or data.get("cta") or self.config.cta).strip()
        hashtags = list(data.get("hashtags") or data.get("tags") or [])
        return LinkedInContent(
            headline=str(data.get("headline") or data.get("title") or "").strip(),
            opening=str(data.get("opening") or "").strip(),
            core_story=str(data.get("core_story") or data.get("body") or data.get("post") or "").strip(),
            key_lessons=lessons,
            closing_cta=cta,
            hashtags=hashtags,
            tags=list(hashtags),
            audience=safe_aud,
        )

    def validate(self, content: PlatformContent) -> LinkedInContent:
        if not isinstance(content, LinkedInContent):
            content = LinkedInContent(
                headline=getattr(content, "title", ""),
                core_story=getattr(content, "body", ""),
                key_lessons=[],
                closing_cta=getattr(content, "cta", ""),
                hashtags=list(getattr(content, "hashtags", []) or []),
            )
        warnings = list(content.warnings)

        headline, w = content.enforce_char_limit(content.headline or "", 200, "headline")
        content.headline = headline
        content.title = headline
        warnings.extend(w)
        if not content.headline:
            content.headline = "Esto cambió mi forma de trabajar."
            content.title = content.headline
            warnings.append("Headline LinkedIn vacío: generado genérico.")

        opening, _ = content.enforce_char_limit(content.opening or "", 1500, "opening")
        content.opening = opening
        story, w = content.enforce_char_limit(content.core_story or "", self.BODY_CHAR_LIMIT, "core_story")
        content.core_story = story
        warnings.extend(w)

        # Longitud total del post
        total_body = len(content.opening) + len(content.core_story)
        if total_body < 500:
            warnings.append(f"Post LinkedIn muy corto ({total_body} chars). Óptimo 1500-3000.")

        closing, w = content.enforce_char_limit(content.closing_cta or "", 600, "closing_cta")
        content.closing_cta = closing
        content.cta = closing
        warnings.extend(w)
        if not any(x in content.closing_cta.lower() for x in ("coment", "opin", "crees", "tu", "ti", "👇")):
            if len(content.closing_cta) + 150 < 600:
                content.closing_cta = (
                    (content.closing_cta + "\n\n" if content.closing_cta else "")
                    + "¿Tú lo has vivido en tu carrera? Cuéntame tu experiencia en los comentarios 👇"
                )
                warnings.append("CTA LinkedIn no contenía pregunta abierta; añadida.")
            content.cta = content.closing_cta

        cleaned, w = content.clean_hashtags(content.tags or content.hashtags or [], self.effective_max_hashtags)
        content.tags = cleaned
        content.hashtags = cleaned
        warnings.extend(w)

        # Key lessons: 3-7
        if not content.key_lessons:
            warnings.append("Key lessons vacías: deducidas desde core_story.")
            sents = re.split(r"[.!?]\s+|\n+", content.core_story or "")
            lessons = [s.strip() for s in sents if 40 < len(s.strip()) < 250][:5]
            content.key_lessons = lessons or ["Lección clave 1", "Lección clave 2", "Lección clave 3"]
        for i, l in enumerate(content.key_lessons):
            content.key_lessons[i], _ = content.enforce_char_limit(l, 300, f"key_lesson[{i}]")
        if len(content.key_lessons) > 10:
            content.key_lessons = content.key_lessons[:10]
            warnings.append("Key lessons >10; truncadas.")

        if not content.audience:
            content.audience = {"objetivo": "engagement"}

        # Rebuild body
        body_parts = [content.opening, content.core_story]
        if content.key_lessons:
            body_parts.append("Lecciones clave:\n" + "\n".join(f"  - {l}" for l in content.key_lessons))
        if content.closing_cta:
            body_parts.append(content.closing_cta)
        content.body = "\n\n".join(p for p in body_parts if p)
        content.warnings = warnings
        return content
