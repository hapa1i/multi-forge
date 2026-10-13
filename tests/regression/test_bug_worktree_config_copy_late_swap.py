"""A destination swap at the final open cannot redirect or overwrite config copies."""

import builtins
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from forge.session.worktree import config_copy

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("swap", ["parent", "leaf"])
def test_copy_guards_final_destination_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str) -> None:
    source = tmp_path / "source"
    worktree = tmp_path / "worktree"
    outside = tmp_path / "outside"
    (source / "nested").mkdir(parents=True)
    (worktree / "nested").mkdir(parents=True)
    outside.mkdir()
    (source / "nested" / ".env").write_text("source config")
    (outside / ".env").write_text("outside user file")
    destination = worktree / "nested" / ".env"
    original_open = builtins.open
    original_os_open = os.open
    swapped = False

    def replace_destination() -> None:
        nonlocal swapped
        if swapped:
            return
        swapped = True
        if swap == "parent":
            (worktree / "nested").rename(worktree / "pinned")
            (worktree / "nested").symlink_to(outside, target_is_directory=True)
        else:
            with original_open(destination, "w") as stream:
                stream.write("concurrent user file")

    def racing_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if file == destination and mode == "wb":
            replace_destination()
        return original_open(file, mode, *args, **kwargs)

    def racing_os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & os.O_CREAT and os.fspath(path) == ".env":
            replace_destination()
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", racing_open)
    monkeypatch.setattr(os, "open", racing_os_open)
    monkeypatch.setattr(config_copy, "is_file_tracked", lambda *_args: False)

    result = config_copy.copy_runtime_config(source, worktree, allowlist=("nested/.env",))

    assert swapped
    assert (outside / ".env").read_text() == "outside user file"
    if swap == "leaf":
        assert destination.read_text() == "concurrent user file"
        assert result.copied == []
        assert result.skipped_exists == ["nested/.env"]


def test_copy_preserves_config_permissions_and_times(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    worktree = tmp_path / "worktree"
    source.mkdir()
    worktree.mkdir()
    config = source / ".env"
    config.write_text("private config")
    config.chmod(0o600)
    os.utime(config, ns=(1234567890000000000, 1234567890000000000))
    monkeypatch.setattr(config_copy, "is_file_tracked", lambda *_args: False)

    result = config_copy.copy_runtime_config(source, worktree, allowlist=(".env",))

    assert result.copied == [".env"]
    copied = worktree / ".env"
    assert copied.read_text() == "private config"
    assert stat.S_IMODE(copied.stat().st_mode) == 0o600
    assert copied.stat().st_mtime_ns == config.stat().st_mtime_ns


def test_copy_refuses_root_replaced_at_directory_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    worktree = tmp_path / "worktree"
    outside = tmp_path / "outside"
    source.mkdir()
    worktree.mkdir()
    outside.mkdir()
    (source / ".env").write_text("source config")
    (outside / "keep.txt").write_text("user file")
    original_open = os.open
    swapped = False

    def racing_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal swapped
        if path == worktree and not swapped:
            swapped = True
            worktree.rename(tmp_path / "pinned-worktree")
            worktree.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)
    monkeypatch.setattr(config_copy, "is_file_tracked", lambda *_args: False)
    result = config_copy.copy_runtime_config(source, worktree, allowlist=(".env",))

    assert swapped
    assert not (outside / ".env").exists()
    assert (outside / "keep.txt").read_text() == "user file"
    assert result.copied == []
