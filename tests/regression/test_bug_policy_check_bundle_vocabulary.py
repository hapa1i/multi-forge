"""Regression coverage for shared terminal and direct policy-check vocabulary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

import forge.cli.policy as policy_cli
from forge.cli.hooks import hooks
from forge.core.ops import policy as policy_ops

pytestmark = pytest.mark.regression


def test_terminal_policy_check_owns_the_shared_bundle_choice() -> None:
    check_command = policy_cli.policy.commands["check"]
    bundle_option = next(param for param in check_command.params if param.name == "bundles")

    assert bundle_option.type is policy_cli._POLICY_BUNDLE_CHOICES


@pytest.mark.parametrize(
    "prompt",
    [
        "%policy check --bundle temporary_bundle",
        "%policy check temporary_bundle",
    ],
)
def test_direct_policy_check_follows_the_shared_bundle_vocabulary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.setattr(
        policy_ops,
        "POLICY_BUNDLE_NAMES",
        (*policy_ops.POLICY_BUNDLE_NAMES, "temporary_bundle"),
    )

    payload = {"prompt": prompt, "transcript_path": ""}
    result = CliRunner().invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

    assert result.exit_code == 0
    response = json.loads(result.output)
    assert response == {
        "decision": "block",
        "passed": True,
        "reason": "No unstaged changes to check.",
    }
