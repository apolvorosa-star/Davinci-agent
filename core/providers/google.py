"""Proveedor **Google Gemini** (https://ai.google.dev/gemini-api).

Implementación directa vía ``requests`` al endpoint
``POST /v1beta/models/{model}:generateContent``. No requiere el SDK oficial
de Google (menor footprint para distribución / PyInstaller).
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


_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"


class GoogleGeminiProvider(BaseProvider):
    """Proveedor Google Gemini (REST API ``generateContent``)."""

    PROVIDER_ID = "google"

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
            raise ValueError(
                "[google] Falta 'model' (ej: gemini-1.5-flash-latest)."
            )
        if not self.api_key:
            raise ValueError(
                "[google] Falta 'api_key'. Define la variable GOOGLE_API_KEY "
                "o añádela a settings.yaml."
            )

    # ------------------------------------------------------------------
    # health_check  (ligero: GET / HEAD sencillo)
    # ------------------------------------------------------------------
    def health_check(self) -> bool:
        """Endpoint ligero: ``GET /v1beta/models`` con la API key."""
        try:
            resp = self._session.get(
                f"{self.base_url}/v1beta/models",
                params={"key": self.api_key},
                headers=self._build_headers(auth=False),
                timeout=min(5.0, float(self.config.timeout)),
            )
            # Google puede devolver 400/403 si hay errores de cuota / proyecto
            # pero hubo respuesta HTTP; lo consideramos "vivo" (no es un
            # error de conexión).
            return resp.status_code in {200, 400, 401, 403}
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # generate
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> ProviderResponse:
        """``POST ...:generateContent`` con backoff exponencial.

        Nota
        ----
        ``json_mode`` en Gemini se puede pedir poniendo
        ``response_mime_type: "application/json"`` pero sólo en las últimas
        versiones de la API y de los modelos. Lo aplicamos como mejor
        esfuerzo.
        """

        def _call_once() -> str:
            endpoint = (
                f"{self.base_url}/v1beta/models/{self.model}:generateContent"
            )
            sys_msg = self._effective_system(system_prompt)

            contents: list[dict[str, Any]] = [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ]

            payload: dict[str, Any] = {
                "contents": contents,
                "generationConfig": {
                    "temperature": float(self.config.temperature),
                },
            }
            if self.config.max_tokens:
                payload["generationConfig"]["maxOutputTokens"] = int(
                    self.config.max_tokens
                )
            if sys_msg:
                payload["system_instruction"] = {
                    "parts": [{"text": sys_msg}]
                }
            if json_mode:
                # Best-effort: no todas las versiones / modelos lo soportan.
                payload["generationConfig"]["response_mime_type"] = (
                    "application/json"
                )
            for k, v in (self.config.extras.get("payload") or {}).items():
                payload[k] = v

            resp = self._session.post(
                endpoint,
                json=payload,
                params={"key": self.api_key},
                headers=self._build_headers(auth=False),
                timeout=float(self.config.timeout),
            )
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                detail = ""
                try:
                    err_payload = resp.json()
                    status = (err_payload.get("error") or {}).get("status", "")
                    msg = (err_payload.get("error") or {}).get("message", "")
                    detail = f" - [{status}] {msg}"
                except Exception:  # noqa: BLE001
                    detail = ""
                message = (
                    f"[google:{self.name}] HTTP {resp.status_code} "
                    f"en Gemini {endpoint}{detail}"
                )
                if resp.status_code == 429:
                    raise RateLimitError(
                        message,
                        retry_after=parse_retry_after(resp, detail, resp.text),
                    ) from exc
                raise RuntimeError(message) from exc

            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates or not isinstance(candidates, list):
                err = ""
                if isinstance(data, dict):
                    err = str((data.get("error") or {}).get("message", ""))
                raise ValueError(
                    f"[google:{self.name}] Respuesta sin 'candidates'. "
                    f"{err or data}"
                )
            first_content = (candidates[0].get("content") or {}).get("parts") or []
            parts: list[str] = []
            for part in first_content:
                if isinstance(part, dict) and "text" in part:
                    t = part.get("text")
                    if isinstance(t, str):
                        parts.append(t)
            if not parts:
                raise ValueError(
                    f"[google:{self.name}] Gemini no devolvió texto. "
                    f"Respuesta: {candidates[0]!r}"
                )
            return "".join(parts)

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
        del auth  # Google envía la key como query param; no es necesario aquí.
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        extra_headers = self.config.extras.get("extra_headers") or {}
        headers.update(dict(extra_headers))
        return headers
