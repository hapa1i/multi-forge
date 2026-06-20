"""Tests for direct-path request correlation primitives (Phase 4c).

``with_forge_request_id`` forwards an ``X-Request-ID`` without clobbering or
mutating the caller's hyperparameters; ``target_is_forge_proxy`` only returns
True for a base_url registered as a Forge proxy (else a stamped
``cost_request_id`` would dangle).
"""

from __future__ import annotations

import json

from forge.core.llm import ModelHyperparameters
from forge.core.run_id import derive_provider_session_id
from forge.core.usage.correlation import (
    mint_request_id,
    resolve_client_base_url,
    resolve_direct_provider_user,
    target_is_forge_proxy,
    with_forge_request_id,
    with_openrouter_user,
)
from forge.proxy.proxies import get_proxy_registry_path
from forge.runtime_config import RuntimeConfig, RuntimeProviderTraceConfig


def _patch_inject_flag(monkeypatch, enabled: bool) -> None:
    """Force the global provider_trace.inject_provider_user toggle for a test."""
    cfg = RuntimeConfig(provider_trace=RuntimeProviderTraceConfig(inject_provider_user=enabled))
    monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: cfg)


def _clear_run_env(monkeypatch) -> None:
    """Start each resolver test from a known empty run-identity environment."""
    for var in ("FORGE_SESSION", "FORGE_ROOT_RUN_ID", "FORGE_RUN_ID"):
        monkeypatch.delenv(var, raising=False)


class TestWithForgeRequestId:
    def test_adds_header_from_none(self) -> None:
        hp = with_forge_request_id(None, "req_x")
        assert hp.extra["openai"]["extra_headers"]["X-Request-ID"] == "req_x"

    def test_merges_without_clobbering(self) -> None:
        base = ModelHyperparameters(extra={"openai": {"extra_headers": {"User-Agent": "ua"}}})
        hp = with_forge_request_id(base, "req_y")
        assert hp.extra["openai"]["extra_headers"] == {"User-Agent": "ua", "X-Request-ID": "req_y"}

    def test_does_not_mutate_caller(self) -> None:
        base = ModelHyperparameters(extra={"openai": {"extra_headers": {"User-Agent": "ua"}}})
        with_forge_request_id(base, "req_z")
        assert base.extra == {"openai": {"extra_headers": {"User-Agent": "ua"}}}

    def test_mint_request_id_prefix(self) -> None:
        rid = mint_request_id()
        assert rid.startswith("req_") and len(rid) > len("req_")


class TestWithOpenrouterUser:
    def test_sets_user_from_none(self) -> None:
        hp = with_openrouter_user(None, "forge_sess_abc123def456_plan_check")
        assert hp.extra["openai"]["user"] == "forge_sess_abc123def456_plan_check"

    def test_no_clobber_existing_user(self) -> None:
        base = ModelHyperparameters(extra={"openai": {"user": "caller_set"}})
        hp = with_openrouter_user(base, "forge_run_000000000000")
        assert hp.extra["openai"]["user"] == "caller_set"

    def test_preserves_sibling_openai_extras(self) -> None:
        # Composes with the request-id wrapper: user injection must keep extra_headers.
        base = with_forge_request_id(None, "req_x")
        hp = with_openrouter_user(base, "forge_run_000000000000")
        assert hp.extra["openai"]["extra_headers"]["X-Request-ID"] == "req_x"
        assert hp.extra["openai"]["user"] == "forge_run_000000000000"

    def test_does_not_mutate_caller(self) -> None:
        base = ModelHyperparameters(extra={"openai": {"extra_headers": {"User-Agent": "ua"}}})
        with_openrouter_user(base, "forge_run_000000000000")
        assert base.extra == {"openai": {"extra_headers": {"User-Agent": "ua"}}}


class TestResolveDirectProviderUser:
    def test_none_when_flag_off(self, monkeypatch) -> None:
        # Default: flag off -> None even with a full run identity present.
        _patch_inject_flag(monkeypatch, False)
        _clear_run_env(monkeypatch)
        monkeypatch.setenv("FORGE_SESSION", "mysession")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_000000000000")
        assert resolve_direct_provider_user("plan-check") is None

    def test_session_label_when_flag_on(self, monkeypatch) -> None:
        _patch_inject_flag(monkeypatch, True)
        _clear_run_env(monkeypatch)
        monkeypatch.setenv("FORGE_SESSION", "mysession")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_000000000000")
        result = resolve_direct_provider_user("plan-check")
        assert result is not None and result.startswith("forge_sess_") and result.endswith("_plan_check")

    def test_run_fallback_when_no_session(self, monkeypatch) -> None:
        _patch_inject_flag(monkeypatch, True)
        _clear_run_env(monkeypatch)
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_000000000000")
        result = resolve_direct_provider_user("transfer-curate")
        assert result is not None and result.startswith("forge_run_") and result.endswith("_transfer_curate")

    def test_run_id_fallback_when_no_root(self, monkeypatch) -> None:
        # Mirrors reactive/env.py: root falls back to FORGE_RUN_ID when root is unset.
        _patch_inject_flag(monkeypatch, True)
        _clear_run_env(monkeypatch)
        monkeypatch.setenv("FORGE_RUN_ID", "run_111111111111")
        result = resolve_direct_provider_user(None)
        assert result == derive_provider_session_id(None, "run_111111111111", None)

    def test_none_when_no_identity(self, monkeypatch) -> None:
        _patch_inject_flag(monkeypatch, True)
        _clear_run_env(monkeypatch)
        assert resolve_direct_provider_user("plan-check") is None

    def test_never_raises_degrades_to_none(self, monkeypatch) -> None:
        # Best-effort: a config read that blows up yields None, not an exception.
        def _boom() -> RuntimeConfig:
            raise RuntimeError("config unreadable")

        monkeypatch.setattr("forge.runtime_config.get_runtime_config", _boom)
        assert resolve_direct_provider_user("plan-check") is None

    def test_matches_proxied_derivation(self, monkeypatch) -> None:
        # Cross-plane consistency: the direct id equals what the proxied path (env.py)
        # derives for the same session+root+role, so account-side grouping coheres.
        _patch_inject_flag(monkeypatch, True)
        _clear_run_env(monkeypatch)
        monkeypatch.setenv("FORGE_SESSION", "mysession")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_222222222222")
        assert resolve_direct_provider_user("plan-check") == derive_provider_session_id(
            "mysession", "run_222222222222", "plan-check"
        )


class TestTargetIsForgeProxy:
    def _write_registry(self, base_url: str) -> None:
        path = get_proxy_registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "proxies": {
                        "p1": {
                            "proxy_id": "p1",
                            "template": "litellm-gemini",
                            "base_url": base_url,
                            "port": 8084,
                        }
                    },
                }
            )
        )

    def test_none_is_false(self) -> None:
        assert target_is_forge_proxy(None) is False

    def test_no_registry_is_false(self) -> None:
        assert target_is_forge_proxy("http://localhost:8084") is False

    def test_registered_url_is_true(self) -> None:
        self._write_registry("http://localhost:8084")
        assert target_is_forge_proxy("http://localhost:8084") is True

    def test_trailing_slash_normalized(self) -> None:
        self._write_registry("http://localhost:8084")
        assert target_is_forge_proxy("http://localhost:8084/") is True

    def test_unregistered_url_is_false(self) -> None:
        self._write_registry("http://localhost:8084")
        assert target_is_forge_proxy("http://localhost:9999") is False


class TestResolveClientBaseUrl:
    def test_litellm_local_from_env(self, monkeypatch) -> None:
        # gemini/* -> litellm_local; base_url resolves from LITELLM_LOCAL_BASE_URL.
        monkeypatch.setenv("LITELLM_LOCAL_BASE_URL", "http://localhost:8084")
        assert resolve_client_base_url("gemini/gemini-2.0-flash") == "http://localhost:8084"

    def test_best_effort_never_raises(self, monkeypatch) -> None:
        monkeypatch.delenv("LITELLM_LOCAL_BASE_URL", raising=False)
        # Whatever the config state, resolution is best-effort: a str or None, never raises.
        result = resolve_client_base_url("gemini/gemini-2.0-flash")
        assert result is None or isinstance(result, str)

    def test_gate_true_when_resolved_url_is_registered_proxy(self, monkeypatch) -> None:
        # The end-to-end direct-path gate: resolved client base_url IS a Forge proxy.
        monkeypatch.setenv("LITELLM_LOCAL_BASE_URL", "http://localhost:8084")
        path = get_proxy_registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "proxies": {
                        "p1": {"proxy_id": "p1", "template": "t", "base_url": "http://localhost:8084", "port": 8084}
                    },
                }
            )
        )
        assert target_is_forge_proxy(resolve_client_base_url("gemini/gemini-2.0-flash")) is True
