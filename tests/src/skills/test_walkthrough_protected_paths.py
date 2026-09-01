"""Tests for the packaged walkthrough protected-path snapshot helper."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "src/skills/walkthrough/scripts/protected-paths.py"


def run_helper(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_capture_records_only_named_target_facts(tmp_path: Path) -> None:
    home = tmp_path / "home"
    secret = home / ".claude/settings.json"
    secret.parent.mkdir(parents=True)
    secret.write_text('{"token":"do-not-copy"}\n')
    snapshot = tmp_path / "snapshot.json"

    result = run_helper("capture", snapshot, "--home", home)

    assert result.returncode == 0
    data = json.loads(snapshot.read_text())
    assert len(data["targets"]) == 6
    assert data["targets"]["claude_settings"]["kind"] == "file"
    assert "do-not-copy" not in snapshot.read_text()
    assert str(home) not in snapshot.read_text()


def test_compare_detects_nested_content_change_without_disclosing_it(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    skill = home / ".agents/skills/example/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("private-before\n")
    snapshot = tmp_path / "snapshot.json"
    assert run_helper("capture", snapshot, "--home", home).returncode == 0
    skill.write_text("private-after\n")

    result = run_helper("compare", snapshot, "--home", home)

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "changed": ["codex_skills"],
        "status": "changed",
    }
    assert "private-before" not in result.stdout
    assert "private-after" not in result.stdout


def test_compare_accepts_an_unchanged_snapshot(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    snapshot = tmp_path / "snapshot.json"
    assert run_helper("capture", snapshot, "--home", home).returncode == 0

    result = run_helper("compare", snapshot, "--home", home)

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"changed": [], "status": "match"}


def test_capture_refuses_unreadable_target_without_writing_snapshot(tmp_path: Path, monkeypatch, capsys) -> None:
    home = tmp_path / "home"
    home.mkdir()
    snapshot = tmp_path / "snapshot.json"
    module_globals = runpy.run_path(str(SCRIPT))

    original = module_globals["_facts"]

    def unreadable(path: Path) -> dict[str, object]:
        if path.name == "settings.json":
            return {
                "exists": True,
                "kind": "unreadable",
                "mode": None,
                "digest": None,
                "error": "OSError",
            }
        return original(path)

    monkeypatch.setitem(module_globals["main"].__globals__, "_facts", unreadable)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "capture", str(snapshot), "--home", str(home)])

    assert module_globals["main"]() == 2
    result = json.loads(capsys.readouterr().err)
    assert result == {
        "reason": "protected_paths_unreadable",
        "status": "error",
        "targets": ["claude_settings"],
    }
    assert not snapshot.exists()


def test_nested_tree_disappearance_is_unreadable_not_missing(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    target = home / ".claude/skills"
    target.mkdir(parents=True)
    module_globals = runpy.run_path(str(SCRIPT))

    def vanished_child(path: Path) -> str:
        raise FileNotFoundError(path / "vanished-during-scan")

    monkeypatch.setitem(module_globals["_facts"].__globals__, "_hash_path", vanished_child)

    facts = module_globals["_facts"](target)

    assert facts == {
        "exists": True,
        "kind": "unreadable",
        "mode": None,
        "digest": None,
        "error": "FileNotFoundError",
    }
