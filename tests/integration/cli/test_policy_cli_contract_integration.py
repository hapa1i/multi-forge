"""Container-boundary coverage for the Wave 8 Batch 3 policy CLI contracts."""

from __future__ import annotations

import json
import shlex

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def test_policy_check_rejects_ambiguous_content_sources(
    mock_claude_workspace: ContainerLike,
) -> None:
    result = mock_claude_workspace.exec(
        "cd /workspace && printf '%s' '+++ b/README.md\n+changed\n' "
        "| forge policy check --bundle tdd --file README.md --diff"
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert "Options --file and --diff cannot be used together" in result.stderr


def test_policy_check_evaluates_every_file_in_diff(
    mock_claude_workspace: ContainerLike,
) -> None:
    diff = (
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # Test workspace\n"
        "+Harmless documentation.\n"
        "diff --git a/src/main.py b/src/main.py\n"
        "--- /dev/null\n"
        "+++ b/src/main.py\n"
        "@@ -0,0 +1 @@\n"
        "+if TYPE_CHECKING:\n"
    )
    result = mock_claude_workspace.exec(
        "cd /workspace && printf '%s' "
        f"{shlex.quote(diff)} | forge policy check --bundle coding_standards --diff --json"
    )

    assert result.returncode == 1, result.stderr
    payload = json.loads(result.stdout)
    assert payload["files_checked"] == 2
    assert any(violation["file_path"] == "src/main.py" for violation in payload["violations"])


def test_missing_supervisor_enabling_actions_fail(
    mock_claude_workspace: ContainerLike,
) -> None:
    created = mock_claude_workspace.exec("cd /workspace && forge session start worker --no-proxy --no-launch")
    assert created.returncode == 0, created.stderr

    for command in (
        "forge policy supervisor on --session worker",
        "forge policy supervisor cascade on --session worker",
    ):
        result = mock_claude_workspace.exec(f"cd /workspace && {command}")
        assert result.returncode == 1
        assert result.stdout == ""
        assert "No supervisor configured" in result.stderr
        assert "forge policy supervisor set <target>" in result.stderr


def test_direct_policy_check_accepts_the_shared_bundle_vocabulary(
    mock_claude_workspace: ContainerLike,
) -> None:
    payload = json.dumps({"prompt": "%policy check --bundle tdd", "transcript_path": ""})
    result = mock_claude_workspace.exec(f"cd /workspace && printf '%s' '{payload}' | forge hook user-prompt-submit")

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "decision": "block",
        "passed": True,
        "reason": "No unstaged changes to check.",
    }
