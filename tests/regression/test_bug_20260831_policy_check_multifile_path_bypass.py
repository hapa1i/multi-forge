"""Regression: terminal policy checks must evaluate every file in a diff."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks._group import hooks
from forge.cli.main import main

pytestmark = pytest.mark.regression


def _make_staged_no_prefix_mixed_diff(repo: Path) -> str:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "diff.noprefix", "true"], cwd=repo, check=True)
    subprocess.run(["git", "config", "diff.renames", "true"], cwd=repo, check=True)
    source = repo / "src"
    source.mkdir()
    (source / "main.py").write_text("value = 1\n")
    (source / "old_name.py").write_text("renamed = True\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

    subprocess.run(["git", "mv", "src/old_name.py", "src/new_name.py"], cwd=repo, check=True)
    (source / "main.py").write_text("value = 1\nif TYPE_CHECKING:\n    pass\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    diff = subprocess.run(
        ["git", "diff", "--staged"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "rename to src/new_name.py" in diff
    assert "+++ src/main.py" in diff
    return diff


def test_later_path_scoped_violation_cannot_hide_behind_first_diff_file() -> None:
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # Project\n"
        "+Harmless documentation.\n"
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1,2 @@\n"
        " x = 1\n"
        "+if TYPE_CHECKING:\n"
    )

    result = CliRunner().invoke(
        main,
        ["policy", "check", "--bundle", "coding_standards", "--diff", "--json"],
        input=diff,
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["passed"] is False
    assert payload["files_checked"] == 2
    assert any(
        violation["file_path"] == "src/main.py" and violation["rule_id"] == "coding_standards.no-type-checking"
        for violation in payload["violations"]
    )


def test_c_quoted_python_violation_cannot_disappear_before_an_unquoted_file() -> None:
    diff = (
        'diff --git "a/src/caf\\303\\251.py" "b/src/caf\\303\\251.py"\n'
        '--- "a/src/caf\\303\\251.py"\n'
        '+++ "b/src/caf\\303\\251.py"\n'
        "@@ -1 +1,2 @@\n"
        " x = 1\n"
        "+if TYPE_CHECKING:\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # Project\n"
        "+Harmless documentation.\n"
    )

    result = CliRunner().invoke(
        main,
        ["policy", "check", "--bundle", "coding_standards", "--diff", "--json"],
        input=diff,
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["files_checked"] == 2
    assert any(
        violation["file_path"] == "src/café.py" and violation["rule_id"] == "coding_standards.no-type-checking"
        for violation in payload["violations"]
    )


def test_headerless_header_shaped_added_lines_cannot_truncate_a_later_violation() -> None:
    diff = (
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1,4 @@\n"
        " x = 1\n"
        "+++ /dev/null\n"
        "+++ b/src/decoy.py\n"
        "+if TYPE_CHECKING:\n"
    )

    result = CliRunner().invoke(
        main,
        ["policy", "check", "--bundle", "coding_standards", "--diff", "--json"],
        input=diff,
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["files_checked"] == 1
    assert any(
        violation["file_path"] == "src/main.py" and violation["rule_id"] == "coding_standards.no-type-checking"
        for violation in payload["violations"]
    )


@pytest.mark.parametrize("combined_kind", ["cc", "combined"])
def test_combined_python_violation_cannot_fold_into_an_ordinary_file(
    combined_kind: str,
) -> None:
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # Project\n"
        "+Harmless documentation.\n"
        f"diff --{combined_kind} src/main.py\n"
        "index 1111111,2222222..3333333\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@@ -1,1 -1,1 +1,2 @@@\n"
        "  x = 1\n"
        "++if TYPE_CHECKING:\n"
    )

    result = CliRunner().invoke(
        main,
        ["policy", "check", "--bundle", "coding_standards", "--diff", "--json"],
        input=diff,
    )

    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["files_checked"] == 2
    assert any(
        violation["file_path"] == "src/main.py" and violation["rule_id"] == "coding_standards.no-type-checking"
        for violation in payload["violations"]
    )


def test_mixed_no_prefix_diff_fails_closed_in_terminal_and_direct_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diff = _make_staged_no_prefix_mixed_diff(tmp_path)

    terminal = CliRunner().invoke(
        main,
        ["policy", "check", "--bundle", "coding_standards", "--diff"],
        input=diff,
    )

    assert terminal.exit_code == 2, terminal.output
    assert "Diff could not be parsed completely" in terminal.output
    assert "1 file chunk could not be attributed" in terminal.output

    monkeypatch.chdir(tmp_path)
    direct = CliRunner().invoke(
        hooks,
        ["user-prompt-submit"],
        input=json.dumps(
            {
                "prompt": "%policy check --staged --bundle coding_standards",
                "transcript_path": "",
            }
        ),
    )

    assert direct.exit_code == 0, direct.output
    payload = json.loads(direct.output)
    assert payload["passed"] is False
    assert "Diff could not be parsed completely" in payload["reason"]
    assert "1 file chunk could not be attributed" in payload["reason"]
