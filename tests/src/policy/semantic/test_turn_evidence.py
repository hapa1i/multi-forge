"""Raw turn evidence preserves dirty baselines without invoking Git helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.policy.semantic import turn_evidence as evidence
from tests.fixtures.stop_review import context, deadline, git


def capture(ctx):
    return evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())


def actions():
    return [{"id": "tool", "phase": phase} for phase in ("request", "outcome")]


def test_dirty_staged_baseline_add_delete_rename_and_mode(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    root = ctx.checkout
    (root / "work.txt").write_text("already staged\n")
    git(root, "add", "work.txt")
    (root / "work.txt").write_text("already dirty\n")
    (root / "renamed.txt").write_text("preserve me\n")
    before = capture(ctx)
    index = (root / ".git/index").read_bytes()
    (root / "work.txt").write_text("already dirty\nnew work\n")
    (root / "renamed.txt").rename(root / "moved.txt")
    (root / "moved.txt").chmod(0o755)
    (root / "new.txt").write_text("addition\n")
    result = evidence.compare(ctx.storage, before, capture(ctx), actions())
    assert result["complete"]
    changes = {c["path"]: c for c in result["changes"]}
    assert "already staged" not in changes["work.txt"]["diff"]
    assert "+new work" in changes["work.txt"]["diff"]
    assert changes["moved.txt"]["renamed_from"] == "renamed.txt"
    assert changes["moved.txt"]["after"]["mode"] == 0o755
    assert changes["renamed.txt"]["kind"] == "delete"
    assert changes["new.txt"]["kind"] == "add"
    assert (root / ".git/index").read_bytes() == index


def test_clean_process_filters_and_fsmonitor_never_run(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    root, marker = ctx.checkout, tmp_path / "external-marker"
    command = f"touch '{marker}'; cat"
    git(root, "config", "filter.spy.clean", command)
    git(root, "config", "filter.lfs.process", command)
    git(root, "config", "core.fsmonitor", command)
    (root / ".gitattributes").write_text("*.dat filter=spy\n*.lfs filter=lfs diff=lfs merge=lfs\n")
    (root / "test.dat").write_text("raw\n")
    (root / "pointer.lfs").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 100\n")
    original_index = (root / ".git/index").read_bytes()
    objects = sorted(p.relative_to(root) for p in (root / ".git/objects").rglob("*") if p.is_file())
    before = capture(ctx)
    (root / "test.dat").write_text("raw changed\n")
    result = evidence.compare(ctx.storage, before, capture(ctx), actions())
    assert result["complete"]
    assert not marker.exists()
    assert (root / ".git/index").read_bytes() == original_index
    assert objects == sorted(p.relative_to(root) for p in (root / ".git/objects").rglob("*") if p.is_file())
    assert "raw changed" in json.dumps(result)


@pytest.mark.parametrize("kind", ["binary", "large", "symlink", "index"])
def test_unsupported_changed_scope_never_clean(tmp_path: Path, kind: str) -> None:
    ctx = context(tmp_path)
    before = capture(ctx)
    path = ctx.checkout / "work.txt"
    if kind == "binary":
        path.write_bytes(b"binary\x00")
    elif kind == "large":
        path.write_bytes(b"x" * (evidence.MAX_FILE_BYTES + 1))
    elif kind == "symlink":
        path.unlink()
        path.symlink_to(tmp_path / "approved.md")
    else:
        path.write_text("staged by someone\n")
        git(ctx.checkout, "add", "work.txt")
    result = evidence.compare(ctx.storage, before, capture(ctx), actions())
    assert not result["complete"]
    assert result["omissions"]


def test_outcomes_survive_edit_revert_and_missing_event_is_incomplete(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    before = capture(ctx)
    result = evidence.compare(ctx.storage, before, capture(ctx), actions())
    assert not result["changes"] and result["actions"] == actions()
    result = evidence.compare(ctx.storage, before, capture(ctx), actions()[:1])
    assert result["omissions"] == ["missing_tool_event"]


def test_tampered_content_and_missing_snapshot_refused(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    before = capture(ctx)
    (ctx.storage / (before["digest"] + ".snapshot")).write_text("{}")
    with pytest.raises(ValueError, match="digest changed"):
        evidence.compare(ctx.storage, before, before, [])


def test_private_index_candidate_still_runs_external_clean_filter(tmp_path: Path) -> None:
    """Negative control: private Git storage does not contain executable filters."""
    import os
    import shutil
    import subprocess

    ctx = context(tmp_path)
    root = ctx.checkout
    private = tmp_path / "private-git"
    private.mkdir()
    (private / "objects").mkdir()
    shutil.copy2(root / ".git/index", private / "index")
    index_before = (root / ".git/index").read_bytes()
    objects_before = sorted(p.relative_to(root) for p in (root / ".git/objects").rglob("*") if p.is_file())
    marker = tmp_path / "outside-private-storage"
    git(root, "config", "filter.spy.clean", f"touch '{marker}'; cat")
    (root / ".gitattributes").write_text("*.dat filter=spy\n")
    (root / "input.dat").write_text("candidate input\n")
    env = dict(
        os.environ,
        GIT_INDEX_FILE=str(private / "index"),
        GIT_OBJECT_DIRECTORY=str(private / "objects"),
        GIT_ALTERNATE_OBJECT_DIRECTORIES=str(root / ".git/objects"),
    )
    subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "add", "input.dat"],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        timeout=5,
    )
    assert marker.exists()  # Deliberate negative-control effect, unlike the product capture test above.
    assert (root / ".git/index").read_bytes() == index_before
    assert objects_before == sorted(p.relative_to(root) for p in (root / ".git/objects").rglob("*") if p.is_file())
