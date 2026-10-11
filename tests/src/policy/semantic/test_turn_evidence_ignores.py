"""Stop capture honors Git exclusions without enabling global executable helpers."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

import pytest

from forge.policy.semantic import turn_evidence as evidence
from tests.fixtures.stop_review import context, deadline, git


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path: Path, monkeypatch) -> None:
    for key in os.environ:
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def captured_paths(ctx) -> set[str]:
    reference = evidence.capture(ctx.checkout, ctx.storage, deadline=deadline())
    return set(evidence.load(ctx.storage, reference)["files"])


def assert_matches_git(ctx) -> set[str]:
    expected = {
        os.fsdecode(path)
        for path in git(ctx.checkout, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")
        if path and not path.startswith(b".forge/")
    }
    actual = captured_paths(ctx)
    assert actual == expected
    return actual


@pytest.mark.parametrize("scope", ["global", "include", "conditional", "system", "local", "worktree", "environment"])
def test_effective_config_precedence_and_includes(tmp_path: Path, monkeypatch, scope: str) -> None:
    ctx = context(tmp_path)
    primary, override = tmp_path / "global-ignore", tmp_path / "effective-ignore"
    primary.write_text("global.txt\n")
    override.write_text("effective.txt\nwork.txt\n")
    global_config = tmp_path / "gitconfig"
    git(ctx.checkout, "config", "--file", str(global_config), "core.excludesFile", str(primary))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    if scope == "global":
        git(ctx.checkout, "config", "--file", str(global_config), "core.excludesFile", str(override))
    elif scope in {"include", "conditional"}:
        included = tmp_path / "included-config"
        git(ctx.checkout, "config", "--file", str(included), "core.excludesFile", str(override))
        key = "include.path" if scope == "include" else f"includeIf.gitdir:{ctx.checkout.resolve()}/.git.path"
        git(ctx.checkout, "config", "--file", str(global_config), key, str(included))
    elif scope == "system":
        monkeypatch.delenv("GIT_CONFIG_NOSYSTEM")
        monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(global_config))
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
        git(ctx.checkout, "config", "--file", str(global_config), "core.excludesFile", str(override))
    elif scope == "local":
        git(ctx.checkout, "config", "core.excludesFile", str(override))
    elif scope == "worktree":
        git(ctx.checkout, "config", "extensions.worktreeConfig", "true")
        linked = tmp_path / "linked"
        git(ctx.checkout, "worktree", "add", "--detach", str(linked))
        ctx = replace(ctx, checkout=linked)
        git(linked, "config", "--worktree", "core.excludesFile", str(override))
    else:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(override))
    for name in ("global.txt", "effective.txt", "ordinary.txt", "ignored.txt", "local.txt", "info.txt"):
        (ctx.checkout / name).write_text(name + "\n")
    (ctx.checkout / ".gitignore").write_text(".forge/\nignored.txt\nlocal.txt\n!effective.txt\n")
    # Per-directory rules outrank the global excludes file; info/exclude remains active.
    common = Path(os.fsdecode(git(ctx.checkout, "rev-parse", "--git-common-dir")).strip())
    (ctx.checkout / common / "info/exclude").write_text("info.txt\n")
    actual = assert_matches_git(ctx)
    assert {"global.txt", "effective.txt", "ordinary.txt", "work.txt"} <= actual
    assert {"ignored.txt", "local.txt", "info.txt"}.isdisjoint(actual)
    (ctx.checkout / ".gitignore").write_text(".forge/\nignored.txt\nlocal.txt\n")
    assert "effective.txt" not in assert_matches_git(ctx)


@pytest.mark.parametrize("location", ["xdg", "home", "empty-xdg", "tilde", "relative", "symlink", "newline"])
def test_default_and_configured_paths(tmp_path: Path, monkeypatch, location: str) -> None:
    ctx = context(tmp_path)
    if location == "xdg":
        ignore = Path(os.environ["XDG_CONFIG_HOME"]) / "git/ignore"
    elif location in {"home", "empty-xdg"}:
        monkeypatch.delenv("XDG_CONFIG_HOME")
        if location == "empty-xdg":
            monkeypatch.setenv("XDG_CONFIG_HOME", "")
        ignore = Path.home() / ".config/git/ignore"
    else:
        ignore = Path.home() / ("rules with\nnewline" if location == "newline" else "rules with spaces")
    ignore.parent.mkdir(parents=True, exist_ok=True)
    ignore.write_text("hidden.txt\n")
    if location not in {"xdg", "home", "empty-xdg"}:
        path = str(ignore)
        if location == "tilde":
            path = "~/rules with spaces"
        elif location == "relative":
            path = os.path.relpath(ignore, ctx.checkout)
        elif location == "symlink":
            link = tmp_path / "ignore-link"
            link.symlink_to(ignore)
            path = str(link)
        git(ctx.checkout, "config", "--global", "core.excludesFile", path)
    (ctx.checkout / "hidden.txt").write_text("synthetic ignored content\n")
    (ctx.checkout / "visible.txt").write_text("visible\n")
    actual = assert_matches_git(ctx)
    assert "hidden.txt" not in actual and "visible.txt" in actual


@pytest.mark.parametrize("override", ["", os.devnull, "missing"])
def test_empty_or_missing_override_does_not_restore_global_or_default(tmp_path: Path, override: str) -> None:
    ctx = context(tmp_path)
    ignore = Path(os.environ["XDG_CONFIG_HOME"]) / "git/ignore"
    ignore.parent.mkdir(parents=True)
    ignore.write_text("hidden.txt\n")
    git(ctx.checkout, "config", "--global", "core.excludesFile", str(ignore))
    git(ctx.checkout, "config", "core.excludesFile", override)
    (ctx.checkout / "hidden.txt").write_text("explicitly included\n")
    assert "hidden.txt" in assert_matches_git(ctx)


@pytest.mark.parametrize("failure", ["unreadable", "large", "fifo", "directory", "bad-config", "config-fifo"])
def test_invalid_exclusions_refuse_before_snapshot_content(tmp_path: Path, monkeypatch, failure: str) -> None:
    ctx = context(tmp_path)
    ignore = tmp_path / "rules"
    ignore.write_text("work.txt\n")
    config = tmp_path / "gitconfig"
    git(ctx.checkout, "config", "--file", str(config), "core.excludesFile", str(ignore))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    expected: type[Exception] = ValueError
    if failure == "unreadable":
        real_open = os.open

        def fail_read(path, *args, **kwargs):
            if path == ignore:
                raise PermissionError("fixture permission failure")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(os, "open", fail_read)
        expected = PermissionError
    elif failure == "large":
        ignore.write_bytes(b"x" * (evidence.MAX_FILE_BYTES + 1))
    elif failure in {"fifo", "directory"}:
        ignore.unlink()
        os.mkfifo(ignore) if failure == "fifo" else ignore.mkdir()
    elif failure == "bad-config":
        config.write_text("[invalid\n")
    else:
        config.unlink()
        os.mkfifo(config)
        expected = TimeoutError
    start = time.monotonic()
    with pytest.raises((expected, IsADirectoryError)):
        evidence.capture(ctx.checkout, ctx.storage, deadline=start + 0.5)
    assert time.monotonic() - start < 3
    assert not list(ctx.storage.glob("*.blob"))
    assert not list(ctx.storage.glob("*.snapshot"))


def test_config_query_ignores_inherited_repository_selectors(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    git(ctx.checkout, "config", "--global", "core.excludesFile", "../rules")
    (tmp_path / "rules").write_text("hidden.txt\n")
    (ctx.checkout / "hidden.txt").write_text("excluded\n")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "wrong-repo"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "wrong-tree"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(tmp_path / "wrong-index"))
    # GIT_CONFIG is a config-command-only --file override, not effective repo config.
    monkeypatch.setenv("GIT_CONFIG", str(tmp_path / "wrong-config"))
    assert captured_paths(ctx) == {".gitignore", "work.txt"}


def test_global_helpers_and_trace_outputs_remain_disabled(tmp_path: Path, monkeypatch) -> None:
    ctx = context(tmp_path)
    config = tmp_path / "gitconfig"
    marker = tmp_path / "helper-ran"
    for key in (
        "core.fsmonitor",
        "filter.spy.clean",
        "filter.spy.process",
        "diff.external",
        "diff.spy.textconv",
        "credential.helper",
    ):
        git(ctx.checkout, "config", "--file", str(config), key, f"touch '{marker}'; cat")
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    post_index = hooks / "post-index-change"
    post_index.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    post_index.chmod(0o755)
    git(ctx.checkout, "config", "--file", str(config), "core.hooksPath", str(hooks))
    traces = [tmp_path / name for name in ("normal", "perf", "event")]
    for key, path in zip(("trace2.normalTarget", "trace2.perfTarget", "trace2.eventTarget"), traces):
        git(ctx.checkout, "config", "--file", str(config), key, str(path))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    (ctx.checkout / ".gitattributes").write_text("*.dat filter=spy diff=spy\n")
    (ctx.checkout / "raw.dat").write_text("raw contents\n")
    index = (ctx.checkout / ".git/index").read_bytes()
    objects = sorted((ctx.checkout / ".git/objects").rglob("*"))
    assert "raw.dat" in captured_paths(ctx)
    assert not marker.exists()
    assert all(not path.exists() for path in traces)
    assert (ctx.checkout / ".git/index").read_bytes() == index
    assert sorted((ctx.checkout / ".git/objects").rglob("*")) == objects
