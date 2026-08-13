"""D037 regression: re-tracking cannot update an OKF-reserved document."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session.passport import serialize_passport, synthesize_passport

pytestmark = pytest.mark.regression


def _write_hand_authored_passport(path: Path) -> None:
    passport_yaml = serialize_passport(synthesize_passport(strategy="generic"))
    path.write_text(f"---\n{passport_yaml}---\n# Reserved OKF document\n", encoding="utf-8")


def _make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    (project / "docs").mkdir()
    monkeypatch.chdir(project)
    return project


@pytest.mark.parametrize("basename", ["index.md", "log.md"])
def test_retrack_rejects_reserved_logical_basename_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    basename: str,
) -> None:
    project = _make_project(tmp_path, monkeypatch)
    document = project / "docs" / basename
    _write_hand_authored_passport(document)
    before = document.read_bytes()

    result = CliRunner().invoke(
        main,
        ["memory", "track", f"docs/{basename}", "--strategy", "changelog"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "reserved" in result.stderr
    assert document.read_bytes() == before


def test_retrack_rejects_alias_resolving_to_reserved_basename_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path, monkeypatch)
    reserved = project / "docs" / "index.md"
    _write_hand_authored_passport(reserved)
    alias = project / "docs" / "memory.md"
    alias.symlink_to(reserved)
    before = reserved.read_bytes()

    result = CliRunner().invoke(
        main,
        ["memory", "track", "docs/memory.md", "--strategy", "changelog"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "reserved" in result.stderr
    assert reserved.read_bytes() == before


def test_retrack_rejects_reserved_logical_alias_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _make_project(tmp_path, monkeypatch)
    document = project / "docs" / "concept.md"
    _write_hand_authored_passport(document)
    alias = project / "docs" / "index.md"
    alias.symlink_to(document)
    before = document.read_bytes()

    result = CliRunner().invoke(
        main,
        ["memory", "track", "docs/index.md", "--strategy", "changelog"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "reserved" in result.stderr
    assert document.read_bytes() == before
