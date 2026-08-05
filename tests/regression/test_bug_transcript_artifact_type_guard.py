"""Regression: native resume must not leak non-string transcript artifact paths.

Bug: the native-resume branch in ``SessionManager.resume_session`` copied the latest
transcript artifact's ``copied_path`` without the ``isinstance(str)`` guard used by
its helper/twin. A malformed manifest could therefore persist a non-string
``parent_transcript`` and return a non-string transfer artifact path. D024 later
strengthened the durable-state contract from silent omission to a specific error.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session import SessionManager, SessionStore
from forge.session.exceptions import TranscriptArtifactStateError

pytestmark = pytest.mark.regression


def _init_forge_project(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    (path / ".claude").mkdir()
    (path / ".forge").mkdir()


def test_native_resume_rejects_non_string_transcript_copied_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _init_forge_project(project)
    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(project), direct=True)

    store = SessionStore(str(project), "parent")

    def _corrupt_artifact(manifest: object) -> None:
        manifest.confirmed.artifacts["transcripts"] = [{"copied_path": {"not": "a string"}}]  # type: ignore[attr-defined]

    store.update(timeout_s=5.0, mutate=_corrupt_artifact)

    with pytest.raises(TranscriptArtifactStateError, match="non-string or empty copied_path"):
        manager.resume_session("parent", child_name="child", resume_mode="native")

    assert not SessionStore(str(project), "child").exists()
