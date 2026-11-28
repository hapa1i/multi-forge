"""An occupied session name must refuse before a template can start a listener."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from tests.fixtures.session_state import publish_session, seed_row_only_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("options", [[], ["--resume-from", "planner", "--task", "continue"]])
@pytest.mark.parametrize("occupied", ["published", "manifest-only", "row-only", "another-project"])
def test_proxy_start_checks_the_name_in_its_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, options: list[str], occupied: str
) -> None:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    monkeypatch.chdir(project)
    monkeypatch.setattr("forge.cli.guards.require_repo_root", lambda *a, **kw: project)
    index = IndexStore()
    publish_session(index, create_session_state("planner", worktree_path=str(project)), project)
    collision_root = tmp_path / "other" if occupied == "another-project" else project
    (collision_root / ".forge").mkdir(parents=True, exist_ok=True)
    state = create_session_state("target", worktree_path=str(collision_root))
    if occupied == "manifest-only":
        # An orphan manifest occupies the actual target path even without its index row.
        SessionStore(str(project), "target").write(state)
    elif occupied == "row-only":
        # A crash between row and manifest publication leaves a reusable name.
        seed_row_only_session(index, state, project)
    else:
        publish_session(index, state, collision_root)
    resolve = Mock(side_effect=ValueError("fixture stopped at proxy resolution"))
    monkeypatch.setattr("forge.core.ops.codex_session.resolve_codex_proxy_launch", resolve)

    result = CliRunner().invoke(
        main,
        [
            "session",
            "start",
            "target",
            "--runtime",
            "codex",
            "--proxy",
            "route",
            *options,
        ],
    )

    assert result.exit_code == 1, (result.output, result.exception)
    if occupied in {"published", "manifest-only"}:
        assert "session 'target' already exists" in result.output
        resolve.assert_not_called()
    else:
        assert "fixture stopped at proxy resolution" in result.output
        resolve.assert_called_once()
