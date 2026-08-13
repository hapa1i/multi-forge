"""D034 regression: session-scoped direct-command no-ops must be silent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param("%policy status", id="policy-status"),
        pytest.param("%policy enable tdd", id="policy-enable"),
        pytest.param("%policy disable", id="policy-disable"),
        pytest.param("%policy supervisor", id="policy-supervisor"),
        pytest.param("%cancel-verification", id="cancel-verification"),
    ],
)
def test_no_session_direct_command_is_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
) -> None:
    monkeypatch.delenv("FORGE_FORK_NAME", raising=False)
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.delenv("FORGE_FORGE_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        hooks,
        ["user-prompt-submit"],
        input=json.dumps({"prompt": prompt, "transcript_path": ""}),
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == ""
