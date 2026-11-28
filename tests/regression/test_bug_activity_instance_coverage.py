"""An unavailable session instance must leave a visible coverage note in activity reports."""

import json

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.reactive.env import new_root_run_identity
from forge.core.usage.ledger import UsageEvent, log_usage_event
from forge.session import IndexStore, SessionStore, create_session_state
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("failure", ["manifest", "index"])
def test_unavailable_claude_session_identity_explains_empty_activity(tmp_path, monkeypatch, failure):
    (tmp_path / ".forge").mkdir()
    (tmp_path / ".git").mkdir()
    state = create_session_state("worker", worktree_path=str(tmp_path))
    entry = publish_session(IndexStore(), state, tmp_path, forge_root=tmp_path)
    monkeypatch.chdir(tmp_path)
    run = new_root_run_identity()
    log_usage_event(
        UsageEvent(
            run_id=run.run_id,
            root_run_id=run.root_run_id,
            runtime="claude_code",
            command="supervisor",
            status="success",
            session=state.name,
            session_instance_id=entry.instance_id,
            input_tokens=12,
        )
    )
    runner = CliRunner()
    args = ["telemetry", "activity", state.name, "--period", "all"]
    original = runner.invoke(main, [*args, "--json"])
    assert original.exit_code == 0, original.exception
    assert json.loads(original.output)["downstream"]["total_input_tokens"] == 12

    if failure == "manifest":
        SessionStore(str(tmp_path), state.name).manifest_path.write_text("{", encoding="utf-8")
    else:

        def unavailable(*_args):
            raise OSError("index unavailable")

        monkeypatch.setattr(IndexStore, "peek_session", unavailable)

    partial = runner.invoke(main, [*args, "--json"])
    assert partial.exit_code == 0, partial.exception
    report = json.loads(partial.output)
    assert "session_identity_unavailable" in report["notes"]
    assert report["downstream"]["total_input_tokens"] == 0
    human = runner.invoke(main, args)
    assert human.exit_code == 0, human.exception
    assert "Session identity could not be verified" in human.output
    assert "No verified Forge activity" in human.output
