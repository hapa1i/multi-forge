"""Generic overrides must not author native supervisor identity, including no-op values."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import (
    ForgeOpError,
    reset_session_overrides,
    set_session_override,
)
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import (
    ConsumerLaneIntent,
    LaneRecord,
    NativeSupervisorSource,
    PolicyIntent,
    SupervisorConfig,
)
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / ".forge").mkdir()
    monkeypatch.chdir(root)
    return root


def _publish_parent(project: Path, *, native: bool) -> tuple[SessionStore, IndexStore, NativeSupervisorSource | None]:
    state = create_session_state("parent", worktree_path=str(project))
    source = (
        NativeSupervisorSource(
            "codex", "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00", "/codex", "/codex/source.jsonl", "/planner", "a" * 64
        )
        if native
        else None
    )
    state.intent.policy = PolicyIntent(
        supervisor=(
            SupervisorConfig(
                native_source=source,
                supervisor_model="gpt-6.1-sol",
                supervisor_effort="low",
                auth_mode="subscription-only",
            )
            if native
            else None
        )
    )
    if native:
        state.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-6.1-sol"))
    state.overrides = {"memory": {"auto_recall": True}}
    index = IndexStore()
    publish_session(index, state, project)
    return SessionStore(str(project), state.name), index, source


@pytest.mark.parametrize("surface", ["direct", "supervisor-object", "policy-object", "wildcard"])
@pytest.mark.parametrize("source_mode", ["absent-null", "native-null", "native-identical"])
def test_native_source_set_refuses_without_changing_persisted_state(
    project: Path, surface: str, source_mode: str
) -> None:
    store, index, source = _publish_parent(project, native=source_mode != "absent-null")
    value: Any = asdict(source) if source_mode == "native-identical" and source is not None else None
    if surface == "supervisor-object":
        key, value = "policy.supervisor", {"native_source": value, "suspended": True}
    elif surface == "policy-object":
        key, value = "policy", {"enabled": False, "supervisor": {"native_source": value}}
    else:
        key = "policy.*" if surface == "wildcard" else "policy.supervisor.native_source"
    before = store.manifest_path.read_bytes()
    index_before = index.index_path.read_bytes()

    with pytest.raises(ForgeOpError, match="native_source") as refused:
        set_session_override(
            ctx=ExecutionContext(project, project, project, project),
            session_name="parent",
            key=key,
            value_str=json.dumps(value),
        )

    assert "forge policy supervisor set" in str(refused.value)
    assert store.manifest_path.read_bytes() == before
    assert index.index_path.read_bytes() == index_before


@pytest.mark.parametrize("field", ["runtime", "thread_id", "home", "header_digest", "managed_session"])
def test_identical_native_source_descendant_cannot_be_authored(project: Path, field: str) -> None:
    store, index, source = _publish_parent(project, native=True)
    assert source is not None
    before = store.manifest_path.read_bytes()
    index_before = index.index_path.read_bytes()

    with pytest.raises(ForgeOpError, match="native_source") as refused:
        set_session_override(
            ctx=ExecutionContext(project, project, project, project),
            session_name="parent",
            key=f"policy.supervisor.native_source.{field}",
            value_str=json.dumps(getattr(source, field)),
        )

    assert "forge policy supervisor set" in str(refused.value)
    assert store.manifest_path.read_bytes() == before
    assert index.index_path.read_bytes() == index_before


@pytest.mark.parametrize(
    ("key", "value"), [("policy", None), ("policy.supervisor", None), ("policy", {"supervisor": None})]
)
def test_nullable_parent_clears_do_not_invent_native_source_overrides(project: Path, key: str, value: Any) -> None:
    store, _, _ = _publish_parent(project, native=False)

    set_session_override(
        ctx=ExecutionContext(project, project, project, project),
        session_name="parent",
        key=key,
        value_str=json.dumps(value),
    )

    assert store.read().overrides["policy"] == (None if key == "policy" and value is None else {"supervisor": None})


@pytest.mark.parametrize("reset_key", ["policy.supervisor.native_source", "policy.supervisor.native_source.home"])
def test_legacy_identical_native_source_keyed_reset_still_works(project: Path, reset_key: str) -> None:
    store, _, source = _publish_parent(project, native=True)
    assert source is not None
    state = store.read()
    # Legacy generic writers could persist redundant native identity. Seed only
    # after coherent publication so reset exercises its historical recovery path.
    source_override = asdict(source) if reset_key.endswith("native_source") else {"home": source.home}
    state.overrides["policy"] = {"supervisor": {"native_source": source_override}}
    store.write(state)

    result = reset_session_overrides(
        ctx=ExecutionContext(project, project, project, project), session_name="parent", key=reset_key
    )

    updated = store.read()
    assert result.was_present
    assert updated.intent.policy is not None and updated.intent.policy.supervisor is not None
    assert updated.intent.policy.supervisor.native_source == source
    expected: dict[str, Any] = {} if reset_key.endswith("native_source") else {"native_source": {}}
    assert updated.overrides == {"memory": {"auto_recall": True}, "policy": {"supervisor": expected}}


def test_legacy_null_native_source_keyed_reset_still_works(project: Path) -> None:
    store, _, _ = _publish_parent(project, native=False)
    state = store.read()
    # A historical explicit null is forbidden for new writes but safe to reset.
    state.overrides["policy"] = {"supervisor": {"native_source": None}}
    store.write(state)

    reset_session_overrides(
        ctx=ExecutionContext(project, project, project, project),
        session_name="parent",
        key="policy.supervisor.native_source",
    )

    assert store.read().overrides == {"memory": {"auto_recall": True}, "policy": {"supervisor": {}}}


def test_legacy_reset_cannot_change_native_identity(project: Path) -> None:
    store, index, _ = _publish_parent(project, native=True)
    state = store.read()
    # Deliberately seed an identity-changing legacy override, which still needs
    # supervisor removal/reconfiguration rather than a generic reset.
    state.overrides["policy"] = {"supervisor": {"native_source": {"home": "/different-codex"}}}
    store.write(state)
    before = store.manifest_path.read_bytes()
    index_before = index.index_path.read_bytes()

    with pytest.raises(ForgeOpError, match="Native source identity requires remove/reconfigure"):
        reset_session_overrides(
            ctx=ExecutionContext(project, project, project, project),
            session_name="parent",
            key="policy.supervisor.native_source.home",
        )

    assert store.manifest_path.read_bytes() == before
    assert index.index_path.read_bytes() == index_before
