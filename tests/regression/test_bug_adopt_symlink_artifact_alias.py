"""Regression: adoption rollback must not unlink a native transcript through an artifact symlink.

Bug: extension_disable_runtime pre-PR review, CRITICAL.
Root cause: the adoption artifact parent could be a symlink to the native
transcript directory. The source and destination then named the same file,
so ``shutil.copy2`` raised ``SameFileError`` and rollback unlinked the
destination alias, deleting the user-owned source.

Fix: reject artifact destinations that resolve outside Forge's canonical
artifact namespace or alias the source, and only roll back an artifact that
the successful copy attempt created.

Affected: src/forge/core/ops/session_adopt.py
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import AdoptError, adopt_session, plan_adoption
from forge.session.claude.paths import get_transcript_path

pytestmark = pytest.mark.regression

_UUID = "dddd4444-5555-6666-7777-888899990000"


def _project_with_native_transcript(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".forge").mkdir()

    native = get_transcript_path(str(project), _UUID)
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_text(
        json.dumps({"type": "user", "cwd": str(project), "message": {"role": "user"}}) + "\n",
        encoding="utf-8",
    )
    os.utime(native, (0, 0))
    return project, native


def test_symlinked_artifact_parent_cannot_alias_native_transcript(tmp_path: Path) -> None:
    project, native = _project_with_native_transcript(tmp_path)
    original = native.read_bytes()

    artifact_root = project / ".forge" / "artifacts" / "adopted"
    artifact_root.mkdir(parents=True)
    (artifact_root / "transcripts").symlink_to(native.parent, target_is_directory=True)

    ctx = ExecutionContext.from_cwd(project)
    with pytest.raises(AdoptError, match="resolves outside the canonical artifact directory"):
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="adopted")

    assert native.is_file(), "a rollback must never unlink the user-owned native transcript"
    assert native.read_bytes() == original


def test_rollback_does_not_unlink_a_preexisting_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, native = _project_with_native_transcript(tmp_path)
    destination = project / ".forge" / "artifacts" / "adopted" / "transcripts" / f"{_UUID}.jsonl"
    destination.parent.mkdir(parents=True)
    destination.write_text("preexisting\n", encoding="utf-8")

    import forge.core.ops.session_adopt as adopt_mod

    def fail_manifest_update(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected manifest update failure")

    monkeypatch.setattr(adopt_mod.SessionStore, "update", fail_manifest_update)

    ctx = ExecutionContext.from_cwd(project)
    with pytest.raises(AdoptError, match="could not capture the transcript"):
        adopt_session(ctx, plan_adoption(ctx, _UUID), name="adopted")

    assert native.is_file(), "the source remains user-owned throughout adoption"
    assert destination.is_file(), "rollback may only unlink an artifact created by this attempt"
