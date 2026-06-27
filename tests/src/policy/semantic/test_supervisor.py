"""Tests for SemanticSupervisorPolicy.

Tests cover:
- _evaluate() via mocked invoke_supervisor
- Cache behavior (hit/miss/expiry/skip-on-warn)
- State persistence (get_state/set_state with pruning)
- applies_to() filtering
- Engine integration (supervisor + deterministic composition)
- Hook warning output
- Policy state generalization round-trip (M25)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.policy.engine import build_engine
from forge.policy.semantic.supervisor import SemanticSupervisorPolicy
from forge.policy.semantic.verdict import verdict_to_decision
from forge.policy.types import ActionContext, PolicyDecision, Violation
from forge.session.models import SupervisorConfig, create_session_state

# --- Fixtures ---


def _make_context(tool_name: str = "Write", target_path: str = "src/main.py") -> ActionContext:
    """Create a minimal ActionContext for testing."""
    return ActionContext(
        origin="claude_code",
        event=f"PreToolUse.{tool_name}",
        tool_name=tool_name,
        tool_args={"file_path": target_path, "content": "print('hello')"},
        repo_root="/workspace",
        session_name="test-session",
        target_path=target_path,
        new_content="print('hello')",
    )


def _make_config(**overrides: object) -> SupervisorConfig:
    """Create a SupervisorConfig with defaults suitable for testing."""
    defaults = {
        "resume_id": "uuid-test-supervisor",
        "timeout_seconds": 10,
        "throttle_seconds": 30,
    }
    defaults.update(overrides)
    return SupervisorConfig(**defaults)  # type: ignore[arg-type]


def _codex_result(**overrides: Any) -> Any:
    """Build a HeadlessResult shaped like ``CodexHeadlessInvoker.run`` returns (T4 codex arm).

    Defaults to a clean exit-0 turn; pass ``runtime_is_error``/``returncode``/``stdout`` to
    model a failed turn. Imported lazily so the helper has no import-time cost for the
    (majority) claude-only tests.
    """
    from forge.core.invoker.types import HeadlessResult

    defaults: dict[str, Any] = {
        "label": "supervisor",
        "stdout": "",
        "stderr": "",
        "returncode": 0,
        "duration_seconds": 0.1,
    }
    defaults.update(overrides)
    return HeadlessResult(**defaults)


_VALID_VERDICT_STDOUT = '```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```'


def _allow_decision(warnings: list[str] | None = None) -> PolicyDecision:
    """Create a clean allow decision."""
    return PolicyDecision(
        decision="allow",
        policy_id="semantic.supervisor",
        warnings=warnings or [],
    )


def _warn_decision(msg: str = "Possible divergence") -> PolicyDecision:
    """Create a warn decision."""
    return PolicyDecision(
        decision="warn",
        policy_id="semantic.supervisor",
        warnings=[msg],
    )


def _deny_decision(msg: str = "Divergent from plan") -> PolicyDecision:
    """Create a deny decision with a violation."""
    return PolicyDecision(
        decision="deny",
        policy_id="semantic.supervisor",
        violations=[
            Violation(
                rule_id="semantic.supervisor.alignment",
                message=msg,
                severity="high",
                citations=["Section 2: API design"],
            )
        ],
    )


# --- applies_to() Tests ---


class TestSupervisorAppliesTo:
    """Tests for SemanticSupervisorPolicy.applies_to()."""

    def test_write_with_resume_id(self) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config())
        assert policy.applies_to(_make_context("Write")) is True

    def test_edit_with_resume_id(self) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config())
        assert policy.applies_to(_make_context("Edit")) is True

    def test_read_tool_excluded(self) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config())
        assert policy.applies_to(_make_context("Read")) is False

    def test_no_resume_id(self) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config(resume_id=None))
        assert policy.applies_to(_make_context("Write")) is False

    def test_no_config(self) -> None:
        policy = SemanticSupervisorPolicy(config=None)
        assert policy.applies_to(_make_context("Write")) is False


# --- _evaluate() and Caching Tests ---


class TestSupervisorEvaluate:
    """Tests for SemanticSupervisorPolicy._evaluate() with mocked invoke_supervisor."""

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_aligned_verdict_allows(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = _allow_decision()
        policy = SemanticSupervisorPolicy(config=_make_config())
        result = policy.evaluate(_make_context())
        assert result.decision == "allow"
        mock_invoke.assert_called_once()

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_divergent_high_confidence_denies(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = _deny_decision()
        policy = SemanticSupervisorPolicy(config=_make_config())
        result = policy.evaluate(_make_context())
        assert result.decision == "deny"

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_divergent_low_confidence_warns(self, mock_invoke: MagicMock) -> None:
        mock_invoke.return_value = _warn_decision("Possible divergence (confidence: 40%)")
        policy = SemanticSupervisorPolicy(config=_make_config())
        result = policy.evaluate(_make_context())
        assert result.decision == "warn"

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_timeout_allows_with_warning(self, mock_invoke: MagicMock) -> None:
        """Supervisor timeout should fail-open with warning."""
        mock_invoke.return_value = PolicyDecision(
            decision="allow",
            policy_id="semantic.supervisor",
            warnings=["Supervisor timed out after 10s"],
        )
        policy = SemanticSupervisorPolicy(config=_make_config())
        result = policy.evaluate(_make_context())
        assert result.decision == "allow"
        assert len(result.warnings) > 0

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_clean_allow_is_cached(self, mock_invoke: MagicMock) -> None:
        """Clean allows (no warnings) should be cached."""
        mock_invoke.return_value = _allow_decision()
        policy = SemanticSupervisorPolicy(config=_make_config(throttle_seconds=60))

        # First call: cache miss, invokes supervisor
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 1

        # Second call: cache hit, no invocation
        result = policy.evaluate(_make_context())
        assert mock_invoke.call_count == 1
        assert result.cached is True

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_warn_outcome_not_cached(self, mock_invoke: MagicMock) -> None:
        """Warn outcomes should NOT be cached (M26 fix)."""
        mock_invoke.return_value = _warn_decision()
        policy = SemanticSupervisorPolicy(config=_make_config(throttle_seconds=60))

        # First call
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 1

        # Second call: should re-invoke (not cached)
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 2

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_allow_with_warnings_not_cached(self, mock_invoke: MagicMock) -> None:
        """Allow-with-warnings (e.g., timeout) should NOT be cached (M26 fix)."""
        mock_invoke.return_value = PolicyDecision(
            decision="allow",
            policy_id="semantic.supervisor",
            warnings=["Supervisor timed out after 10s"],
        )
        policy = SemanticSupervisorPolicy(config=_make_config(throttle_seconds=60))

        policy.evaluate(_make_context())
        policy.evaluate(_make_context())
        # Both calls should invoke supervisor (nothing cached)
        assert mock_invoke.call_count == 2

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_deny_not_cached(self, mock_invoke: MagicMock) -> None:
        """Denials should NOT be cached (allows re-evaluation after fix)."""
        mock_invoke.return_value = _deny_decision()
        policy = SemanticSupervisorPolicy(config=_make_config(throttle_seconds=60))

        policy.evaluate(_make_context())
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 2

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_cache_expires_after_throttle(self, mock_invoke: MagicMock) -> None:
        """Cached entries should expire after the throttle window."""
        mock_invoke.return_value = _allow_decision()
        policy = SemanticSupervisorPolicy(config=_make_config(throttle_seconds=0))

        # With throttle=0, cache always expires
        policy.evaluate(_make_context())
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 2


# --- State Persistence Tests ---


class TestSupervisorState:
    """Tests for get_state/set_state and cache pruning."""

    def test_get_state_returns_cache(self) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config())
        policy._cache.update("key1", verdict="aligned")
        state = policy.get_state()
        assert "cache" in state
        assert "key1" in state["cache"]

    def test_set_state_restores_cache(self) -> None:
        from forge.core.state import now_iso

        policy = SemanticSupervisorPolicy(config=_make_config())
        saved = {"cache": {"key1": {"verdict": "aligned", "checked_at": now_iso()}}}
        policy.set_state(saved)
        assert policy._cache.check("key1") is not None

    def test_set_state_empty_dict(self) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config())
        policy._cache.update("something", verdict="aligned")
        policy.set_state({})
        assert policy._cache.check("something") is None

    def test_get_state_prunes_to_50(self) -> None:
        """Cache should be pruned to 50 most recent entries on get_state()."""
        policy = SemanticSupervisorPolicy(config=_make_config())
        # Add 60 entries directly to ThrottleCache internals
        for i in range(60):
            policy._cache._cache[f"key{i:03d}"] = {
                "verdict": "aligned",
                "checked_at": f"2025-01-01T{i:02d}:00:00Z",
                "confidence": 1.0,
            }
        state = policy.get_state()
        assert len(state["cache"]) == 50
        # Should keep the most recent (highest checked_at)
        assert "key059" in state["cache"]
        assert "key000" not in state["cache"]

    def test_state_round_trips(self) -> None:
        """State should survive save → restore cycle."""
        policy1 = SemanticSupervisorPolicy(config=_make_config())
        policy1._cache.update("key1", verdict="aligned", confidence=1.0)
        state = policy1.get_state()

        policy2 = SemanticSupervisorPolicy(config=_make_config())
        policy2.set_state(state)
        result = policy2._cache.check("key1")
        assert result is not None
        assert result["verdict"] == "aligned"


# --- FORGE_DEPTH Guard Tests ---


class TestSupervisorDepthGuard:
    """Verify invoke_supervisor skips at FORGE_DEPTH >= MAX_DEPTH."""

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_skips_supervisor_at_max_depth(self, mock_run: MagicMock) -> None:
        """At FORGE_DEPTH=2, supervisor should return allow without spawning."""
        from forge.policy.semantic.supervisor import invoke_supervisor

        with patch.dict("os.environ", {"FORGE_DEPTH": "2"}):
            result = invoke_supervisor(_make_config(), _make_context())

        assert result.decision == "allow"
        assert any("FORGE_DEPTH" in w for w in result.warnings)
        assert result.fail_open is True
        assert result.failure_type == "skipped"
        mock_run.assert_not_called()

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_runs_supervisor_below_max_depth(self, mock_run: MagicMock) -> None:
        """At FORGE_DEPTH=1, supervisor should proceed normally."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        with patch.dict("os.environ", {"FORGE_DEPTH": "1"}):
            result = invoke_supervisor(_make_config(), _make_context())

        assert result.decision == "allow"
        mock_run.assert_called_once()

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_stamps_provider_trace_identity_env(self, mock_run: MagicMock) -> None:
        """Phase 1: the fork spawn is tagged with the session name + supervisor role."""
        from forge.core.reactive.env import FORGE_COMMAND_VAR, FORGE_SESSION_VAR
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        with patch.dict("os.environ", {"FORGE_DEPTH": "1"}):
            invoke_supervisor(_make_config(), _make_context())

        extra_env = mock_run.call_args.kwargs["extra_env"]
        assert extra_env[FORGE_COMMAND_VAR] == "supervisor"
        assert extra_env[FORGE_SESSION_VAR] == "test-session"


class TestSupervisorResumeTargetResolution:
    """Tests for resolving supervisor resume targets."""

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_resolves_forge_session_name_to_uuid(self, mock_run: MagicMock) -> None:
        """A Forge session name should resolve to its confirmed Claude UUID."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        session_state = MagicMock()
        session_state.confirmed.claude_session_id = "resolved-uuid-1234"
        session_state.worktree.path = "/workspace"

        with patch("forge.session.manager.SessionManager.get_session", return_value=session_state):
            result = invoke_supervisor(_make_config(resume_id="planner-session"), _make_context())

        assert result.decision == "allow"
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_id"] == "resolved-uuid-1234"

    def test_stale_manifest_uuid_uses_latest_resumable_transcript_uuid(self) -> None:
        """A stale same-dir fork target should use the verified child UUID when available."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        session_state = create_session_state(
            "policy-supervisor",
            parent_session="policy-planner",
            is_fork=True,
            worktree_path="/workspace",
            worktree_branch="main",
        )
        session_state.forge_root = "/workspace"
        session_state.confirmed.claude_session_id = "parent-uuid"
        session_state.confirmed.artifacts = {
            "transcripts": [
                {
                    "session_id": "child-uuid",
                    "copied_path": ".forge/artifacts/policy-supervisor/transcripts/child-uuid.jsonl",
                }
            ]
        }

        with (
            patch("forge.session.manager.SessionManager.get_session", return_value=session_state),
            patch("forge.policy.semantic.supervisor._raw_claude_transcript_exists", return_value=True),
            patch("forge.policy.semantic.supervisor.run_claude_session") as mock_run,
        ):
            mock_run.return_value = SessionResult(
                stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
                stderr="",
                returncode=0,
            )
            result = invoke_supervisor(_make_config(resume_id="policy-supervisor"), _make_context())

        assert result.decision == "allow"
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["resume_id"] == "child-uuid"

    def test_stale_manifest_uuid_without_resumable_child_fails_open(self) -> None:
        """A suspicious supervisor target should not block from the wrong parent context."""
        from forge.policy.semantic.supervisor import invoke_supervisor

        session_state = create_session_state(
            "policy-supervisor",
            parent_session="policy-planner",
            is_fork=True,
            worktree_path="/workspace",
            worktree_branch="main",
        )
        session_state.forge_root = "/workspace"
        session_state.confirmed.claude_session_id = "parent-uuid"
        session_state.confirmed.artifacts = {
            "transcripts": [
                {
                    "session_id": "child-uuid",
                    "copied_path": ".forge/artifacts/policy-supervisor/transcripts/child-uuid.jsonl",
                }
            ]
        }

        with (
            patch("forge.session.manager.SessionManager.get_session", return_value=session_state),
            patch("forge.policy.semantic.supervisor._raw_claude_transcript_exists", return_value=False),
            patch("forge.policy.semantic.supervisor.run_claude_session") as mock_run,
        ):
            result = invoke_supervisor(_make_config(resume_id="policy-supervisor"), _make_context())

        assert result.decision == "allow"
        assert result.warnings is not None
        assert "inconsistent Claude UUID state" in result.warnings[0]
        mock_run.assert_not_called()

    def test_fork_target_pointing_at_parent_uuid_fails_open(self) -> None:
        """A fork target must not invoke the supervisor using the parent's UUID."""
        from forge.policy.semantic.supervisor import invoke_supervisor

        parent_state = create_session_state("policy-planner", worktree_path="/workspace", worktree_branch="main")
        parent_state.confirmed.claude_session_id = "parent-uuid"

        session_state = create_session_state(
            "policy-supervisor",
            parent_session="policy-planner",
            is_fork=True,
            worktree_path="/workspace",
            worktree_branch="main",
        )
        session_state.forge_root = "/workspace"
        session_state.confirmed.claude_session_id = "parent-uuid"

        def get_session(name: str, forge_root: str | None = None):
            return parent_state if name == "policy-planner" else session_state

        with (
            patch("forge.session.manager.SessionManager.get_session", side_effect=get_session),
            patch("forge.policy.semantic.supervisor.run_claude_session") as mock_run,
        ):
            result = invoke_supervisor(_make_config(resume_id="policy-supervisor"), _make_context())

        assert result.decision == "allow"
        assert result.warnings is not None
        assert "points at its parent Claude UUID" in result.warnings[0]
        mock_run.assert_not_called()

    def test_validate_rejects_fork_target_pointing_at_parent_uuid(self) -> None:
        """Wiring should reject a supervisor fork that still has the parent's UUID."""
        from forge.policy.semantic.supervisor import validate_supervisor_target

        parent_state = create_session_state("policy-planner", worktree_path="/workspace", worktree_branch="main")
        parent_state.confirmed.claude_session_id = "parent-uuid"

        session_state = create_session_state(
            "policy-supervisor",
            parent_session="policy-planner",
            is_fork=True,
            worktree_path="/workspace",
            worktree_branch="main",
        )
        session_state.forge_root = "/workspace"
        session_state.confirmed.claude_session_id = "parent-uuid"
        session_state.confirmed.confirmed_by = "hook:SessionStart:startup"

        def get_session(name: str, forge_root: str | None = None):
            return parent_state if name == "policy-planner" else session_state

        with patch("forge.session.manager.SessionManager.get_session", side_effect=get_session):
            with pytest.raises(ValueError, match="points at its parent Claude UUID"):
                validate_supervisor_target("policy-supervisor", forge_root="/workspace")

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_missing_confirmed_uuid_fails_open(self, mock_run: MagicMock) -> None:
        """A Forge session without a confirmed UUID should fail open with a warning."""
        from forge.policy.semantic.supervisor import invoke_supervisor

        session_state = MagicMock()
        session_state.confirmed.claude_session_id = None

        with patch("forge.session.manager.SessionManager.get_session", return_value=session_state):
            result = invoke_supervisor(_make_config(resume_id="planner-session"), _make_context())

        assert result.decision == "allow"
        assert result.warnings == [
            "Supervisor error: Forge session 'planner-session' has no confirmed Claude session ID, failing open"
        ]
        mock_run.assert_not_called()

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_resolved_target_includes_source_cwd(self, mock_run: MagicMock) -> None:
        """Forge session resolution should include the source worktree path as CWD."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        session_state = MagicMock()
        session_state.confirmed.claude_session_id = "resolved-uuid-1234"
        session_state.worktree.path = "/original/checkout"

        with patch("forge.session.manager.SessionManager.get_session", return_value=session_state):
            invoke_supervisor(_make_config(resume_id="planner-session"), _make_context())

        assert mock_run.call_args.kwargs["cwd"] == "/original/checkout"

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_resolved_target_raw_uuid_no_cwd(self, mock_run: MagicMock) -> None:
        """Raw UUID targets should not set source_cwd (no resolution possible)."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        raw_uuid = "12345678-1234-1234-1234-123456789abc"
        invoke_supervisor(_make_config(resume_id=raw_uuid), _make_context())

        assert mock_run.call_args.kwargs["cwd"] is None

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_fork_session_passed_to_run_claude(self, mock_run: MagicMock) -> None:
        """invoke_supervisor should pass fork_session from config to run_claude_session."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        raw_uuid = "12345678-1234-1234-1234-123456789abc"
        invoke_supervisor(_make_config(resume_id=raw_uuid, fork_session=True), _make_context())
        assert mock_run.call_args.kwargs["fork_session"] is True

        invoke_supervisor(_make_config(resume_id=raw_uuid, fork_session=False), _make_context())
        assert mock_run.call_args.kwargs["fork_session"] is False

    @patch("forge.policy.semantic.supervisor.resolve_subprocess_routing")
    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_proxied_supervisor_uses_proxy_opus_tier_without_executor_model_pin(
        self,
        mock_run: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        """Executor --model pins should not leak into proxied supervisor calls."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_resolve.return_value = SimpleNamespace(base_url="http://localhost:8095")
        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        raw_uuid = "12345678-1234-1234-1234-123456789abc"
        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_MODEL": "opus",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "claude-opus-4-8",
            },
        ):
            invoke_supervisor(_make_config(resume_id=raw_uuid, proxy="openrouter-anthropic"), _make_context())

        kwargs = mock_run.call_args.kwargs
        assert kwargs["base_url"] == "http://localhost:8095"
        assert kwargs["model"] == "opus"
        assert "ANTHROPIC_MODEL" in kwargs["unset_env_vars"]
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" in kwargs["unset_env_vars"]

    @patch("forge.policy.semantic.supervisor.resolve_subprocess_routing")
    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_direct_mode_skips_routing_resolver(self, mock_run: MagicMock, mock_resolve: MagicMock) -> None:
        """direct=True should not consult proxy/env routing before invoking Claude."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        raw_uuid = "12345678-1234-1234-1234-123456789abc"
        with patch.dict("os.environ", {"FORGE_SUBPROCESS_PROXY": "broken-proxy"}):
            result = invoke_supervisor(_make_config(resume_id=raw_uuid, direct=True), _make_context())

        assert result.decision == "allow"
        mock_resolve.assert_not_called()
        assert mock_run.call_args.kwargs["base_url"] is None
        assert mock_run.call_args.kwargs["direct"] is True

    @patch("forge.policy.semantic.supervisor.resolve_subprocess_routing")
    def test_proxy_not_found_is_structural_fail_open(self, mock_resolve: MagicMock) -> None:
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_resolve.side_effect = RuntimeError("proxy offline")
        raw_uuid = "12345678-1234-1234-1234-123456789abc"

        result = run_supervisor_check(
            _make_config(resume_id=raw_uuid, proxy="missing-proxy"),
            _make_context(),
        )

        assert result.decision.decision == "allow"
        assert result.decision.fail_open is True
        assert result.decision.failure_type == "proxy_not_found"
        assert "missing-proxy" in result.decision.warnings[0]

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_unparseable_response_is_structural_fail_open(self, mock_run: MagicMock) -> None:
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_run.return_value = SessionResult(
            stdout="not json",
            stderr="",
            returncode=0,
            run_id="run_parse_fail",
            parent_run_id="run_parent",
            root_run_id="run_root",
        )
        raw_uuid = "12345678-1234-1234-1234-123456789abc"

        result = run_supervisor_check(_make_config(resume_id=raw_uuid, direct=True), _make_context())

        assert result.run_ok is True
        assert result.parsed is False
        assert result.decision.decision == "allow"
        assert result.decision.fail_open is True
        assert result.decision.failure_type == "parse_failure"
        assert result.decision.telemetry_run_id == "run_parse_fail"


# --- Lane Dispatch Tests (T3) ---


class TestSupervisorLaneDispatch:
    """T3: the supervisor is a Consumer whose lane is resolved then dispatched.

    The default lane is ``claude_code`` and the run stays byte-identical -- the
    existing ``TestSupervisorResumeTargetResolution`` cases now exercise the seam
    end-to-end. These add the lane-binding, single-emission, and stubbed-arm
    contracts specific to T3.
    """

    def test_supervisor_consumer_resolves_to_claude_lane(self) -> None:
        from forge.core.lanes import Lane, resolve_lane
        from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER

        assert SUPERVISOR_CONSUMER.capability_floor == "tool_agent"
        assert resolve_lane(SUPERVISOR_CONSUMER) == Lane(
            runtime_id="claude_code", backend_id="anthropic-direct", model="opus"
        )

    def test_supervisor_consumer_allows_codex_override(self) -> None:
        """T4: the codex-exec lane is a declared candidate, so an override resolves (not LaneError)."""
        from forge.core.lanes import Lane, resolve_lane
        from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER

        codex_lane = Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")
        assert codex_lane in SUPERVISOR_CONSUMER.allowed_lanes
        assert resolve_lane(SUPERVISOR_CONSUMER, override=codex_lane) == codex_lane
        # Default (no override) stays claude_code -- byte-identical to T3.
        assert resolve_lane(SUPERVISOR_CONSUMER).runtime_id == "claude_code"

    @patch("forge.core.usage.emit_usage_for_session_result")
    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_single_usage_emission_on_success(self, mock_run: MagicMock, mock_emit: MagicMock) -> None:
        """A successful dispatch records exactly one usage event."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )
        raw_uuid = "12345678-1234-1234-1234-123456789abc"

        run_supervisor_check(_make_config(resume_id=raw_uuid, direct=True), _make_context())

        assert mock_emit.call_count == 1

    @patch("forge.core.usage.emit_usage_for_session_result")
    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_single_usage_emission_on_failed_run(self, mock_run: MagicMock, mock_emit: MagicMock) -> None:
        """A failed dispatch still records exactly one event (emitted before the fail branch)."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_run.return_value = SessionResult(stdout="", stderr="boom", returncode=1, error="boom")
        raw_uuid = "12345678-1234-1234-1234-123456789abc"

        result = run_supervisor_check(_make_config(resume_id=raw_uuid, direct=True), _make_context())

        assert mock_emit.call_count == 1
        assert result.decision.fail_open is True

    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_codex_arm_dispatches_through_invoker(
        self, mock_read: MagicMock, mock_prepare: MagicMock, mock_invoker_cls: MagicMock
    ) -> None:
        """T4 codex arm: reads the cached preflight (no doctor in the hook), builds a read-only request, runs invoker."""
        from forge.core.lanes import Lane
        from forge.policy.semantic.supervisor import (
            _dispatch_supervisor,
            _ResolvedTarget,
        )

        mock_read.return_value = SimpleNamespace(ready=True, blocking_reason=None)
        mock_invoker_cls.return_value.run.return_value = _codex_result(stdout="VERDICT")

        codex_lane = Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")
        result = _dispatch_supervisor(
            codex_lane,
            prompt="check this",
            config=_make_config(direct=True),
            context=_make_context(),
            resolved=_ResolvedTarget(resume_id="uuid", source_cwd="/workspace"),
            usage_command="supervisor",
        )

        # Cached read, NOT a live doctor probe (the whole point of the T4 review fix).
        mock_read.assert_called_once_with()
        mock_invoker_cls.return_value.run.assert_called_once()
        # Read-only sandbox + no model pin (codex picks its own); plan-bearing prompt passed through.
        assert mock_prepare.call_args.kwargs["sandbox"] == "read-only"
        assert mock_prepare.call_args.kwargs["model"] is None
        assert mock_prepare.call_args.kwargs["prompt"] == "check this"
        assert mock_prepare.call_args.kwargs["cwd"] == "/workspace"
        assert result.stdout == "VERDICT"
        assert result.success is True

    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_codex_arm_unready_cache_raises_routing_error(self, mock_read: MagicMock) -> None:
        """An unready cached preflight raises _SupervisorRoutingError(codex_unavailable); the caller fails open."""
        from forge.core.lanes import Lane
        from forge.policy.semantic.supervisor import (
            _dispatch_supervisor,
            _ResolvedTarget,
            _SupervisorRoutingError,
        )

        mock_read.return_value = SimpleNamespace(ready=False, blocking_reason="codex not installed")
        codex_lane = Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")

        with pytest.raises(_SupervisorRoutingError) as exc:
            _dispatch_supervisor(
                codex_lane,
                prompt="x",
                config=_make_config(direct=True),
                context=_make_context(),
                resolved=_ResolvedTarget(resume_id="uuid", source_cwd=None),
                usage_command="supervisor",
            )
        assert exc.value.failure_type == "codex_unavailable"
        assert "codex not installed" in str(exc.value)

    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight", return_value=None)
    def test_codex_arm_cold_cache_fails_open(self, mock_read: MagicMock) -> None:
        """A cold cache (read returns None) raises codex_unavailable with a refresh hint, never spawns codex."""
        from forge.core.lanes import Lane
        from forge.policy.semantic.supervisor import (
            _dispatch_supervisor,
            _ResolvedTarget,
            _SupervisorRoutingError,
        )

        codex_lane = Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")
        with pytest.raises(_SupervisorRoutingError) as exc:
            _dispatch_supervisor(
                codex_lane,
                prompt="x",
                config=_make_config(direct=True),
                context=_make_context(),
                resolved=_ResolvedTarget(resume_id="uuid", source_cwd=None),
                usage_command="supervisor",
            )
        assert exc.value.failure_type == "codex_unavailable"
        assert "forge runtime preflight codex" in str(exc.value)

    def test_unknown_runtime_arm_raises_routing_error(self) -> None:
        """A reachable lane with no adapter (core_llm) raises _SupervisorRoutingError(configuration_error).

        Critically NOT a bare LaneError: run_supervisor_check's dispatch except catches only
        _SupervisorRoutingError, so a LaneError here would escape uncaught -> engine policy_error
        -> DENY under fail_mode='closed' (M2 regression guard).
        """
        from forge.core.lanes import Lane
        from forge.policy.semantic.supervisor import (
            _dispatch_supervisor,
            _ResolvedTarget,
            _SupervisorRoutingError,
        )

        single_shot_lane = Lane(runtime_id="core_llm", backend_id="anthropic-direct", model="opus")
        with pytest.raises(_SupervisorRoutingError) as exc:
            _dispatch_supervisor(
                single_shot_lane,
                prompt="x",
                config=_make_config(direct=True),
                context=_make_context(),
                resolved=_ResolvedTarget(resume_id="uuid", source_cwd=None),
                usage_command="supervisor",
            )
        assert exc.value.failure_type == "configuration_error"

    def test_supervisor_runtimes_match_allowed_lanes(self) -> None:
        """Drift guard (M3): _SUPERVISOR_RUNTIMES == {default runtime} ∪ allowed-lane runtime ids.

        The validated runtime set (models.py) and the lane map (SUPERVISOR_CONSUMER) are coupled
        only by comments. If they drift, a validated-but-unmapped runtime silently falls back to
        claude. This test fails loudly the moment a runtime is added to one but not the other.
        """
        from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
        from forge.session.models import _SUPERVISOR_RUNTIMES

        lane_runtimes = {SUPERVISOR_CONSUMER.default_lane.runtime_id} | {
            lane.runtime_id for lane in SUPERVISOR_CONSUMER.allowed_lanes
        }
        assert lane_runtimes == set(_SUPERVISOR_RUNTIMES)

    def test_lane_override_raises_on_validated_but_unmapped_runtime(self, monkeypatch) -> None:
        """If the runtime set drifts ahead of allowed_lanes, _supervisor_lane_override raises (M3).

        A raise (-> configuration_error fail-open via the resolve guard) beats silently returning
        None, which would route a misconfigured codex session to the claude default.
        """
        from dataclasses import replace

        from forge.core.lanes import LaneError
        from forge.policy.semantic import supervisor as sup

        # Simulate drift: codex stays a validated runtime, but its lane is gone from allowed_lanes.
        monkeypatch.setattr(sup, "SUPERVISOR_CONSUMER", replace(sup.SUPERVISOR_CONSUMER, allowed_lanes=()))
        with pytest.raises(LaneError):
            sup._supervisor_lane_override(_make_config(supervisor_runtime="codex"))


# --- Codex Supervisor Lane Tests (T4) ---

_CODEX_UUID = "12345678-1234-1234-1234-123456789abc"


def _codex_config(**overrides: Any) -> SupervisorConfig:
    """A supervisor config bound to the codex lane (resume_id present, raw-UUID path)."""
    base: dict[str, Any] = {"resume_id": _CODEX_UUID, "direct": True, "supervisor_runtime": "codex"}
    base.update(overrides)
    return _make_config(**base)


class TestCodexSupervisorLane:
    """T4: run_supervisor_check end-to-end on the codex lane override.

    Every non-claude failure (bad lane, unready preflight, plan-absent, in-stream
    runtime error) must fail OPEN -- the supervisor's contract (design_workflows 1.2).
    All tests mock the invoker + preflight; no real codex binary is required.
    """

    @patch("forge.policy.semantic.supervisor.load_plan_override", return_value="approved plan body")
    @patch("forge.policy.semantic.supervisor.run_claude_session")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_override_dispatches_to_codex_and_parses_verdict(
        self,
        mock_read: MagicMock,
        mock_prepare: MagicMock,
        mock_invoker_cls: MagicMock,
        mock_claude: MagicMock,
        mock_plan: MagicMock,
    ) -> None:
        """A codex override routes to the invoker (not run_claude_session); codex stdout parses like claude's."""
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_read.return_value = SimpleNamespace(ready=True, blocking_reason=None)
        mock_invoker_cls.return_value.run.return_value = _codex_result(stdout=_VALID_VERDICT_STDOUT)

        result = run_supervisor_check(_codex_config(plan_override_path="/plan.md"), _make_context())

        mock_claude.assert_not_called()
        mock_invoker_cls.return_value.run.assert_called_once()
        # Blind: codex gets no Claude-UUID resume (transfer-fed via the prompt only).
        assert mock_prepare.call_args.kwargs.get("resume_thread_id") is None
        assert result.run_ok is True
        assert result.parsed is True
        assert result.decision.decision == "allow"
        assert not result.decision.fail_open  # a genuine aligned verdict, not a fail-open

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_plan_absent_fails_open_without_spawning_codex(
        self, mock_read: MagicMock, mock_invoker_cls: MagicMock, mock_claude: MagicMock
    ) -> None:
        """Codex has no --resume: with no plan in-band, fail open WITHOUT spawning (failure_type=plan_missing)."""
        from forge.policy.semantic.supervisor import run_supervisor_check

        # No plan_override_path => load_plan_override returns None (real path, not patched).
        result = run_supervisor_check(_codex_config(), _make_context())

        assert result.decision.fail_open is True
        assert result.decision.failure_type == "plan_missing"
        # Short-circuit is BEFORE any codex work: neither the preflight cache read nor the invoker ran.
        mock_read.assert_not_called()
        mock_invoker_cls.return_value.run.assert_not_called()
        mock_claude.assert_not_called()

    @patch("forge.policy.semantic.supervisor.load_plan_override", return_value="plan")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_unready_cache_fails_open(
        self, mock_read: MagicMock, mock_invoker_cls: MagicMock, mock_plan: MagicMock
    ) -> None:
        """An unready cached preflight fails open (codex_unavailable); no doctor probe in the hook, codex not spawned."""
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_read.return_value = SimpleNamespace(ready=False, blocking_reason="not logged in")

        result = run_supervisor_check(_codex_config(plan_override_path="/p"), _make_context())

        assert result.decision.fail_open is True
        assert result.decision.failure_type == "codex_unavailable"
        mock_read.assert_called_once_with()  # cache read, not a live doctor probe
        mock_invoker_cls.return_value.run.assert_not_called()

    @patch("forge.policy.semantic.supervisor.resolve_lane")
    def test_bad_lane_resolution_fails_open(self, mock_resolve: MagicMock) -> None:
        """A LaneError from resolve_lane (override not a declared candidate) degrades to a configuration_error fail-open."""
        from forge.core.lanes import LaneError
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_resolve.side_effect = LaneError("override is not a declared candidate")

        result = run_supervisor_check(_codex_config(plan_override_path="/p"), _make_context())

        assert result.decision.fail_open is True
        assert result.decision.failure_type == "configuration_error"

    @patch("forge.policy.semantic.supervisor.resolve_lane")
    def test_no_adapter_lane_fails_open_not_uncaught(self, mock_resolve: MagicMock) -> None:
        """A resolved lane with no dispatch adapter fails open, never escapes uncaught (M2 regression).

        Drives the no-adapter branch through the real dispatch try/except: it must catch the
        _SupervisorRoutingError(configuration_error) the arm raises, NOT let a bare LaneError escape
        to the engine (which would DENY under fail_mode='closed').
        """
        from forge.core.lanes import Lane
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_resolve.return_value = Lane(runtime_id="core_llm", backend_id="anthropic-direct", model="opus")

        # Plain config (no codex override): _supervisor_lane_override -> None, the mock forces core_llm.
        result = run_supervisor_check(_make_config(resume_id=_CODEX_UUID, direct=True), _make_context())

        assert result.decision.fail_open is True
        assert result.decision.failure_type == "configuration_error"

    @patch("forge.policy.semantic.supervisor.load_plan_override", return_value="plan")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_runtime_error_at_exit_zero_is_runtime_failure_not_unparseable(
        self,
        mock_read: MagicMock,
        mock_prepare: MagicMock,
        mock_invoker_cls: MagicMock,
        mock_plan: MagicMock,
    ) -> None:
        """Codex exit-0 + runtime_is_error must classify as a runtime failure, not a parse failure (review claim 7)."""
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_read.return_value = SimpleNamespace(ready=True, blocking_reason=None)
        mock_invoker_cls.return_value.run.return_value = _codex_result(
            returncode=0,
            runtime_is_error=True,
            stdout="(no final text)",  # not a parseable verdict
            stderr="model overloaded",
            run_id="r1",
            parent_run_id="p1",
            root_run_id="root1",
        )

        result = run_supervisor_check(_codex_config(plan_override_path="/p"), _make_context())

        assert result.decision.fail_open is True
        # The runtime-failure gate fired (error set) instead of parsing empty stdout.
        assert result.decision.failure_type == "subprocess_error"
        # Run-tree identity is carried onto the fail-open telemetry (read on both paths).
        assert result.decision.telemetry_run_id == "r1"
        assert result.decision.telemetry_parent_run_id == "p1"
        assert result.decision.telemetry_root_run_id == "root1"

    @patch("forge.core.usage.emit_usage_for_session_result")
    @patch("forge.policy.semantic.supervisor.load_plan_override", return_value="plan")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_no_double_emit_on_codex_path(
        self,
        mock_read: MagicMock,
        mock_prepare: MagicMock,
        mock_invoker_cls: MagicMock,
        mock_plan: MagicMock,
        mock_emit: MagicMock,
    ) -> None:
        """The codex arm relies on the invoker's emit_codex_usage; it must NOT also call the claude-arm emitter."""
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_read.return_value = SimpleNamespace(ready=True, blocking_reason=None)
        mock_invoker_cls.return_value.run.return_value = _codex_result(stdout=_VALID_VERDICT_STDOUT)

        run_supervisor_check(_codex_config(plan_override_path="/p"), _make_context())

        # The claude-arm emitter is never called on the codex path (no double-count).
        mock_emit.assert_not_called()
        # The invoker has what it needs to emit exactly one codex usage event: an Attribution.
        attribution = mock_prepare.call_args.kwargs["attribution"]
        assert attribution.command == "supervisor"
        assert attribution.session == "test-session"

    @patch("forge.policy.semantic.supervisor.load_plan_override", return_value="plan")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_cache_read_exception_fails_open_not_uncaught(self, mock_read: MagicMock, mock_plan: MagicMock) -> None:
        """An unexpected exception in the cache read becomes codex_unavailable, never escapes (review claim 2)."""
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_read.side_effect = RuntimeError("boom reading cache")

        # Must NOT raise: run_supervisor_check returns a structured fail-open, not policy_error.
        result = run_supervisor_check(_codex_config(plan_override_path="/p"), _make_context())

        assert result.decision.fail_open is True
        assert result.decision.failure_type == "codex_unavailable"

    @patch("forge.policy.semantic.supervisor.load_plan_override", return_value="plan")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_request_shaping_exception_fails_open_not_uncaught(
        self, mock_read: MagicMock, mock_prepare: MagicMock, mock_plan: MagicMock
    ) -> None:
        """An exception in prepare_codex_request (after a ready cache) also degrades to codex_unavailable."""
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_read.return_value = SimpleNamespace(ready=True, blocking_reason=None)
        mock_prepare.side_effect = RuntimeError("bad request shape")

        result = run_supervisor_check(_codex_config(plan_override_path="/p"), _make_context())

        assert result.decision.fail_open is True
        assert result.decision.failure_type == "codex_unavailable"

    def test_headless_to_session_result_maps_fields_and_folds_runtime_error(self) -> None:
        """The HeadlessResult->SessionResult adapter carries every load-bearing field and folds runtime_is_error."""
        from forge.policy.semantic.supervisor import _headless_to_session_result

        # Clean turn: all fields carried, success stays True.
        ok = _headless_to_session_result(
            _codex_result(
                stdout="V",
                returncode=0,
                run_id="r",
                parent_run_id="p",
                root_run_id="root",
                input_tokens=10,
                output_tokens=20,
                cached_tokens=5,
                envelope_parsed=True,
            )
        )
        assert ok.success is True
        assert (ok.stdout, ok.run_id, ok.parent_run_id, ok.root_run_id) == ("V", "r", "p", "root")
        assert (ok.input_tokens, ok.output_tokens, ok.cached_tokens) == (10, 20, 5)
        assert ok.envelope_parsed is True

        # Failed turn at exit 0: runtime_is_error folds into error so success flips to False.
        failed = _headless_to_session_result(
            _codex_result(returncode=0, runtime_is_error=True, stderr="provider boom", stdout="")
        )
        assert failed.success is False
        assert failed.error == "provider boom"
        assert failed.runtime_is_error is True

        # Failed turn with empty stderr still gets a non-empty reason (never a blank error).
        failed_blank = _headless_to_session_result(
            _codex_result(returncode=0, runtime_is_error=True, stderr="", stdout="")
        )
        assert failed_blank.success is False
        assert failed_blank.error


# --- Engine Integration Tests ---


class TestSupervisorEngineIntegration:
    """Tests for supervisor integration with PolicyEngine."""

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_supervisor_plus_tdd_both_allow(self, mock_invoke: MagicMock) -> None:
        """When both supervisor and TDD allow, final decision is allow."""
        mock_invoke.return_value = _allow_decision()
        engine = build_engine(["tdd"], fail_mode="open")
        engine.register(SemanticSupervisorPolicy(config=_make_config()))

        # Write to tests/ first (satisfies TDD)
        ctx_test = _make_context("Write", "tests/test_foo.py")
        engine.evaluate(ctx_test)

        # Write to src/ (supervisor allows, TDD allows because tests touched)
        ctx_src = _make_context("Write", "src/foo.py")
        result = engine.evaluate(ctx_src)
        assert result.final_decision == "allow"

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_supervisor_deny_blocks(self, mock_invoke: MagicMock) -> None:
        """Supervisor deny should block even if TDD allows."""
        mock_invoke.return_value = _deny_decision()
        engine = build_engine(["tdd"], fail_mode="open")
        engine.register(SemanticSupervisorPolicy(config=_make_config()))

        # Touch tests first
        ctx_test = _make_context("Write", "tests/test_foo.py")
        engine.evaluate(ctx_test)

        # Supervisor denies the src write
        ctx_src = _make_context("Write", "src/foo.py")
        result = engine.evaluate(ctx_src)
        assert result.final_decision == "deny"

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_supervisor_warns_surfaces_warnings(self, mock_invoke: MagicMock) -> None:
        """Supervisor warn should surface via all_warnings."""
        mock_invoke.return_value = _warn_decision("Possible divergence from plan")
        engine = build_engine([], fail_mode="open")
        engine.register(SemanticSupervisorPolicy(config=_make_config()))

        result = engine.evaluate(_make_context())
        assert result.final_decision == "warn"
        assert any("divergence" in w.lower() for w in result.all_warnings)

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_empty_bundles_supervisor_only(self, mock_invoke: MagicMock) -> None:
        """Supervisor should run even with empty bundles (gating fix verification)."""
        mock_invoke.return_value = _allow_decision()
        engine = build_engine([], fail_mode="open")
        engine.register(SemanticSupervisorPolicy(config=_make_config()))

        result = engine.evaluate(_make_context())
        assert result.final_decision == "allow"
        mock_invoke.assert_called_once()

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_state_persists_through_engine(self, mock_invoke: MagicMock) -> None:
        """Engine should collect and restore supervisor state."""
        mock_invoke.return_value = _allow_decision()
        engine = build_engine([], fail_mode="open")
        engine.register(SemanticSupervisorPolicy(config=_make_config()))

        engine.evaluate(_make_context())
        collected = engine.get_collected_state()
        assert "semantic.supervisor" in collected
        assert "cache" in collected["semantic.supervisor"]


# --- Verdict Integration Tests (L13 fix verification) ---


class TestFailOpenWithWarning:
    """Verify that empty/unparseable responses produce warn, not silent allow (L13 fix)."""

    def test_empty_response_produces_warn(self) -> None:
        """Empty supervisor response should map to warn decision."""
        from forge.policy.semantic.verdict import parse_supervisor_verdict

        verdict = parse_supervisor_verdict("")
        decision = verdict_to_decision(verdict)
        assert decision.decision == "warn"
        assert len(decision.warnings) > 0

    def test_unparseable_response_produces_warn(self) -> None:
        """Unparseable supervisor response should map to warn decision."""
        from forge.policy.semantic.verdict import parse_supervisor_verdict

        verdict = parse_supervisor_verdict("This is not JSON at all.")
        decision = verdict_to_decision(verdict)
        assert decision.decision == "warn"
        assert len(decision.warnings) > 0


# --- Policy State Generalization (M25) ---


class TestPolicyStateGeneralization:
    """Verify generic policy_states round-trip through engine."""

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_policy_states_round_trip(self, mock_invoke: MagicMock) -> None:
        """policy_states should round-trip through engine restore → evaluate → collect."""
        mock_invoke.return_value = _allow_decision()

        # Set up engine with supervisor
        engine = build_engine(["tdd"], fail_mode="open")
        supervisor = SemanticSupervisorPolicy(config=_make_config())
        engine.register(supervisor)

        # Simulate restored state from manifest
        persisted = {
            "tdd.tests-before-impl": {"tests_touched": ["tests/test_old.py"]},
            "semantic.supervisor": {
                "cache": {
                    "old_key": {
                        "verdict": "aligned",
                        "checked_at": "2025-01-01T00:00:00Z",
                        "confidence": 1.0,
                    }
                }
            },
        }
        engine.restore_state(persisted)

        # Evaluate (adds new state)
        ctx = _make_context("Write", "tests/test_new.py")
        engine.evaluate(ctx)

        # Collect state — should contain both old and new data
        collected = engine.get_collected_state()
        assert "tdd.tests-before-impl" in collected
        assert "semantic.supervisor" in collected

        # TDD state should include both old and new test paths
        tdd_state = collected["tdd.tests-before-impl"]
        assert "tests/test_old.py" in tdd_state.get("tests_touched", [])
        assert "tests/test_new.py" in tdd_state.get("tests_touched", [])

    def test_non_applicable_policy_state_preserved(self) -> None:
        """State for policies that didn't apply should be preserved in merged output.

        Regression test: when TDD's applies_to() returns False (e.g., writing to docs/),
        its state should not be lost from the merged policy_states.
        """
        from forge.policy.store import build_policy_state_update
        from forge.policy.types import CompositeDecision

        # Simulate: TDD didn't run (wrote to docs/), only provenance collected
        engine_state: dict[str, dict[str, Any]] = {}  # No stateful policies collected
        existing = {
            "decisions": [],
            "policy_states": {
                "tdd.tests-before-impl": {"tests_touched": ["tests/test_important.py"]},
                "semantic.supervisor": {"cache": {"k1": {"verdict": "aligned"}}},
            },
        }

        result = CompositeDecision(final_decision="allow")
        updated = build_policy_state_update(
            result=result,
            engine_state=engine_state,
            existing_state=existing,
        )

        # Both policy states should be preserved even though neither was collected
        assert "tdd.tests-before-impl" in updated["policy_states"]
        assert "tests/test_important.py" in updated["policy_states"]["tdd.tests-before-impl"]["tests_touched"]
        assert "semantic.supervisor" in updated["policy_states"]
        assert "k1" in updated["policy_states"]["semantic.supervisor"]["cache"]


# --- Setup Helper Tests ---


class TestValidateSupervisorTarget:
    """Tests for validate_supervisor_target()."""

    def test_valid_target_with_uuid_and_confirmation(self) -> None:
        from forge.policy.semantic.supervisor import validate_supervisor_target

        state = MagicMock()
        state.confirmed.claude_session_id = "uuid-1234"
        state.confirmed.confirmed_by = "hook:SessionStart:startup"
        state.confirmed.transcript_path = None

        with patch("forge.session.manager.SessionManager.get_session", return_value=state):
            result = validate_supervisor_target("planner")
        assert result is state

    def test_missing_session_raises(self) -> None:
        from forge.policy.semantic.supervisor import validate_supervisor_target

        with (
            patch(
                "forge.session.manager.SessionManager.get_session",
                side_effect=KeyError("not found"),
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            validate_supervisor_target("nonexistent")

    def test_no_claude_uuid_raises(self) -> None:
        from forge.policy.semantic.supervisor import validate_supervisor_target

        state = MagicMock()
        state.confirmed.claude_session_id = None

        with (
            patch("forge.session.manager.SessionManager.get_session", return_value=state),
            pytest.raises(ValueError, match="no confirmed Claude session ID"),
        ):
            validate_supervisor_target("unlaunched-session")

    def test_pre_seeded_uuid_without_evidence_raises(self) -> None:
        """Pre-seeded UUID alone (no hook confirmation, no transcript) is rejected."""
        from forge.policy.semantic.supervisor import validate_supervisor_target

        state = MagicMock()
        state.confirmed.claude_session_id = "pre-seeded-uuid"
        state.confirmed.confirmed_by = None
        state.confirmed.transcript_path = None
        state.worktree = None

        with (
            patch("forge.session.manager.SessionManager.get_session", return_value=state),
            pytest.raises(ValueError, match="pre-seeded UUID but no confirmed"),
        ):
            validate_supervisor_target("no-launch-session")

    def test_transcript_on_disk_is_valid_evidence(self, tmp_path) -> None:
        """A transcript file on disk counts as conversation evidence."""
        from forge.policy.semantic.supervisor import validate_supervisor_target

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("{}\n")

        state = MagicMock()
        state.confirmed.claude_session_id = "uuid-with-transcript"
        state.confirmed.confirmed_by = None
        state.confirmed.transcript_path = str(transcript)

        with patch("forge.session.manager.SessionManager.get_session", return_value=state):
            result = validate_supervisor_target("transcript-session")
        assert result is state


class TestAutoSeedSupervisorProxy:
    """Tests for auto_seed_supervisor_proxy()."""

    def test_different_routing_returns_proxy(self) -> None:
        from forge.policy.semantic.supervisor import auto_seed_supervisor_proxy

        state = MagicMock()
        state.confirmed.started_with_proxy.proxy_id = "proxy-123"
        state.confirmed.started_with_proxy.template = "litellm-openai"

        result = auto_seed_supervisor_proxy(state, current_proxy_id=None, current_template=None, current_direct=True)
        assert result == "proxy-123"

    def test_same_routing_returns_none(self) -> None:
        from forge.policy.semantic.supervisor import auto_seed_supervisor_proxy

        state = MagicMock()
        state.confirmed.started_with_proxy.proxy_id = "proxy-123"
        state.confirmed.started_with_proxy.template = "litellm-openai"

        result = auto_seed_supervisor_proxy(
            state, current_proxy_id="proxy-123", current_template="litellm-openai", current_direct=False
        )
        assert result is None

    def test_no_confirmed_proxy_returns_none(self) -> None:
        from forge.policy.semantic.supervisor import auto_seed_supervisor_proxy

        state = MagicMock()
        state.confirmed.started_with_proxy = None

        result = auto_seed_supervisor_proxy(state, current_proxy_id=None, current_template=None, current_direct=False)
        assert result is None

    def test_falls_back_to_template_when_no_proxy_id(self) -> None:
        from forge.policy.semantic.supervisor import auto_seed_supervisor_proxy

        state = MagicMock()
        state.confirmed.started_with_proxy.proxy_id = None
        state.confirmed.started_with_proxy.template = "litellm-gemini"

        result = auto_seed_supervisor_proxy(
            state, current_proxy_id=None, current_template="litellm-openai", current_direct=False
        )
        assert result == "litellm-gemini"


class TestApplySupervisorRouting:
    """Tests for apply_supervisor_routing()."""

    def test_explicit_proxy_overrides_auto_seed(self) -> None:
        from forge.policy.semantic.supervisor import apply_supervisor_routing
        from forge.session.models import SupervisorConfig

        state = MagicMock()
        state.confirmed.started_with_proxy.proxy_id = "planner-proxy"
        state.confirmed.started_with_proxy.template = "litellm-openai"
        sup_config = SupervisorConfig()

        with patch("forge.policy.semantic.supervisor.auto_seed_supervisor_proxy") as mock_seed:
            result = apply_supervisor_routing(
                sup_config,
                state,
                supervisor_proxy="pre-validated-proxy",
            )
            mock_seed.assert_not_called()
        assert sup_config.proxy == "pre-validated-proxy"
        assert result == "pre-validated-proxy"

    def test_explicit_direct_overrides_auto_seed(self) -> None:
        from forge.policy.semantic.supervisor import apply_supervisor_routing
        from forge.session.models import SupervisorConfig

        state = MagicMock()
        state.confirmed.started_with_proxy.proxy_id = "planner-proxy"
        sup_config = SupervisorConfig()

        with patch("forge.policy.semantic.supervisor.auto_seed_supervisor_proxy") as mock_seed:
            result = apply_supervisor_routing(sup_config, state, supervisor_direct=True)
            mock_seed.assert_not_called()
        assert sup_config.direct is True
        assert result == "direct"

    def test_neither_flag_falls_through_to_auto_seed(self) -> None:
        from forge.policy.semantic.supervisor import apply_supervisor_routing
        from forge.session.models import SupervisorConfig

        state = MagicMock()
        state.confirmed.started_with_proxy.proxy_id = "planner-proxy"
        state.confirmed.started_with_proxy.template = "litellm-openai"
        sup_config = SupervisorConfig()

        result = apply_supervisor_routing(
            sup_config,
            state,
            current_proxy_id=None,
            current_template=None,
            current_direct=True,
        )
        assert sup_config.proxy == "planner-proxy"
        assert result == "planner-proxy"

    def test_auto_seed_direct_returns_direct_string(self) -> None:
        """When source was direct (no proxy), display string should be 'direct'."""
        from forge.policy.semantic.supervisor import apply_supervisor_routing
        from forge.session.models import SupervisorConfig

        state = MagicMock()
        state.confirmed.started_with_proxy = None  # source was direct
        sup_config = SupervisorConfig()

        result = apply_supervisor_routing(
            sup_config,
            state,
            current_proxy_id="some-proxy",
            current_template="litellm-openai",
            current_direct=False,
        )
        assert sup_config.direct is True
        assert result == "direct"

    def test_ensure_supervisor_proxy_no_proxy_or_template_raises(self) -> None:
        from forge.policy.semantic.supervisor import ensure_supervisor_proxy
        from forge.proxy.proxies import ProxyNotFoundError

        with patch("forge.proxy.proxy_orchestrator.ensure_proxy", side_effect=ProxyNotFoundError("bad-proxy")):
            with pytest.raises(ValueError, match="no template named 'bad-proxy'"):
                ensure_supervisor_proxy("bad-proxy")

    def test_ensure_supervisor_proxy_returns_resolved_id(self) -> None:
        from forge.policy.semantic.supervisor import ensure_supervisor_proxy

        mock_entry = MagicMock()
        mock_entry.proxy_id = "resolved-id"
        with patch("forge.proxy.proxy_orchestrator.ensure_proxy", return_value=(mock_entry, False)):
            proxy_id, started = ensure_supervisor_proxy("my-proxy")
        assert proxy_id == "resolved-id"
        assert started is False

    def test_ensure_supervisor_proxy_autostart_returns_started_id(self) -> None:
        from forge.policy.semantic.supervisor import ensure_supervisor_proxy

        mock_entry = MagicMock()
        mock_entry.proxy_id = "openrouter-deepseek"
        with patch("forge.proxy.proxy_orchestrator.ensure_proxy", return_value=(mock_entry, True)):
            proxy_id, started = ensure_supervisor_proxy("openrouter-deepseek")
        assert proxy_id == "openrouter-deepseek"
        assert started is True

    def test_ensure_supervisor_proxy_ambiguous_raises(self) -> None:
        from forge.policy.semantic.supervisor import ensure_supervisor_proxy
        from forge.proxy.proxies import AmbiguousProxyError

        with patch(
            "forge.proxy.proxy_orchestrator.ensure_proxy",
            side_effect=AmbiguousProxyError("tmpl", ["a", "b"]),
        ):
            with pytest.raises(ValueError, match="ambiguous"):
                ensure_supervisor_proxy("tmpl")

    def test_ensure_supervisor_proxy_start_failure_raises(self) -> None:
        from forge.policy.semantic.supervisor import ensure_supervisor_proxy
        from forge.proxy.proxy_orchestrator import ProxyStartError

        with patch("forge.proxy.proxy_orchestrator.ensure_proxy", side_effect=ProxyStartError("boom")):
            with pytest.raises(ValueError, match="failed to start"):
                ensure_supervisor_proxy("tmpl")


class TestApplySupervisorToIntent:
    """Tests for apply_supervisor_to_intent()."""

    def test_sets_supervisor_and_enables_policy(self) -> None:
        from forge.policy.semantic.supervisor import apply_supervisor_to_intent

        manifest = MagicMock()
        manifest.intent.policy = None
        sup_config = SupervisorConfig(resume_id="planner")

        apply_supervisor_to_intent(manifest, sup_config)

        assert manifest.intent.policy.enabled is True
        assert manifest.intent.policy.supervisor is sup_config

    def test_preserves_existing_policy_fields(self) -> None:
        from forge.policy.semantic.supervisor import apply_supervisor_to_intent
        from forge.session.models import PolicyIntent

        manifest = MagicMock()
        manifest.intent.policy = PolicyIntent(enabled=False, bundles=["tdd"], fail_mode="closed")
        sup_config = SupervisorConfig(resume_id="planner")

        apply_supervisor_to_intent(manifest, sup_config)

        assert manifest.intent.policy.enabled is True
        assert manifest.intent.policy.bundles == ["tdd"]
        assert manifest.intent.policy.fail_mode == "closed"
        assert manifest.intent.policy.supervisor is sup_config

    def test_clears_policy_enabled_override(self) -> None:
        """Wiring supervisor clears a prior %policy disable override."""
        from forge.policy.semantic.supervisor import apply_supervisor_to_intent
        from forge.session.models import PolicyIntent

        manifest = MagicMock()
        manifest.intent.policy = PolicyIntent(enabled=False)
        manifest.overrides = {"policy": {"enabled": False}}
        sup_config = SupervisorConfig(resume_id="planner")

        apply_supervisor_to_intent(manifest, sup_config)

        assert manifest.intent.policy.enabled is True
        assert manifest.intent.policy.supervisor is sup_config
        # Override should be cleared so it doesn't shadow intent
        assert "enabled" not in manifest.overrides.get("policy", {})

    def test_no_overrides_dict_does_not_crash(self) -> None:
        """Works when overrides is None or empty."""
        from forge.policy.semantic.supervisor import apply_supervisor_to_intent
        from forge.session.models import PolicyIntent

        manifest = MagicMock()
        manifest.intent.policy = PolicyIntent(enabled=False)
        manifest.overrides = None
        sup_config = SupervisorConfig(resume_id="planner")

        apply_supervisor_to_intent(manifest, sup_config)
        assert manifest.intent.policy.enabled is True


class TestShouldSupervisorUseDirect:
    """Tests for should_supervisor_use_direct()."""

    def test_direct_mode_planner_returns_true(self) -> None:
        from forge.policy.semantic.supervisor import should_supervisor_use_direct

        state = MagicMock()
        state.confirmed.started_with_proxy = None
        assert should_supervisor_use_direct(state) is True

    def test_proxied_planner_returns_false(self) -> None:
        from forge.policy.semantic.supervisor import should_supervisor_use_direct

        state = MagicMock()
        state.confirmed.started_with_proxy = MagicMock()
        state.confirmed.started_with_proxy.template = "litellm-openai"
        assert should_supervisor_use_direct(state) is False


# --- Suspended supervisor tests (applies_to + _evaluate guard) ---


class TestSupervisorSuspended:
    """Tests for the suspended toggle on supervision."""

    def test_suspended_config_applies_to_returns_false(self) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config(suspended=True))
        assert policy.applies_to(_make_context("Write")) is False

    def test_unsuspended_config_applies_to_returns_true(self) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config(suspended=False))
        assert policy.applies_to(_make_context("Write")) is True

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_evaluate_suspended_returns_allow_without_invoke(self, mock_invoke: MagicMock) -> None:
        policy = SemanticSupervisorPolicy(config=_make_config(suspended=True))
        result = policy.evaluate(_make_context())
        assert result.decision == "allow"
        assert not result.warnings
        mock_invoke.assert_not_called()

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_evaluate_not_configured_preserves_warning(self, mock_invoke: MagicMock) -> None:
        """Missing config still produces the 'not configured' warning."""
        policy = SemanticSupervisorPolicy(config=_make_config(resume_id=None))
        result = policy.evaluate(_make_context())
        assert result.decision == "allow"
        assert any("not configured" in w for w in result.warnings)
        mock_invoke.assert_not_called()


# --- Plan override tests ---


class TestLoadPlanOverride:
    """Tests for load_plan_override()."""

    def test_no_override_returns_none(self) -> None:
        from forge.policy.semantic.supervisor import load_plan_override

        config = _make_config(plan_override_path=None)
        assert load_plan_override(config) is None

    def test_reads_file_content(self, tmp_path) -> None:
        from forge.policy.semantic.supervisor import load_plan_override

        plan = tmp_path / "plan.md"
        plan.write_text("# My Plan\nDo the thing.")
        config = _make_config(plan_override_path=str(plan))
        assert load_plan_override(config) == "# My Plan\nDo the thing."

    def test_missing_file_returns_none(self, tmp_path) -> None:
        from forge.policy.semantic.supervisor import load_plan_override

        config = _make_config(plan_override_path=str(tmp_path / "nonexistent.md"))
        assert load_plan_override(config) is None

    def test_empty_file_returns_none(self, tmp_path) -> None:
        from forge.policy.semantic.supervisor import load_plan_override

        plan = tmp_path / "empty.md"
        plan.write_text("")
        config = _make_config(plan_override_path=str(plan))
        assert load_plan_override(config) is None

    def test_relative_path_resolves_from_forge_root(self, tmp_path) -> None:
        from forge.policy.semantic.supervisor import load_plan_override

        (tmp_path / "plans").mkdir()
        plan = tmp_path / "plans" / "plan.md"
        plan.write_text("Plan content")
        config = _make_config(plan_override_path="plans/plan.md", forge_root=str(tmp_path))
        assert load_plan_override(config) == "Plan content"


class TestPlanOverridePrompt:
    """Tests for plan override injection into the supervisor prompt."""

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    @patch("forge.policy.semantic.supervisor._resolve_resume_target")
    def test_invoke_with_plan_override_prepends_preamble(
        self, mock_resolve: MagicMock, mock_run: MagicMock, tmp_path
    ) -> None:
        from forge.policy.semantic.supervisor import (
            _PLAN_OVERRIDE_PREAMBLE,
            invoke_supervisor,
        )

        plan = tmp_path / "plan.md"
        plan.write_text("# Updated Plan\nNew requirements.")

        mock_resolve.return_value = MagicMock(resume_id="uuid-123", warning=None, source_cwd=None)
        mock_run.return_value = MagicMock(success=True, stdout='{"verdict":"aligned","confidence":0.9,"violations":[]}')

        config = _make_config(plan_override_path=str(plan))
        invoke_supervisor(config, _make_context())

        prompt_sent = mock_run.call_args[0][0]
        assert "Updated Plan" in _PLAN_OVERRIDE_PREAMBLE
        assert "# Updated Plan\nNew requirements." in prompt_sent
        assert "supersedes" in prompt_sent.lower()

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    @patch("forge.policy.semantic.supervisor._resolve_resume_target")
    def test_invoke_without_override_no_preamble(self, mock_resolve: MagicMock, mock_run: MagicMock) -> None:
        from forge.policy.semantic.supervisor import invoke_supervisor

        mock_resolve.return_value = MagicMock(resume_id="uuid-123", warning=None, source_cwd=None)
        mock_run.return_value = MagicMock(success=True, stdout='{"verdict":"aligned","confidence":0.9,"violations":[]}')

        config = _make_config(plan_override_path=None)
        invoke_supervisor(config, _make_context())

        prompt_sent = mock_run.call_args[0][0]
        assert "supersedes" not in prompt_sent.lower()


class TestPlanOverrideCache:
    """Tests for cache key differentiation with plan_override_path."""

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_different_plan_override_produces_cache_miss(self, mock_invoke: MagicMock, tmp_path) -> None:
        """Changing plan_override_path on the same policy must miss the cache."""
        mock_invoke.return_value = _allow_decision()

        plan_a = tmp_path / "plan_a.md"
        plan_a.write_text("Plan A")
        plan_b = tmp_path / "plan_b.md"
        plan_b.write_text("Plan B")

        config = _make_config(plan_override_path=str(plan_a), throttle_seconds=60)
        policy = SemanticSupervisorPolicy(config=config)

        # First eval with plan_a — cache miss
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 1

        # Second eval same plan_a — cache hit
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 1

        # Switch to plan_b — must be a cache miss
        config.plan_override_path = str(plan_b)
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 2

    @patch("forge.policy.semantic.supervisor.invoke_supervisor")
    def test_same_plan_path_edited_produces_cache_miss(self, mock_invoke: MagicMock, tmp_path) -> None:
        """In-place edit of the plan file (different mtime/size) must miss cache."""
        import time

        mock_invoke.return_value = _allow_decision()

        plan = tmp_path / "plan.md"
        plan.write_text("Version 1")

        config = _make_config(plan_override_path=str(plan), throttle_seconds=60)
        policy = SemanticSupervisorPolicy(config=config)

        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 1

        # Cache hit with same content
        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 1

        # Edit in place — mtime and size change
        time.sleep(0.01)  # Ensure mtime_ns differs
        plan.write_text("Version 2 with more content")

        policy.evaluate(_make_context())
        assert mock_invoke.call_count == 2


# --- Reasoning effort (launch controls) ---


class TestSupervisorEffort:
    """Tests for supervisor reasoning-effort plumbing (checker + frontier)."""

    def test_validate_checker_model_rejects_unprefixed(self) -> None:
        from forge.policy.semantic.supervisor import validate_checker_model

        with pytest.raises(ValueError, match=r"--checker-model must be a prefixed model id \(got 'flash'\)"):
            validate_checker_model("flash")

    def test_validate_checker_model_allows_prefixed_and_none(self) -> None:
        from forge.policy.semantic.supervisor import validate_checker_model

        # Neither should raise.
        validate_checker_model(None)
        validate_checker_model("openrouter/google/gemini-3.5-flash")

    def test_apply_checker_options_sets_truthy_fields(self) -> None:
        from forge.policy.semantic.supervisor import apply_checker_options

        sup = SupervisorConfig()
        apply_checker_options(
            sup,
            checker_model="gemini/gemini-3.5-flash",
            checker_provider="litellm-local",
            checker_effort="high",
        )
        assert sup.checker_model == "gemini/gemini-3.5-flash"
        # Provider arg is normalized dash -> underscore.
        assert sup.checker_provider == "litellm_local"
        assert sup.checker_effort == "high"

    def test_apply_checker_options_leaves_unset_fields_untouched(self) -> None:
        from forge.policy.semantic.supervisor import apply_checker_options

        sup = SupervisorConfig(
            checker_model="existing/model",
            checker_provider="openrouter",
            checker_effort="low",
        )
        apply_checker_options(sup, checker_model=None, checker_provider=None, checker_effort=None)
        assert sup.checker_model == "existing/model"
        assert sup.checker_provider == "openrouter"
        assert sup.checker_effort == "low"

    def test_apply_checker_options_effort_defaults_to_none(self) -> None:
        """checker_effort is keyword-optional and defaults to leaving the field alone."""
        from forge.policy.semantic.supervisor import apply_checker_options

        sup = SupervisorConfig(checker_effort="medium")
        apply_checker_options(sup, checker_model=None, checker_provider=None)
        assert sup.checker_effort == "medium"

    def test_normalize_checker_provider_arg(self) -> None:
        from forge.policy.semantic.supervisor import normalize_checker_provider_arg

        assert normalize_checker_provider_arg("litellm-local") == "litellm_local"
        assert normalize_checker_provider_arg("openrouter") == "openrouter"
        assert normalize_checker_provider_arg(None) is None

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_supervisor_effort_forwarded_to_run_claude_session(self, mock_run: MagicMock) -> None:
        """run_supervisor_check forwards config.supervisor_effort to run_claude_session."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        raw_uuid = "12345678-1234-1234-1234-123456789abc"
        config = _make_config(resume_id=raw_uuid, supervisor_effort="medium", direct=True)
        run_supervisor_check(config, _make_context())

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["reasoning_effort"] == "medium"

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_supervisor_effort_none_forwards_none(self, mock_run: MagicMock) -> None:
        """An unset supervisor_effort forwards None (model/tier default)."""
        from forge.core.reactive.session_runner import SessionResult
        from forge.policy.semantic.supervisor import run_supervisor_check

        mock_run.return_value = SessionResult(
            stdout='```json\n{"verdict": "aligned", "confidence": 0.9, "violations": []}\n```',
            stderr="",
            returncode=0,
        )

        raw_uuid = "12345678-1234-1234-1234-123456789abc"
        config = _make_config(resume_id=raw_uuid, direct=True)
        run_supervisor_check(config, _make_context())

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["reasoning_effort"] is None
