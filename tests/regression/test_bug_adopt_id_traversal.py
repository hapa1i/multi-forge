"""Regression: `forge session adopt` deleted arbitrary files via an unvalidated id.

Bug: native_session_adoption Slice 2 review, CRITICAL.
Root cause: `plan_adoption` only rejected an empty conversation id, then fed it
straight into `get_transcript_path()`. `Path(base) / "/abs/path"` discards
`base`, so an absolute-path id made `transcript_path` point at an arbitrary
file. The artifact copy derived its destination from the same id, so source and
destination aliased to one path; `shutil.copy2` raised `SameFileError`, and the
adopt rollback then unlinked that path -- deleting the user's file.

Fix: `normalize_conversation_id` anchors the id to canonical UUID shape before
any path is constructed.

Affected: src/forge/core/ops/session_adopt.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import AdoptError, plan_adoption

pytestmark = pytest.mark.regression


def test_absolute_path_id_cannot_reach_a_file_outside_the_project(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()

    victim = tmp_path / "precious" / "my-notes.jsonl"
    victim.parent.mkdir()
    victim.write_text('{"type":"user","cwd":"/anywhere"}\n', encoding="utf-8")

    # The exploit passed the victim's path stem so both the read and the copy
    # destination resolved to it. Rejection must happen before any path is built.
    with pytest.raises(AdoptError, match="is not a conversation id"):
        plan_adoption(ExecutionContext.from_cwd(project), str(victim.with_suffix("")))

    assert victim.exists(), "adoption must never unlink a file outside its own artifacts"
    assert victim.read_text(encoding="utf-8").startswith('{"type":"user"')
