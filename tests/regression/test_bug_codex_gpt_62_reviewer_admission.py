"""GPT-6.2 plan-file reviewers need a capable Codex binary at setup and dispatch."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.policy.semantic.identity import select_supervisor_lane
from forge.policy.semantic.supervisor import run_supervisor_check
from forge.policy.types import ActionContext
from forge.session import IndexStore, SessionStore
from forge.session.models import SupervisorConfig
from tests.fixtures.codex_result import codex_result
from tests.fixtures.review_workers import make_codex_preflight
from tests.fixtures.session_state import publish_session_from_fields

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("alias", ["astra", "sol"])
@pytest.mark.parametrize("unsupported", ["0.149.1", None])
def test_setup_refuses_before_saving_and_succeeds_after_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: str, unsupported: str | None
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".forge").mkdir()
    publish_session_from_fields(IndexStore(), "worker", tmp_path, tmp_path)
    store = SessionStore(str(tmp_path), "worker")
    original = store.manifest_path.read_bytes()
    plan = tmp_path / "plan.md"
    plan.write_text("Add a greeting.")
    args = [
        "policy",
        "supervisor",
        "set",
        "--session",
        "worker",
        "--plan",
        str(plan),
        "--runtime",
        "codex",
        "--model",
        alias,
    ]
    with patch("forge.core.reactive.reviewer_runtime.get_runtime") as runtime:
        runtime.return_value.detect.return_value = unsupported
        refused = CliRunner().invoke(main, args)
        assert refused.exit_code == 1, refused.output
        assert f"gpt-6.2-{alias} requires Codex CLI 0.166.0" in " ".join(refused.stderr.split())
        assert "forge runtime preflight codex" in refused.stderr
        assert store.manifest_path.read_bytes() == original
        runtime.return_value.detect.return_value = "0.166.0"
        accepted = CliRunner().invoke(main, args)
    assert accepted.exit_code == 0, accepted.output
    policy = store.read().intent.policy
    assert policy and policy.supervisor and policy.supervisor.supervisor_model == f"gpt-6.2-{alias}"


@pytest.mark.parametrize("model", ["gpt-6.2-astra", "gpt-6.2-sol"])
def test_dispatch_checks_cached_version_and_passes_the_exact_model(tmp_path: Path, model: str) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("Add a greeting.")
    lane = select_supervisor_lane(runtime="codex", model=model)
    config = SupervisorConfig(forge_root=str(tmp_path), plan_override_path=str(plan), supervisor_model=model)
    action = ActionContext(
        origin="codex",
        event="PreToolUse.Write",
        tool_name="Write",
        tool_args={},
        repo_root=str(tmp_path),
        session_name="worker",
        target_path="greeting.txt",
        new_content="hello",
    )
    with (
        patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight") as cached,
        patch("forge.core.reactive.reviewer_runtime.get_runtime") as probe,
        patch(
            "forge.core.invoker.codex.CodexHeadlessInvoker.run",
            return_value=codex_result(stdout='{"verdict":"aligned","confidence":1,"violations":[]}'),
        ) as invoke,
    ):
        cached.return_value = replace(make_codex_preflight(), version="0.149.1")
        refused = run_supervisor_check(config, action, lane_record=lane)
        assert refused.decision.failure_type == "codex_unavailable" and refused.dispatched is False
        assert any("0.166.0" in warning for warning in refused.decision.warnings)
        invoke.assert_not_called()

        cached.return_value = replace(cached.return_value, version="0.170.0")
        accepted = run_supervisor_check(config, action, lane_record=lane)
        assert accepted.run_ok and accepted.parsed and not accepted.decision.fail_open
        invoke.assert_called_once()
        argv = invoke.call_args.args[0].argv
        assert argv[argv.index("-m") + 1] == model
        assert argv[argv.index("--sandbox") + 1] == "read-only"
        probe.assert_not_called()
