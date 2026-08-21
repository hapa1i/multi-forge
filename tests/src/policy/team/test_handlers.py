"""Tests for forge.policy.team.handlers and CLI cache helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.cli.hooks.commands import _safe_cache_key
from forge.core.llm import CompletionResponse
from forge.core.reactive.session_runner import SessionResult
from forge.core.state import now_iso
from forge.core.usage.ledger import read_usage_events
from forge.policy.team.config import TeamSupervisorConfig
from forge.policy.team.handlers import (
    _classify_event,
    _is_fresh,
    _run_supervisor,
    handle_task_completed,
    handle_teammate_idle,
)


def _config(**overrides: object) -> TeamSupervisorConfig:
    defaults: dict[str, object] = {
        "enabled": True,
        "tagger_model": "test-model",
        "resume_id": "plan-session-123",
        "timeout_seconds": 30,
        "throttle_seconds": 60,
        "max_blocks_per_task": 3,
    }
    defaults.update(overrides)
    return TeamSupervisorConfig(**defaults)  # type: ignore[arg-type]


def _idle_event(teammate: str = "executor", team: str = "my-project") -> dict:
    return {
        "teammate_name": teammate,
        "team_name": team,
        "hook_event_name": "TeammateIdle",
    }


def _task_event(
    teammate: str = "executor",
    team: str = "my-project",
    task_id: str = "task-001",
    task_subject: str = "Implement auth",
) -> dict:
    return {
        "teammate_name": teammate,
        "team_name": team,
        "task_id": task_id,
        "task_subject": task_subject,
        "hook_event_name": "TaskCompleted",
    }


@pytest.fixture(autouse=True)
def _clear_team_routing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the team-routing matrix independent of the invoking Forge session."""
    for name in (
        "ANTHROPIC_BASE_URL",
        "FORGE_LAUNCH_MODE",
        "FORGE_SIDECAR",
        "FORGE_SUBPROCESS_BASE_URL",
        "FORGE_SUBPROCESS_PROXY",
        "FORGE_SUBPROCESS_PROXY_ID",
        "FORGE_SUBPROCESS_TEMPLATE",
    ):
        monkeypatch.delenv(name, raising=False)


def _invoke_supervisor_with_spies(
    config: TeamSupervisorConfig,
    *,
    result: SessionResult | None = None,
) -> tuple[tuple[int, str], MagicMock, MagicMock, MagicMock]:
    """Invoke the supervisor while exposing dispatch, runner, and usage boundaries."""
    dispatch = MagicMock()
    with (
        patch("forge.policy.team.handlers.run_claude_session") as run,
        patch("forge.core.reactive.cost_tracking.track_verb_cost") as track_cost,
        patch("forge.core.usage.emit_usage_for_session_result") as emit_usage,
    ):
        run.return_value = result or SessionResult(
            stdout='{"verdict": "aligned", "confidence": 0.9}',
            stderr="",
            returncode=0,
        )
        outcome = _run_supervisor(
            config,
            "alice",
            "team",
            "idle",
            "",
            on_dispatch=dispatch,
        )
    if run.called:
        base_url = run.call_args.kwargs["base_url"]
        track_cost.assert_called_once_with("team-supervisor", [base_url] if base_url else [])
        emit_usage.assert_called_once()
        assert emit_usage.call_args.kwargs["base_url"] == base_url
    else:
        track_cost.assert_not_called()
        emit_usage.assert_not_called()
    return outcome, run, emit_usage, dispatch


class TestIsFresh:
    def test_fresh_entry(self):
        entry = {"checked_at": now_iso()}
        assert _is_fresh(entry, throttle_seconds=60) is True

    def test_stale_entry(self):
        entry = {"checked_at": "2020-01-01T00:00:00Z"}
        assert _is_fresh(entry, throttle_seconds=60) is False

    def test_missing_checked_at(self):
        assert _is_fresh({}, throttle_seconds=60) is False

    def test_invalid_timestamp(self):
        assert _is_fresh({"checked_at": "not-a-date"}, throttle_seconds=60) is False

    def test_naive_timestamp_is_not_interpreted_in_host_timezone(self):
        assert _is_fresh({"checked_at": "2999-01-01T00:00:00"}, throttle_seconds=60) is False


class TestClassifyEvent:
    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_returns_tag(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="needs-review")
        mock_adapter_cls.return_value = mock_adapter

        result = _classify_event("test-model", "Prompt: {teammate_name}", "alice", "team-a")
        assert result == "needs-review"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_strips_whitespace(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="  Routine  \n")
        mock_adapter_cls.return_value = mock_adapter

        result = _classify_event("test-model", "{teammate_name}", "alice", "team-a")
        assert result == "routine"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_llm_error_returns_routine(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("LLM down")
        mock_adapter_cls.return_value = mock_adapter

        result = _classify_event("test-model", "{teammate_name}", "alice", "team-a")
        assert result == "routine"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_none_task_subject_handled(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="routine")
        mock_adapter_cls.return_value = mock_adapter

        _classify_event("test-model", "{task_subject}", "alice", "team-a", task_subject=None)
        messages = mock_adapter.complete.call_args[0][0]
        assert "None" not in messages[-1].content

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_emits_team_tagger_usage_event(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """The team tagger emits a usage event tagged from FORGE_SESSION."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_tt")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_tt")
        monkeypatch.setenv("FORGE_SESSION", "team-sess")
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text="routine", usage={"prompt_tokens": 6, "completion_tokens": 1}
        )
        mock_adapter_cls.return_value = mock_adapter

        _classify_event("gemini/gemini-2.0-flash", "{teammate_name}", "alice", "team-a")

        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert (e.command, e.session, e.provider, e.status) == (
            "team-tagger",
            "team-sess",
            "gemini",
            "success",
        )
        assert (e.input_tokens, e.output_tokens) == (6, 1)

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_exception_emits_error_event(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """A team-tagger LLM exception emits an error event and still returns routine."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_tt")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_tt")
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("LLM down")
        mock_adapter_cls.return_value = mock_adapter

        assert _classify_event("gemini/gemini-2.0-flash", "{teammate_name}", "alice", "team-a") == "routine"

        events = read_usage_events()
        assert len(events) == 1
        assert (events[0].command, events[0].status) == ("team-tagger", "error")

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_emits_ambient_when_no_forge_session(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """Without FORGE_SESSION, the team tagger emits an ambient event with no session."""
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        monkeypatch.setenv("FORGE_RUN_ID", "run_tt")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_tt")
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text="routine", usage={"prompt_tokens": 3, "completion_tokens": 1}
        )
        mock_adapter_cls.return_value = mock_adapter

        _classify_event("gemini/gemini-2.0-flash", "{teammate_name}", "alice", "team-a")

        events = read_usage_events()
        assert len(events) == 1
        assert events[0].command == "team-tagger"
        assert events[0].session is None  # ambient: no FORGE_SESSION to attribute


class TestRunSupervisor:
    @patch("forge.policy.team.handlers.run_claude_session")
    def test_aligned_allows(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "aligned", "confidence": 0.9}',
            stderr="",
            returncode=0,
        )
        exit_code, feedback = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0
        assert feedback == ""

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_divergent_blocks(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "divergent", "confidence": 0.9, "feedback": "Missing tests"}',
            stderr="",
            returncode=0,
        )
        exit_code, feedback = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 2
        assert "Missing tests" in feedback

    @pytest.mark.parametrize(
        "payload",
        [
            '{"verdict": "divergent", "confidence": 0.3, "feedback": "Check scope"}',
            '{"verdict": "divergent", "confidence": "invalid", "feedback": "Check scope"}',
            '{"verdict": "divergent", "feedback": "Check scope"}',
        ],
        ids=["low", "malformed", "missing"],
    )
    @patch("forge.policy.team.handlers.run_claude_session")
    def test_divergent_below_bar_allows_with_feedback(self, mock_session, payload):
        mock_session.return_value = SessionResult(stdout=payload, stderr="", returncode=0)

        exit_code, feedback = _run_supervisor(_config(), "alice", "team", "idle", "")

        assert exit_code == 0
        assert feedback == "Check scope"

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_confidence_threshold_is_read_at_call_time(self, mock_session, monkeypatch):
        from forge.policy.semantic import verdict as verdict_module

        mock_session.return_value = SessionResult(
            stdout='{"verdict": "divergent", "confidence": 0.9, "feedback": "Check scope"}',
            stderr="",
            returncode=0,
        )
        monkeypatch.setattr(verdict_module, "CONFIDENCE_THRESHOLD", 0.95)

        assert _run_supervisor(_config(), "alice", "team", "idle", "") == (0, "Check scope")

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_subprocess_failure_allows(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout="",
            stderr="",
            returncode=1,
            error="timeout",
        )
        exit_code, _ = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_parse_failure_allows(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout="not json",
            stderr="",
            returncode=0,
        )
        exit_code, _ = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_missing_verdict_allows(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout='{"confidence": 0.5}',
            stderr="",
            returncode=0,
        )
        exit_code, _ = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_direct_config_forwarded_to_session_runner(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "aligned"}',
            stderr="",
            returncode=0,
        )
        exit_code, _ = _run_supervisor(_config(direct=True), "alice", "team", "idle", "")

        assert exit_code == 0
        mock_session.assert_called_once()
        assert mock_session.call_args.kwargs["base_url"] is None
        assert mock_session.call_args.kwargs["direct"] is True
        assert mock_session.call_args.kwargs["unset_env_vars"] is None


class TestRunSupervisorRoutingMatrix:
    """Pin the D3 pre-dispatch route, freeze, usage, and pin-scrub contract."""

    def test_direct_skips_resolver_and_preserves_model_pins(self, monkeypatch):
        monkeypatch.setenv("FORGE_SUBPROCESS_PROXY", "ambient-proxy")
        with patch("forge.policy.team.handlers.resolve_subprocess_routing") as resolve:
            outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config(direct=True))

        assert outcome == (0, "")
        resolve.assert_not_called()
        assert run.call_args.kwargs["base_url"] is None
        assert run.call_args.kwargs["direct"] is True
        assert run.call_args.kwargs["unset_env_vars"] is None
        dispatch.assert_called_once_with()
        emit_usage.assert_called_once()

    def test_explicit_base_url_dispatches_proxied_and_scrubs_model_pins(self):
        outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config(base_url="http://proxy.test:8095"))

        assert outcome == (0, "")
        assert run.call_args.kwargs["base_url"] == "http://proxy.test:8095"
        assert run.call_args.kwargs["direct"] is False
        assert "ANTHROPIC_MODEL" in run.call_args.kwargs["unset_env_vars"]
        assert "model" not in run.call_args.kwargs
        dispatch.assert_called_once_with()
        emit_usage.assert_called_once()

    def test_explicit_named_proxy_reachable_dispatches_after_strict_preflight(self):
        entry = MagicMock(
            proxy_id="team-proxy",
            template="openrouter-anthropic",
            base_url="http://proxy.test:8095",
        )
        with (
            patch("forge.core.reactive.routing.lookup_proxy_entry_strict", return_value=entry) as lookup,
            patch("forge.core.reactive.routing._check_proxy_reachable", return_value=True) as health,
        ):
            outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config(proxy="team-proxy"))

        assert outcome == (0, "")
        lookup.assert_called_once_with("team-proxy")
        health.assert_called_once_with(entry)
        assert run.call_args.kwargs["base_url"] == "http://proxy.test:8095"
        assert "ANTHROPIC_MODEL" in run.call_args.kwargs["unset_env_vars"]
        dispatch.assert_called_once_with()
        emit_usage.assert_called_once()

    def test_explicit_named_proxy_missing_fails_open_before_commitment(self):
        with patch(
            "forge.core.reactive.routing.lookup_proxy_entry_strict",
            side_effect=RuntimeError("not registered"),
        ):
            outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config(proxy="missing-proxy"))

        assert outcome == (0, "")
        run.assert_not_called()
        dispatch.assert_not_called()
        emit_usage.assert_not_called()

    def test_explicit_named_proxy_unreachable_fails_open_before_commitment(self):
        entry = MagicMock(
            proxy_id="team-proxy",
            template="openrouter-anthropic",
            base_url="http://proxy.test:8095",
        )
        with (
            patch("forge.core.reactive.routing.lookup_proxy_entry_strict", return_value=entry),
            patch("forge.core.reactive.routing._check_proxy_reachable", return_value=False),
        ):
            outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config(proxy="team-proxy"))

        assert outcome == (0, "")
        run.assert_not_called()
        dispatch.assert_not_called()
        emit_usage.assert_not_called()

    def test_ambient_subprocess_proxy_reachable_is_visible_before_dispatch(self, monkeypatch):
        monkeypatch.setenv("FORGE_SUBPROCESS_PROXY", "ambient-proxy")
        entry = MagicMock(
            proxy_id="ambient-proxy",
            template="openrouter-anthropic",
            base_url="http://ambient.test:8095",
        )
        with (
            patch("forge.core.reactive.routing.lookup_proxy_entry_strict", return_value=entry),
            patch("forge.core.reactive.routing._check_proxy_reachable", return_value=True),
        ):
            outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config())

        assert outcome == (0, "")
        assert run.call_args.kwargs["base_url"] == "http://ambient.test:8095"
        assert "ANTHROPIC_MODEL" in run.call_args.kwargs["unset_env_vars"]
        dispatch.assert_called_once_with()
        emit_usage.assert_called_once()

    def test_ambient_subprocess_proxy_missing_fails_open_before_commitment(self, monkeypatch):
        monkeypatch.setenv("FORGE_SUBPROCESS_PROXY", "missing-proxy")
        with patch(
            "forge.core.reactive.routing.lookup_proxy_entry_strict",
            side_effect=RuntimeError("not registered"),
        ):
            outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config())

        assert outcome == (0, "")
        run.assert_not_called()
        dispatch.assert_not_called()
        emit_usage.assert_not_called()

    def test_ambient_subprocess_proxy_unreachable_fails_open_before_commitment(self, monkeypatch):
        monkeypatch.setenv("FORGE_SUBPROCESS_PROXY", "ambient-proxy")
        entry = MagicMock(
            proxy_id="ambient-proxy",
            template="openrouter-anthropic",
            base_url="http://ambient.test:8095",
        )
        with (
            patch("forge.core.reactive.routing.lookup_proxy_entry_strict", return_value=entry),
            patch("forge.core.reactive.routing._check_proxy_reachable", return_value=False),
        ):
            outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config())

        assert outcome == (0, "")
        run.assert_not_called()
        dispatch.assert_not_called()
        emit_usage.assert_not_called()

    def test_inherited_base_url_is_visible_before_dispatch(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://inherited.test:8095")
        registry = MagicMock()
        registry.proxies = {}
        with (
            patch("forge.proxy.proxies.ProxyRegistryStore.read", return_value=registry),
            patch("forge.proxy.proxies.lookup_proxy_by_base_url", return_value=None),
            patch("forge.core.reactive.routing._probe_proxy_metadata", return_value=None),
        ):
            outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config())

        assert outcome == (0, "")
        assert run.call_args.kwargs["base_url"] == "http://inherited.test:8095"
        assert "ANTHROPIC_MODEL" in run.call_args.kwargs["unset_env_vars"]
        dispatch.assert_called_once_with()
        emit_usage.assert_called_once()

    def test_sidecar_injected_base_url_is_visible_before_dispatch(self, monkeypatch):
        monkeypatch.setenv("FORGE_SIDECAR", "1")
        monkeypatch.setenv("FORGE_SUBPROCESS_BASE_URL", "http://host.docker.internal:8095")
        monkeypatch.setenv("FORGE_SUBPROCESS_PROXY_ID", "team-proxy")
        monkeypatch.setenv("FORGE_SUBPROCESS_TEMPLATE", "openrouter-anthropic")

        outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config())

        assert outcome == (0, "")
        assert run.call_args.kwargs["base_url"] == "http://host.docker.internal:8095"
        assert "ANTHROPIC_MODEL" in run.call_args.kwargs["unset_env_vars"]
        dispatch.assert_called_once_with()
        emit_usage.assert_called_once()

    def test_unresolved_dispatches_direct_without_scrubbing_model_pins(self):
        outcome, run, emit_usage, dispatch = _invoke_supervisor_with_spies(_config())

        assert outcome == (0, "")
        assert run.call_args.kwargs["base_url"] is None
        assert run.call_args.kwargs["direct"] is False
        assert run.call_args.kwargs["unset_env_vars"] is None
        dispatch.assert_called_once_with()
        emit_usage.assert_called_once()


class TestRunSupervisorUsageEmission:
    """The team supervisor's `claude -p` run is attributed to the usage ledger,
    mirroring the semantic supervisor (direct -> claude_code self-report)."""

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_direct_run_emits_claude_code_usage_event(self, mock_session):
        # Default config: direct=False but proxy=None -> base_url resolves to None ->
        # the direct cost branch (claude_code/runtime_native) applies.
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "aligned"}',
            stderr="",
            returncode=0,
            run_id="team-run-1",
            root_run_id="team-run-1",
            envelope_parsed=True,
            cost_micro_usd=5_000,
            input_tokens=120,
            output_tokens=30,
        )
        _run_supervisor(_config(), "alice", "team", "idle", "")

        events = read_usage_events(command="team-supervisor")
        assert len(events) == 1
        ev = events[0]
        assert ev.route == "claude_p"
        assert ev.reporter == "claude_code"
        assert ev.measurement_source == "runtime_native"
        assert ev.cost_micro_usd == 5_000
        assert ev.input_tokens == 120

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_failed_run_is_still_attributed(self, mock_session):
        # Emission happens before the success gate, so a failed run records an error
        # event rather than vanishing from the ledger.
        mock_session.return_value = SessionResult(
            stdout="",
            stderr="boom",
            returncode=1,
            error="timeout",
            run_id="team-run-2",
            root_run_id="team-run-2",
        )
        exit_code, _ = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0  # fail-open

        events = read_usage_events(command="team-supervisor")
        assert len(events) == 1
        assert events[0].status == "error"
        assert events[0].cost_micro_usd is None


class TestRunSupervisorDepthGuard:
    """Verify _run_supervisor skips at FORGE_DEPTH >= MAX_DEPTH."""

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_skips_at_max_depth(self, mock_run: MagicMock):
        """At FORGE_DEPTH=2, _run_supervisor should return (0, '') without spawning."""
        with patch.dict("os.environ", {"FORGE_DEPTH": "2"}):
            exit_code, feedback = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0
        assert feedback == ""
        mock_run.assert_not_called()

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_runs_below_max_depth(self, mock_run: MagicMock):
        """At FORGE_DEPTH=1, _run_supervisor should proceed normally."""
        mock_run.return_value = SessionResult(
            stdout='{"verdict": "aligned"}',
            stderr="",
            returncode=0,
        )
        with patch.dict("os.environ", {"FORGE_DEPTH": "1"}):
            exit_code, _ = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0
        mock_run.assert_called_once()


class TestHandleTeammateIdle:
    @patch("forge.policy.team.handlers._classify_event", return_value="routine")
    def test_routine_allows(self, _mock_classify):
        cache: dict = {}
        exit_code, _ = handle_teammate_idle(_idle_event(), _config(), cache)
        assert exit_code == 0

    @patch("forge.policy.team.handlers._run_supervisor", return_value=(2, "Fix the tests"))
    @patch("forge.policy.team.handlers._classify_event", return_value="needs-review")
    def test_needs_review_escalates(self, _mock_classify, _mock_supervisor):
        cache: dict = {}
        exit_code, feedback = handle_teammate_idle(_idle_event(), _config(), cache)
        assert exit_code == 2
        assert "Fix the tests" in feedback

    @patch("forge.policy.team.handlers._classify_event", return_value="needs-review")
    def test_no_supervisor_allows(self, _mock_classify):
        cache: dict = {}
        exit_code, _ = handle_teammate_idle(_idle_event(), _config(resume_id=None), cache)
        assert exit_code == 0

    def test_cache_hit_returns_cached(self):
        cache = {"executor:idle": {"checked_at": now_iso(), "exit_code": 0, "feedback": ""}}
        exit_code, _ = handle_teammate_idle(_idle_event(), _config(), cache)
        assert exit_code == 0

    @patch("forge.policy.team.handlers.run_claude_session")
    @patch("forge.policy.team.handlers._classify_event", return_value="needs-review")
    def test_claude_max_binding_emits_subscription_quota(self, _mock_classify, mock_session, monkeypatch):
        """End-to-end through the public handler: a claude-max backend_id threads
        handle_teammate_idle -> _run_supervisor -> emit, so the usage event is
        labeled subscription_quota. Guards the forwarding a type check can't (a
        dropped read or a None passed in a refactor)."""
        monkeypatch.setattr(
            "forge.core.auth.template_secrets.resolve_env_or_credential",
            lambda _key: None,  # keyless: no resolvable ANTHROPIC_API_KEY
        )
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "aligned"}',
            stderr="",
            returncode=0,
            run_id="team-run-max",
            root_run_id="team-run-max",
        )
        handle_teammate_idle(_idle_event(), _config(direct=True), {}, backend_id="claude-max")

        events = read_usage_events(command="team-supervisor")
        assert len(events) == 1
        assert events[0].billing_mode == "subscription_quota"


class TestHandleTaskCompleted:
    @patch("forge.policy.team.handlers._classify_event", return_value="routine")
    def test_routine_allows(self, _mock_classify):
        cache: dict = {}
        exit_code, _ = handle_task_completed(_task_event(), _config(), cache)
        assert exit_code == 0

    @patch("forge.policy.team.handlers._run_supervisor", return_value=(2, "Needs rework"))
    @patch("forge.policy.team.handlers._classify_event", return_value="needs-review")
    def test_needs_review_blocks(self, _mock_classify, _mock_supervisor):
        cache: dict = {}
        exit_code, feedback = handle_task_completed(_task_event(), _config(), cache)
        assert exit_code == 2
        assert "Needs rework" in feedback

    @patch("forge.policy.team.handlers.run_claude_session")
    @patch("forge.policy.team.handlers._classify_event", return_value="needs-review")
    def test_claude_max_binding_emits_subscription_quota(self, _mock_classify, mock_session, monkeypatch):
        """Sibling to the idle path: handle_task_completed -> _run_supervisor -> emit threads
        backend_id at an independent call site, so cover it too (not just teammate-idle)."""
        monkeypatch.setattr(
            "forge.core.auth.template_secrets.resolve_env_or_credential",
            lambda _key: None,  # keyless: no resolvable ANTHROPIC_API_KEY
        )
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "aligned"}',
            stderr="",
            returncode=0,
            run_id="task-run-max",
            root_run_id="task-run-max",
        )
        handle_task_completed(_task_event(), _config(direct=True), {}, backend_id="claude-max")

        events = read_usage_events(command="team-supervisor")
        assert len(events) == 1
        assert events[0].billing_mode == "subscription_quota"

    @patch("forge.policy.team.handlers._run_supervisor", return_value=(2, "Still bad"))
    @patch("forge.policy.team.handlers._classify_event", return_value="needs-review")
    def test_escape_hatch_auto_allows(self, _mock_classify, _mock_supervisor):
        """After max_blocks_per_task, auto-allow."""
        cache = {
            "executor:task-001": {
                "block_count": 3,
                "checked_at": "2020-01-01T00:00:00Z",
            }
        }
        exit_code, _ = handle_task_completed(_task_event(), _config(max_blocks_per_task=3), cache)
        assert exit_code == 0
        _mock_classify.assert_not_called()

    @patch("forge.policy.team.handlers._run_supervisor", return_value=(2, "Bad"))
    @patch("forge.policy.team.handlers._classify_event", return_value="needs-review")
    def test_block_count_increments(self, _mock_classify, _mock_supervisor):
        cache: dict = {}
        handle_task_completed(_task_event(), _config(), cache)
        assert cache["executor:task-001"]["block_count"] == 1

        # Simulate stale cache for second call
        cache["executor:task-001"]["checked_at"] = "2020-01-01T00:00:00Z"
        handle_task_completed(_task_event(), _config(), cache)
        assert cache["executor:task-001"]["block_count"] == 2

    @patch("forge.policy.team.handlers._classify_event", return_value="routine")
    def test_optional_teammate_name(self, _mock_classify):
        """TaskCompleted may have no teammate_name."""
        event = {"task_id": "task-001", "task_subject": "Fix bug"}
        cache: dict = {}
        exit_code, _ = handle_task_completed(event, _config(), cache)
        assert exit_code == 0


class TestSafeCacheKey:
    def test_valid_uuid(self):
        assert _safe_cache_key("abc-123-def") == "abc-123-def"

    def test_none_returns_default(self):
        assert _safe_cache_key(None) == "default"

    def test_empty_string_returns_default(self):
        assert _safe_cache_key("") == "default"

    def test_path_traversal_returns_default(self):
        assert _safe_cache_key("../../etc/passwd") == "default"

    def test_slash_returns_default(self):
        assert _safe_cache_key("foo/bar") == "default"

    def test_non_string_returns_default(self):
        assert _safe_cache_key(42) == "default"

    def test_dots_and_underscores_allowed(self):
        assert _safe_cache_key("session.2026_02") == "session.2026_02"


class TestHookInstallConfig:
    def test_teammate_idle_in_config(self):
        from forge.install.preset import get_builtin_preset

        hook_config = get_builtin_preset()["hooks"]
        assert "TeammateIdle" in hook_config
        hooks = hook_config["TeammateIdle"]
        assert any(h.get("command", "").endswith("forge-hook teammate-idle") for group in hooks for h in group["hooks"])

    def test_task_completed_in_config(self):
        from forge.install.preset import get_builtin_preset

        hook_config = get_builtin_preset()["hooks"]
        assert "TaskCompleted" in hook_config
        hooks = hook_config["TaskCompleted"]
        assert any(
            h.get("command", "").endswith("forge-hook task-completed") for group in hooks for h in group["hooks"]
        )


class TestRunSupervisorEffort:
    """config.effort is forwarded to run_claude_session as reasoning_effort."""

    @patch("forge.policy.team.handlers.run_claude_session")
    def test_effort_forwarded(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "aligned"}',
            stderr="",
            returncode=0,
        )
        _run_supervisor(_config(effort="high"), "alice", "team", "idle", "")

        mock_session.assert_called_once()
        _, kwargs = mock_session.call_args
        assert kwargs["reasoning_effort"] == "high"
