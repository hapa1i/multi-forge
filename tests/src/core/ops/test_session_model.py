"""Stable session model-route report tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import forge.core.ops.session_model as ops
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_routing import (
    build_claude_routing_payload,
    build_runtime_native_routing_payload,
    commit_launch_routing,
)
from forge.core.reactive.env import new_root_run_identity
from forge.proxy.runtime_truth import ProxyRuntimeTruth
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import LaunchConfirmed, ProxyIntent, RouteCommitConfirmed
from tests.fixtures.session_state import publish_session


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    root = tmp_path / "project"
    home.mkdir()
    (root / ".git").mkdir(parents=True)
    (root / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(root)
    return root


def _publish(project: Path, *, proxy: bool = False, runtime: str = "claude_code") -> SessionStore:
    state = create_session_state(
        "planner",
        worktree_path=str(project),
        proxy_template="openrouter-anthropic" if proxy else None,
        proxy_base_url="http://127.0.0.1:8999" if proxy else None,
        runtime=runtime,
    )
    state.forge_root = str(project)
    publish_session(
        IndexStore(),
        state,
        project,
        forge_root=project,
        checkout_root=project,
        relative_path=".",
    )
    return SessionStore(str(project), "planner")


def _proxy_config() -> SimpleNamespace:
    provider = SimpleNamespace(
        tiers=SimpleNamespace(
            haiku="anthropic/claude-haiku-4-5",
            sonnet="anthropic/claude-sonnet-5",
            opus="anthropic/claude-opus-5",
            get=lambda tier: {
                "haiku": "anthropic/claude-haiku-4-5",
                "sonnet": "anthropic/claude-sonnet-5",
                "opus": "anthropic/claude-opus-5",
            }[tier],
        ),
        model_alternatives={"opus": {"opus": "anthropic/claude-opus-5"}},
        allow_non_zdr=True,
        zdr_fallbacks={},
    )
    proxy = SimpleNamespace(
        preferred_provider="openrouter",
        get_provider=lambda _provider=None: provider,
        default_tier="sonnet",
        active_template="openrouter-anthropic",
        backend="openrouter",
    )
    return SimpleNamespace(proxy=proxy)


def _assert_stable_report_shape(payload: dict[str, object]) -> None:
    assert list(payload) == [
        "schema_version",
        "session",
        "runtime",
        "active",
        "route_intent",
        "route_commit",
        "live_proxy",
        "current_request_tier",
        "current_request_source",
        "history_status",
        "marking",
        "limitations",
    ]
    intent = payload["route_intent"]
    assert isinstance(intent, dict)
    assert list(intent) == [
        "kind",
        "template",
        "proxy_id",
        "custom_route_fingerprint",
        "requested_model",
    ]
    commit = payload["route_commit"]
    if commit is not None:
        assert isinstance(commit, dict)
        assert list(commit) == [
            "run_id",
            "event_id",
            "evidence_source",
            "kind",
            "backend_id",
            "proxy_id",
            "template",
            "custom_route_fingerprint",
            "requested_model",
            "selected_tier",
            "selected_model",
            "default_tier",
            "direct_model",
            "tier_mappings",
            "model_alternatives",
            "billing_mode",
            "route_scope_tags",
        ]
    live = payload["live_proxy"]
    assert isinstance(live, dict)
    assert list(live) == [
        "reachable",
        "evidence_source",
        "proxy_id",
        "template",
        "backend_id",
        "default_tier",
        "tier_mappings",
        "model_alternatives",
    ]
    marking = payload["marking"]
    assert isinstance(marking, dict)
    assert list(marking) == [
        "scope",
        "provider_declared",
        "launch_entries",
        "live_proxy_entries",
    ]
    for entry in marking["launch_entries"]:
        assert list(entry) == [
            "slot",
            "tier",
            "request_model",
            "route_model",
            "canonical_model",
            "launch_snapshot",
            "current_declaration",
            "changed_since_launch",
        ]
    for entry in marking["live_proxy_entries"]:
        assert list(entry) == [
            "slot",
            "tier",
            "request_model",
            "route_model",
            "canonical_model",
            "evidence_source",
            "declaration",
        ]


def test_no_route_evidence_uses_stable_null_and_empty_shapes(project: Path) -> None:
    _publish(project)

    payload = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(payload)
    assert payload["route_intent"] == {
        "kind": "direct",
        "template": None,
        "proxy_id": None,
        "custom_route_fingerprint": None,
        "requested_model": None,
    }
    assert payload["route_commit"] is None
    assert payload["history_status"] is None
    assert payload["live_proxy"]["evidence_source"] == "not_applicable"
    assert payload["marking"]["launch_entries"] == []
    assert payload["marking"]["provider_declared"] is True


def test_supported_projection_exposes_journal_owned_scope_and_launch_marking(
    project: Path,
) -> None:
    store = _publish(project)
    state = store.read()
    root = new_root_run_identity()
    payload = build_claude_routing_payload(
        state,
        effective_template=None,
        runtime_base_url=None,
        proxy_id=None,
        effective_direct_model="claude-opus-5",
    )
    projection = commit_launch_routing(
        store=store,
        state=state,
        root=root,
        operation="start",
        payload=payload,
        authority_attempt=None,
    )

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    commit = report["route_commit"]
    assert list(commit) == [
        "run_id",
        "event_id",
        "evidence_source",
        "kind",
        "backend_id",
        "proxy_id",
        "template",
        "custom_route_fingerprint",
        "requested_model",
        "selected_tier",
        "selected_model",
        "default_tier",
        "direct_model",
        "tier_mappings",
        "model_alternatives",
        "billing_mode",
        "route_scope_tags",
    ]
    assert commit["event_id"] == projection.event_id
    assert commit["run_id"] == root.run_id
    assert commit["evidence_source"] == "route_commit"
    assert commit["billing_mode"] == "unknown"
    assert commit["route_scope_tags"] == ["route:direct", "runtime:claude_code"]
    assert "marking_snapshots" not in commit
    assert report["history_status"] == "supported"
    assert report["marking"]["launch_entries"][0]["launch_snapshot"]["status"] == "unknown"
    assert report["marking"]["launch_entries"][0]["changed_since_launch"] is False


def test_custom_route_report_keeps_only_the_origin_fingerprint(project: Path) -> None:
    store = _publish(project)
    state = store.read()
    state.intent.proxy = ProxyIntent(template="", base_url="https://user:secret@Example.com/private?token=x")
    store.write(state)
    root = new_root_run_identity()
    commit_launch_routing(
        store=store,
        state=state,
        root=root,
        operation="resume",
        payload=build_claude_routing_payload(
            state,
            effective_template=None,
            runtime_base_url=state.intent.proxy.base_url,
            proxy_id=None,
        ),
        authority_attempt=None,
    )

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert report["route_intent"]["kind"] == "custom"
    assert report["route_commit"]["kind"] == "custom"
    assert report["route_commit"]["custom_route_fingerprint"] == report["route_intent"]["custom_route_fingerprint"]
    assert "secret" not in repr(report)
    assert report["live_proxy"]["evidence_source"] == "not_applicable"


def test_runtime_native_report_does_not_claim_a_model_or_backend(project: Path) -> None:
    store = _publish(project, runtime="codex")
    state = store.read()
    commit_launch_routing(
        store=store,
        state=state,
        root=new_root_run_identity(),
        operation="start",
        payload=build_runtime_native_routing_payload(),
        authority_attempt=None,
    )

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert report["route_intent"] == {
        "kind": "runtime_native",
        "template": None,
        "proxy_id": None,
        "custom_route_fingerprint": None,
        "requested_model": None,
    }
    assert report["route_commit"]["kind"] == "runtime_native"
    assert report["route_commit"]["backend_id"] is None
    assert report["route_commit"]["billing_mode"] == "unknown"
    assert report["marking"]["launch_entries"] == []


def test_unproven_projection_preserves_only_pointer_identity(project: Path) -> None:
    store = _publish(project)
    store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(
            state.confirmed,
            "route_commit",
            RouteCommitConfirmed(
                event_id="sevt_0123456789abcdef0123456789abcdef",
                run_id="run_0123456789ab",
            ),
        ),
    )

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    commit = report["route_commit"]
    assert commit["evidence_source"] == "unproven_projection"
    assert commit["event_id"] == "sevt_0123456789abcdef0123456789abcdef"
    assert commit["kind"] is None
    assert commit["billing_mode"] is None
    assert commit["route_scope_tags"] == []
    assert report["history_status"] == "unproven"


def test_legacy_launch_summary_does_not_synthesize_history(project: Path) -> None:
    store = _publish(project)
    store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(
            state.confirmed,
            "launch",
            LaunchConfirmed(routing_mode="direct", api_key_source="none"),
        ),
    )

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert report["route_commit"]["evidence_source"] == "legacy_confirmed_launch"
    assert report["route_commit"]["event_id"] is None
    assert report["route_commit"]["kind"] == "direct"
    assert report["history_status"] is None
    assert report["marking"]["launch_entries"] == []


def test_live_proxy_runtime_is_authoritative_and_keeps_marking_planes_separate(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(project, proxy=True)
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "proxy": {"proxy_id": "p1", "template": "openrouter-anthropic"},
            "runtime": {
                "backend_id": "openrouter",
                "active_tier": "sonnet",
                "tier_mappings": {"sonnet": "anthropic/claude-sonnet-5"},
                "model_alternatives": {"opus": {"claude-opus-5": "anthropic/claude-opus-5"}},
            },
        }
    )
    monkeypatch.setattr(ops, "_probe_proxy_runtime", lambda *_args, **_kwargs: runtime)

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert report["live_proxy"] == {
        "reachable": True,
        "evidence_source": "runtime",
        "proxy_id": "p1",
        "template": "openrouter-anthropic",
        "backend_id": "openrouter",
        "default_tier": "sonnet",
        "tier_mappings": {"sonnet": "anthropic/claude-sonnet-5"},
        "model_alternatives": {"opus": {"claude-opus-5": "anthropic/claude-opus-5"}},
    }
    assert report["marking"]["launch_entries"] == []
    assert len(report["marking"]["live_proxy_entries"]) == 2


def test_unreachable_proxy_uses_config_fallback_without_live_marking(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _publish(project, proxy=True)
    store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(
            state.confirmed,
            "launch",
            LaunchConfirmed(
                routing_mode="proxy",
                proxy_id="p1",
                base_url="http://127.0.0.1:8999",
            ),
        ),
    )
    monkeypatch.setattr(ops, "_probe_proxy_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ops, "load_config", lambda **_kwargs: _proxy_config())

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert report["live_proxy"]["reachable"] is False
    assert report["live_proxy"]["evidence_source"] == "proxy_config"
    assert report["live_proxy"]["backend_id"] == "openrouter"
    assert report["marking"]["live_proxy_entries"] == []


def test_older_reachable_proxy_response_uses_labelled_config_fallback(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(project, proxy=True)
    legacy_runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "proxy": {"proxy_id": "p1", "template": "openrouter-anthropic"},
            "runtime": {
                "active_tier": "sonnet",
                "tier_mappings": {"sonnet": "old/runtime-model"},
            },
        }
    )
    monkeypatch.setattr(ops, "_probe_proxy_runtime", lambda *_args, **_kwargs: legacy_runtime)
    monkeypatch.setattr(ops, "load_config", lambda **_kwargs: _proxy_config())

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert report["live_proxy"]["reachable"] is True
    assert report["live_proxy"]["evidence_source"] == "proxy_config"
    assert report["live_proxy"]["tier_mappings"] != legacy_runtime.tier_mappings
    assert report["marking"]["live_proxy_entries"] == []


def test_malformed_reachable_proxy_response_uses_labelled_config_fallback(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(project, proxy=True)
    malformed_runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "proxy": {"proxy_id": "p1", "template": "openrouter-anthropic"},
            "runtime": {
                "backend_id": "openrouter",
                "active_tier": "sonnet",
                "tier_mappings": ["not", "a", "mapping"],
                "model_alternatives": {},
            },
        }
    )
    monkeypatch.setattr(ops, "_probe_proxy_runtime", lambda *_args, **_kwargs: malformed_runtime)
    monkeypatch.setattr(ops, "load_config", lambda **_kwargs: _proxy_config())

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert report["live_proxy"]["reachable"] is True
    assert report["live_proxy"]["evidence_source"] == "proxy_config"
    assert report["live_proxy"]["tier_mappings"] == {
        "haiku": "anthropic/claude-haiku-4-5",
        "sonnet": "anthropic/claude-sonnet-5",
        "opus": "anthropic/claude-opus-5",
    }
    assert report["marking"]["live_proxy_entries"] == []


def test_template_only_proxy_intent_uses_current_config_fallback(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _publish(project, proxy=True)
    monkeypatch.setattr(ops, "_probe_proxy_runtime", lambda *_args, **_kwargs: None)
    loads: list[dict[str, str | None]] = []

    def load_config(**kwargs: str | None) -> SimpleNamespace:
        loads.append(kwargs)
        return _proxy_config()

    monkeypatch.setattr(ops, "load_config", load_config)

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert loads == [{"template": "openrouter-anthropic"}]
    assert report["live_proxy"]["evidence_source"] == "proxy_config"
    assert report["live_proxy"]["proxy_id"] is None
    assert report["live_proxy"]["template"] == "openrouter-anthropic"
    assert report["marking"]["live_proxy_entries"] == []


def test_proxy_route_commit_is_the_last_fallback(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _publish(project, proxy=True)
    state = store.read()
    monkeypatch.setattr("forge.core.ops.session_routing.load_config", lambda **_kwargs: _proxy_config())
    commit_launch_routing(
        store=store,
        state=state,
        root=new_root_run_identity(),
        operation="start",
        payload=build_claude_routing_payload(
            state,
            effective_template="openrouter-anthropic",
            runtime_base_url="http://127.0.0.1:8999",
            proxy_id="p1",
        ),
        authority_attempt=None,
    )
    monkeypatch.setattr(ops, "_probe_proxy_runtime", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(ops, "load_config", lambda **_kwargs: (_ for _ in ()).throw(OSError("gone")))

    report = ops.get_session_model_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    _assert_stable_report_shape(report)
    assert report["live_proxy"]["evidence_source"] == "route_commit"
    assert report["live_proxy"]["tier_mappings"] == report["route_commit"]["tier_mappings"]
    assert report["marking"]["live_proxy_entries"] == []


def test_history_wrapper_returns_full_events_in_append_order(project: Path) -> None:
    store = _publish(project)
    state = store.read()
    root = new_root_run_identity()
    commit_launch_routing(
        store=store,
        state=state,
        root=root,
        operation="resume",
        payload=build_claude_routing_payload(
            state,
            effective_template=None,
            runtime_base_url=None,
            proxy_id=None,
            effective_direct_model="claude-sonnet-5",
        ),
        authority_attempt=None,
    )

    payload = ops.get_session_model_history_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    ).to_dict()

    assert payload["schema_version"] == 1
    assert payload["session"] == "planner"
    assert payload["history_status"] == "supported"
    assert [event["event_type"] for event in payload["events"]] == ["launch_routing_committed"]
    assert set(payload["events"][0]) == {
        "schema_version",
        "event_id",
        "timestamp",
        "session",
        "runtime",
        "event_type",
        "run_id",
        "origin_surface",
        "operation",
        "outcome",
        "reason_code",
        "payload",
    }
