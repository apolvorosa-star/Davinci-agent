"""Clase base abstracta y helpers compartidos para todos los proveedores de IA.

Definiciones clave
------------------
:class:`BaseProvider`
    Interfaz que **deben** implementar todos los proveedores concretos.
    Todos los métodos públicos abstractos (``generate``, ``health_check``,
    ``validate``) permiten tratar a los proveedores de forma polimórfica.

:class:`ProviderConfig`
    Configuración normalizada inyectada a cada proveedor (una única fuente de
    verdad para ``model``, ``api_key``, ``timeout``, ``max_retries``...).

:class:`ProviderResponse`
    Valor de retorno estándar de ``generate()``: texto plano + metadata de
    trazabilidad (proveedor, modelo, latencia, payload raw si aplica).

Compatibilidad hacia atrás
--------------------------
``expand_env_vars`` se re-exporta aquí (aunque su implementación viva ahora en
:mod:`core.providers.env_loader`) para no romper código antiguo que la importe
directamente desde ``base.py``.
"""
from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .env_loader import expand_env_vars  # noqa: F401  (re-export)


# Espera máxima que _with_retries aceptará de un hint "Retry-After".
# Pasado este tope se prefiere fallar y saltar al siguiente proveedor de
# la fallback chain que bloquear el pipeline durante minutos.
_MAX_RATE_LIMIT_WAIT_S = 300.0

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ProviderConfig  -  configuración normalizada
# ---------------------------------------------------------------------------
@dataclass
class ProviderConfig:
    """Configuración normalizada que recibe cada proveedor.

    Se construye a partir del diccionario tal cual sale del YAML (validado,
    con variables de entorno expandidas) vía :meth:`from_dict`.
    """

    name: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    url: str | None = None
    system_prompt: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout: float = 600.0
    max_retries: int = 3
    extras: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(
        name: str,
        raw: dict[str, Any],
        ai_root_cfg: dict[str, Any] | None = None,
    ) -> "ProviderConfig":
        """Factoría que construye una ``ProviderConfig`` desde dict/YAML.

        - Expandirá **aquí** todas las variables de entorno ``${VAR}`` (así
          no se expanden en proveedores ``enabled:false`` que tengan
          ``${API_KEY}`` sin definir).
        - Toma valores por defecto desde ``ai_root_cfg`` (bloque ``ai:`` de
          ``settings.yaml``) para ``temperature``, ``timeout``, ``max_retries``.
        - Mantiene compatibilidad hacia atrás con claves antiguas como
          ``request_timeout`` (equivalente a ``timeout``).
        """
        raw_expanded: dict[str, Any] = expand_env_vars(raw or {})
        ai_root_cfg = ai_root_cfg or {}

        # Backward compat: el yaml viejo usaba "request_timeout" en vez de
        # "timeout". Aceptamos ambos, "timeout" tiene prioridad.
        global_timeout = ai_root_cfg.get(
            "timeout", ai_root_cfg.get("request_timeout", 600)
        )
        global_max_retries = int(ai_root_cfg.get("max_retries", 3))
        global_temperature = float(ai_root_cfg.get("temperature", 0.0))

        raw_timeout = raw_expanded.get(
            "timeout", raw_expanded.get("request_timeout", global_timeout)
        )

        return ProviderConfig(
            name=name,
            model=str(raw_expanded.get("model")),
            api_key=raw_expanded.get("api_key"),
            base_url=raw_expanded.get("base_url") or raw_expanded.get("url"),
            url=raw_expanded.get("url") or raw_expanded.get("base_url"),
            system_prompt=raw_expanded.get("system_prompt"),
            temperature=float(
                raw_expanded.get("temperature", global_temperature)
            ),
            max_tokens=raw_expanded.get("max_tokens"),
            timeout=float(raw_timeout),
            max_retries=int(
                raw_expanded.get("max_retries", global_max_retries)
            ),
            extras={
                k: v
                for k, v in raw_expanded.items()
                if k
                not in {
                    "enabled",
                    "model",
                    "api_key",
                    "base_url",
                    "url",
                    "system_prompt",
                    "temperature",
                    "max_tokens",
                    "timeout",
                    "request_timeout",
                    "max_retries",
                }
            },
        )


# ---------------------------------------------------------------------------
# ProviderResponse  -  valor de retorno estándar de generate()
# ---------------------------------------------------------------------------
@dataclass
class ProviderResponse:
    """Respuesta estandarizada de cualquier proveedor de IA.

    Fields:
        text:       Texto final (ya stripped, sin artefactos JSON).
        provider:   ID constante del proveedor (``PROVIDER_ID``, p.ej. ``"openai"``).
        model:      Nombre del modelo que realmente respondió (útil en
                    OpenRouter / agregadores que pueden redirigir).
        latency_ms: Milisegundos transcurridos entre petición y respuesta.
        raw:        Payload JSON tal cual devolvió la API (``None`` si no
                    aplica; útil para debugging).
    """

    text: str
    provider: str
    model: str
    latency_ms: int
    raw: Any = None

    def __str__(self) -> str:  # pragma: no cover - helper trivial
        return self.text


# ---------------------------------------------------------------------------
# RateLimitError  -  HTTP 429 con espera sugerida por el servidor
# ---------------------------------------------------------------------------
class RateLimitError(RuntimeError):
    """El proveedor respondió HTTP 429 / rate-limit.

    ``retry_after`` (segundos) refleja la espera sugerida por el servidor
    (cabecera ``Retry-After`` o mensajes tipo ``Soonest reset ~Ns`` de
    proxies de LLM). :meth:`BaseProvider._with_retries` la respeta para no
    quemar los reintentos en segundos mientras el cooldown sigue activo.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


_RESET_HINT_RE = re.compile(
    r"(?:soonest\s+)?reset[^0-9]{0,20}?(\d+)\s*s", re.IGNORECASE
)


def parse_retry_after(resp: Any, *texts: str) -> float | None:
    """Extrae los segundos sugeridos antes de reintentar tras un 429.

    Orden de búsqueda:
    1. Cabecera ``Retry-After`` (formato numérico en segundos).
    2. Texto del error: patrones tipo ``Soonest reset: ~72s`` que emiten
       algunos proxies locales de LLM.
    """
    headers = getattr(resp, "headers", None) or {}
    header = headers.get("Retry-After") if hasattr(headers, "get") else None
    if header:
        try:
            return max(0.0, float(str(header).strip()))
        except (TypeError, ValueError):
            pass
    for text in texts:
        if not text:
            continue
        m = _RESET_HINT_RE.search(str(text))
        if m:
            return float(m.group(1))
    return None


# ---------------------------------------------------------------------------
# BaseProvider  -  interfaz abstracta común
# ---------------------------------------------------------------------------
class BaseProvider(ABC):
    """Interfaz común para **todos** los proveedores de IA del sistema.

    Ciclo de vida recomendado:

    1. :meth:`validate`  → comprueba que la configuración es mínimamente correcta
                            (sin realizar peticiones caras de red).
    2. :meth:`health_check` → petición ligera para ver si el endpoint responde.
    3. :meth:`generate`  → llamada real con el prompt (la que se usa en producción).
    """

    PROVIDER_ID: str = "base"

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self.name = config.name
        self.model = config.model

    # ------------------------------------------------------------------
    # Validaciones / sanidad
    # ------------------------------------------------------------------
    @abstractmethod
    def validate(self) -> None:
        """Comprueba **sin realizar peticiones** que la config es correcta.

        Debe lanzar :class:`ValueError` / :class:`RuntimeError` descriptivo si
        falta algo obligatorio (API key, modelo, URL…).
        """

    @abstractmethod
    def health_check(self) -> bool:
        """Comprobación **ligera y rápida** de que el endpoint responde.

        Implementaciones típicas:
        - Ollama    : ``GET /api/tags``
        - OpenAI y compatibles: ``HEAD /models`` o ``GET /models``
        - Anthropic : ``GET /v1/models`` o ``GET /v1/messages`` mínimo
        - Google    : HEAD o GET simple

        Returns:
            ``True`` si el proveedor parece operativo, ``False`` en caso
            contrario (**nunca** lanza excepciones: captura todo internamente).
        """

    # ------------------------------------------------------------------
    # Generación (método público abstracto según la especificación)
    # ------------------------------------------------------------------
    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> ProviderResponse:
        """Genera texto a partir de un prompt.

        Args:
            prompt:         Texto enviado como mensaje *user* al modelo.
            system_prompt:  Sistema opcional. Si es ``None``, se usará el
                            ``system_prompt`` configurado en :class:`ProviderConfig`,
                            y si tampoco hay → un valor por defecto genérico.
            json_mode:      Si es ``True``, el proveedor debe **intentar**
                            forzar una respuesta JSON v¹a response_format /
                            instrucciones especiales (mejor esfuerzo: no hay
                            garantía en proveedores que no lo soporten nativamente).

        Returns:
            :class:`ProviderResponse` con texto limpio y metadatos.

        Raises:
            RuntimeError: Si tras agotar ``max_retries`` reintentos no se ha
                          podido obtener una respuesta válida.
        """

    # ------------------------------------------------------------------
    # Helpers protegidos (reutilizables por las subclases)
    # ------------------------------------------------------------------
    def _effective_system(self, caller_system: Optional[str]) -> str:
        """Sistema **final** que se envía al modelo.

        Prioridad:
        1. ``caller_system`` (pasado en la llamada)
        2. ``config.system_prompt`` (del YAML)
        3. Un default neutral en español
        """
        if caller_system and caller_system.strip():
            return caller_system.strip()
        if self.config.system_prompt and str(self.config.system_prompt).strip():
            return str(self.config.system_prompt).strip()
        return "Eres un asistente experto. Responde con precisión y claridad."

    def _with_retries(self, operation: Callable[[], str]) -> tuple[str, int]:
        """Helper común: ejecuta ``operation`` con backoff exponencial.

        Args:
            operation:  Función sin argumentos que realiza **una única**
                        llamada a la API y devuelve el texto crudo de la
                        respuesta. Puede lanzar cualquier excepción en caso
                        de fallo; este helper la captura y reintenta.

        Returns:
            Tupla ``(texto_final, latencia_total_ms)``.

        Raises:
            RuntimeError: Si se agotan los reintentos sin éxito; el mensaje
                          incluye el último error y el número de intentos.
        """
        last_error: Optional[Exception] = None
        total_attempts = max(1, int(self.config.max_retries))
        start = time.perf_counter()

        for attempt in range(1, total_attempts + 1):
            try:
                text = operation()
                text = text.strip() if isinstance(text, str) else str(text or "").strip()
                if not text:
                    raise ValueError("La respuesta del proveedor estaba vacía.")
                latency_ms = int((time.perf_counter() - start) * 1000)
                return text, latency_ms
            except Exception as exc:  # noqa: BLE001  (queremos capturar TODO)
                last_error = exc
                if attempt < total_attempts:
                    wait_seconds = float(2 ** (attempt - 1))
                    # HTTP 429: si el servidor sugiere una espera explícita
                    # (Retry-After / "soonest reset"), respetarla — el
                    # backoff corto quemaría los reintentos en segundos
                    # mientras el cooldown del proveedor sigue activo.
                    hint = getattr(exc, "retry_after", None)
                    if hint:
                        wait_seconds = max(
                            wait_seconds,
                            min(float(hint) + 1.0, _MAX_RATE_LIMIT_WAIT_S),
                        )
                    _LOG.info(
                        "[%s:%s] intento %d/%d falló (%s); "
                        "reintentando en %.1fs",
                        self.PROVIDER_ID,
                        self.name,
                        attempt,
                        total_attempts,
                        type(exc).__name__,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)

        raise RuntimeError(
            f"Proveedor [{self.PROVIDER_ID}:{self.name}] agotó "
            f"{total_attempts} reintentos. Último error: "
            f"{type(last_error).__name__}: {last_error}"
        ) from last_error
