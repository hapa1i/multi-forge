"""Regression: terminal policy checks must evaluate every file in a diff."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


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
