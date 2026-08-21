"""O080 regressions for missing supervisor prerequisite exit semantics."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import SessionStore, create_session_state

pytestmark = pytest.mark.regression


@pytest.fixture
def unsupervised_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("FORGE_SESSION", "worker")

    manifest = create_session_state("worker", worktree_path=str(project))
    manifest.forge_root = str(project)
    SessionStore(str(project), "worker").write(manifest)
    return project


@pytest.mark.parametrize(
    ("leaf_args", "expected_exit", "expected_stream"),
    [
        pytest.param(["on"], 1, "stderr", id="on-fails"),
        pytest.param(["cascade", "on"], 1, "stderr", id="cascade-on-fails"),
        pytest.param(["off"], 0, "stdout", id="off-is-idempotent"),
        pytest.param(["remove"], 0, "stdout", id="remove-is-idempotent"),
        pytest.param(["cascade", "off"], 0, "stdout", id="cascade-off-is-idempotent"),
    ],
)
def test_missing_supervisor_exit_and_stream_matrix(
    unsupervised_project: Path,
    leaf_args: list[str],
    expected_exit: int,
    expected_stream: str,
) -> None:
    result = CliRunner().invoke(main, ["policy", "supervisor", *leaf_args])

    assert result.exit_code == expected_exit
    if expected_stream == "stderr":
        assert result.stdout == ""
        assert "No supervisor configured" in result.stderr
        assert "forge policy supervisor set <target>" in result.stderr
    else:
        assert result.stderr == ""
        assert "No supervisor configured" in result.stdout
