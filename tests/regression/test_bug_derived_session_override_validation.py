"""Derivation validates stored override layers before publishing or preparing a child."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops.context import ExecutionContext
from forge.core.ops.policy import supervisor_remove
from forge.core.ops.session import (
    ForgeOpError,
    reset_session_overrides,
    set_session_override,
)
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.effective import compute_effective_intent
from forge.session.exceptions import ForgeSessionError, ManifestCorruptedError
from forge.session.models import (
    ConsumerLaneBinding,
    ConsumerLaneConfirmed,
    ConsumerLaneIntent,
    LaneRecord,
    LaunchIntent,
    MemoryIntent,
    MemoryWriterConfig,
    NativeSupervisorSource,
    PolicyConfirmed,
    PolicyIntent,
    ProxyIntent,
    SessionState,
    StartedWithProxy,
    SupervisorConfig,
)
from forge.session.plan_resolution import resolve_plan_info
from forge.session.prev_sessions import parent_dir
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression
OPERATIONS = ("fork", "fresh-native", "fresh-transfer", "relaunch")


@dataclass
class DerivationCase:
    root: Path
    manager: SessionManager
    parent: SessionState

    @property
    def store(self) -> SessionStore:
        return SessionStore(str(self.root), "parent")

    @property
    def ctx(self) -> ExecutionContext:
        return ExecutionContext(self.root, self.root, self.root, self.root)

    def publish(self) -> None:
        publish_session(self.manager.index_store, self.parent, self.root)

    def replace_raw(self, **changes: Any) -> bytes:
        # Deliberately violate the published manifest's override/schema invariant
        # after publishing coherent state, as a legacy or manually edited parent.
        data = json.loads(self.store.manifest_path.read_text())
        data.update(changes)
        self.store.manifest_path.write_text(json.dumps(data))
        return self.store.manifest_path.read_bytes()

    def derive(self, operation: str, *, memory_flag: bool | None = None) -> SessionState:
        if operation == "fork":
            return self.manager.fork_session("parent", "child", forge_root=str(self.root), memory_flag=memory_flag)[1]
        if operation == "relaunch":
            return self.manager.relaunch_session("parent", child_name="child", forge_root=str(self.root))[1]
        mode = "native" if operation == "fresh-native" else "transfer"
        return self.manager.resume_session(
            "parent",
            child_name="child",
            resume_mode=mode,
            forge_root=str(self.root),
            memory_flag=memory_flag,
        )[0]

    def assert_no_child(self, parent_bytes: bytes, index_bytes: bytes) -> None:
        assert self.store.manifest_path.read_bytes() == parent_bytes
        assert self.manager.index_store.index_path.read_bytes() == index_bytes
        assert not SessionStore(str(self.root), "child").exists()
        assert not parent_dir(self.root, "parent").exists()


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DerivationCase:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".forge").mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "500")
    state = create_session_state("parent", worktree_path=str(root))
    state.intent.launch = LaunchIntent()
    return DerivationCase(root, SessionManager(IndexStore()), state)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    ("overrides", "path"),
    [
        ({"verification": {"bypass": "bad"}}, "verification.bypass"),
        ({"memory": "not-an-object"}, "memory"),
        (
            {"memory": {"auto_update": {"min_turns": "bad"}}},
            "memory.auto_update.min_turns",
        ),
        ({"launch": {"runtime": "codex"}}, "launch.runtime"),
        ({"launch": {"mode": "host", "model_route": None}}, "launch.model_route"),
        ({"authority": {"role": "producer"}}, "authority"),
        ({"consumer_lanes": {"memory_writer": None}}, "consumer_lanes"),
        (
            {"policy": {"supervisor": {"native_source": None}}},
            "policy.supervisor.native_source",
        ),
    ],
)
def test_invalid_parent_refuses_every_derivation_before_writes(
    case: DerivationCase, operation: str, overrides: dict[str, Any], path: str
) -> None:
    case.publish()
    before = case.replace_raw(overrides=overrides, schema_version=5)
    index_before = case.manager.index_store.index_path.read_bytes()

    with pytest.raises(ForgeSessionError, match=path):
        case.derive(operation)

    case.assert_no_child(before, index_before)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    "changes",
    [
        {"overrides": {"unknown": True}},
        {"overrides": []},
        {"overrides": {"verification": {"bypass": {"nested": True}}}},
        {"schema_version": 999},
    ],
)
def test_strict_manifest_read_failures_remain_atomic(
    case: DerivationCase, operation: str, changes: dict[str, Any]
) -> None:
    case.publish()
    before = case.replace_raw(**changes)
    index_before = case.manager.index_store.index_path.read_bytes()

    with pytest.raises(ManifestCorruptedError):
        case.derive(operation)

    case.assert_no_child(before, index_before)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_invalid_ownerless_parent_is_not_migrated(case: DerivationCase, operation: str) -> None:
    case.publish()
    before = case.replace_raw(overrides={"launch": {"runtime": "codex"}})
    # Deliberately reconstruct an ownerless legacy record after coherent publication.
    # Refusal must precede the parent lease's ordinary identity migration.
    (case.store.session_dir / "review-identity").unlink()
    index = case.manager.index_store.read()
    for entry in index.sessions.values():
        entry.instance_id = None
    case.manager.index_store.write(index)
    index_before = case.manager.index_store.index_path.read_bytes()

    with pytest.raises(ForgeSessionError, match="launch.runtime"):
        case.derive(operation)

    case.assert_no_child(before, index_before)
    assert not (case.store.session_dir / "review-identity").exists()


def test_invalid_fresh_parent_never_assembles_ai_curated_transfer(
    case: DerivationCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    case.publish()
    before = case.replace_raw(overrides={"verification": {"bypass": "bad"}})
    index_before = case.manager.index_store.index_path.read_bytes()
    assemble = Mock(side_effect=AssertionError("invalid parent reached transfer inference"))
    monkeypatch.setattr("forge.session.manager.assemble_transfer_context", assemble)

    with pytest.raises(ForgeSessionError, match="verification.bypass"):
        case.manager.resume_session(
            "parent",
            child_name="child",
            strategy="ai-curated",
            forge_root=str(case.root),
        )

    assemble.assert_not_called()
    case.assert_no_child(before, index_before)


def test_invalid_forced_fork_preserves_existing_worktree(case: DerivationCase) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-m",
            "base",
        ],
        cwd=case.root,
        check=True,
        capture_output=True,
    )
    case.publish()
    _, target = case.manager.fork_session("parent", "child", create_worktree=True, forge_root=str(case.root))
    assert target.worktree is not None and target.forge_root is not None
    target_root = Path(target.worktree.path)
    marker = target_root / "keep.txt"
    marker.write_text("existing target")
    target_store = SessionStore(target.forge_root, "child")
    target_before = target_store.manifest_path.read_bytes()
    before = case.replace_raw(overrides={"verification": {"bypass": "bad"}})
    index_before = case.manager.index_store.index_path.read_bytes()
    worktrees_before = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=case.root,
        capture_output=True,
        check=True,
    ).stdout

    with pytest.raises(ForgeSessionError, match="verification.bypass"):
        case.manager.fork_session(
            "parent",
            "child",
            create_worktree=True,
            force=True,
            forge_root=str(case.root),
        )

    assert marker.read_text() == "existing target"
    assert target_store.manifest_path.read_bytes() == target_before
    assert case.store.manifest_path.read_bytes() == before
    assert case.manager.index_store.index_path.read_bytes() == index_before
    assert (
        subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=case.root,
            capture_output=True,
            check=True,
        ).stdout
        == worktrees_before
    )


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("baseline_enabled", [False, True])
def test_policy_layers_and_authored_verification_follow_selected_inheritance(
    case: DerivationCase, operation: str, baseline_enabled: bool
) -> None:
    case.parent.intent.policy = PolicyIntent(enabled=baseline_enabled)
    case.publish()
    for key, value in (
        ("policy.enabled", json.dumps(not baseline_enabled)),
        ("verification.type", "test_suite"),
        ("verification.max_iterations", "7"),
        ("verification.bypass", "true"),
    ):
        set_session_override(ctx=case.ctx, session_name="parent", key=key, value_str=value)
    parent = case.store.read()
    before = case.store.manifest_path.read_bytes()

    child = case.derive(operation)

    persisted = SessionStore(str(case.root), child.name).read()
    assert persisted.intent.policy == parent.intent.policy
    assert persisted.intent.verification is None
    effective = compute_effective_intent(persisted)
    assert effective.policy is not None
    assert effective.policy.enabled == (not baseline_enabled if operation == "relaunch" else baseline_enabled)
    if operation == "relaunch":
        assert persisted.overrides == parent.overrides
        assert effective.verification is not None and effective.verification.bypass
        assert effective.verification.type == "test_suite"
        assert effective.verification.max_iterations == 7
    else:
        assert persisted.overrides == {}
        assert effective.verification is None
    reset_session_overrides(ctx=case.ctx, session_name="child")
    reset = compute_effective_intent(SessionStore(str(case.root), "child").read())
    assert reset.policy is not None and reset.policy.enabled == baseline_enabled
    assert reset.verification is None
    assert case.store.manifest_path.read_bytes() == before


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("command", ["terminal", "direct"])
def test_supervisor_off_baseline_survives_child_reset(
    case: DerivationCase,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    command: str,
) -> None:
    case.parent.intent.policy = PolicyIntent(enabled=True, supervisor=SupervisorConfig(resume_id="planner"))
    case.parent.overrides = {"policy": {"supervisor": {"suspended": False}}}
    case.publish()
    if command == "terminal":
        result = CliRunner().invoke(main, ["policy", "supervisor", "off", "--session", "parent"])
        assert result.exit_code == 0, result.output
    else:
        from forge.cli.hooks.direct_commands import _handle_policy_supervisor

        monkeypatch.setenv("FORGE_SESSION", "parent")
        _handle_policy_supervisor(["off"])
        assert "Supervisor suspended" in json.loads(capsys.readouterr().out)["reason"]
        monkeypatch.delenv("FORGE_SESSION")
    parent = case.store.read()
    assert parent.intent.policy and parent.intent.policy.supervisor and parent.intent.policy.supervisor.suspended
    assert "suspended" not in parent.overrides.get("policy", {}).get("supervisor", {})

    case.derive(operation)
    reset_session_overrides(ctx=case.ctx, session_name="child")

    effective = compute_effective_intent(SessionStore(str(case.root), "child").read())
    assert effective.policy and effective.policy.supervisor and effective.policy.supervisor.suspended


@pytest.mark.parametrize("operation", OPERATIONS)
def test_memory_effective_exception_retains_only_writer_config(case: DerivationCase, operation: str) -> None:
    case.parent.intent.memory = MemoryIntent(
        auto_recall=True,
        tags=["parent-only"],
        max_chars=9999,
        auto_update=MemoryWriterConfig(enabled=False),
    )
    case.parent.overrides = {
        "memory": {
            "auto_update": {
                "enabled": True,
                "mode": "review-only",
                "proxy": "writer-proxy",
                "direct": True,
                "min_turns": 12,
                "effort": "high",
            }
        }
    }
    case.publish()
    expected_writer = compute_effective_intent(case.store.read()).memory.auto_update  # type: ignore[union-attr]

    case.derive(operation)

    child = SessionStore(str(case.root), "child").read()
    assert child.intent.memory is not None
    if operation == "relaunch":
        assert child.intent.memory == case.parent.intent.memory
        assert child.overrides == case.parent.overrides
    else:
        assert child.intent.memory == MemoryIntent(auto_update=expected_writer)
        assert child.overrides == {}
    assert compute_effective_intent(child).memory.auto_update == expected_writer  # type: ignore[union-attr]


@pytest.mark.parametrize("operation", ["fork", "fresh-native", "fresh-transfer"])
@pytest.mark.parametrize("parent_enabled", [True, False, None])
@pytest.mark.parametrize("memory_flag", [True, False])
def test_explicit_memory_choice_reaches_persisted_child(
    case: DerivationCase, operation: str, parent_enabled: bool | None, memory_flag: bool
) -> None:
    selected = MemoryWriterConfig(
        enabled=bool(parent_enabled),
        mode="review-only",
        proxy="writer",
        direct=True,
        min_turns=17,
        effort="high",
    )
    case.parent.intent.memory = MemoryIntent(auto_update=MemoryWriterConfig(enabled=True))
    case.parent.overrides = {"memory": None if parent_enabled is None else {"auto_update": asdict(selected)}}
    case.publish()

    case.derive(operation, memory_flag=memory_flag)

    child = SessionStore(str(case.root), "child").read()
    expected = (
        replace(selected, enabled=True)
        if parent_enabled is not None and memory_flag
        else MemoryWriterConfig(enabled=memory_flag)
    )
    assert child.intent.memory == MemoryIntent(auto_update=expected)
    assert child.overrides == {}


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("section", ["memory", "policy", "launch"])
def test_nullable_parent_overrides_remain_legal(case: DerivationCase, operation: str, section: str) -> None:
    case.parent.intent.policy = PolicyIntent(enabled=True)
    case.parent.intent.memory = MemoryIntent(auto_update=MemoryWriterConfig(enabled=True))
    case.parent.overrides = {section: None}
    case.publish()

    case.derive(operation)

    child = SessionStore(str(case.root), "child").read()
    effective = compute_effective_intent(child)
    if operation == "relaunch" or section == "memory":
        assert getattr(effective, section) is None
    else:
        assert getattr(effective, section) == getattr(case.parent.intent, section)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("clear_requested_lane", [False, True])
def test_children_inherit_four_lane_requests_without_confirmed_ownership(
    case: DerivationCase, operation: str, clear_requested_lane: bool
) -> None:
    from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
    from forge.policy.team.handlers import TEAM_SUPERVISOR_CONSUMER
    from forge.session.consumer_lanes import read_bound_lane
    from forge.session.memory_writer import MEMORY_WRITER_CONSUMER
    from forge.session.shadow_curation import SHADOW_CURATION_CONSUMER

    requested = LaneRecord("claude_code", "claude-max", "opus")
    frozen = ConsumerLaneBinding(LaneRecord("codex", "chatgpt", "gpt-6.1-sol"), "intent", "2026-10-30T00:00:00Z")
    slots = ("supervisor", "memory_writer", "shadow_curation", "team_supervisor")
    case.parent.intent.consumer_lanes = ConsumerLaneIntent(
        **{slot: None if clear_requested_lane else requested for slot in slots}
    )
    case.parent.confirmed.consumer_lanes = ConsumerLaneConfirmed(**{slot: frozen for slot in slots})
    case.parent.confirmed.policy = PolicyConfirmed(policy_states={"supervisor": {"degraded": True}})
    case.parent.confirmed.artifacts = {"review": {"spent": True}}
    case.publish()
    parent_owner = case.store.review_identity()
    review = case.root / ".forge" / "artifacts" / "parent" / "review"
    review.mkdir(parents=True)
    (review / "spent.json").write_text('{"spent":true}')

    case.derive(operation)

    child_store = SessionStore(str(case.root), "child")
    child = child_store.read()
    assert child.intent.consumer_lanes == case.parent.intent.consumer_lanes
    assert child.confirmed.consumer_lanes is None
    assert child.confirmed.policy is None
    assert child.confirmed.artifacts == {}
    assert child_store.review_identity() not in {None, parent_owner}
    assert not (case.root / ".forge" / "artifacts" / "child" / "review").exists()
    for consumer in (
        SUPERVISOR_CONSUMER,
        MEMORY_WRITER_CONSUMER,
        SHADOW_CURATION_CONSUMER,
        TEAM_SUPERVISOR_CONSUMER,
    ):
        assert read_bound_lane(child, consumer) == (None if clear_requested_lane else requested)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_config_is_independent_while_plan_lookup_remains_live(case: DerivationCase, operation: str) -> None:
    case.parent.intent.policy = PolicyIntent(enabled=True)
    case.parent.confirmed.latest_plan_path = ".claude/plans/first.md"
    case.publish()
    case.derive(operation)
    child_store = SessionStore(str(case.root), "child")
    set_session_override(ctx=case.ctx, session_name="parent", key="policy.enabled", value_str="false")
    set_session_override(
        ctx=case.ctx,
        session_name="child",
        key="policy.bundles",
        value_str='["coding_standards"]',
    )
    child = child_store.read()
    assert compute_effective_intent(child).policy.enabled is True  # type: ignore[union-attr]
    assert compute_effective_intent(case.store.read()).policy.bundles == []  # type: ignore[union-attr]
    case.store.update(
        timeout_s=5,
        mutate=lambda state: setattr(state.confirmed, "latest_plan_path", ".claude/plans/new.md"),
    )
    inherited = resolve_plan_info(child, current_forge_root=str(case.root))
    assert inherited.source == "parent" and inherited.draft_path == ".claude/plans/new.md"
    child_store.update(
        timeout_s=5,
        mutate=lambda state: setattr(state.confirmed, "latest_plan_path", ".claude/plans/own.md"),
    )
    owned = resolve_plan_info(child_store.read(), current_forge_root=str(case.root))
    assert owned.source == "self" and owned.draft_path == ".claude/plans/own.md"


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("schema_version", [2, 3, 4, 5])
def test_empty_overrides_supported_versions_do_not_rewrite_parent(
    case: DerivationCase, operation: str, schema_version: int
) -> None:
    case.publish()
    before = case.replace_raw(schema_version=schema_version)

    case.derive(operation)

    assert case.store.manifest_path.read_bytes() == before
    assert compute_effective_intent(SessionStore(str(case.root), "child").read()).launch == LaunchIntent()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_allowlisted_legacy_memory_projection_is_read_only(case: DerivationCase, operation: str) -> None:
    case.parent.intent.memory = MemoryIntent(auto_update=MemoryWriterConfig(enabled=True))
    case.publish()
    data = json.loads(case.store.manifest_path.read_text())
    # The removed generated_file field is one of the store's explicit no-write migrations.
    data["intent"]["memory"]["generated_file"] = "legacy-memory.md"
    before = case.replace_raw(intent=data["intent"])

    case.derive(operation)

    assert case.store.manifest_path.read_bytes() == before
    assert compute_effective_intent(SessionStore(str(case.root), "child").read()).memory is not None


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("has_current_proxy", [False, True])
def test_legacy_sidecar_and_current_proxy_intent_are_preserved(
    case: DerivationCase, operation: str, has_current_proxy: bool
) -> None:
    case.parent.intent.launch = None
    case.parent.confirmed.is_sandboxed = True
    case.parent.intent.proxy = ProxyIntent("current", "http://localhost:9000") if has_current_proxy else None
    case.parent.confirmed.started_with_proxy = StartedWithProxy("http://localhost:8000", template="old")
    case.publish()

    case.derive(operation)

    child = SessionStore(str(case.root), "child").read()
    assert child.intent.launch is not None and child.intent.launch.mode == "sidecar"
    assert child.intent.proxy == case.parent.intent.proxy
    assert child.confirmed.started_with_proxy is None


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("invalid_kind", ["native-source", "frozen-identity", "malformed-timeout"])
def test_recovery_respects_real_supervisor_reset_limits(
    case: DerivationCase, operation: str, invalid_kind: str
) -> None:
    supervisor = SupervisorConfig(resume_id="planner", supervisor_model="opus", supervisor_effort="low")
    case.parent.intent.policy = PolicyIntent(enabled=False, supervisor=supervisor)
    overrides: dict[str, Any]
    reset_key: str | None
    if invalid_kind == "native-source":
        supervisor.resume_id = None
        supervisor.native_source = NativeSupervisorSource(
            "codex",
            "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00",
            "/codex",
            "/codex/log",
            str(case.root),
            "a" * 64,
        )
        supervisor.auth_mode = "subscription-only"
        supervisor.supervisor_model = "gpt-6.1-sol"
        case.parent.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-6.1-sol"))
        overrides = {"policy": {"supervisor": {"native_source": None}}}
        reset_key = "policy.supervisor.native_source"
    elif invalid_kind == "frozen-identity":
        case.parent.confirmed.consumer_lanes = ConsumerLaneConfirmed(
            supervisor=ConsumerLaneBinding(LaneRecord("claude_code", "anthropic-direct", "opus"), "intent", "now")
        )
        overrides = {
            "authority": None,
            "policy": {"supervisor": {"supervisor_effort": "high"}},
        }
        reset_key = None
    else:
        overrides = {"policy": {"supervisor": {"timeout_seconds": "bad"}}}
        reset_key = "policy.supervisor.timeout_seconds"
    case.publish()
    before = case.replace_raw(overrides=overrides)
    index_before = case.manager.index_store.index_path.read_bytes()

    with pytest.raises(ForgeSessionError) as refused:
        case.derive(operation)

    assert "forge policy supervisor remove --session parent" in str(refused.value)
    with pytest.raises(ForgeOpError):
        reset_session_overrides(ctx=case.ctx, session_name="parent", key=reset_key)
    case.assert_no_child(before, index_before)
    supervisor_remove(store=case.store, manifest=case.store.read())
    if invalid_kind == "frozen-identity":
        reset_session_overrides(ctx=case.ctx, session_name="parent")
    case.derive(operation)
    child = SessionStore(str(case.root), "child").read()
    assert child.intent.policy is not None and child.intent.policy.supervisor is None
    assert child.confirmed.consumer_lanes is None
