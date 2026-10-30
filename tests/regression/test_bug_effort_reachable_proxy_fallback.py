"""Route fallback must not discard independently valid live effort evidence."""

from types import SimpleNamespace

import pytest

import forge.core.ops.session_model as ops
from forge.proxy.runtime_truth import ProxyRuntimeTruth
from forge.session import create_session_state

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("config_available", [True, False])
@pytest.mark.parametrize("with_effort", [True, False])
def test_route_fallback_preserves_reachable_effort_evidence(monkeypatch, config_available, with_effort):
    record = {
        "tier": "opus",
        "tier_source": "request",
        "client_model": "claude-opus-4-6",
        "mapped_model": "openai/gpt-6-astra",
        "requested": "high",
        "thinking": "adaptive",
        "opt_in": True,
        "client_applicable": True,
        "derived": "medium",
        "floor": None,
        "pre_clamp": "high",
        "supported": ["low", "medium", "high"],
        "resolved": "high",
        "source": "client",
        "applied": "high",
        "wire": "reasoning.effort",
        "note": None,
        "observed_at": "2026-10-30T12:00:00Z",
    }
    raw_runtime = {
        "backend_id": "INVALID BACKEND",  # Deliberately invalid route metadata from a reachable proxy.
        "active_tier": "opus",
        "tier_mappings": {"opus": "openai/gpt-6-astra"},
        "model_alternatives": {},
    }
    if with_effort:
        raw_runtime["effort"] = {"opus": record}
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "wire_shape": "openai_translated",
            "proxy": {"proxy_id": "p1", "template": "openrouter-openai"},
            "runtime": raw_runtime,
        }
    )
    assert not runtime.has_authoritative_route_truth
    monkeypatch.setattr(ops, "_probe_proxy_runtime", lambda *_args, **_kwargs: runtime)

    def load_config(**_kwargs):
        if not config_available:
            raise OSError("config unavailable")
        return SimpleNamespace(
            proxy=SimpleNamespace(active_template="openrouter-openai", backend="openrouter", default_tier="opus")
        )

    monkeypatch.setattr(ops, "load_config", load_config)
    monkeypatch.setattr(ops, "effective_proxy_model_maps", lambda _proxy: ({"opus": "openai/gpt-6-astra"}, {}))
    state = create_session_state("planner", proxy_template="openrouter-openai", proxy_base_url="http://127.0.0.1:8999")
    commit = {
        "kind": "proxy",
        "evidence_source": "route_commit",
        "run_id": "run_0123456789ab",
        "proxy_id": "p1",
        "template": "openrouter-openai",
        "backend_id": "openrouter",
        "default_tier": "opus",
        "tier_mappings": {"opus": "openai/gpt-6-astra"},
        "model_alternatives": {},
    }
    live, effort_runtime = ops._live_proxy(state, {"kind": "proxy"}, commit, launch_id=commit["run_id"])

    assert live["reachable"] is True
    assert live["evidence_source"] == ("proxy_config" if config_available else "route_commit")
    effort = ops._effort_report(commit, effort_runtime)
    assert effort["status"] == ("observed" if with_effort else "unknown")
    assert effort["reason"] == (None if with_effort else "proxy_effort_unavailable")
    assert effort["backend_id"] is None
    assert effort["observations"] == ({"opus": record} if with_effort else {})
