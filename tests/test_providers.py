"""Tests unitarios de la capa de proveedores de IA.

Cubre: parseo de Retry-After en HTTP 429, backoff que respeta la espera
sugerida por el servidor, la fallback chain y la expansion de variables
de entorno en la configuracion.
"""

from __future__ import annotations

import time

import pytest
import requests

from core.providers.base import (
    BaseProvider,
    ProviderConfig,
    ProviderResponse,
    RateLimitError,
    parse_retry_after,
)
from core.providers.env_loader import expand_env_vars
from core.providers.factory import FallbackChainExecutor
from core.providers.openai_compatible import OpenAICompatibleProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeResp:
    """Respuesta HTTP minima compatible con lo que usan los providers."""

    def __init__(self, status: int, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def _provider(name="test", **kwargs) -> OpenAICompatibleProvider:
    cfg = ProviderConfig(name=name, model="m", api_key="k", base_url="http://x/v1", **kwargs)
    return OpenAICompatibleProvider(cfg)


# ---------------------------------------------------------------------------
# parse_retry_after
# ---------------------------------------------------------------------------
class TestParseRetryAfter:
    def test_retry_after_header(self):
        resp = _FakeResp(429, headers={"Retry-After": "72"})
        assert parse_retry_after(resp) == 72.0

    def test_soonest_reset_variants(self):
        for text in (
            "Soonest reset: ~72s.",
            "Soonest reset ~55s. 2 models skipped",
            "wait for rate limits to reset. Soonest reset ~90s",
        ):
            assert parse_retry_after(_FakeResp(429), text) in {72.0, 55.0, 90.0}

    def test_header_wins_over_text(self):
        resp = _FakeResp(429, headers={"Retry-After": "10"}, text="reset ~99s")
        assert parse_retry_after(resp, "reset ~99s") == 10.0

    def test_no_hint(self):
        assert parse_retry_after(_FakeResp(429), "otro error") is None


# ---------------------------------------------------------------------------
# _with_retries: respeta retry_after del servidor
# ---------------------------------------------------------------------------
class _Dummy(BaseProvider):
    PROVIDER_ID = "dummy"

    def validate(self):
        pass

    def health_check(self):
        return True

    def generate(self, prompt, system_prompt=None, json_mode=False):
        pass


class TestWithRetries:
    def test_waits_retry_after_on_429(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)
        p = _Dummy(ProviderConfig(name="d", model="m", max_retries=3))
        calls = {"n": 0}

        def op():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RateLimitError("HTTP 429", retry_after=72.0)
            return "ok"

        text, _ = p._with_retries(op)
        assert text == "ok"
        assert sleeps == [73.0]  # 72s hint + 1s margen

    def test_caps_huge_retry_after(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)
        p = _Dummy(ProviderConfig(name="d", model="m", max_retries=2))

        def op():
            raise RateLimitError("HTTP 429", retry_after=9999.0)

        with pytest.raises(RuntimeError, match="agotó"):
            p._with_retries(op)
        assert sleeps == [300.0]  # cap _MAX_RATE_LIMIT_WAIT_S

    def test_plain_error_uses_short_backoff(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)
        p = _Dummy(ProviderConfig(name="d", model="m", max_retries=3))

        def op():
            raise ValueError("boom")

        with pytest.raises(RuntimeError):
            p._with_retries(op)
        assert sleeps == [1.0, 2.0]


# ---------------------------------------------------------------------------
# OpenAICompatibleProvider: 429 -> RateLimitError con hint
# ---------------------------------------------------------------------------
class TestOpenAICompatible429:
    def test_429_raises_rate_limit_with_hint(self, monkeypatch):
        provider = _provider(max_retries=2)
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)

        body = {"error": {"message": "All models exhausted. Soonest reset ~42s."}}
        monkeypatch.setattr(
            provider._session,
            "post",
            lambda *a, **kw: _FakeResp(429, payload=body),
        )

        with pytest.raises(RuntimeError, match="HTTP 429"):
            provider.generate("hola")
        assert sleeps == [43.0]

    def test_200_returns_text(self, monkeypatch):
        provider = _provider()
        body = {"choices": [{"message": {"content": "respuesta"}}]}
        monkeypatch.setattr(
            provider._session,
            "post",
            lambda *a, **kw: _FakeResp(200, payload=body),
        )
        resp = provider.generate("hola")
        assert isinstance(resp, ProviderResponse)
        assert resp.text == "respuesta"
        assert resp.provider == "openai_compatible"


# ---------------------------------------------------------------------------
# FallbackChainExecutor
# ---------------------------------------------------------------------------
class _StubProvider(_Dummy):
    def __init__(self, cfg, result):
        super().__init__(cfg)
        self._result = result

    def generate(self, prompt, system_prompt=None, json_mode=False):
        if isinstance(self._result, Exception):
            raise self._result
        return ProviderResponse(text=self._result, provider="x", model="m", latency_ms=1)


class TestFallbackChain:
    def _executor(self, providers, default, chain=()):
        return FallbackChainExecutor(
            providers=providers,
            default_provider_name=default,
            fallback_chain=list(chain),
        )

    def test_first_success_wins(self):
        ok = _StubProvider(ProviderConfig(name="a", model="m"), "ok!")
        ex = self._executor({"a": ok}, "a")
        assert ex.execute("p").text == "ok!"

    def test_falls_back_to_next(self):
        bad = _StubProvider(ProviderConfig(name="a", model="m"), ValueError("x"))
        ok = _StubProvider(ProviderConfig(name="b", model="m"), "desde b")
        ex = self._executor({"a": bad, "b": ok}, "a", ["b"])
        assert ex.execute("p").text == "desde b"

    def test_all_fail_reports_history(self):
        bad1 = _StubProvider(ProviderConfig(name="a", model="m"), ValueError("e1"))
        bad2 = _StubProvider(ProviderConfig(name="b", model="m"), RuntimeError("e2"))
        ex = self._executor({"a": bad1, "b": bad2}, "a", ["b"])
        with pytest.raises(RuntimeError, match="TODOS los proveedores") as err:
            ex.execute("p")
        assert "e1" in str(err.value) and "e2" in str(err.value)

    def test_order_dedups_default_in_chain(self):
        p = _StubProvider(ProviderConfig(name="a", model="m"), "x")
        ex = self._executor({"a": p}, "a", ["a", "a"])
        assert ex.execution_order() == ["a"]


# ---------------------------------------------------------------------------
# expand_env_vars
# ---------------------------------------------------------------------------
class TestExpandEnvVars:
    def test_required_var(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "valor")
        assert expand_env_vars({"k": "${MY_KEY}"}) == {"k": "valor"}

    def test_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        out = expand_env_vars("${MISSING_VAR:-http://localhost}")
        assert out == "http://localhost"

    def test_missing_required_raises(self, monkeypatch):
        monkeypatch.delenv("NOPE_VAR", raising=False)
        with pytest.raises(ValueError, match="NOPE_VAR"):
            expand_env_vars("${NOPE_VAR}")

    def test_recursion_and_other_types(self, monkeypatch):
        monkeypatch.setenv("V", "x")
        out = expand_env_vars({"a": ["${V}", 42, None], "b": ("${V}",)})
        assert out == {"a": ["x", 42, None], "b": ("x",)}
