"""Native configuration across terminal setup, overrides, reset and inheritance."""

import json

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.reactive import codex_reviewer_home as reviewer
from forge.policy.semantic.identity import validate_inherited_claude_trigger
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import SupervisorConfig
from forge.session.store import manifest_for_write
from tests.fixtures.native_supervisor import (
    THREAD,
    allow_synthetic_instructions,
    synthetic_rows,
    write_rollout,
)
from tests.fixtures.session_state import publish_session


@pytest.fixture
def native_setup(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".forge").mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("FORGE_SESSION", "executor")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(root))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setattr(reviewer, "get_forge_home", lambda: tmp_path / "review-forge")
    monkeypatch.setattr(reviewer, "require_codex_fork_binary", lambda: "/synthetic/codex")
    allow_synthetic_instructions(monkeypatch)
    write_rollout(tmp_path / "codex", synthetic_rows())
    home = reviewer.initialize_home(extra_usage_off=True)
    (home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "account_id": "synthetic-account",
                    "access_token": "synthetic",
                    "refresh_token": "synthetic",
                },
            }
        )
    )
    state = create_session_state("executor", worktree_path=str(root))
    publish_session(IndexStore(), state, root)
    return SessionStore(str(root), "executor")


def configure(*extra):
    return CliRunner().invoke(
        main,
        [
            "policy",
            "supervisor",
            "set",
            THREAD,
            "--source-runtime",
            "codex",
            "--runtime",
            "codex",
            "--model",
            "gpt-6.1-sol",
            "--auth-mode",
            "subscription-only",
            *extra,
        ],
    )


def test_native_setup_has_distinct_v5_source_and_no_legacy_resume(native_setup):
    result = configure()
    assert result.exit_code == 0, result.output
    raw = json.loads(native_setup.manifest_path.read_text())
    sup = raw["intent"]["policy"]["supervisor"]
    assert raw["schema_version"] == 5
    assert sup["native_source"]["runtime"] == "codex" and sup["native_source"]["thread_id"] == THREAD
    assert sup["resume_id"] is None and sup["supervisor_effort"] == "low"
    status = CliRunner().invoke(main, ["policy", "supervisor", "status", "--json"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["supervisor"]["source"] == "native"


@pytest.mark.parametrize(
    "extra",
    [
        ("--auth-mode", "inherit"),
        ("--runtime", "claude_code"),
        ("--cascade",),
        ("--trigger", "stop"),
        ("--supervisor-proxy", "unexpected"),
        ("--supervisor-effort", "high"),
    ],
)
def test_invalid_setup_never_partially_writes_configuration(native_setup, extra):
    before = native_setup.manifest_path.read_bytes()
    result = configure(*extra)
    assert result.exit_code != 0
    assert native_setup.manifest_path.read_bytes() == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("cascade", "true"),
        ("shadow_sample_rate", "0.5"),
        ("auth_mode", "inherit"),
        ("fork_session", "false"),
        ("resume_id", "legacy"),
        ("supervisor_model", "gpt-6-astra"),
        ("native_source.thread_id", '"01a12b73-202d-7dd0-a058-f74ec9375dd2"'),
    ],
)
def test_effective_override_rules_preserve_bytes_on_refusal(native_setup, key, value):
    result = configure()
    assert result.exit_code == 0, result.output
    before = native_setup.manifest_path.read_bytes()
    result = CliRunner().invoke(main, ["session", "set", "--session", "executor", f"policy.supervisor.{key}", value])
    assert result.exit_code != 0, result.output
    assert native_setup.manifest_path.read_bytes() == before


def test_reset_cannot_expose_invalid_inherited_native_auth(native_setup):
    assert configure().exit_code == 0
    state = native_setup.read()
    state.intent.policy.supervisor.auth_mode = "inherit"
    state.overrides = {"policy": {"supervisor": {"auth_mode": "subscription-only"}}}
    native_setup.write(state)
    before = native_setup.manifest_path.read_bytes()
    result = CliRunner().invoke(main, ["session", "reset", "--session", "executor", "policy.supervisor.auth_mode"])
    assert result.exit_code != 0, result.output
    assert native_setup.manifest_path.read_bytes() == before
    with pytest.raises(ValueError, match="explicit"):
        validate_inherited_claude_trigger(state)


def test_existing_versions_do_not_gain_native_null_fields(native_setup):
    state = native_setup.read()
    from forge.session.models import PolicyIntent

    for config, version in (
        (SupervisorConfig(resume_id="legacy"), 2),
        (SupervisorConfig(plan_override_path="/plan", supervisor_model="opus"), 3),
        (SupervisorConfig(plan_override_path="/plan", review_trigger="stop"), 4),
    ):
        state.intent.policy = PolicyIntent(supervisor=config)
        data = manifest_for_write(state)
        assert data["schema_version"] == version
        assert "native_source" not in data["intent"]["policy"]["supervisor"]


def test_on_revalidates_a_deleted_native_source(native_setup):
    assert configure().exit_code == 0
    runner = CliRunner()
    assert runner.invoke(main, ["policy", "supervisor", "off"]).exit_code == 0
    state = native_setup.read()
    from pathlib import Path

    Path(state.intent.policy.supervisor.native_source.rollout_path).unlink()
    before = native_setup.manifest_path.read_bytes()
    result = runner.invoke(main, ["policy", "supervisor", "on"])
    assert result.exit_code != 0
    assert native_setup.manifest_path.read_bytes() == before


def test_inherited_intent_uses_child_lane_not_parent_frozen_binding(native_setup):
    from forge.policy.semantic.identity import SUPERVISOR_CONSUMER
    from forge.session.consumer_lanes import (
        ensure_consumer_lane_binding,
        read_bound_lane,
    )
    from forge.session.models import LaneRecord

    assert configure().exit_code == 0
    state = native_setup.read()
    ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, read_bound_lane(state, SUPERVISOR_CONSUMER))
    state.intent.consumer_lanes.supervisor = LaneRecord("claude_code", "anthropic-direct", "opus")
    with pytest.raises(ValueError, match="model differs"):
        validate_inherited_claude_trigger(state)


def test_masking_override_cannot_bypass_native_setup(native_setup):
    state = native_setup.read()
    state.overrides = {"policy": {"supervisor": {"shadow_sample_rate": 0.5}}}
    native_setup.write(state)
    before = native_setup.manifest_path.read_bytes()
    assert configure().exit_code != 0
    assert native_setup.manifest_path.read_bytes() == before


def test_direct_setup_uses_the_terminal_options_and_shared_operations(native_setup, capsys):
    from forge.cli.hooks import direct_commands

    direct_commands._handle_policy_supervisor(
        [
            "set",
            THREAD,
            "--source-runtime",
            "codex",
            "--runtime",
            "codex",
            "--model",
            "gpt-6.1-sol",
            "--auth-mode",
            "subscription-only",
        ]
    )
    assert native_setup.read().intent.policy.supervisor.native_source.thread_id == THREAD, capsys.readouterr().out
