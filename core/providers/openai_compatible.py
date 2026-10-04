"""Proveedor **genérico compatible con la API Chat Completions de OpenAI**.

Sirve *out-of-the-box* para:
  * OpenAI oficial
  * OpenRouter (agregador)
  * Mistral AI
  * LM Studio / LocalAI / Ollama OpenAI-compat layer
  * Groq
  * Together.ai
  * Perplexity
  * Fireworks.ai / DeepInfra / Anyscale / etc.

Todos exponen ``POST /chat/completions`` con el mismo formato estándar, y
muchos soportan ``response_format: {"type": "json_object"}`` para ``json_mode``.
"""
from __future__ import annotations

from typing import Any, Optional

import requests

from .base import (
    BaseProvider,
    ProviderConfig,
    ProviderResponse,
    RateLimitError,
    parse_retry_after,
)


_DEFAULT_BASE_URL = "https://api.openai.com/v1"


# =====================================================================
# OpenAICompatibleProvider  (clase base / genérica)
# =====================================================================
class OpenAICompatibleProvider(BaseProvider):
    """Proveedor genérico compatible con la interfaz de OpenAI."""

    PROVIDER_ID = "openai_compatible"

    def __init__(
        self,
        config: ProviderConfig,
        provider_id_override: Optional[str] = None,
        default_base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        super().__init__(config)
        if provider_id_override:
            self.PROVIDER_ID = provider_id_override
        self.base_url = (config.base_url or default_base_url).rstrip("/")
        self.api_key = (config.api_key or "").strip()
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # validate  (sin red)
    # ------------------------------------------------------------------
    def validate(self) -> None:
        if not self.model:
            raise ValueError(
                f"[{self.PROVIDER_ID}:{self.name}] Falta 'model' "
                "(ej: gpt-4o-mini, llama-3.1…)."
            )
        if not self.api_key:
            # Para servidores locales sin auth (LM Studio / LocalAI) permitimos
            # vacío siempre que la URL sea localhost / 127.0.0.1.
            is_local = (
                "localhost" in self.base_url or "127.0.0.1" in self.base_url
            )
            if not is_local:
                raise ValueError(
                    f"[{self.PROVIDER_ID}:{self.name}] Falta 'api_key'. "
                    "Define la variable de entorno correspondiente (recomendado) "
                    "o añádela en config/settings.yaml."
                )

    # ------------------------------------------------------------------
    # health_check  (red ligera)
    # ------------------------------------------------------------------
    def health_check(self) -> bool:
        """``GET /models`` corto; devuelve False ante cualquier problema."""
        try:
            resp = self._session.get(
                f"{self.base_url}/models",
                headers=self._build_headers(auth=True),
                timeout=min(5.0, float(self.config.timeout)),
            )
            return 200 <= resp.status_code < 400
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # generate  (pública, con reintentos + json_mode)
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> ProviderResponse:
        def _call_once() -> str:
            url = f"{self.base_url}/chat/completions"
            sys_msg = self._effective_system(system_prompt)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt},
            ]
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": float(self.config.temperature),
                "stream": False,
            }
            if self.config.max_tokens:
                payload["max_tokens"] = int(self.config.max_tokens)
            # json_mode nativo (soportado por OpenAI >=1106, OpenRouter,
            # Groq, y la mayoría de proveedores compatibles modernos).
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            # Payload custom via extras (top_p, frequency_penalty, etc.)
            for k, v in (self.config.extras.get("payload") or {}).items():
                payload[k] = v

            resp = self._session.post(
                url,
                json=payload,
                headers=self._build_headers(auth=True),
                timeout=float(self.config.timeout),
            )
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                detail = ""
                try:
                    err_payload = resp.json()
                    if isinstance(err_payload, dict):
                        err = err_payload.get("error")
                        if isinstance(err, dict):
                            detail = f" - {err.get('message', '')}"
                        elif isinstance(err, str):
                            detail = f" - {err}"
                except Exception:  # noqa: BLE001
                    detail = ""
                message = (
                    f"[{self.PROVIDER_ID}:{self.name}] HTTP {resp.status_code} "
                    f"en {url}{detail}"
                )
                if resp.status_code == 429:
                    raise RateLimitError(
                        message,
                        retry_after=parse_retry_after(resp, detail, resp.text),
                    ) from exc
                raise RuntimeError(message) from exc

            data = resp.json()
            return self._extract_text(data)

        text, latency_ms = self._with_retries(_call_once)
        return ProviderResponse(
            text=text,
            provider=self.PROVIDER_ID,
            model=self.model,
            latency_ms=latency_ms,
            raw=None,
        )

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------
    def _build_headers(self, auth: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if auth and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        extra_headers = self.config.extras.get("extra_headers") or {}
        headers.update(dict(extra_headers))
        return headers

    @staticmethod
    def _extract_text(data: Any) -> str:
        """Extrae el texto de una respuesta ``chat/completions``.

        Soporta:
          * ``choices[].message.content: str``  — estándar
          * ``choices[].message.content: list`` — contenido multimodal
          * ``choices[].text``                  — algunos servidores legacy
        """
        if not isinstance(data, dict):
            raise ValueError(f"Respuesta no JSON / formato inválido: {data!r}")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            err = data.get("error")
            raise ValueError(
                f"[openai_compat] Respuesta sin 'choices': {err or data}"
            )
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts: list[str] = []
                    for block in content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "text"
                        ):
                            t = block.get("text")
                            if isinstance(t, str):
                                parts.append(t)
                    return "".join(parts)
            if isinstance(first.get("text"), str):
                return str(first["text"])
        raise ValueError(
            f"[openai_compat] Formato de respuesta desconocido: {first!r}"
        )


# =====================================================================
# Especializaciones concretas (cambian PROVIDER_ID + default base_url)
# =====================================================================

class OpenAIProvider(OpenAICompatibleProvider):
    """Proveedor oficial de OpenAI (``api.openai.com``)."""

    PROVIDER_ID = "openai"

    def __init__(self, config: ProviderConfig) -> None:
        config.base_url = config.base_url or "https://api.openai.com/v1"
        super().__init__(
            config,
            provider_id_override="openai",
            default_base_url="https://api.openai.com/v1",
        )


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter — agregador multi-modelo (``openrouter.ai``)."""

    PROVIDER_ID = "openrouter"

    def __init__(self, config: ProviderConfig) -> None:
        config.base_url = config.base_url or "https://openrouter.ai/api/v1"
        super().__init__(
            config,
            provider_id_override="openrouter",
            default_base_url="https://openrouter.ai/api/v1",
        )


class MistralProvider(OpenAICompatibleProvider):
    """Mistral AI oficial (``api.mistral.ai``)."""

    PROVIDER_ID = "mistral"

    def __init__(self, config: ProviderConfig) -> None:
        config.base_url = config.base_url or "https://api.mistral.ai/v1"
        super().__init__(
            config,
            provider_id_override="mistral",
            default_base_url="https://api.mistral.ai/v1",
        )
