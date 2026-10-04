"""Plataforma YouTube — títulos SEO, descripciones largas, capítulos y tags."""
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


# ---------------------------------------------------------------------------
# YouTubeContent
# ---------------------------------------------------------------------------
@dataclass
class YouTubeContent(PlatformContent):
    tags: list[str] = field(default_factory=list)
    capitulos: list[dict[str, str]] = field(default_factory=list)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(platform="youtube", **{k: v for k, v in kwargs.items() if k in PlatformContent.__dataclass_fields__})
        self.tags = list(kwargs.get("tags", []) or [])
        self.capitulos = list(kwargs.get("capitulos", []) or [])

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["tags"] = list(self.tags)
        d["capitulos"] = [dict(c) for c in self.capitulos]
        return d


# ---------------------------------------------------------------------------
# YouTubePlatform
# ---------------------------------------------------------------------------
class YouTubePlatform(BaseSocialPlatform):
    PLATFORM_ID = "youtube"
    DISPLAY_NAME = "YouTube"

    TITLE_CHAR_LIMIT = 100
    BODY_CHAR_LIMIT = 5000
    MAX_HASHTAGS_DEFAULT = 15  # YouTube recomienda <15 hashtags efectivos

    # ------------------------------------------------------------------
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
            "Eres un experto SEO certificado en YouTube para contenido en español. "
            "A partir de la transcripción siguiente, genera ÚNICAMENTE un JSON válido "
            "con esta estructura EXACTA (no añadas texto fuera del JSON):\n"
            "{\n"
            '  "title": "Título atractivo, máximo 100 caracteres, con palabras clave SEO front-loaded",\n'
            '  "body": "Descripción larga (mínimo 200 palabras, máximo 5000) con palabras clave, contexto, hashtags embebidos y CTA. El primer párrafo debe ser un hook de 2-3 frases. Incluye enlaces a redes sociales, timestamps si procede.",\n'
            '  "hashtags": ["hashtag1", "hashtag2", "... mínimo 8, máximo 15 hashtags SEO mezclando broad + long-tail"],\n'
            '  "tags": ["tag1", "tag2", "... 20-50 tags relevantes en español"],\n'
            '  "cta": "Call-To-Action final claro y específico (suscríbete, comenta, activa la campanita)",\n'
            '  "capitulos": [\n'
            '    {"inicio": "0:00", "titulo": "🎬 Título del capítulo"}, ...\n'
            "  ]\n"
            "}\n\n"
            "Reglas estrictas YouTube:\n"
            "- El título debe contener la palabra clave principal en los primeros 40 caracteres.\n"
            "- Usa números, emojis y paréntesis estratégicamente en el título: (2024), [GUÍA], 5 TIPS...\n"
            "- La descripción debe tener al menos 200 palabras. Los primeros 120 caracteres son el snippet visible — pon ahí el hook.\n"
            "- Los capítulos SOLO si la transcripción refleja secciones con tiempos reales. Si no, envía array vacío [].\n"
            "- Los tags son palabras/phrases exactas que la gente busca (mezcla broad + long tail en español).\n"
            "- TODO en español neutro/profesional. NUNCA inventes datos, nombres, fechas ni estadísticas que no aparezcan en la transcripción.\n"
            f"{extra_block}"
            f"{ctx}"
            f"Idioma destino: {self.config.language}\n"
            f"Tono: {self.config.tone}\n\n"
            "TRANSCRIPCIÓN:\n"
            f"{transcript}"
        )
        system = (
            "Eres un Senior YouTube Growth Strategist con 10 años de experiencia en "
            "canales en español. Cumples estrictamente todos los límites de caracteres. "
            "Respondes SÓLO con JSON, sin markdown, sin explicaciones."
        )
        return prompt, system

    # ------------------------------------------------------------------
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
                        candidate = text[start_idx: idx + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            start_idx = -1
        return {}

    def parse_response(self, raw_text: str) -> YouTubeContent:
        data = self._extract_json(raw_text)
        content = YouTubeContent(
            title=str(data.get("title") or data.get("titulo") or "").strip(),
            body=str(data.get("body") or data.get("descripcion") or "").strip(),
            cta=str(data.get("cta") or self.config.cta).strip(),
            hashtags=list(data.get("hashtags") or data.get("tags") or []),
            tags=list(data.get("tags") or []),
            capitulos=[
                dict(c) for c in (data.get("capitulos") or data.get("chapters") or [])
                if isinstance(c, dict)
            ],
        )
        # Extrae hashtags embebidos en la descripción (merge + dedupe)
        if content.body:
            embedded = content.extract_hashtags_from_text(content.body)
            merged = list(content.hashtags) + [h for h in embedded if h not in set(content.hashtags)]
            content.hashtags = merged
        return content

    # ------------------------------------------------------------------
    def validate(self, content: PlatformContent) -> YouTubeContent:
        if not isinstance(content, YouTubeContent):
            c = YouTubeContent()
            for fld in PlatformContent.__dataclass_fields__:
                if hasattr(content, fld):
                    setattr(c, fld, getattr(content, fld))
            content = c
        warnings = list(content.warnings)

        # Título: 100 chars hard limit YouTube
        title, w = content.enforce_char_limit(content.title or "", self.TITLE_CHAR_LIMIT, "title")
        content.title = title
        warnings.extend(w)

        # Body / descripción: 5000 chars hard limit
        body, w = content.enforce_char_limit(content.body or "", self.BODY_CHAR_LIMIT, "body")
        content.body = body
        warnings.extend(w)

        # CTA: 200 chars soft
        cta, w = content.enforce_char_limit(content.cta or "", 200, "cta")
        content.cta = cta
        warnings.extend(w)

        # Hashtags: max 15 + limpieza
        cleaned, w = content.clean_hashtags(content.hashtags or [], 15)
        content.hashtags = cleaned
        warnings.extend(w)

        # Tags: máximo 50 tags YouTube
        raw_tags = content.tags or []
        tags_clean: list[str] = []
        seen: set[str] = set()
        for t in raw_tags:
            s = str(t).strip().lower()
            if s and s not in seen:
                seen.add(s)
                if len(tags_clean) >= 50:
                    warnings.append("Tags excedieron límite de 50; se truncaron.")
                    break
                tags_clean.append(str(t).strip())
        content.tags = tags_clean

        # Capítulos: valida formato
        safe_chapters: list[dict[str, str]] = []
        for chap in content.capitulos or []:
            if not isinstance(chap, dict):
                continue
            inicio = str(chap.get("inicio") or chap.get("start") or "").strip()
            titulo = str(chap.get("titulo") or chap.get("title") or "").strip()
            if not inicio or not titulo:
                continue
            if not re.match(r"^\d{1,2}(:\d{1,2}){1,2}$", inicio):
                warnings.append(f"Capítulo con marca inválida ignorado: {inicio}")
                continue
            safe_chapters.append({"inicio": inicio, "titulo": titulo})
        content.capitulos = safe_chapters

        # Si no hay hashtags del todo, deduce al menos 3 del título/body
        if not content.hashtags:
            text = f"{content.title} {content.body}".lower()
            common = re.findall(r"[a-záéíóúüñ]{5,}", text)
            from collections import Counter
            top = [w for w, _ in Counter(common).most_common(3)]
            content.hashtags = top
            warnings.append("Hashtags vacíos: deducidos automáticamente desde título/descripción.")

        content.warnings = warnings
        return content
