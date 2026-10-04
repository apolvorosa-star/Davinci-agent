"""Plataforma X (anteriormente Twitter) — hilo de tweets cortos y virales."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..base import BaseSocialPlatform, PlatformContent


@dataclass
class XTwitterContent(PlatformContent):
    main_tweet: str = ""
    thread: list[str] = field(default_factory=list)
    hashtags_per_tweet: list[list[str]] = field(default_factory=list)
    media_hint_per_tweet: list[str] = field(default_factory=list)
    engagement_cta: str = ""
    poll: dict[str, Any] | None = None

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(platform="twitter_x", **{k: v for k, v in kwargs.items() if k in PlatformContent.__dataclass_fields__})
        self.main_tweet = str(kwargs.get("main_tweet") or kwargs.get("title") or kwargs.get("tweet") or "").strip()
        self.thread = [str(x).strip() for x in (kwargs.get("thread") or kwargs.get("tweets") or []) if str(x).strip()]
        self.hashtags_per_tweet = [list(x or []) for x in (kwargs.get("hashtags_per_tweet") or [])]
        self.media_hint_per_tweet = [str(x).strip() for x in (kwargs.get("media_hint_per_tweet") or kwargs.get("media") or [])]
        self.engagement_cta = str(kwargs.get("engagement_cta") or kwargs.get("cta") or "").strip()
        poll_raw = kwargs.get("poll")
        self.poll = dict(poll_raw) if isinstance(poll_raw, dict) else None
        self.title = self.main_tweet
        self.body = "\n\n---\n\n".join([self.main_tweet] + self.thread)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["main_tweet"] = self.main_tweet
        d["thread"] = list(self.thread)
        d["hashtags_per_tweet"] = [list(x) for x in self.hashtags_per_tweet]
        d["media_hint_per_tweet"] = list(self.media_hint_per_tweet)
        d["engagement_cta"] = self.engagement_cta
        d["poll"] = dict(self.poll) if self.poll else None
        return d


class XTwitterPlatform(BaseSocialPlatform):
    PLATFORM_ID = "twitter_x"
    DISPLAY_NAME = "X / Twitter"

    TITLE_CHAR_LIMIT = 280  # hard-limit de X
    BODY_CHAR_LIMIT = 4000  # para el body compuesto
    MAX_HASHTAGS_DEFAULT = 3  # X: 1-3 hashtags por tweet óptimo

    # Límites estrictos
    TWEET_CHAR_LIMIT = 280
    MAX_THREAD_LENGTH = 15

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
            "Eres Ghostwriter senior de marcas en X (Twitter) en español. Escribes "
            "hilos que consiguen retuiteos y saves masivos. Genera SÓLO JSON:\n"
            "{\n"
            '  "main_tweet": "Tweet principal (<=280 chars). Debe ser HOOK + IDEA CLAVE. Estructura: Oración corta potente + dato/clave principal. Si es hilo, termina con 🧵👇 y la frase: \\"Hilo corto con todo lo que necesitas saber:\\"" ,\n'
            '  "thread": ["Tweet 2 (<=280 chars): punto clave 1 con ejemplo/metáfora", "Tweet 3: punto clave 2", "... de 3 a 14 tweets más, todos <=280 chars, lenguaje claro, ideas concretas. Último tweet del hilo: resumen breve + CTA de engagement (guarda, sigue, RT). NO pongas \\"Tweet N/Total\\" en cada uno; escribe el texto directamente."],\n'
            '  "hashtags": ["hashtag_global_1", "... máximo 3 hashtags GLOBALES de marca/niches (sin # repetir)"],\n'
            '  "hashtags_per_tweet": [["#por_tweet"], [".opcional"], ...], (mismo length que thread + main_tweet, o vacío),\n'
            '  "cta": "CTA de cierre global",\n'
            '  "engagement_cta": "Pregunta específica para generar comentarios en el tweet principal: \\"¿Tú qué harías? 👇 Comenta 1 palabra\\"",\n'
            '  "media_hint_per_tweet": ["imagen/vídeo/gif o vacío para el tweet 0 (main)", "hint tweet 1", ...],\n'
            '  "poll": {"opciones": ["Opción A", "Opción B", "(hasta 4 opciones)"], "duracion_horas": 24, "pregunta": "Pregunta de la encuesta para el tweet principal (<=120 chars)"} (opcional, null si no aplica)\n'
            "}\n\n"
            "Reglas X estrictas:\n"
            "- **Cada tweet individual (main + thread) NO debe superar 280 caracteres JAMÁS.**\n"
            "- Estilo: frases cortas. 1 idea por tweet. Uso estratégico de emojis (1 max por tweet).\n"
            "- Evita links si no son absolutamente necesarios; suprimen alcance orgánico.\n"
            "- Las listas con viñetas o emojis numéricos 1️⃣ 2️⃣ 3️⃣ funcionan mucho.\n"
            f"{extra_block}"
            f"{ctx}"
            f"Idioma: {self.config.language} | Tono: {self.config.tone}\n\n"
            "TRANSCRIPCIÓN:\n"
            f"{transcript}"
        )
        system = (
            "Eres escritor de hilos virales en X en español. Cumples a rajatabla los 280 caracteres "
            "por tweet — NO escribas ni uno más. Respondes SÓLO JSON válido."
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

    def parse_response(self, raw_text: str) -> XTwitterContent:
        data = self._extract_json(raw_text)
        thread_raw = [str(x).strip() for x in (data.get("thread") or data.get("tweets") or []) if str(x).strip()]
        hashtags_per = list(data.get("hashtags_per_tweet") or [])
        while len(hashtags_per) < len(thread_raw) + 1:
            hashtags_per.append([])
        hashtags_per = hashtags_per[: len(thread_raw) + 1]
        media_hints = [str(x).strip() for x in (data.get("media_hint_per_tweet") or data.get("media") or [])]
        while len(media_hints) < len(thread_raw) + 1:
            media_hints.append("")
        media_hints = media_hints[: len(thread_raw) + 1]
        poll = data.get("poll")
        if isinstance(poll, dict) and poll:
            opts_raw = poll.get("opciones") or poll.get("options") or []
            opts = [str(x).strip() for x in opts_raw if str(x).strip()]
            if opts:
                poll = {
                    "pregunta": str(poll.get("pregunta") or poll.get("question") or "").strip(),
                    "opciones": opts[:4],
                    "duracion_horas": int(poll.get("duracion_horas") or poll.get("duration_hours") or 24),
                }
            else:
                poll = None
        else:
            poll = None
        global_hashtags = list(data.get("hashtags") or [])
        content = XTwitterContent(
            main_tweet=str(data.get("main_tweet") or data.get("tweet") or data.get("title") or "").strip(),
            thread=thread_raw,
            hashtags=global_hashtags,
            hashtags_per_tweet=hashtags_per,
            media_hint_per_tweet=media_hints,
            cta=str(data.get("cta") or self.config.cta).strip(),
            engagement_cta=str(data.get("engagement_cta") or "").strip(),
            poll=poll,
        )
        return content

    def validate(self, content: PlatformContent) -> XTwitterContent:
        if not isinstance(content, XTwitterContent):
            content = XTwitterContent(
                main_tweet=getattr(content, "title", ""),
                thread=[getattr(content, "body", "")],
                hashtags=list(getattr(content, "hashtags", []) or []),
                cta=getattr(content, "cta", ""),
            )
        warnings = list(content.warnings)

        # 1) Main tweet: 280 chars HARD
        main, w = content.enforce_char_limit(content.main_tweet or "", self.TWEET_CHAR_LIMIT, "main_tweet")
        content.main_tweet = main
        content.title = main
        warnings.extend(w)
        if not content.main_tweet:
            content.main_tweet = "Hilo corto que debes leer 🧵👇"
            warnings.append("Tweet principal vacío: generado genérico.")

        # 2) Thread: limitar longitud, cada tweet <=280
        if not content.thread:
            content.thread = [content.cta or "Lee el hilo y guarda. ✅"]
            warnings.append("Hilo vacío: creado tweet de cierre genérico.")
        if len(content.thread) > self.MAX_THREAD_LENGTH:
            warnings.append(
                f"Hilo excedió {self.MAX_THREAD_LENGTH} tweets ({len(content.thread)}); se truncó."
            )
            content.thread = content.thread[: self.MAX_THREAD_LENGTH]
        safe_thread: list[str] = []
        for i, t in enumerate(content.thread):
            tweet, w = content.enforce_char_limit(t, self.TWEET_CHAR_LIMIT, f"thread[{i}]")
            if not tweet:
                tweet = f"Punto clave {i+1}."
                warnings.append(f"thread[{i}] vacío: generado genérico.")
            safe_thread.append(tweet)
            warnings.extend(w)
        content.thread = safe_thread

        # Último tweet debe tener CTA si no lo tiene
        last = content.thread[-1]
        if not any(x in last.lower() for x in ("guarda", "sigue", "rt", "retuit", "comenta", "👇", "✅", "compártelo")):
            cta_tail = " | Guarda este hilo ✅ y sígueme para más."
            merged = last + cta_tail
            if len(merged) <= self.TWEET_CHAR_LIMIT:
                content.thread[-1] = merged
            else:
                content.thread.append("Guarda este hilo ✅ y sígueme para más contenido.")
                warnings.append("Añadido tweet de CTA final al hilo.")

        # 3) Hashtags globales
        cleaned, w = content.clean_hashtags(content.hashtags or [], 3)
        content.hashtags = cleaned
        warnings.extend(w)

        # 4) Hashtags por tweet: cada array <=2
        safe_per: list[list[str]] = []
        target = len(content.thread) + 1
        raw_per = list(content.hashtags_per_tweet)
        while len(raw_per) < target:
            raw_per.append([])
        for i, tags in enumerate(raw_per[:target]):
            safe, _ = content.clean_hashtags(list(tags or []), 2)
            safe_per.append(safe)
        content.hashtags_per_tweet = safe_per

        # 5) Media hints: longitud
        safe_media = list(content.media_hint_per_tweet)
        while len(safe_media) < target:
            safe_media.append("")
        for i, m in enumerate(safe_media[:target]):
            safe_media[i], _ = content.enforce_char_limit(m, 120, f"media_hint[{i}]")
        content.media_hint_per_tweet = safe_media[:target]

        # 6) Engagement CTA
        content.engagement_cta, _ = content.enforce_char_limit(content.engagement_cta, 200, "engagement_cta")
        content.cta, _ = content.enforce_char_limit(content.cta, 200, "cta")

        # 7) Poll válido
        if content.poll:
            p = content.poll
            p["pregunta"], _ = content.enforce_char_limit(str(p.get("pregunta", "")), 120, "poll.pregunta")
            opts = [str(x).strip() for x in p.get("opciones", []) if str(x).strip()]
            opts = opts[:4]
            if len(opts) < 2:
                warnings.append("Poll con <2 opciones; eliminado.")
                content.poll = None
            else:
                for i in range(len(opts)):
                    opts[i], _ = content.enforce_char_limit(opts[i], 25, f"poll.opcion[{i}]")
                p["opciones"] = opts
                try:
                    p["duracion_horas"] = int(p.get("duracion_horas", 24))
                except (TypeError, ValueError):
                    p["duracion_horas"] = 24

        content.body = "\n\n---\n\n".join([content.main_tweet] + content.thread)
        content.warnings = warnings
        return content
