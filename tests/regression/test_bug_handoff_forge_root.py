"""Regression: handoff marker must include forge_root for nested projects.

Bug: enqueue_handoff_marker() only passed worktree_path, which the detached
memory writer used as forge_root. For nested Forge projects (forge_root !=
checkout_root), the agent would look for the session manifest in the wrong
directory.

Fix: All three enqueue functions accept forge_root. Hook callers pass
store.forge_root. The memory-writer CLI (--root) and main.py handler forward it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.workqueue.queue import (
    enqueue_handoff_marker,
    enqueue_index_marker,
    enqueue_stop_marker,
)
from forge.session.index import IndexStore
from tests.fixtures.session_state import publish_session_from_fields

pytestmark = pytest.mark.regression


def test_bug_stop_marker_includes_forge_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    import json

    root = tmp_path / "checkout" / "nested"
    publish_session_from_fields(IndexStore(), "my-session", root, root)
    result = enqueue_stop_marker(
        session_id="test-123",
        worktree_path=tmp_path / "checkout",
        session_name="my-session",
        transcript_snapshot_rel=".forge/artifacts/transcript.jsonl",
        forge_root=str(root),
    )
    assert result is not None
    payload = json.loads(result.read_text())["payload"]
    assert payload["forge_root"] == str(root)
    assert payload["worktree_path"] == str(tmp_path / "checkout")


def test_bug_index_marker_includes_forge_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    import json

    root = tmp_path / "checkout" / "nested"
    publish_session_from_fields(IndexStore(), "my-session", root, root)
    result = enqueue_index_marker(
        session_id="test-123",
        worktree_path=tmp_path / "checkout",
        session_name="my-session",
        transcript_snapshot_rel=".forge/artifacts/transcript.jsonl",
        forge_root=str(root),
    )
    assert result is not None
    payload = json.loads(result.read_text())["payload"]
    assert payload["forge_root"] == str(root)


def test_bug_handoff_marker_includes_forge_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    import json

    root = tmp_path / "checkout" / "nested"
    publish_session_from_fields(IndexStore(), "my-session", root, root)
    result = enqueue_handoff_marker(
        session_id="test-123",
        worktree_path=tmp_path / "checkout",
        session_name="my-session",
        transcript_snapshot_rel=".forge/artifacts/transcript.jsonl",
        forge_root=str(root),
    )
    assert result is not None
    payload = json.loads(result.read_text())["payload"]
    assert payload["forge_root"] == str(root)


def test_bug_markers_backward_compat_no_forge_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitting forge_root binds ownership to the supplied worktree."""
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    import json

    root = tmp_path / "checkout" / "nested"
    publish_session_from_fields(IndexStore(), "my-session", root, root)
    result = enqueue_stop_marker(
        session_id="compat-123",
        worktree_path=root,
        session_name="my-session",
        transcript_snapshot_rel=".forge/artifacts/transcript.jsonl",
    )
    assert result is not None
    payload = json.loads(result.read_text())["payload"]
    assert payload["forge_root"] == str(root)
    assert payload["worktree_path"] == str(root)
