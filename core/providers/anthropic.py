"""Proveedor **Anthropic Claude** (https://www.anthropic.com).

Implementación directa vía ``requests`` al endpoint oficial ``/v1/messages``.
No requiere el SDK de Anthropic (así reducimos el tamaño del paquete
distribuido con PyInstaller).
"""

from __future__ import annotations

from typing import Any

import requests

from .base import (
    BaseProvider,
    ProviderConfig,
    ProviderResponse,
    RateLimitError,
    parse_retry_after,
)

_DEFAULT_BASE_URL = "https://api.anthropic.com"
_DEFAULT_MAX_TOKENS = 4096
_API_VERSION = "2023-06-01"


class AnthropicProvider(BaseProvider):
    """Proveedor Anthropic Claude (Messages API)."""

    PROVIDER_ID = "anthropic"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.base_url = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        self.api_key = (config.api_key or "").strip()
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # validate
    # ------------------------------------------------------------------
    def validate(self) -> None:
        if not self.model:
            raise ValueError("[anthropic] Falta 'model' (ej: claude-3-haiku-20240307).")
        if not self.api_key:
            raise ValueError(
                "[anthropic] Falta 'api_key'. Define la variable "
                "ANTHROPIC_API_KEY o añádela a settings.yaml."
            )

    # ------------------------------------------------------------------
    # health_check  (ligero: HEAD / GET)
    # ------------------------------------------------------------------
    def health_check(self) -> bool:
        """``GET /v1/models`` — timeout corto para no bloquear arranque."""
        try:
            resp = self._session.get(
                f"{self.base_url}/v1/models",
                headers=self._build_headers(auth=True),
                timeout=min(5.0, float(self.config.timeout)),
            )
            # Anthropic puede devolver 4xx si la key no tiene permiso para
            # /models; en ese caso consideramos "alive" si hubo respuesta HTTP
            # con código conocido (no ConnectionError).
            return resp.status_code in {200, 401, 403}
        except Exception:
            return False

    # ------------------------------------------------------------------
    # generate  (pública, con reintentos)
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> ProviderResponse:
        """``POST /v1/messages`` con backoff exponencial.

        Nota
        ----
        Anthropic no soporta ``response_format`` nativo al momento de escribir
        esto; ``json_mode`` simplemente se informa pero no fuerza nada.
        """
        del json_mode  # no soportado nativamente; silenciar unused-arg

        def _call_once() -> str:
            url = f"{self.base_url}/v1/messages"
            sys_msg = self._effective_system(system_prompt)
            max_tokens = int(self.config.max_tokens or _DEFAULT_MAX_TOKENS)
            payload: dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": float(self.config.temperature),
                "messages": [{"role": "user", "content": prompt}],
            }
            if sys_msg:
                payload["system"] = [{"type": "text", "text": sys_msg}]
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
                    err = resp.json().get("error")
                    if isinstance(err, dict):
                        detail = f" - {err.get('message', '')}"
                    elif isinstance(err, str):
                        detail = f" - {err}"
                except Exception:
                    detail = ""
                message = f"[anthropic:{self.name}] HTTP {resp.status_code} " f"en {url}{detail}"
                if resp.status_code == 429:
                    raise RateLimitError(
                        message,
                        retry_after=parse_retry_after(resp, detail, resp.text),
                    ) from exc
                raise RuntimeError(message) from exc

            data = resp.json()
            content = data.get("content")
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text")
                        if isinstance(t, str):
                            parts.append(t)
                return "".join(parts)
            err = data.get("error") if isinstance(data, dict) else None
            raise ValueError(
                f"[anthropic:{self.name}] Formato inesperado de " f"respuesta: {err or data}"
            )

        text, latency_ms = self._with_retries(_call_once)
        return ProviderResponse(
            text=text,
            provider=self.PROVIDER_ID,
            model=self.model,
            latency_ms=latency_ms,
            raw=None,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_headers(self, auth: bool = True) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-version": _API_VERSION,
        }
        if auth and self.api_key:
            headers["x-api-key"] = self.api_key
        extra_headers = self.config.extras.get("extra_headers") or {}
        headers.update(dict(extra_headers))
        return headers
