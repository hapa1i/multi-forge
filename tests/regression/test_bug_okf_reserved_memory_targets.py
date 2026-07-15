"""Regression for OKF-reserved official and proposal-shadow targets.

Bug ID: okf-reserved-memory-targets
Root cause: reserved-basename checks were case-sensitive for official docs and
were not applied to custom proposal shadows. On case-insensitive APFS, a mixed-
case spelling could therefore mutate ``index.md``; a proposal could also route
the memory writer into an existing ``docs/log.md``.
Affected files: ``src/forge/session/passport.py``, ``src/forge/cli/memory.py``,
and ``src/forge/session/project_memory.py``.
Fix: case-fold logical and resolved reserved basenames, validate proposal
shadows before side effects, and reject hand-authored reserved shadow targets
during discovery.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


def _forge_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    forge_root = tmp_path / "project"
    (forge_root / ".forge").mkdir(parents=True)
    (forge_root / "docs").mkdir()
    monkeypatch.chdir(forge_root)
    return forge_root


def test_mixed_case_official_alias_cannot_mutate_reserved_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_root = _forge_project(tmp_path, monkeypatch)
    reserved = forge_root / "docs/index.md"
    reserved.write_text("# Reserved OKF index\n", encoding="utf-8")
    mixed_case_alias = forge_root / "docs/Index.md"
    if not mixed_case_alias.exists():
        os.link(reserved, mixed_case_alias)
    assert mixed_case_alias.samefile(reserved)
    before = reserved.read_bytes()

    result = CliRunner().invoke(main, ["memory", "track", "docs/Index.md", "--strategy", "generic"])

    assert result.exit_code == 1
    assert "reserved" in result.output
    assert reserved.read_bytes() == before


def test_custom_proposal_shadow_cannot_target_reserved_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_root = _forge_project(tmp_path, monkeypatch)
    official = forge_root / "docs/notes.md"
    official.write_text("# Notes\n", encoding="utf-8")
    reserved_shadow = forge_root / "docs/log.md"
    reserved_shadow.write_text("# Reserved OKF log\n", encoding="utf-8")
    before_official = official.read_bytes()
    before_shadow = reserved_shadow.read_bytes()

    result = CliRunner().invoke(
        main,
        ["memory", "track", "docs/notes.md", "--propose", "--shadow-path", "docs/log.md"],
    )

    assert result.exit_code == 1
    assert "reserved" in result.output
    assert official.read_bytes() == before_official
    assert reserved_shadow.read_bytes() == before_shadow
