"""B1: legacy recovery paths raised tracebacks or rejected catalog model IDs."""

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.policy.semantic.identity import select_supervisor_lane, validate_reviewer
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import PolicyIntent, SupervisorConfig
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-opus-5.5"])
def test_catalog_opus_selector_is_admitted(model):
    lane = select_supervisor_lane(model=model)
    assert lane.model == "claude-opus-5-5"
    validate_reviewer(SupervisorConfig(plan_override_path="/plan", supervisor_model=lane.model), lane)


def _session(tmp_path, monkeypatch, config, *, sidecar=False):
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "worker")
    state = create_session_state("worker", worktree_path=str(tmp_path), launch_mode="sidecar" if sidecar else "host")
    state.forge_root = str(tmp_path)
    state.intent.policy = PolicyIntent(supervisor=config)
    publish_session(IndexStore(), state, str(tmp_path))
    return SessionStore(str(tmp_path), "worker")


@pytest.mark.parametrize("source", ["empty", "missing", "sidecar"])
def test_reload_reports_plan_error_without_traceback(tmp_path, monkeypatch, source):
    plan = tmp_path / "plan.md"
    if source != "missing":
        plan.write_text("" if source == "empty" else "Keep the approved behavior.")
    store = _session(tmp_path, monkeypatch, SupervisorConfig(plan_override_path=str(plan)), sidecar=source == "sidecar")
    before = store.manifest_path.read_bytes()
    result = CliRunner().invoke(main, ["policy", "supervisor", "reload"])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "Traceback" not in result.output
    assert "plan" in result.output.lower() or "host executor" in result.output
    assert store.manifest_path.read_bytes() == before


def test_legacy_timeout_does_not_block_policy_set_and_reset(tmp_path, monkeypatch):
    store = _session(tmp_path, monkeypatch, SupervisorConfig(resume_id="planner", timeout_seconds=90))
    runner = CliRunner()
    changed = runner.invoke(main, ["session", "set", "policy.enabled", "false"])
    assert changed.exit_code == 0, changed.output
    reset = runner.invoke(main, ["session", "reset", "--all"])
    assert reset.exit_code == 0, reset.output
    assert store.read().intent.policy.supervisor.timeout_seconds == 45
