"""Proveedor de IA local **Ollama** (https://ollama.ai).

Conecta vía HTTP local al endpoint oficial ``POST /api/generate``. No requiere
el SDK Python de Ollama; funciona con ``requests`` estándar para reducir el
tamaño del paquete distribuido (PyInstaller).
"""

from __future__ import annotations

from typing import Any

import requests

from .base import BaseProvider, ProviderConfig, ProviderResponse


class OllamaProvider(BaseProvider):
    """Implementación de :class:`BaseProvider` para Ollama local."""

    PROVIDER_ID = "ollama"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.base_url = (config.url or "http://localhost:11434").rstrip("/")
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # validate  (sin red)
    # ------------------------------------------------------------------
    def validate(self) -> None:
        """Valida que existan ``url`` y ``model``."""
        if not self.base_url:
            raise ValueError("[ollama] Falta 'url' (ej: http://localhost:11434).")
        if not self.model:
            raise ValueError("[ollama] Falta 'model' (ej: llama3, qwen2.5, deepseek-r1…).")

    # ------------------------------------------------------------------
    # health_check  (red ligera: GET /api/tags)
    # ------------------------------------------------------------------
    def health_check(self) -> bool:
        """Retorna ``True`` si el servidor Ollama local responde.

        Nunca lanza excepciones; cualquier fallo de red / timeout devuelve
        ``False``. Usa un timeout corto (5 s) para no bloquear el arranque.
        """
        try:
            resp = self._session.get(
                f"{self.base_url}/api/tags",
                timeout=min(5.0, float(self.config.timeout)),
            )
            return 200 <= resp.status_code < 400
        except Exception:
            return False

    # ------------------------------------------------------------------
    # generate  (pública, con reintentos vía _with_retries)
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> ProviderResponse:
        """``POST /api/generate`` con backoff exponencial + ``json_mode``.

        En Ollama, ``json_mode`` simplemente añade la instrucción de
        ``format: "json"`` en el payload (versiones modernas de Ollama lo
        soportan nativamente).
        """

        def _call_once() -> str:
            url = f"{self.base_url}/api/generate"
            payload: dict[str, Any] = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                # Mantener el modelo en VRAM entre llamadas (evita los ~10s de
                # carga de cada petición). Configurable vía extras.keep_alive.
                "keep_alive": self.config.extras.get("keep_alive", "30m"),
                "options": {
                    "temperature": float(self.config.temperature),
                },
            }
            sys_msg = self._effective_system(system_prompt)
            if sys_msg:
                payload["system"] = sys_msg
            if self.config.max_tokens:
                payload["options"]["num_predict"] = int(self.config.max_tokens)
            # json_mode nativo de Ollama (formato válido garantizado)
            if json_mode:
                payload["format"] = "json"

            extra_headers = self.config.extras.get("extra_headers") or {}
            response = self._session.post(
                url,
                json=payload,
                timeout=float(self.config.timeout),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    **dict(extra_headers),
                },
            )
            response.raise_for_status()
            data = response.json()
            text = data.get("response", "")
            if not isinstance(text, str):
                raise ValueError(f"Respuesta inesperada de Ollama: {data!r}")
            return text

        text, latency_ms = self._with_retries(_call_once)
        return ProviderResponse(
            text=text,
            provider=self.PROVIDER_ID,
            model=self.model,
            latency_ms=latency_ms,
            raw=None,
        )
