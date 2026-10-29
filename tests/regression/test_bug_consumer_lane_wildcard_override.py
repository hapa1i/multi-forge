"""set_override expanded wildcards without validating protected consumer-lane paths."""

from __future__ import annotations

import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.exceptions import InvalidOverrideKeyError
from forge.session.overrides import set_override
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".forge").mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "500")
    return root


def test_consumer_lane_wildcard_rejects_before_mutating() -> None:
    overrides = {"policy": {"enabled": False}}
    before = deepcopy(overrides)
    with pytest.raises(InvalidOverrideKeyError, match="consumer lanes are set via resolving commands"):
        set_override(overrides, "consumer_lanes.*", "x")
    assert overrides == before


def test_consumer_lane_wildcard_cli_preserves_manifest(project: Path) -> None:
    publish_session(IndexStore(), create_session_state("parent", worktree_path=str(project)), project)
    store = SessionStore(str(project), "parent")
    before = store.manifest_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "set", "--session", "parent", "consumer_lanes.*", "x"])

    assert result.exit_code == 1, result.output
    assert "consumer lanes are set via resolving commands" in result.stderr
    assert store.manifest_path.read_bytes() == before
