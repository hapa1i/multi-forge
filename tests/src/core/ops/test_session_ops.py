from __future__ import annotations

import json
import os
from pathlib import Path

from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import list_sessions
from forge.session import IndexStore, create_session_state
from forge.session.active import ActiveSessionStore
from tests.fixtures.session_state import publish_session, publish_session_from_fields


def test_list_sessions_empty(tmp_path: Path, monkeypatch) -> None:
    # Isolate ~/.forge into tmp via HOME.
    monkeypatch.setenv("HOME", str(tmp_path))

    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path)
    result = list_sessions(ctx=ctx, include_incognito=True)

    assert result.sessions == []


def test_list_sessions_reads_index(tmp_path: Path, monkeypatch) -> None:
    # Isolate ~/.forge into tmp via HOME.
    monkeypatch.setenv("HOME", str(tmp_path))

    wt = tmp_path / "wt"
    index = IndexStore()
    publish_session_from_fields(index, "alpha", wt, tmp_path)

    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path)
    result = list_sessions(ctx=ctx, include_incognito=True)

    assert [s.name for s in result.sessions] == ["alpha"]


def test_list_sessions_reports_direct_model_pin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    wt = tmp_path / "wt"
    state = create_session_state("alpha", worktree_path=str(wt), direct_model="claude-opus-4-8")
    publish_session(
        IndexStore(),
        state,
        tmp_path,
        forge_root=str(wt),
        checkout_root=str(wt),
        relative_path=".",
    )

    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path)
    result = list_sessions(ctx=ctx, include_incognito=True)

    assert len(result.sessions) == 1
    item = result.sessions[0]
    assert item.proxy_template == "direct"
    assert item.model == "claude-opus-4-8"
    assert item.models == ("claude-opus-4-8",)


def test_list_sessions_reports_direct_model_history_from_transcripts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    wt = tmp_path / "wt"
    first_rel = Path(".forge") / "artifacts" / "alpha" / "transcripts" / "first.jsonl"
    second_rel = Path(".forge") / "artifacts" / "alpha" / "transcripts" / "second.jsonl"
    first_path = wt / first_rel
    second_path = wt / second_rel
    first_path.parent.mkdir(parents=True)
    first_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "assistant", "message": {"model": "claude-fable-5"}}),
                json.dumps({"type": "assistant", "message": {"model": "claude-fable-5"}}),
            ]
        )
        + "\n"
    )
    second_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "assistant", "message": {"model": "claude-fable-5"}}),
                json.dumps({"type": "assistant", "message": {"model": "<synthetic>"}}),
                json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5"}}),
                json.dumps({"type": "assistant", "message": {"model": "claude-opus-4-8"}}),
            ]
        )
        + "\n"
    )

    state = create_session_state("alpha", worktree_path=str(wt), direct_model="claude-opus-4-8")
    state.confirmed.artifacts["transcripts"] = [
        {"copied_path": str(first_rel)},
        {"copied_path": str(second_rel)},
        {"copied_path": str(second_rel)},
    ]
    publish_session(
        IndexStore(),
        state,
        tmp_path,
        forge_root=str(wt),
        checkout_root=str(wt),
        relative_path=".",
    )

    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path)
    result = list_sessions(ctx=ctx, include_incognito=True)

    assert len(result.sessions) == 1
    item = result.sessions[0]
    assert item.proxy_template == "direct"
    assert item.models == ("claude-fable-5", "claude-sonnet-5", "claude-opus-4-8")
    assert item.model == "claude-fable-5 -> claude-sonnet-5 -> claude-opus-4-8"


def test_list_sessions_is_active_reflects_active_store(tmp_path: Path, monkeypatch) -> None:
    """is_active is True only for sessions the runtime active-session registry lists as live."""
    monkeypatch.setenv("HOME", str(tmp_path))

    wt = tmp_path / "wt"
    for name in ("live", "dormant"):
        publish_session_from_fields(
            IndexStore(),
            name,
            wt,
            tmp_path,
            forge_root=str(wt),
            checkout_root=str(wt),
            relative_path=".",
        )

    # Mark only "live" active, tagged with this process's PID so the liveness probe passes.
    ActiveSessionStore().upsert_session(
        "live",
        worktree_path=str(wt),
        launch_mode="host",
        launcher_pid=os.getpid(),
        forge_root=str(wt),
    )

    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path)
    result = list_sessions(ctx=ctx, include_incognito=True)

    by_name = {s.name: s.is_active for s in result.sessions}
    assert by_name == {"live": True, "dormant": False}


def _seed_sessions(tmp_path: Path) -> None:
    """Seed index with sessions in two repos and two forge roots."""
    index = IndexStore()

    # Session in repo-A, forge root at repo-A root
    wt_a = tmp_path / "repo-a"
    publish_session_from_fields(
        index,
        "sess-a",
        wt_a,
        wt_a,
        forge_root=str(wt_a),
        checkout_root=str(wt_a),
        relative_path=".",
    )

    # Session in repo-A worktree (same project_root, different forge_root)
    wt_a2 = tmp_path / "repo-a-feat"
    publish_session_from_fields(
        index,
        "sess-a-feat",
        wt_a2,
        wt_a,
        forge_root=str(wt_a2),
        checkout_root=str(wt_a2),
        relative_path=".",
    )

    # Session in repo-B (different project_root)
    wt_b = tmp_path / "repo-b"
    publish_session_from_fields(
        index,
        "sess-b",
        wt_b,
        wt_b,
        forge_root=str(wt_b),
        checkout_root=str(wt_b),
        relative_path=".",
    )


def test_list_scope_workspace_filters_by_project_root(tmp_path: Path, monkeypatch) -> None:
    """scope=workspace shows sessions from the same workspace (logical repo) only."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _seed_sessions(tmp_path)

    repo_a = tmp_path / "repo-a"
    ctx = ExecutionContext(cwd=repo_a, worktree_root=repo_a, project_root=repo_a, forge_root=repo_a)
    result = list_sessions(ctx=ctx, include_incognito=True, scope="workspace")

    names = {s.name for s in result.sessions}
    assert names == {"sess-a", "sess-a-feat"}
    assert "sess-b" not in names


def test_list_scope_project_filters_by_forge_root(tmp_path: Path, monkeypatch) -> None:
    """scope=project shows sessions from the same Forge project only."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _seed_sessions(tmp_path)

    repo_a = tmp_path / "repo-a"
    ctx = ExecutionContext(cwd=repo_a, worktree_root=repo_a, project_root=repo_a, forge_root=repo_a)
    result = list_sessions(ctx=ctx, include_incognito=True, scope="project")

    names = {s.name for s in result.sessions}
    assert names == {"sess-a"}


def test_list_scope_all_returns_everything(tmp_path: Path, monkeypatch) -> None:
    """scope=all shows all sessions globally."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _seed_sessions(tmp_path)

    repo_a = tmp_path / "repo-a"
    ctx = ExecutionContext(cwd=repo_a, worktree_root=repo_a, project_root=repo_a, forge_root=repo_a)
    result = list_sessions(ctx=ctx, include_incognito=True, scope="all")

    names = {s.name for s in result.sessions}
    assert names == {"sess-a", "sess-a-feat", "sess-b"}


def test_list_default_scope_is_workspace(tmp_path: Path, monkeypatch) -> None:
    """Default scope is workspace (filters by project_root)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    _seed_sessions(tmp_path)

    repo_a = tmp_path / "repo-a"
    ctx = ExecutionContext(cwd=repo_a, worktree_root=repo_a, project_root=repo_a, forge_root=repo_a)
    # No scope arg = default
    result = list_sessions(ctx=ctx, include_incognito=True)

    names = {s.name for s in result.sessions}
    assert names == {"sess-a", "sess-a-feat"}


def test_list_invalid_scope_raises(tmp_path: Path, monkeypatch) -> None:
    """Invalid scope raises ForgeOpError."""
    from forge.core.ops.session import ForgeOpError

    monkeypatch.setenv("HOME", str(tmp_path))
    ctx = ExecutionContext(cwd=tmp_path, worktree_root=tmp_path, project_root=tmp_path)

    import pytest

    with pytest.raises(ForgeOpError, match="Invalid scope"):
        list_sessions(ctx=ctx, include_incognito=True, scope="bogus")


def test_list_sessions_reads_manifest_with_entry_scope(tmp_path: Path, monkeypatch) -> None:
    """Duplicate names across forge_roots should load the correct manifest metadata."""
    monkeypatch.setenv("HOME", str(tmp_path))

    index = IndexStore()
    project_root = tmp_path / "repo"
    project_root.mkdir()

    forge_root_a = tmp_path / "proj-a"
    forge_root_b = tmp_path / "proj-b"
    worktree_a = tmp_path / "wt-a"
    worktree_b = tmp_path / "wt-b"
    worktree_a.mkdir()
    worktree_b.mkdir()

    manifest_a = create_session_state(
        "shared",
        proxy_template="template-a",
        proxy_base_url="http://localhost:8101",
        worktree_path=str(worktree_a),
    )
    manifest_a.forge_root = str(forge_root_a)

    manifest_b = create_session_state(
        "shared",
        proxy_template="template-b",
        proxy_base_url="http://localhost:8102",
        worktree_path=str(worktree_b),
    )
    manifest_b.forge_root = str(forge_root_b)

    publish_session(
        index,
        manifest_a,
        project_root,
        forge_root=str(forge_root_a),
        checkout_root=str(worktree_a),
        relative_path="alpha",
    )
    publish_session(
        index,
        manifest_b,
        project_root,
        forge_root=str(forge_root_b),
        checkout_root=str(worktree_b),
        relative_path="beta",
    )

    ctx = ExecutionContext(cwd=project_root, worktree_root=project_root, project_root=project_root)
    result = list_sessions(ctx=ctx, include_incognito=True, scope="workspace")

    assert len(result.sessions) == 2
    templates = sorted(item.proxy_template or "" for item in result.sessions)
    assert templates == ["template-a", "template-b"]
    assert {item.entry.forge_root for item in result.sessions} == {str(forge_root_a), str(forge_root_b)}
