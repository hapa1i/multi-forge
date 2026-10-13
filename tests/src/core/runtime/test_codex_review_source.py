"""Boundary/lineage regressions, independent of live model availability."""

import json
from typing import Any

import pytest

from forge.core.native_review_types import NativeReviewBoundary
from forge.core.runtime.codex_review_source import (
    bind_source,
    select_prefixes,
    select_source,
)
from tests.fixtures.native_supervisor import (
    CHILD,
    THREAD,
    TURN,
    allow_synthetic_instructions,
    synthetic_rows,
    write_rollout,
)


@pytest.fixture
def source_home(tmp_path, monkeypatch):
    allow_synthetic_instructions(monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    return tmp_path


def select(source, **changes):
    args: dict[str, Any] = dict(
        model="gpt-6.1-sol",
        auth_mode="subscription-only",
        plan="",
        trigger="pre-tool-use",
        executor_origin="claude_code",
        boundary=None,
    )
    args.update(changes)
    return select_source(source, **args)


def test_compacted_usage_uses_event_baseline_and_exact_prefix(source_home):
    rows = synthetic_rows()
    rows.insert(3, {"type": "compacted", "payload": {"message": "synthetic compaction"}})
    path = write_rollout(source_home, rows)
    source = bind_source(THREAD, forge_root=None)
    selected = select(source)
    assert selected.baseline is not None and selected.baseline.input_tokens == 812603
    assert selected.prefixes[0].data == path.read_bytes()
    assert selected.independence == "separate"
    with pytest.raises(ValueError, match="Long, compacted"):
        select(source, auth_mode="api")


def test_managed_source_binds_confirmed_native_identity_and_rechecks_it(source_home):
    from forge.session import IndexStore, SessionStore, create_session_state
    from forge.session.models import CodexConfirmed
    from tests.fixtures.session_state import publish_session

    project = source_home / "project"
    project.mkdir()
    (project / ".forge").mkdir()
    path = write_rollout(source_home, synthetic_rows())
    state = create_session_state("planner", worktree_path=str(project), runtime="codex")
    state.confirmed.codex = CodexConfirmed(thread_id=THREAD, rollout_path=str(path))
    publish_session(IndexStore(), state, project)
    bound = bind_source("planner", forge_root=str(project))
    assert bound.managed_session == "planner" and bound.thread_id == THREAD
    assert select(bound).prefixes[0].path == path
    state.confirmed.codex.thread_id = CHILD
    SessionStore(str(project), "planner").write(state)
    with pytest.raises(ValueError, match="binding changed"):
        select(bound)


def test_managed_claude_source_cannot_supply_codex_identity(source_home):
    from forge.session import IndexStore, create_session_state
    from tests.fixtures.session_state import publish_session

    project = source_home / "project"
    project.mkdir()
    (project / ".forge").mkdir()
    state = create_session_state("claude-planner", worktree_path=str(project))
    state.confirmed.claude_session_id = THREAD
    publish_session(IndexStore(), state, project)
    with pytest.raises(ValueError, match="confirmed Codex"):
        bind_source("claude-planner", forge_root=str(project))


def test_native_stop_requires_matching_final_answer_and_plan(source_home):
    rows = synthetic_rows()
    path = write_rollout(source_home, rows)
    source = bind_source(THREAD, forge_root=None)
    rows.pop()
    write_rollout(source_home, rows)
    boundary = NativeReviewBoundary(THREAD, TURN, str(path), "Stop", "BOUNDARY_DONE")
    selected = select(source, plan="Use COBALT", trigger="stop", executor_origin="codex", boundary=boundary)
    assert selected.independence == "shared"
    for changed in (
        dict(plan=""),
        dict(boundary=None),
        dict(boundary=NativeReviewBoundary(THREAD, TURN, str(path), "Stop", "wrong")),
    ):
        args: dict[str, Any] = dict(plan="Use COBALT", trigger="stop", executor_origin="codex", boundary=boundary)
        args.update(changed)
        with pytest.raises(ValueError):
            select(source, **args)
    with pytest.raises(ValueError, match="not complete"):
        select(source)


def test_fork_ancestry_is_shared_even_with_a_different_id(source_home):
    parent = synthetic_rows()
    path = write_rollout(source_home, parent)
    child = synthetic_rows(CHILD)
    child[0]["payload"].update(
        history_base={
            "thread_id": THREAD,
            "end_ordinal_exclusive": len(parent),
            "end_byte_offset": path.stat().st_size,
        },
        forked_from_id=THREAD,
        forked_from_ordinal_exclusive=len(parent),
    )
    child_path = write_rollout(source_home, child)
    source = bind_source(CHILD, forge_root=None)
    assert len(select_prefixes(source_home, CHILD)) == 2
    with pytest.raises(ValueError, match="Shared or unknown"):
        select(source, executor_origin="codex", boundary=NativeReviewBoundary(THREAD, TURN, str(path), "PreToolUse"))
    child[0]["payload"]["history_base"]["end_ordinal_exclusive"] -= 1
    child_path.write_text("\n".join(json.dumps(row) for row in child) + "\n")
    with pytest.raises(ValueError, match="ancestry|boundaries"):
        select_prefixes(source_home, CHILD)


@pytest.mark.parametrize(
    "change", ["partial", "pending", "account", "model", "custom", "header", "limit", "symlink", "ambiguous"]
)
def test_unproven_or_changed_sources_refuse_before_inference(source_home, change):
    rows = synthetic_rows()
    path = write_rollout(source_home, rows)
    source = bind_source(THREAD, forge_root=None)
    if change == "partial":
        path.write_bytes(path.read_bytes() + b'{"type":')
    elif change == "pending":
        rows.insert(3, {"type": "response_item", "payload": {"type": "function_call", "call_id": "unfinished"}})
        write_rollout(source_home, rows)
    elif change == "account":
        rows[0]["payload"].pop("creator_account_id")
        write_rollout(source_home, rows)
    elif change == "model":
        rows[2]["payload"]["model"] = "untested"
        write_rollout(source_home, rows)
    elif change == "custom":
        rows[0]["payload"]["base_instructions"] = {"text": "custom instructions"}
        write_rollout(source_home, rows)
    elif change == "header":
        rows[0]["payload"]["cwd"] = "/changed"
        write_rollout(source_home, rows)
    elif change == "limit":
        rows[4]["payload"]["info"]["last_token_usage"]["input_tokens"] = 163003
        write_rollout(source_home, rows)
    elif change == "symlink":
        backup = path.with_suffix(".bak")
        path.rename(backup)
        path.symlink_to(backup)
    elif change == "ambiguous":
        path.with_name(path.name.replace("01-02-03", "02-02-03")).write_bytes(path.read_bytes())
    with pytest.raises((ValueError, OSError)):
        select(source)
