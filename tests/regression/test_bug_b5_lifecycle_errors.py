"""B5 on/reload failures must leave configuration intact and print CLI diagnostics."""

from dataclasses import replace
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.reactive import codex_reviewer_home as reviewer
from tests.src.cli.test_native_supervisor import configure
from tests.src.cli.test_native_supervisor import native_setup as native_setup

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("operation", ["on", "reload"])
@pytest.mark.parametrize("failure", ["source", "managed_source", "binary", "auth", "race"])
def test_native_lifecycle_errors_are_actionable_and_atomic(native_setup, monkeypatch, operation, failure):
    assert configure().exit_code == 0
    runner = CliRunner()
    assert runner.invoke(main, ["policy", "supervisor", "off"]).exit_code == 0
    plan = native_setup.manifest_path.parent / "approved.md"
    plan.write_text("Approved plan.")
    if operation == "reload":
        assert runner.invoke(main, ["policy", "supervisor", "on"]).exit_code == 0
    if failure == "managed_source":
        # A previously bound planning session has been deleted; keep the stale
        # reference in the executor without inventing an indexed planner record.
        state = native_setup.read()
        sup = state.intent.policy.supervisor
        sup.native_source = replace(
            sup.native_source, managed_session="deleted-planner", managed_root=str(native_setup.forge_root)
        )
        native_setup.write(state)
    before = native_setup.manifest_path.read_bytes()
    if failure == "source":
        Path(native_setup.read().intent.policy.supervisor.native_source.rollout_path).unlink()
    elif failure == "auth":
        (reviewer.reviewer_home() / "auth.json").unlink()
    elif failure == "binary":

        def unavailable():
            raise ValueError("The reviewer binary changed; install the supported build")

        monkeypatch.setattr(reviewer, "require_codex_fork_binary", unavailable)
    elif failure == "race":
        original = reviewer.require_codex_fork_binary

        def concurrent_edit():
            native_setup.update(timeout_s=1, mutate=lambda state: state.overrides.update(policy={"enabled": False}))
            return original()

        monkeypatch.setattr(reviewer, "require_codex_fork_binary", concurrent_edit)
    args = ["policy", "supervisor", operation] + (["--from", str(plan)] if operation == "reload" else [])
    result = runner.invoke(main, args)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert result.stderr and not result.stdout and "Traceback" not in result.output
    if failure == "race":
        assert "repeat the command" in result.output
        assert native_setup.read().overrides["policy"]["enabled"] is False
        assert native_setup.read().intent.policy.supervisor.plan_override_path is None
    else:
        assert native_setup.manifest_path.read_bytes() == before
