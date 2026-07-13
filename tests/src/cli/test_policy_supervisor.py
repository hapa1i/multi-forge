"""Tests for the forge policy supervisor command group."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
from pytest import fixture

from forge.cli.main import main
from forge.core.state import now_iso
from forge.policy.types import PolicyDecision, Violation
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import (
    ConsumerLaneBinding,
    ConsumerLaneConfirmed,
    LaneRecord,
    PolicyIntent,
    SessionState,
    StartedWithProxy,
    SupervisorConfig,
)


def _seed_duplicate_supervisor_targets(project: Path) -> tuple[Path, Path]:
    index = IndexStore()

    forge_root_a = project
    forge_root_b = project / "nested-project"
    forge_root_b.mkdir(parents=True, exist_ok=True)

    worktree_a = project
    worktree_b = project / "nested-project-checkout"
    worktree_b.mkdir(parents=True, exist_ok=True)

    target_a = create_session_state(
        "shared",
        proxy_template="template-a",
        proxy_base_url="http://localhost:8101",
        worktree_path=str(worktree_a),
    )
    target_a.forge_root = str(forge_root_a)
    target_a.confirmed.claude_session_id = "uuid-alpha"
    target_a.confirmed.started_with_proxy = StartedWithProxy(base_url="http://localhost:8101", template="template-a")
    SessionStore(str(forge_root_a), "shared").write(target_a)

    target_b = create_session_state(
        "shared",
        proxy_template="template-b",
        proxy_base_url="http://localhost:8102",
        worktree_path=str(worktree_b),
    )
    target_b.forge_root = str(forge_root_b)
    target_b.confirmed.claude_session_id = "uuid-beta"
    target_b.confirmed.started_with_proxy = StartedWithProxy(base_url="http://localhost:8102", template="template-b")
    SessionStore(str(forge_root_b), "shared").write(target_b)

    controller = create_session_state(
        "controller",
        proxy_template="controller-template",
        proxy_base_url="http://localhost:8110",
        worktree_path=str(project),
    )
    controller.forge_root = str(forge_root_a)
    SessionStore(str(forge_root_a), "controller").write(controller)

    index.add_session(
        name="shared",
        worktree_path=str(worktree_a),
        project_root=str(project),
        forge_root=str(forge_root_a),
        checkout_root=str(worktree_a),
        relative_path=".",
    )
    index.add_session(
        name="shared",
        worktree_path=str(worktree_b),
        project_root=str(project),
        forge_root=str(forge_root_b),
        checkout_root=str(worktree_b),
        relative_path="nested-project",
    )
    index.add_session(
        name="controller",
        worktree_path=str(project),
        project_root=str(project),
        forge_root=str(forge_root_a),
        checkout_root=str(project),
        relative_path=".",
    )

    return forge_root_a, forge_root_b


def _read_supervisor_resume_id(forge_root: Path, name: str) -> str | None:
    manifest = SessionStore(str(forge_root), name).read()
    policy = manifest.intent.policy
    if policy and policy.supervisor:
        return policy.supervisor.resume_id
    return None


def _set_supervisor_resume_id(forge_root: Path, name: str, resume_id: str) -> None:
    store = SessionStore(str(forge_root), name)

    def _mutate(state) -> None:
        assert state.intent.policy is not None
        assert state.intent.policy.supervisor is not None
        state.intent.policy.supervisor.resume_id = resume_id

    store.update(timeout_s=5.0, mutate=_mutate)


def _apply_supervisor_to_intent(manifest, supervisor) -> None:
    if manifest.intent.policy is None:
        manifest.intent.policy = PolicyIntent(enabled=True, supervisor=supervisor)
        return
    manifest.intent.policy.enabled = True
    manifest.intent.policy.supervisor = supervisor


def _validate_supervisor_target(target: str, forge_root: str | None = None):
    from unittest.mock import MagicMock

    state = MagicMock()
    state.confirmed.started_with_proxy = None  # direct-mode planner
    state.forge_root = forge_root  # used by SupervisorConfig to scope runtime lookups
    return state


def _auto_seed_supervisor_proxy(*args, **kwargs):
    return None


def _hooks_installed(*args, **kwargs):
    return True


def _project_env(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


@fixture
def temp_guard_env(tmp_path: Path, monkeypatch):
    return _project_env(tmp_path, monkeypatch)


@fixture
def runner() -> CliRunner:
    return CliRunner()


def _allow_decision(**kwargs) -> PolicyDecision:
    return PolicyDecision(decision="allow", policy_id="semantic.supervisor", **kwargs)


def _deny_decision(violations: list[Violation] | None = None, **kwargs) -> PolicyDecision:
    return PolicyDecision(
        decision="deny",
        policy_id="semantic.supervisor",
        violations=violations or [],
        **kwargs,
    )


def _warn_decision(**kwargs) -> PolicyDecision:
    return PolicyDecision(decision="warn", policy_id="semantic.supervisor", **kwargs)


# --- Slice 10 clean break: `supervise` removed, one-shot moved under `evaluate` ---


class TestSupervisorCleanBreak:
    def test_supervise_verb_removed(self) -> None:
        """`forge policy supervise` no longer exists (Click reports no such command)."""
        result = CliRunner().invoke(main, ["policy", "supervise"])
        assert result.exit_code == 2
        assert "No such command" in result.output

    def test_bare_oneshot_requires_evaluate(self, tmp_path) -> None:
        """`supervisor` is now a group: the bare one-shot `-f/-r` form no longer parses."""
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        result = CliRunner().invoke(main, ["policy", "supervisor", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 2

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_evaluate_subcommand_runs(self, mock_invoke, tmp_path) -> None:
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision()
        result = CliRunner().invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 0


class TestSupervisorHelp:
    def test_help_exits_zero(self):
        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "--help"])
        assert result.exit_code == 0
        assert "--resume-id" in result.output
        assert "--file" in result.output
        assert "--json" in result.output

    def test_group_help_lists_leaves(self):
        result = CliRunner().invoke(main, ["policy", "supervisor", "--help"])
        assert result.exit_code == 0
        for leaf in (
            "status",
            "set",
            "off",
            "on",
            "remove",
            "reload",
            "cascade",
            "evaluate",
        ):
            assert leaf in result.output

    def test_missing_resume_id_exits_error(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("pass")
        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f)])
        assert result.exit_code != 0

    def test_missing_file_exits_error(self):
        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-r", "abc-123"])
        assert result.exit_code != 0


class TestSupervisorAligned:
    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_aligned_exits_0(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision()

        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 0

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_aligned_json(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision()

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "evaluate",
                "-f",
                str(f),
                "-r",
                "abc-123",
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["passed"] is True
        assert data["clean"] is True
        assert data["final_decision"] == "allow"
        assert data["violations"] == []

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_warn_exits_0(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _warn_decision(warnings=["Possible divergence: minor (confidence: 50%)"])

        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 0


class TestSupervisorDivergent:
    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_deny_exits_1(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _deny_decision(
            violations=[
                Violation(
                    rule_id="semantic.supervisor.alignment",
                    message="Action diverges from plan",
                    severity="high",
                    evidence="wrote code not in plan",
                    suggested_fix="follow the plan",
                    citations=["plan section 3"],
                )
            ]
        )

        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 1

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_deny_json_includes_violations(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _deny_decision(
            violations=[
                Violation(
                    rule_id="semantic.supervisor.alignment",
                    message="Divergent action",
                    severity="high",
                    evidence="wrong code",
                    suggested_fix="fix it",
                )
            ]
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "evaluate",
                "-f",
                str(f),
                "-r",
                "abc-123",
                "--json",
            ],
        )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["passed"] is False
        assert data["final_decision"] == "deny"
        assert len(data["violations"]) == 1
        assert data["violations"][0]["severity"] == "high"


class TestSupervisorInfraFailure:
    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_supervisor_error_exits_2(self, mock_invoke, tmp_path):
        """Fail-open allow with infra-failure markers -> exit 2."""
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision(warnings=["Supervisor error: exit 1, failing open"])

        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 2

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_supervisor_skipped_exits_2(self, mock_invoke, tmp_path):
        """Supervisor skipped (depth limit) -> exit 2."""
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision(warnings=["Supervisor skipped (FORGE_DEPTH limit reached)"])

        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 2

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_fail_open_without_infra_prefix_exits_2(self, mock_invoke, tmp_path):
        """Regression (Gap A): a fail-open allow whose warning does NOT start with an
        `_INFRA_FAILURE_PREFIXES` prefix must still exit 2. The structural `fail_open`
        flag is authoritative -- lane-unavailable / plan-missing / routing-error /
        parse-failure fail-opens all set it but emit warnings the prose match misses, so
        the pre-fix CLI reported exit-0 'passed' on a supervisor that never evaluated.
        """
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision(
            fail_open=True,
            warnings=["Supervisor lane unavailable: LaneError('bad lane'), failing open"],
        )

        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 2

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_fail_open_without_infra_prefix_json(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision(
            fail_open=True,
            warnings=["Supervisor verdict could not be parsed, failing open"],
        )

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "evaluate",
                "-f",
                str(f),
                "-r",
                "abc-123",
                "--json",
            ],
        )
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["passed"] is False
        assert data["clean"] is False
        assert data["final_decision"] == "error"

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_infra_failure_json(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision(warnings=["Supervisor error: timeout, failing open"])

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "evaluate",
                "-f",
                str(f),
                "-r",
                "abc-123",
                "--json",
            ],
        )
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["passed"] is False
        assert data["clean"] is False
        assert data["final_decision"] == "error"

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_exception_exits_2(self, mock_invoke, tmp_path):
        """Exception during invocation -> exit 2."""
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.side_effect = RuntimeError("connection failed")

        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        assert result.exit_code == 2


class TestSupervisorSet:
    @patch("forge.install.hooks.has_forge_hook", side_effect=_hooks_installed)
    @patch(
        "forge.policy.semantic.supervisor.apply_supervisor_to_intent",
        side_effect=_apply_supervisor_to_intent,
    )
    @patch(
        "forge.policy.semantic.supervisor.auto_seed_supervisor_proxy",
        side_effect=_auto_seed_supervisor_proxy,
    )
    @patch(
        "forge.policy.semantic.supervisor.validate_supervisor_target",
        side_effect=_validate_supervisor_target,
    )
    def test_set_session_uses_current_project_scope(
        self,
        _mock_validate,
        _mock_seed,
        _mock_apply,
        _mock_hook,
        runner: CliRunner,
        temp_guard_env: Path,
    ):
        forge_root_a, _forge_root_b = _seed_duplicate_supervisor_targets(temp_guard_env)

        result = runner.invoke(main, ["policy", "supervisor", "set", "shared", "--session", "controller"])

        assert result.exit_code == 0
        assert _read_supervisor_resume_id(forge_root_a, "controller") == "shared"
        assert "Supervisor set to" in result.output

    @patch("forge.install.hooks.has_forge_hook", side_effect=_hooks_installed)
    @patch(
        "forge.policy.semantic.supervisor.apply_supervisor_to_intent",
        side_effect=_apply_supervisor_to_intent,
    )
    @patch(
        "forge.policy.semantic.supervisor.auto_seed_supervisor_proxy",
        side_effect=_auto_seed_supervisor_proxy,
    )
    @patch(
        "forge.policy.semantic.supervisor.validate_supervisor_target",
        side_effect=_validate_supervisor_target,
    )
    def test_set_session_validates_in_selected_session_scope(
        self,
        mock_validate,
        _mock_seed,
        _mock_apply,
        _mock_hook,
        runner: CliRunner,
        temp_guard_env: Path,
    ):
        """Validation should use the selected session's forge_root, not CWD."""
        forge_root_a, _forge_root_b = _seed_duplicate_supervisor_targets(temp_guard_env)

        result = runner.invoke(main, ["policy", "supervisor", "set", "shared", "--session", "controller"])
        assert result.exit_code == 0

        # validate_supervisor_target must be called with the selected session's
        # forge_root (forge_root_a), not from _resolve_forge_root(cwd) which
        # could differ in cross-worktree scenarios.
        call_kwargs = mock_validate.call_args
        assert call_kwargs is not None
        actual_fr = (
            call_kwargs[1].get("forge_root") or call_kwargs[0][1]
            if len(call_kwargs[0]) > 1
            else call_kwargs[1].get("forge_root")
        )
        assert actual_fr == str(forge_root_a)

    @patch("forge.install.hooks.has_forge_hook", side_effect=_hooks_installed)
    @patch(
        "forge.policy.semantic.supervisor.apply_supervisor_to_intent",
        side_effect=_apply_supervisor_to_intent,
    )
    @patch(
        "forge.policy.semantic.supervisor.auto_seed_supervisor_proxy",
        side_effect=_auto_seed_supervisor_proxy,
    )
    @patch(
        "forge.policy.semantic.supervisor.validate_supervisor_target",
        side_effect=_validate_supervisor_target,
    )
    def test_status_uses_same_project_target_metadata(
        self,
        _mock_validate,
        _mock_seed,
        _mock_apply,
        _mock_hook,
        runner: CliRunner,
        temp_guard_env: Path,
    ):
        forge_root_a, _forge_root_b = _seed_duplicate_supervisor_targets(temp_guard_env)
        result = runner.invoke(main, ["policy", "supervisor", "set", "shared", "--session", "controller"])
        assert result.exit_code == 0

        show_result = runner.invoke(main, ["policy", "supervisor", "status", "--session", "controller"])

        assert show_result.exit_code == 0
        assert "Supervisor: [green]shared[/green]" not in show_result.output
        assert "Supervisor: shared" in show_result.output or "Target" in show_result.output
        assert "Claude UUID: uuid-alpha" in show_result.output or "Claude UUID: uuid-alpha..." in show_result.output
        assert "Source model: template-a" in show_result.output


class TestEvaluateContext:
    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_proxy_passed_to_config(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision()

        runner = CliRunner()
        runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "evaluate",
                "-f",
                str(f),
                "-r",
                "abc-123",
                "--proxy",
                "litellm-openai",
            ],
        )
        config = mock_invoke.call_args[0][0]
        assert config.proxy == "litellm-openai"

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_timeout_passed_to_config(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision()

        runner = CliRunner()
        runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "evaluate",
                "-f",
                str(f),
                "-r",
                "abc-123",
                "-t",
                "90",
            ],
        )
        config = mock_invoke.call_args[0][0]
        assert config.timeout_seconds == 90

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_file_content_in_context(self, mock_invoke, tmp_path):
        f = tmp_path / "src.py"
        f.write_text("def hello(): pass")
        mock_invoke.return_value = _allow_decision()

        runner = CliRunner()
        runner.invoke(main, ["policy", "supervisor", "evaluate", "-f", str(f), "-r", "abc-123"])
        context = mock_invoke.call_args[0][1]
        assert "def hello(): pass" in (context.new_content or "")


# --- Toggle tests for `forge policy supervisor off/on/remove/reload` ---


def _make_supervised_project(project: Path, monkeypatch, *, suspended: bool = False) -> SessionStore:
    """Create a project with a supervised session for toggle tests."""
    from forge.session.models import SupervisorConfig

    monkeypatch.setenv("FORGE_SESSION", "worker")

    manifest = create_session_state(
        "worker",
        proxy_template="test-template",
        proxy_base_url="http://localhost:8080",
        worktree_path=str(project),
    )
    manifest.forge_root = str(project)
    _apply_supervisor_to_intent(
        manifest,
        SupervisorConfig(resume_id="planner", proxy="litellm-openai", suspended=suspended),
    )
    store = SessionStore(str(project), "worker")
    store.write(manifest)
    return store


class TestSupervisorStatus:
    """Tests for `forge policy supervisor status` (display + --json)."""

    def test_status_remains_readable_under_incompatible_pin(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        _make_supervised_project(temp_guard_env, monkeypatch)
        (temp_guard_env / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(main, ["policy", "supervisor", "status"])

        assert result.exit_code == 0, result.output
        assert "Supervisor" in result.output

    def test_status_displays_proxy_routing(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        from forge.session.models import SupervisorConfig

        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(
            manifest,
            SupervisorConfig(resume_id="planner", proxy="litellm-gemini"),
        )
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status"])
        assert result.exit_code == 0
        assert "Routing: proxy: litellm-gemini" in result.output

    def test_status_displays_direct_routing(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        from forge.session.models import SupervisorConfig

        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(
            manifest,
            SupervisorConfig(resume_id="planner", direct=True),
        )
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status"])
        assert result.exit_code == 0
        assert "Routing: direct (no proxy)" in result.output

    _SUPERVISOR_JSON_KEYS = {
        "resume_id",
        "suspended",
        "plan_override_path",
        "proxy",
        "direct",
        "fork_session",
        "timeout_seconds",
        "throttle_seconds",
        "cascade",
        "checker_model",
        "checker_provider",
        "checker_budget_tokens",
        "checker_effort",
        "supervisor_effort",
        "resolved_uuid",
        "source_model",
        "lane",
        "degraded",
    }

    def test_status_json_configured(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(main, ["policy", "supervisor", "status", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["session_name"] == "worker"
        sup = data["supervisor"]
        assert sup is not None
        assert sup["resume_id"] == "planner"
        assert set(sup.keys()) == self._SUPERVISOR_JSON_KEYS
        assert sup["degraded"] is None  # T7: not degraded => null (only set after a codex exhaustion)

    def test_status_json_unconfigured(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["session_name"] == "worker"
        assert data["supervisor"] is None

    def test_status_json_shows_degraded_when_degraded(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        """T7: `supervisor status --json` surfaces the sticky degrade (reason + from/to lane) while the
        bound `lane` stays codex -- the operator sees dispatch was routed around without editing it.
        """
        from forge.policy.supervisor_lane_degrade import set_supervisor_degrade
        from forge.session.models import (
            ConsumerLaneIntent,
            LaneRecord,
            SupervisorConfig,
        )

        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(manifest, SupervisorConfig(resume_id="planner", direct=True))
        # The realistic state: the supervisor is bound to codex AND degraded -- the binding stays,
        # the overlay routes around it. `lane` reflects the binding; `degraded` reflects the overlay.
        manifest.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-5-codex"))
        set_supervisor_degrade(
            manifest,
            from_lane=LaneRecord("codex", "chatgpt", "gpt-5-codex"),
            to_lane=LaneRecord("claude_code", "anthropic-direct", "opus"),
            reason="subscription_exhausted",
            at=now_iso(),
        )
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status", "--json"])
        assert result.exit_code == 0, result.output
        sup = json.loads(result.output)["supervisor"]
        assert sup["degraded"] is not None
        assert sup["degraded"]["reason"] == "subscription_exhausted"
        assert sup["degraded"]["from_lane"] == {
            "runtime_id": "codex",
            "backend_id": "chatgpt",
            "model": "gpt-5-codex",
        }
        # The bound lane is untouched -- still codex, observable alongside the degrade.
        assert sup["lane"] == {
            "runtime": "codex",
            "backend": "chatgpt",
            "model": "gpt-5-codex",
        }

    def test_status_table_shows_degraded_line(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        """T7: the human table calls out the degrade so `Lane: ...codex...` is not misread as live codex."""
        from forge.policy.supervisor_lane_degrade import set_supervisor_degrade
        from forge.session.models import LaneRecord, SupervisorConfig

        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(manifest, SupervisorConfig(resume_id="planner", direct=True))
        set_supervisor_degrade(
            manifest,
            from_lane=LaneRecord("codex", "chatgpt", "gpt-5-codex"),
            to_lane=None,
            reason="subscription_exhausted",
            at=now_iso(),
        )
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status"])
        assert result.exit_code == 0, result.output
        assert "Degraded" in result.output
        assert "subscription spent" in result.output

    def test_status_json_carries_default_lane(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        """T5/WS3: a default (claude) supervisor reports its full lane (claude_code/anthropic-direct/opus)."""
        _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(main, ["policy", "supervisor", "status", "--json"])
        assert result.exit_code == 0, result.output
        sup = json.loads(result.output)["supervisor"]
        assert sup["lane"] == {
            "runtime": "claude_code",
            "backend": "anthropic-direct",
            "model": "opus",
        }

    def test_status_json_carries_codex_lane(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        """T1b: a codex-bound supervisor reports the full codex lane from its consumer-lane binding."""
        from forge.session.models import (
            ConsumerLaneIntent,
            LaneRecord,
            SupervisorConfig,
        )

        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(manifest, SupervisorConfig(resume_id="planner", direct=True))
        manifest.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-5-codex"))
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status", "--json"])
        assert result.exit_code == 0, result.output
        sup = json.loads(result.output)["supervisor"]
        assert sup["lane"] == {
            "runtime": "codex",
            "backend": "chatgpt",
            "model": "gpt-5-codex",
        }

    def test_status_displays_codex_lane(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        """T1b: the human view shows the resolved codex lane line from the consumer-lane binding."""
        from forge.session.models import (
            ConsumerLaneIntent,
            LaneRecord,
            SupervisorConfig,
        )

        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(manifest, SupervisorConfig(resume_id="planner", direct=True))
        manifest.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-5-codex"))
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status"])
        assert result.exit_code == 0, result.output
        assert "Lane: runtime=codex backend=chatgpt model=gpt-5-codex" in result.output

    def test_status_displays_confirmed_lane_over_intent(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        """T1b: with both intent and a frozen binding, status shows the *confirmed* lane.

        read_bound_lane is confirmed-first, so the displayed lane is the one that actually
        dispatches -- a drifted intent override must not mislead the status view.
        """
        from forge.session.models import ConsumerLaneIntent

        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(manifest, SupervisorConfig(resume_id="planner", direct=True))
        # Intent says codex, but the frozen binding is the default claude lane -> confirmed wins.
        manifest.intent.consumer_lanes = ConsumerLaneIntent(supervisor=LaneRecord("codex", "chatgpt", "gpt-5-codex"))
        manifest.confirmed.consumer_lanes = ConsumerLaneConfirmed(
            supervisor=ConsumerLaneBinding(
                lane=LaneRecord("claude_code", "anthropic-direct", "opus"),
                source="intent",
                resolved_at=now_iso(),
            )
        )
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status"])
        assert result.exit_code == 0, result.output
        assert "Lane: runtime=claude_code backend=anthropic-direct model=opus" in result.output

    def test_status_json_lane_null_on_resolution_failure(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        """A drifted binding (catalog entry removed) -> resolve raises -> status shows lane=null,
        never crashes (fail-open display)."""
        from forge.core.lanes import LaneError

        def _boom(_lane: object) -> object:
            raise LaneError("backend renamed out of the catalog")

        monkeypatch.setattr("forge.cli.policy.resolve_supervisor_lane", _boom)
        _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(main, ["policy", "supervisor", "status", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["supervisor"]["lane"] is None

    def test_status_human_lane_unresolved_on_failure(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        """T5/WS3: on resolution failure the human view degrades to '(unresolved)' (with the runtime)."""
        from forge.core.lanes import LaneError
        from forge.session.models import SupervisorConfig

        def _boom(_lane: object) -> object:
            raise LaneError("backend renamed out of the catalog")

        monkeypatch.setattr("forge.cli.policy.resolve_supervisor_lane", _boom)
        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(
            manifest,
            SupervisorConfig(resume_id="planner", direct=True),
        )
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "status"])
        assert result.exit_code == 0, result.output
        assert "Lane: not executable" in result.output


class TestSupervisorToggle:
    """Tests for forge policy supervisor off/on/remove."""

    def test_off_suspends(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(main, ["policy", "supervisor", "off"])

        assert result.exit_code == 0
        assert "suspended" in result.output.lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.suspended is True
        assert updated.intent.policy.supervisor.resume_id == "planner"

    def test_off_refuses_incompatible_target_without_manifest_write(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        before = store.manifest_path.read_bytes()
        (temp_guard_env / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(main, ["policy", "supervisor", "off"])

        assert result.exit_code == 1
        assert "requires Forge" in result.output
        assert store.manifest_path.read_bytes() == before

    def test_on_resumes(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch, suspended=True)
        result = runner.invoke(main, ["policy", "supervisor", "on"])

        assert result.exit_code == 0
        assert "resumed" in result.output.lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.suspended is False

    def test_remove_clears(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(main, ["policy", "supervisor", "remove"])

        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is None

    def test_remove_clears_confirmed_consumer_lane(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        # remove tears down the supervisor's *frozen* lane too, not just intent: the binding
        # belongs to the consumer, so a later re-add starts from the default and never
        # resurrects the removed lane (read_bound_lane is confirmed-first, else intent).
        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(manifest, SupervisorConfig(resume_id="planner", direct=True))
        manifest.confirmed.consumer_lanes = ConsumerLaneConfirmed(
            supervisor=ConsumerLaneBinding(
                lane=LaneRecord("codex", "chatgpt", "gpt-5-codex"),
                source="intent",
                resolved_at=now_iso(),
            )
        )
        store = SessionStore(str(temp_guard_env), "worker")
        store.write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "remove"])
        assert result.exit_code == 0

        updated = store.read()
        confirmed = updated.confirmed.consumer_lanes
        assert confirmed is None or confirmed.supervisor is None

    def test_remove_clears_supervisor_degrade(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        """T7: removing the supervisor orphans the codex binding, so the sticky degrade is dropped too."""
        from forge.policy.supervisor_lane_degrade import (
            is_supervisor_degraded,
            set_supervisor_degrade,
        )

        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        _apply_supervisor_to_intent(manifest, SupervisorConfig(resume_id="planner", direct=True))
        set_supervisor_degrade(
            manifest,
            from_lane=LaneRecord("codex", "chatgpt", "gpt-5-codex"),
            to_lane=None,
            reason="subscription_exhausted",
            at=now_iso(),
        )
        store = SessionStore(str(temp_guard_env), "worker")
        store.write(manifest)
        assert is_supervisor_degraded(store.read()) is True  # precondition

        result = runner.invoke(main, ["policy", "supervisor", "remove"])
        assert result.exit_code == 0, result.output

        assert is_supervisor_degraded(store.read()) is False

    def test_off_without_supervisor_reports_not_configured(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "off"])
        assert result.exit_code == 0
        assert "no supervisor configured" in result.output.lower()

    def test_reload_from_path(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        plan = temp_guard_env / "plan.md"
        plan.write_text("# Updated Plan")

        result = runner.invoke(main, ["policy", "supervisor", "reload", "--from", str(plan)])

        assert result.exit_code == 0
        assert "plan updated" in result.output.lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.plan_override_path is not None
        assert "plan.md" in updated.intent.policy.supervisor.plan_override_path


class TestSupervisorSetProxyFlags:
    """Tests for --supervisor-proxy / --no-supervisor-proxy on `policy supervisor set`."""

    def test_supervisor_proxy_mutual_exclusivity(self, temp_guard_env: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "set",
                "planner",
                "--supervisor-proxy",
                "x",
                "--no-supervisor-proxy",
            ],
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_supervisor_proxy_requires_target(self, temp_guard_env: Path) -> None:
        """`set` makes the target positional, so the proxy flag can't be used without it."""
        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "set", "--supervisor-proxy", "x"])
        assert result.exit_code == 2
        assert "TARGET" in result.output

    def test_no_supervisor_proxy_requires_target(self, temp_guard_env: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "set", "--no-supervisor-proxy"])
        assert result.exit_code == 2
        assert "TARGET" in result.output

    @patch(
        "forge.policy.semantic.supervisor.validate_supervisor_target",
        side_effect=_validate_supervisor_target,
    )
    @patch("forge.policy.semantic.supervisor.apply_supervisor_routing")
    @patch(
        "forge.policy.semantic.supervisor.ensure_supervisor_proxy",
        return_value=("litellm-gemini", False),
    )
    def test_supervisor_proxy_passed_to_apply(
        self, mock_ensure, mock_apply, mock_validate, temp_guard_env: Path
    ) -> None:
        project = temp_guard_env
        store = SessionStore(str(project), "test-session")
        state = create_session_state("test-session", worktree_path=str(project))
        state.forge_root = str(project)
        store.write(state)

        runner = CliRunner()
        monkeypatch_env = {"FORGE_SESSION": "test-session"}
        with patch.dict("os.environ", monkeypatch_env):
            result = runner.invoke(
                main,
                [
                    "policy",
                    "supervisor",
                    "set",
                    "planner",
                    "--supervisor-proxy",
                    "litellm-gemini",
                ],
            )

        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.output}"
        mock_ensure.assert_called_once_with("litellm-gemini")
        mock_apply.assert_called_once()
        assert mock_apply.call_args.kwargs.get("supervisor_proxy") == "litellm-gemini"


class TestSupervisorSetTimeoutFlag:
    """--timeout on `policy supervisor set`: a modifier on the target, enforced structurally."""

    def _set_supervisor(self, project: Path, args: list[str]) -> SupervisorConfig:
        """Run ``policy supervisor set planner <args>`` against a real store; return persisted config."""
        store = SessionStore(str(project), "test-session")
        state = create_session_state("test-session", worktree_path=str(project))
        state.forge_root = str(project)
        store.write(state)

        runner = CliRunner()
        with (
            patch.dict("os.environ", {"FORGE_SESSION": "test-session"}),
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                side_effect=_validate_supervisor_target,
            ),
            patch("forge.policy.semantic.supervisor.apply_supervisor_routing"),
        ):
            result = runner.invoke(main, ["policy", "supervisor", "set", "planner", *args])
        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.output}"
        manifest = store.read()
        assert manifest.intent.policy is not None and manifest.intent.policy.supervisor is not None
        return manifest.intent.policy.supervisor

    def test_timeout_persists_into_intent(self, temp_guard_env: Path) -> None:
        sup = self._set_supervisor(temp_guard_env, ["--timeout", "90"])
        assert sup.timeout_seconds == 90

    def test_default_unchanged_without_flag(self, temp_guard_env: Path) -> None:
        sup = self._set_supervisor(temp_guard_env, [])
        assert sup.timeout_seconds == 45

    def test_timeout_requires_target(self, temp_guard_env: Path) -> None:
        """`--timeout` lives only on `set`, whose TARGET is required (Click usage error)."""
        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "set", "--timeout", "90"])
        assert result.exit_code == 2
        assert "TARGET" in result.output

    def test_timeout_rejects_non_positive(self, temp_guard_env: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["policy", "supervisor", "set", "planner", "--timeout", "0"])
        assert result.exit_code == 2  # Click IntRange(min=1) usage error


class TestSupervisorSetRuntimeFlag:
    """--runtime on `policy supervisor set`: writes the consumer-lane binding; rejects a post-bind change."""

    _CODEX = LaneRecord("codex", "chatgpt", "gpt-5-codex")

    def _set_and_read(self, project: Path, args: list[str]) -> SessionState:
        """Run ``policy supervisor set planner <args>`` against a real store; return the persisted manifest."""
        store = SessionStore(str(project), "test-session")
        state = create_session_state("test-session", worktree_path=str(project))
        state.forge_root = str(project)
        store.write(state)

        runner = CliRunner()
        with (
            patch.dict("os.environ", {"FORGE_SESSION": "test-session"}),
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                side_effect=_validate_supervisor_target,
            ),
            patch("forge.policy.semantic.supervisor.apply_supervisor_routing"),
        ):
            result = runner.invoke(main, ["policy", "supervisor", "set", "planner", *args])
        assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}: {result.output}"
        return store.read()

    def test_runtime_writes_intent_lane(self, temp_guard_env: Path) -> None:
        manifest = self._set_and_read(temp_guard_env, ["--runtime", "codex"])
        assert manifest.intent.consumer_lanes is not None
        assert manifest.intent.consumer_lanes.supervisor == self._CODEX

    def test_no_runtime_leaves_lane_unset(self, temp_guard_env: Path) -> None:
        # Setting other supervisor options must not implicitly bind a lane.
        manifest = self._set_and_read(temp_guard_env, [])
        assert manifest.intent.consumer_lanes is None

    def test_backend_writes_claude_max_intent_lane(self, temp_guard_env: Path) -> None:
        # --backend selects the claude-max subscription lane, which --runtime claude_code cannot
        # (both share the claude_code runtime; runtime alone returns the default anthropic-direct).
        manifest = self._set_and_read(temp_guard_env, ["--backend", "claude-max"])
        assert manifest.intent.consumer_lanes is not None
        assert manifest.intent.consumer_lanes.supervisor == LaneRecord("claude_code", "claude-max", "opus")

    def test_backend_set_output_shows_full_lane(self, temp_guard_env: Path) -> None:
        # The success line must name the chosen backend, not just the runtime: claude-max and
        # anthropic-direct share the claude_code runtime, so runtime alone hides the user's choice.
        store = SessionStore(str(temp_guard_env), "test-session")
        state = create_session_state("test-session", worktree_path=str(temp_guard_env))
        state.forge_root = str(temp_guard_env)
        store.write(state)

        runner = CliRunner()
        with (
            patch.dict("os.environ", {"FORGE_SESSION": "test-session"}),
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                side_effect=_validate_supervisor_target,
            ),
            patch("forge.policy.semantic.supervisor.apply_supervisor_routing"),
        ):
            result = runner.invoke(
                main,
                ["policy", "supervisor", "set", "planner", "--backend", "claude-max"],
            )

        assert result.exit_code == 0, result.output
        assert "Lane: runtime=claude_code backend=claude-max model=opus" in result.output

    def test_runtime_after_bind_rejected(self, temp_guard_env: Path) -> None:
        # Once confirmed.consumer_lanes.supervisor is frozen, --runtime is rejected: dispatch is
        # confirmed-first, so a new intent lane would be recorded-but-ignored (the launch.runtime
        # failure mode). The reject is stateful (reads confirmed), unlike the cached validate_key.
        store = SessionStore(str(temp_guard_env), "test-session")
        state = create_session_state("test-session", worktree_path=str(temp_guard_env))
        state.forge_root = str(temp_guard_env)
        state.confirmed.consumer_lanes = ConsumerLaneConfirmed(
            supervisor=ConsumerLaneBinding(lane=self._CODEX, source="intent", resolved_at=now_iso())
        )
        store.write(state)

        runner = CliRunner()
        with (
            patch.dict("os.environ", {"FORGE_SESSION": "test-session"}),
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                side_effect=_validate_supervisor_target,
            ),
            patch("forge.policy.semantic.supervisor.apply_supervisor_routing"),
        ):
            result = runner.invoke(
                main,
                ["policy", "supervisor", "set", "planner", "--runtime", "claude_code"],
            )

        assert result.exit_code == 1, result.output
        assert "already-bound" in result.output
        assert "frozen on codex/chatgpt/gpt-5-codex" in result.output
        after = store.read()
        # The frozen binding is untouched, and no intent lane was written.
        assert after.confirmed.consumer_lanes is not None
        assert after.confirmed.consumer_lanes.supervisor is not None
        assert after.confirmed.consumer_lanes.supervisor.lane == self._CODEX
        assert after.intent.consumer_lanes is None

    def test_runtime_race_frozen_under_lock_aborts(self, temp_guard_env: Path, monkeypatch) -> None:
        # TOCTOU (review P2): the pre-lock check sees the lane unbound, but a hook freezes a
        # *different* lane (the default claude) between that read and the locked write. The
        # under-lock re-check must abort so our codex intent is not persisted as
        # recorded-but-ignored (dispatch is confirmed-first on the hook's frozen lane). A
        # same-lane race would be an idempotent no-op, so the conflict must be a different lane.
        store = SessionStore(str(temp_guard_env), "test-session")
        state = create_session_state("test-session", worktree_path=str(temp_guard_env))
        state.forge_root = str(temp_guard_env)
        store.write(state)

        calls = {"n": 0}
        hook_frozen = LaneRecord("claude_code", "anthropic-direct", "opus")  # != the requested codex lane

        def _fake_confirmed_lane(_m, _consumer):
            calls["n"] += 1
            return None if calls["n"] == 1 else hook_frozen  # unbound pre-lock, a different lane under lock

        monkeypatch.setattr("forge.cli.policy.confirmed_lane", _fake_confirmed_lane)

        runner = CliRunner()
        with (
            patch.dict("os.environ", {"FORGE_SESSION": "test-session"}),
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                side_effect=_validate_supervisor_target,
            ),
            patch("forge.policy.semantic.supervisor.apply_supervisor_routing"),
        ):
            result = runner.invoke(main, ["policy", "supervisor", "set", "planner", "--runtime", "codex"])

        assert calls["n"] == 2, "expected a pre-lock and an under-lock confirmed check"
        assert result.exit_code == 1, result.output
        assert "already-bound" in result.output
        # The mutate raised, so store.update persisted nothing -- not even the supervisor config.
        after = store.read()
        assert after.intent.consumer_lanes is None
        assert after.intent.policy is None or after.intent.policy.supervisor is None

    def test_set_remove_set_does_not_resurrect_lane(self, temp_guard_env: Path) -> None:
        # Reviewer P2 repro: set --runtime codex -> remove -> set planner (no runtime) must leave
        # no bound lane, not resurrect codex. remove orphan-clears the supervisor consumer lane.
        from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
        from forge.session.consumer_lanes import read_bound_lane

        store = SessionStore(str(temp_guard_env), "test-session")
        state = create_session_state("test-session", worktree_path=str(temp_guard_env))
        state.forge_root = str(temp_guard_env)
        store.write(state)

        runner = CliRunner()
        with (
            patch.dict("os.environ", {"FORGE_SESSION": "test-session"}),
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                side_effect=_validate_supervisor_target,
            ),
            patch("forge.policy.semantic.supervisor.apply_supervisor_routing"),
        ):
            assert (
                runner.invoke(
                    main,
                    ["policy", "supervisor", "set", "planner", "--runtime", "codex"],
                ).exit_code
                == 0
            )
            assert store.read().intent.consumer_lanes.supervisor == self._CODEX  # type: ignore[union-attr]
            assert runner.invoke(main, ["policy", "supervisor", "remove"]).exit_code == 0
            assert runner.invoke(main, ["policy", "supervisor", "set", "planner"]).exit_code == 0

        # No bound lane survives: read_bound_lane returns None -> the default claude lane dispatches.
        assert read_bound_lane(store.read(), SUPERVISOR_CONSUMER) is None

    def test_runtime_resetting_same_lane_is_idempotent(self, temp_guard_env: Path) -> None:
        # Re-pinning the *already-frozen* lane is a permitted no-op, not an already-bound reject:
        # only a different lane is rejected (test_runtime_after_bind_rejected). The command still
        # succeeds so a user can re-run `set --runtime codex` to also retarget the supervisor.
        store = SessionStore(str(temp_guard_env), "test-session")
        state = create_session_state("test-session", worktree_path=str(temp_guard_env))
        state.forge_root = str(temp_guard_env)
        state.confirmed.consumer_lanes = ConsumerLaneConfirmed(
            supervisor=ConsumerLaneBinding(lane=self._CODEX, source="intent", resolved_at=now_iso())
        )
        store.write(state)

        runner = CliRunner()
        with (
            patch.dict("os.environ", {"FORGE_SESSION": "test-session"}),
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                side_effect=_validate_supervisor_target,
            ),
            patch("forge.policy.semantic.supervisor.apply_supervisor_routing"),
        ):
            result = runner.invoke(main, ["policy", "supervisor", "set", "planner", "--runtime", "codex"])

        assert result.exit_code == 0, result.output
        assert "already-bound" not in result.output
        after = store.read()
        # Frozen binding intact, and intent now also records the (same) requested lane.
        assert after.confirmed.consumer_lanes.supervisor.lane == self._CODEX  # type: ignore[union-attr]
        assert after.intent.consumer_lanes.supervisor == self._CODEX  # type: ignore[union-attr]


# --- Cascade tests for `forge policy supervisor cascade` and `set --cascade` ---


def _fake_resolved_plan(path: str, source: str = "self", session_name: str = "worker"):
    from types import SimpleNamespace

    return SimpleNamespace(path=path, source=source, session_name=session_name, captured_at=None)


def _set_supervisor_fields(store: SessionStore, **fields) -> None:
    def _mutate(m) -> None:
        assert m.intent.policy is not None and m.intent.policy.supervisor is not None
        for key, value in fields.items():
            setattr(m.intent.policy.supervisor, key, value)

    store.update(timeout_s=5.0, mutate=_mutate)


def _read_supervisor(store: SessionStore):
    manifest = store.read()
    assert manifest.intent.policy is not None
    assert manifest.intent.policy.supervisor is not None
    return manifest.intent.policy.supervisor


class TestSupervisorCascade:
    """Tests for the `cascade` leaf (standalone toggle) and `set --cascade` (modifier)."""

    def test_standalone_cascade_enables_with_existing_plan(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        plan = temp_guard_env / "plan.md"
        plan.write_text("# Plan")
        _set_supervisor_fields(store, plan_override_path=str(plan))

        result = runner.invoke(main, ["policy", "supervisor", "cascade", "on"])
        assert result.exit_code == 0, result.output
        assert "cascade enabled" in result.output.lower()

        sup = _read_supervisor(store)
        assert sup.cascade is True
        assert sup.plan_override_path == str(plan)

    def test_standalone_cascade_auto_resolves_plan(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        plan = temp_guard_env / "resolved.md"
        plan.write_text("# Plan")

        with patch(
            "forge.policy.semantic.supervisor.resolve_supervisor_reload_plan_path",
            return_value=_fake_resolved_plan(str(plan)),
        ):
            result = runner.invoke(main, ["policy", "supervisor", "cascade", "on"])

        assert result.exit_code == 0, result.output
        assert "current session" in result.output

        sup = _read_supervisor(store)
        assert sup.cascade is True
        assert sup.plan_override_path == str(plan)

    def test_standalone_cascade_unresolvable_exits_1_manifest_untouched(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)

        with patch(
            "forge.policy.semantic.supervisor.resolve_supervisor_reload_plan_path",
            return_value=None,
        ):
            result = runner.invoke(main, ["policy", "supervisor", "cascade", "on"])

        assert result.exit_code == 1
        assert "No approved plan snapshot" in result.output
        assert "Tip:" in result.output

        sup = _read_supervisor(store)
        assert sup.cascade is False
        assert sup.plan_override_path is None

    def test_standalone_cascade_off_disables(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        _set_supervisor_fields(store, cascade=True, plan_override_path="/tmp/plan.md")

        result = runner.invoke(main, ["policy", "supervisor", "cascade", "off"])
        assert result.exit_code == 0, result.output
        assert "cascade disabled" in result.output.lower()

        sup = _read_supervisor(store)
        assert sup.cascade is False

    def test_cascade_without_supervisor_reports_not_configured(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        SessionStore(str(temp_guard_env), "worker").write(manifest)

        result = runner.invoke(main, ["policy", "supervisor", "cascade", "on"])
        assert result.exit_code == 0
        assert "no supervisor configured" in result.output.lower()

    def test_cascade_rejects_bad_state(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        """`cascade` takes a positional on|off; anything else is a Click usage error."""
        _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(main, ["policy", "supervisor", "cascade", "maybe"])
        assert result.exit_code == 2

    def test_no_cascade_on_set_rejected(self, runner: CliRunner, temp_guard_env: Path) -> None:
        result = runner.invoke(main, ["policy", "supervisor", "set", "planner", "--no-cascade"])
        assert result.exit_code == 1
        assert "redundant" in result.output

    def test_checker_model_must_be_prefixed(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(main, ["policy", "supervisor", "cascade", "on", "--checker-model", "flash"])
        assert result.exit_code == 1
        assert "prefixed model id" in result.output

    def test_checker_model_validation_precedes_session_resolution(
        self, runner: CliRunner, temp_guard_env: Path
    ) -> None:
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "cascade",
                "on",
                "--session",
                "missing",
                "--checker-model",
                "flash",
            ],
        )
        assert result.exit_code == 1
        assert "prefixed model id" in result.output

    def test_checker_model_stored_with_standalone_cascade(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        plan = temp_guard_env / "plan.md"
        plan.write_text("# Plan")
        _set_supervisor_fields(store, plan_override_path=str(plan))

        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "cascade",
                "on",
                "--checker-model",
                "openrouter/some-cheap-model",
            ],
        )
        assert result.exit_code == 0, result.output

        sup = _read_supervisor(store)
        assert sup.checker_model == "openrouter/some-cheap-model"

    def test_checker_provider_stored_with_standalone_cascade(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        plan = temp_guard_env / "plan.md"
        plan.write_text("# Plan")
        _set_supervisor_fields(store, plan_override_path=str(plan))

        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "cascade",
                "on",
                "--checker-provider",
                "litellm-local",
            ],
        )
        assert result.exit_code == 0, result.output

        sup = _read_supervisor(store)
        assert sup.checker_provider == "litellm_local"
        assert sup.checker_budget_tokens is None
        assert "gemini/gemini-3.5-flash via litellm_local" in result.output

    def test_checker_budget_is_not_a_cascade_option(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "cascade",
                "on",
                "--checker-budget-tokens",
                "64000",
            ],
        )
        assert result.exit_code == 2
        assert "No such option" in result.output
        assert "--checker-budget-tokens" in result.output

    @patch(
        "forge.policy.semantic.supervisor.validate_supervisor_target",
        side_effect=_validate_supervisor_target,
    )
    @patch("forge.policy.semantic.supervisor.apply_supervisor_routing", return_value=None)
    def test_set_with_cascade_modifier(
        self,
        mock_apply,
        mock_validate,
        runner: CliRunner,
        temp_guard_env: Path,
        monkeypatch,
    ) -> None:
        """`set <target> --cascade` is a modifier on the set action."""
        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        store = SessionStore(str(temp_guard_env), "worker")
        store.write(manifest)
        plan = temp_guard_env / "approved.md"
        plan.write_text("# Plan")

        with patch(
            "forge.policy.semantic.supervisor.resolve_supervisor_reload_plan_path",
            return_value=_fake_resolved_plan(str(plan), source="target"),
        ):
            result = runner.invoke(main, ["policy", "supervisor", "set", "planner", "--cascade"])

        assert result.exit_code == 0, result.output
        assert "Cascade: on" in result.output
        assert "supervisor target" in result.output

        sup = _read_supervisor(store)
        assert (sup.resume_id, sup.cascade, sup.plan_override_path) == (
            "planner",
            True,
            str(plan),
        )

    @patch(
        "forge.policy.semantic.supervisor.validate_supervisor_target",
        side_effect=_validate_supervisor_target,
    )
    @patch("forge.policy.semantic.supervisor.apply_supervisor_routing", return_value=None)
    def test_set_with_cascade_unresolvable_plan_exits_1(
        self,
        mock_apply,
        mock_validate,
        runner: CliRunner,
        temp_guard_env: Path,
        monkeypatch,
    ) -> None:
        """Wiring-time plan resolution failure exits before any manifest mutation."""
        monkeypatch.setenv("FORGE_SESSION", "worker")
        manifest = create_session_state("worker", worktree_path=str(temp_guard_env))
        manifest.forge_root = str(temp_guard_env)
        store = SessionStore(str(temp_guard_env), "worker")
        store.write(manifest)

        with patch(
            "forge.policy.semantic.supervisor.resolve_supervisor_reload_plan_path",
            return_value=None,
        ):
            result = runner.invoke(main, ["policy", "supervisor", "set", "planner", "--cascade"])

        assert result.exit_code == 1
        assert "No approved plan snapshot" in result.output

        updated = store.read()
        assert updated.intent.policy is None or updated.intent.policy.supervisor is None

    def test_status_displays_cascade(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        _set_supervisor_fields(store, cascade=True, plan_override_path="/tmp/plan.md")

        result = runner.invoke(main, ["policy", "supervisor", "status"])
        assert result.exit_code == 0
        assert "Cascade: on" in result.output
        assert "Checker provider: openrouter" in result.output
        assert "Checker model: google/gemini-3.5-flash" in result.output
        assert "Checker budget: 32000 tokens" in result.output

    def test_status_displays_effort_fields(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        _set_supervisor_fields(store, cascade=True, supervisor_effort="high", checker_effort="low")

        result = runner.invoke(main, ["policy", "supervisor", "status"])

        assert result.exit_code == 0, result.output
        assert "Supervisor effort: high" in result.output
        assert "Checker effort: low" in result.output

    def test_status_hides_checker_effort_when_cascade_off(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        _set_supervisor_fields(store, cascade=False, supervisor_effort="high", checker_effort="low")

        result = runner.invoke(main, ["policy", "supervisor", "status"])

        assert result.exit_code == 0, result.output
        # supervisor_effort governs the always-on frontier; checker_effort is cascade-only.
        assert "Supervisor effort: high" in result.output
        assert "Checker effort" not in result.output

    def test_status_displays_unsupported_checker_provider(
        self, runner: CliRunner, temp_guard_env: Path, monkeypatch
    ) -> None:
        store = _make_supervised_project(temp_guard_env, monkeypatch)
        _set_supervisor_fields(store, cascade=True, checker_provider="anthropic")

        result = runner.invoke(main, ["policy", "supervisor", "status"])

        assert result.exit_code == 0, result.output
        assert "Checker provider: anthropic (unsupported)" in result.output
        assert "Checker model: unresolved" in result.output

    def test_status_displays_cascade_off_by_default(self, runner: CliRunner, temp_guard_env: Path, monkeypatch) -> None:
        _make_supervised_project(temp_guard_env, monkeypatch)
        result = runner.invoke(main, ["policy", "supervisor", "status"])
        assert result.exit_code == 0
        assert "Cascade: off" in result.output
        assert "Checker model" not in result.output


class TestEvaluateEffort:
    """Effort controls for the one-shot `forge policy supervisor evaluate` command."""

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_supervisor_effort_passed_to_config(self, mock_invoke, tmp_path):
        """--supervisor-effort lands on the ephemeral SupervisorConfig given to the invoker."""
        f = tmp_path / "src.py"
        f.write_text("x = 1")
        mock_invoke.return_value = _allow_decision()

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "evaluate",
                "-f",
                str(f),
                "-r",
                "abc-123",
                "--supervisor-effort",
                "high",
            ],
        )
        assert result.exit_code == 0, result.output
        config = mock_invoke.call_args[0][0]
        assert config.supervisor_effort == "high"

    def test_checker_effort_is_not_an_evaluate_option(self):
        """The one-shot evaluate command intentionally has no --checker-effort; Click rejects it."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "policy",
                "supervisor",
                "evaluate",
                "-f",
                "ignored.py",
                "-r",
                "abc-123",
                "--checker-effort",
                "low",
            ],
        )
        assert result.exit_code == 2
        assert "no such option" in result.output.lower()
