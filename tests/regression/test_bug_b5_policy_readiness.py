"""B5 reviewer readiness cannot hold the session lock or block policy recovery."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.reactive import codex_reviewer_home as reviewer
from forge.core.reactive.reviewer_runtime import preflight_host_supervisor
from forge.core.state.lock import file_lock_for_target
from forge.session.models import CodexConfirmed, PolicyIntent, SupervisorConfig
from tests.fixtures.native_supervisor import CHILD, synthetic_rows, write_rollout
from tests.src.cli.test_native_supervisor import configure
from tests.src.cli.test_native_supervisor import native_setup as native_setup

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "key,value",
    [
        ("policy.enabled", "false"),
        ("policy.fail_mode", "closed"),
        ("policy.supervisor.timeout_seconds", "12"),
        ("policy.supervisor.suspended", "true"),
    ],
)
def test_policy_overrides_and_resets_do_not_preflight_native_reviewer(native_setup, monkeypatch, key, value):
    assert configure().exit_code == 0
    original = native_setup.read().intent.policy.supervisor
    Path(original.native_source.rollout_path).unlink()
    monkeypatch.setattr(reviewer, "require_codex_fork_binary", lambda: pytest.fail("Unrelated edit hashed binary"))
    runner = CliRunner()
    for args in (["set", key, value], ["reset", key], ["set", key, value], ["reset", "--all"]):
        result = runner.invoke(main, ["session", *args])
        assert result.exit_code == 0, result.output
    assert native_setup.read().intent.policy.supervisor == original


def test_disabled_policy_can_launch_without_reviewer_readiness(native_setup, monkeypatch):
    assert configure().exit_code == 0
    state = native_setup.read()
    state.intent.policy.enabled = False
    monkeypatch.setattr(reviewer, "require_codex_fork_binary", lambda: pytest.fail("Disabled policy preflighted"))
    preflight_host_supervisor(state)


@pytest.mark.parametrize("operation", ["on", "reload"])
def test_explicit_readiness_runs_outside_session_lock(native_setup, monkeypatch, operation):
    assert configure().exit_code == 0
    runner = CliRunner()
    plan = native_setup.manifest_path.parent / "plan.md"
    plan.write_text("Approved plan.")
    if operation == "on":
        assert runner.invoke(main, ["policy", "supervisor", "off"]).exit_code == 0
    calls = []
    original = reviewer.require_codex_fork_binary

    def check_lock_is_free():
        with file_lock_for_target(target_path=native_setup.manifest_path, timeout_s=0.05):
            calls.append(True)
        return original()

    monkeypatch.setattr(reviewer, "require_codex_fork_binary", check_lock_is_free)
    args = ["policy", "supervisor", operation] + (["--from", str(plan)] if operation == "reload" else [])
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert calls


def test_long_confirmed_executor_allows_setup_and_launch(native_setup, monkeypatch, tmp_path):
    # The executor can use a different Codex home from the bound planning source.
    import os

    source_home = Path(os.environ["CODEX_HOME"])
    executor_home = tmp_path / "executor-codex"
    path = write_rollout(executor_home, synthetic_rows(CHILD, complete=False))
    with path.open("ab") as stream:
        stream.write(b"x" * 2_000_000)
    state = native_setup.read()
    state.intent.launch.runtime = "codex"
    state.confirmed.codex = CodexConfirmed(thread_id=CHILD, rollout_path=str(path))
    native_setup.write(state)
    # Setup resolves the source before its executor readiness check.
    from forge.policy.semantic import native_codex

    monkeypatch.setattr(native_codex, "codex_home", lambda: executor_home)
    result = configure()
    assert result.exit_code == 0, result.output
    assert Path(native_setup.read().intent.policy.supervisor.native_source.home) == source_home
    preflight_host_supervisor(native_setup.read())


@pytest.mark.parametrize("operation", ["on", "reload"])
@pytest.mark.parametrize("trigger", ["pre-tool-use", "stop"])
def test_ordinary_lifecycle_keeps_enrollment_but_does_not_probe_reviewer(native_setup, monkeypatch, operation, trigger):
    plan = native_setup.manifest_path.parent / "plan.md"
    plan.write_text("Approved plan.")
    state = native_setup.read()
    state.intent.launch.runtime = "codex" if trigger == "stop" else "claude_code"
    state.intent.policy = PolicyIntent(
        enabled=True,
        supervisor=SupervisorConfig(
            plan_override_path=str(plan),
            supervisor_model="opus",
            suspended=True,
            review_trigger=trigger,
        ),
    )
    native_setup.write(state)
    monkeypatch.setattr(
        "forge.core.reactive.reviewer_runtime.preflight_host_supervisor",
        lambda _: pytest.fail("Ordinary on/reload must not acquire a new runtime prerequisite"),
    )
    enrollment = []

    def check_enrollment(**kwargs):
        with file_lock_for_target(target_path=native_setup.manifest_path, timeout_s=0.05):
            enrollment.append(True)

    monkeypatch.setattr("forge.core.runtime.codex_turn_enrollment.require_for_launch", check_enrollment)
    result = CliRunner().invoke(main, ["policy", "supervisor", operation])
    assert result.exit_code == 0, result.output
    assert bool(enrollment) == (trigger == "stop")
