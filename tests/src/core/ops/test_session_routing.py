"""Launch-route preparation and required commit transaction tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import forge.core.ops.session_routing as ops
from forge.core.ops.session import ForgeOpError
from forge.core.reactive.env import new_root_run_identity
from forge.session import SessionStore, create_session_state
from forge.session.routing import read_routing_events


def _store(tmp_path: Path, *, runtime: str = "codex") -> tuple[SessionStore, Any]:
    state = create_session_state("planner", worktree_path=str(tmp_path), runtime=runtime)
    state.forge_root = str(tmp_path)
    store = SessionStore(str(tmp_path), state.name)
    store.write(state)
    return store, state


def test_required_commit_projects_exact_pointer_without_touching_confirmed_by(
    tmp_path: Path,
) -> None:
    store, state = _store(tmp_path)
    state.confirmed.confirmed_by = "hook:stop"
    store.write(state)
    root = new_root_run_identity()
    payload = ops.build_runtime_native_routing_payload()

    projection = ops.commit_launch_routing(
        store=store,
        state=state,
        root=root,
        operation="start",
        payload=payload,
        authority_attempt=None,
    )

    current = store.read()
    assert current.confirmed.route_commit == projection
    assert current.confirmed.confirmed_by == "hook:stop"
    events = read_routing_events(tmp_path, current)
    assert len(events) == 1
    assert events[0].payload == payload
    assert events[0].run_id == root.run_id


def test_direct_payload_uses_shared_catalog_normalization(tmp_path: Path) -> None:
    _, state = _store(tmp_path, runtime="claude_code")
    state.intent.launch.direct_model = "opus"

    payload = ops.build_claude_routing_payload(
        state,
        effective_template=None,
        runtime_base_url=None,
        proxy_id=None,
        effective_direct_model="anthropic/claude-opus-5[1m]",
    )

    assert payload["route"]["kind"] == "direct"
    assert payload["requested_model"] == "claude-opus-5"
    assert payload["selected_tier"] == "opus"
    assert payload["selected_model"] == "claude-opus-5"
    assert payload["direct_model"] == "claude-opus-5"
    assert payload["marking_snapshots"] == [
        {
            "slot": "direct",
            "tier": None,
            "request_model": None,
            "route_model": "claude-opus-5",
            "canonical_model": "claude-opus-5",
            "declaration": {
                "status": "unknown",
                "basis": None,
                "source_url": None,
                "checked_at": None,
                "effective_from": None,
                "route_scope": [],
            },
        }
    ]


def test_proxy_payload_captures_effective_zdr_defaults_and_alternatives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, state = _store(tmp_path, runtime="claude_code")
    provider = SimpleNamespace(
        tiers={"sonnet": "qwen/qwen3.6-flash", "opus": "anthropic/claude-opus-5"},
        model_alternatives={"opus": {"opus": "qwen/qwen3.6-max-preview"}},
        allow_non_zdr=False,
        zdr_fallbacks={},
    )
    proxy = SimpleNamespace(
        preferred_provider="openrouter",
        get_provider=lambda _provider: provider,
        default_tier="sonnet",
        active_template="openrouter-qwen",
        backend="openrouter",
    )
    monkeypatch.setattr(ops, "load_config", lambda **_kwargs: SimpleNamespace(proxy=proxy))

    payload = ops.build_claude_routing_payload(
        state,
        effective_template="openrouter-qwen",
        runtime_base_url="http://localhost:8085",
        proxy_id="qwen-1",
    )

    assert payload["route"] == {
        "kind": "proxy",
        "backend_id": "openrouter",
        "proxy_id": "qwen-1",
        "template": "openrouter-qwen",
        "custom_route_fingerprint": None,
    }
    assert payload["tier_mappings"] == {
        "sonnet": "qwen/qwen3.8-27b",
        "opus": "anthropic/claude-opus-5",
    }
    assert payload["model_alternatives"] == {"opus": {"opus": "qwen/qwen3.8-2.4t-a95b"}}
    assert payload["route_scope_tags"] == [
        "backend:openrouter",
        "route:proxy",
        "runtime:claude_code",
    ]
    assert [(entry["slot"], entry["route_model"]) for entry in payload["marking_snapshots"]] == [
        ("tier_default", "qwen/qwen3.8-27b"),
        ("tier_default", "anthropic/claude-opus-5"),
        ("model_alternative", "qwen/qwen3.8-2.4t-a95b"),
    ]


@pytest.mark.parametrize("launch_mode", ["host", "sidecar"])
def test_template_route_preserves_unknown_proxy_id(
    launch_mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, state = _store(tmp_path, runtime="claude_code")
    state.intent.launch.mode = launch_mode
    provider = SimpleNamespace(
        tiers={
            "haiku": "openai/gpt-5.4-mini",
            "sonnet": "openai/gpt-5.5",
            "opus": "openai/gpt-5.5",
        },
        model_alternatives={},
        allow_non_zdr=False,
        zdr_fallbacks={},
    )
    proxy = SimpleNamespace(
        preferred_provider="litellm",
        get_provider=lambda _provider: provider,
        default_tier="sonnet",
        active_template="litellm-openai",
        backend="",
    )
    calls: list[dict[str, str | None]] = []

    def load_config(**kwargs: str | None) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(proxy=proxy)

    monkeypatch.setattr(ops, "load_config", load_config)

    payload = ops.build_claude_routing_payload(
        state,
        effective_template="litellm-openai",
        runtime_base_url="http://localhost:8085",
        proxy_id=None,
    )

    assert calls == [{"template": "litellm-openai"}]
    assert payload["route"]["kind"] == "proxy"
    assert payload["route"]["proxy_id"] is None
    assert payload["route"]["template"] == "litellm-openai"
    assert payload["default_tier"] == "sonnet"


def test_custom_payload_stores_only_a_secret_free_origin_fingerprint(
    tmp_path: Path,
) -> None:
    _, state = _store(tmp_path, runtime="claude_code")

    payload = ops.build_claude_routing_payload(
        state,
        effective_template=None,
        runtime_base_url="https://user:secret@Example.com:443/private?token=x",
        proxy_id=None,
    )

    assert payload["route"]["kind"] == "custom"
    assert payload["route"]["custom_route_fingerprint"] == ops.custom_route_fingerprint("https://example.com")
    assert "secret" not in repr(payload)
    assert "private" not in repr(payload)


def test_routing_append_failure_compensates_only_touched_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state = _store(tmp_path)
    calls: list[str] = []
    attempt = SimpleNamespace(abort_before_child=lambda **_kwargs: calls.append("authority"))
    monkeypatch.setattr(
        ops,
        "append_routing_event",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(ForgeOpError, match="routing commit append failed: disk full"):
        ops.commit_launch_routing(
            store=store,
            state=state,
            root=new_root_run_identity(),
            operation="start",
            payload=ops.build_runtime_native_routing_payload(),
            authority_attempt=cast(Any, attempt),
        )

    assert calls == ["authority"]
    assert not (tmp_path / ".forge" / "artifacts" / "planner" / "routing" / "events.jsonl").exists()


def test_projection_failure_reuses_immutable_payload_and_compensates_in_reverse_touch_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, state = _store(tmp_path)
    calls: list[str] = []
    payloads: list[dict[str, Any]] = []
    payload = ops.build_runtime_native_routing_payload()
    real_append = ops.append_routing_event

    def append(root: str | Path, event: Any) -> Path:
        calls.append(event.event_type)
        payloads.append(event.payload)
        if event.event_type == "launch_routing_committed":
            payload["billing_mode"] = "api"
            monkeypatch.setattr(
                ops,
                "load_model_practices",
                lambda: (_ for _ in ()).throw(AssertionError("catalog reread during compensation")),
            )
            monkeypatch.setattr(
                ops,
                "load_config",
                lambda **_kwargs: (_ for _ in ()).throw(AssertionError("config reread during compensation")),
            )
        return real_append(root, event)

    attempt = SimpleNamespace(abort_before_child=lambda **_kwargs: calls.append("authority"))
    monkeypatch.setattr(ops, "append_routing_event", append)
    monkeypatch.setattr(
        store,
        "update",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("manifest read-only")),
    )

    with pytest.raises(ForgeOpError, match="route projection failed: manifest read-only"):
        ops.commit_launch_routing(
            store=store,
            state=state,
            root=new_root_run_identity(),
            operation="resume",
            payload=payload,
            authority_attempt=cast(Any, attempt),
        )

    assert calls == ["launch_routing_committed", "launch_aborted", "authority"]
    assert payloads[0] == payloads[1]
    assert payloads[0]["billing_mode"] == "unknown"
    assert store.read().confirmed.route_commit is None


def test_projection_failure_names_every_failed_compensation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, state = _store(tmp_path)
    real_append = ops.append_routing_event

    def append(root: str | Path, event: Any) -> Path:
        if event.event_type == "launch_aborted":
            raise OSError("routing disk full")
        return real_append(root, event)

    attempt = SimpleNamespace(
        abort_before_child=lambda **_kwargs: (_ for _ in ()).throw(OSError("authority disk full"))
    )
    monkeypatch.setattr(ops, "append_routing_event", append)
    monkeypatch.setattr(
        store,
        "update",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("manifest read-only")),
    )

    with pytest.raises(ForgeOpError) as raised:
        ops.commit_launch_routing(
            store=store,
            state=state,
            root=new_root_run_identity(),
            operation="resume",
            payload=ops.build_runtime_native_routing_payload(),
            authority_attempt=cast(Any, attempt),
        )

    message = str(raised.value)
    assert "route projection failed: manifest read-only" in message
    assert "routing abort failed: routing disk full" in message
    assert "authority abort failed: authority disk full" in message
