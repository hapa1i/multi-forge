"""Tests for forge.guard.team.handlers and CLI cache helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from forge.cli.hooks.commands import _safe_cache_key
from forge.core.reactive.session_runner import SessionResult
from forge.core.state import now_iso
from forge.guard.team.config import TeamSupervisorConfig
from forge.guard.team.handlers import (
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


# --- _is_fresh ---


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


# --- _classify_event ---


class TestClassifyEvent:
    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_returns_tag(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.ask.return_value = "needs-review"
        mock_adapter_cls.return_value = mock_adapter

        result = _classify_event("test-model", "Prompt: {teammate_name}", "alice", "team-a")
        assert result == "needs-review"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_strips_whitespace(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.ask.return_value = "  Routine  \n"
        mock_adapter_cls.return_value = mock_adapter

        result = _classify_event("test-model", "{teammate_name}", "alice", "team-a")
        assert result == "routine"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_llm_error_returns_routine(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.ask.side_effect = RuntimeError("LLM down")
        mock_adapter_cls.return_value = mock_adapter

        result = _classify_event("test-model", "{teammate_name}", "alice", "team-a")
        assert result == "routine"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_none_task_subject_handled(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.ask.return_value = "routine"
        mock_adapter_cls.return_value = mock_adapter

        _classify_event("test-model", "{task_subject}", "alice", "team-a", task_subject=None)
        prompt = mock_adapter.ask.call_args[0][0]
        assert "None" not in prompt


# --- _run_supervisor ---


class TestRunSupervisor:
    @patch("forge.guard.team.handlers.run_claude_session")
    def test_aligned_allows(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "aligned", "confidence": 0.9}',
            stderr="",
            returncode=0,
        )
        exit_code, feedback = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0
        assert feedback == ""

    @patch("forge.guard.team.handlers.run_claude_session")
    def test_divergent_blocks(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout='{"verdict": "divergent", "feedback": "Missing tests"}',
            stderr="",
            returncode=0,
        )
        exit_code, feedback = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 2
        assert "Missing tests" in feedback

    @patch("forge.guard.team.handlers.run_claude_session")
    def test_subprocess_failure_allows(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout="",
            stderr="",
            returncode=1,
            error="timeout",
        )
        exit_code, _ = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0

    @patch("forge.guard.team.handlers.run_claude_session")
    def test_parse_failure_allows(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout="not json",
            stderr="",
            returncode=0,
        )
        exit_code, _ = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0

    @patch("forge.guard.team.handlers.run_claude_session")
    def test_missing_verdict_allows(self, mock_session):
        mock_session.return_value = SessionResult(
            stdout='{"confidence": 0.5}',
            stderr="",
            returncode=0,
        )
        exit_code, _ = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0


# --- FORGE_DEPTH guard for _run_supervisor ---


class TestRunSupervisorDepthGuard:
    """Verify _run_supervisor skips at FORGE_DEPTH >= MAX_DEPTH."""

    @patch("forge.guard.team.handlers.run_claude_session")
    def test_skips_at_max_depth(self, mock_run: MagicMock):
        """At FORGE_DEPTH=2, _run_supervisor should return (0, '') without spawning."""
        with patch.dict("os.environ", {"FORGE_DEPTH": "2"}):
            exit_code, feedback = _run_supervisor(_config(), "alice", "team", "idle", "")
        assert exit_code == 0
        assert feedback == ""
        mock_run.assert_not_called()

    @patch("forge.guard.team.handlers.run_claude_session")
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


# --- handle_teammate_idle ---


class TestHandleTeammateIdle:
    @patch("forge.guard.team.handlers._classify_event", return_value="routine")
    def test_routine_allows(self, _mock_classify):
        cache: dict = {}
        exit_code, _ = handle_teammate_idle(_idle_event(), _config(), cache)
        assert exit_code == 0

    @patch("forge.guard.team.handlers._run_supervisor", return_value=(2, "Fix the tests"))
    @patch("forge.guard.team.handlers._classify_event", return_value="needs-review")
    def test_needs_review_escalates(self, _mock_classify, _mock_supervisor):
        cache: dict = {}
        exit_code, feedback = handle_teammate_idle(_idle_event(), _config(), cache)
        assert exit_code == 2
        assert "Fix the tests" in feedback

    @patch("forge.guard.team.handlers._classify_event", return_value="needs-review")
    def test_no_supervisor_allows(self, _mock_classify):
        cache: dict = {}
        exit_code, _ = handle_teammate_idle(_idle_event(), _config(resume_id=None), cache)
        assert exit_code == 0

    def test_cache_hit_returns_cached(self):
        cache = {"executor:idle": {"checked_at": now_iso(), "exit_code": 0, "feedback": ""}}
        exit_code, _ = handle_teammate_idle(_idle_event(), _config(), cache)
        assert exit_code == 0


# --- handle_task_completed ---


class TestHandleTaskCompleted:
    @patch("forge.guard.team.handlers._classify_event", return_value="routine")
    def test_routine_allows(self, _mock_classify):
        cache: dict = {}
        exit_code, _ = handle_task_completed(_task_event(), _config(), cache)
        assert exit_code == 0

    @patch("forge.guard.team.handlers._run_supervisor", return_value=(2, "Needs rework"))
    @patch("forge.guard.team.handlers._classify_event", return_value="needs-review")
    def test_needs_review_blocks(self, _mock_classify, _mock_supervisor):
        cache: dict = {}
        exit_code, feedback = handle_task_completed(_task_event(), _config(), cache)
        assert exit_code == 2
        assert "Needs rework" in feedback

    @patch("forge.guard.team.handlers._run_supervisor", return_value=(2, "Still bad"))
    @patch("forge.guard.team.handlers._classify_event", return_value="needs-review")
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

    @patch("forge.guard.team.handlers._run_supervisor", return_value=(2, "Bad"))
    @patch("forge.guard.team.handlers._classify_event", return_value="needs-review")
    def test_block_count_increments(self, _mock_classify, _mock_supervisor):
        cache: dict = {}
        handle_task_completed(_task_event(), _config(), cache)
        assert cache["executor:task-001"]["block_count"] == 1

        # Simulate stale cache for second call
        cache["executor:task-001"]["checked_at"] = "2020-01-01T00:00:00Z"
        handle_task_completed(_task_event(), _config(), cache)
        assert cache["executor:task-001"]["block_count"] == 2

    @patch("forge.guard.team.handlers._classify_event", return_value="routine")
    def test_optional_teammate_name(self, _mock_classify):
        """TaskCompleted may have no teammate_name."""
        event = {"task_id": "task-001", "task_subject": "Fix bug"}
        cache: dict = {}
        exit_code, _ = handle_task_completed(event, _config(), cache)
        assert exit_code == 0


# --- _safe_cache_key ---


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


# --- FORGE_HOOK_CONFIG ---


class TestHookInstallConfig:
    def test_teammate_idle_in_config(self):
        from forge.cli.hooks.install import FORGE_HOOK_CONFIG

        assert "TeammateIdle" in FORGE_HOOK_CONFIG["hooks"]
        hooks = FORGE_HOOK_CONFIG["hooks"]["TeammateIdle"]
        assert any("forge hook teammate-idle" in h.get("command", "") for group in hooks for h in group["hooks"])

    def test_task_completed_in_config(self):
        from forge.cli.hooks.install import FORGE_HOOK_CONFIG

        assert "TaskCompleted" in FORGE_HOOK_CONFIG["hooks"]
        hooks = FORGE_HOOK_CONFIG["hooks"]["TaskCompleted"]
        assert any("forge hook task-completed" in h.get("command", "") for group in hooks for h in group["hooks"])
