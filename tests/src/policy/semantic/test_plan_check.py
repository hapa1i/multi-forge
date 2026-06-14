"""Tests for PlanCheckPolicy (the supervisor cascade's tier-1 checker).

Tests cover:
- parse_plan_check_verdict() strictness
- run_plan_check() via mocked core.llm (tagger test pattern)
- applies_to() gating (cascade/resume_id/suspended)
- _evaluate() verdict mapping -- allow / needs_review only, violations-only contract
- Cache behavior (clean-allow-only, plan fingerprint invalidation, TTL, state round-trip)
- Usage emission (session-tagged plan-check events, request-id forwarding)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from forge.core.llm import CompletionResponse
from forge.policy.semantic.plan_check import (
    _MAX_REASON_CHARS,
    DEFAULT_PLAN_CHECK_BUDGET_TOKENS,
    DEFAULT_PLAN_CHECK_MODEL,
    PlanCheckPolicy,
    PlanCheckVerdict,
    parse_plan_check_verdict,
    resolve_plan_check_route,
    run_plan_check,
)
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.models import SupervisorConfig

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
    """Create a cascade-enabled SupervisorConfig with defaults suitable for testing."""
    defaults = {
        "resume_id": "uuid-test-supervisor",
        "timeout_seconds": 10,
        "throttle_seconds": 30,
        "cascade": True,
    }
    defaults.update(overrides)
    return SupervisorConfig(**defaults)  # type: ignore[arg-type]


def _config_with_plan(tmp_path: Path, content: str = "# Plan\nDo the thing.", **overrides: object) -> SupervisorConfig:
    plan = tmp_path / "plan.md"
    plan.write_text(content)
    return _make_config(plan_override_path=str(plan), **overrides)


def _assert_escalation(decision: PolicyDecision, rule_id: str) -> None:
    """Assert the violations-only escalation contract."""
    assert decision.decision == "needs_review"
    assert decision.policy_id == "semantic.plan_check"
    assert decision.warnings == []  # tier-1 never warns
    assert len(decision.violations) == 1
    assert decision.violations[0].rule_id == rule_id
    assert decision.violations[0].severity == "low"


# --- parse_plan_check_verdict ---


class TestParsePlanCheckVerdict:
    def test_aligned_true(self) -> None:
        v = parse_plan_check_verdict('{"aligned": true, "reason": "matches step 2"}')
        assert v == PlanCheckVerdict(aligned=True, reason="matches step 2")

    def test_aligned_false(self) -> None:
        v = parse_plan_check_verdict('{"aligned": false, "reason": "not in plan"}')
        assert v == PlanCheckVerdict(aligned=False, reason="not in plan")

    def test_code_fenced_json(self) -> None:
        v = parse_plan_check_verdict('```json\n{"aligned": true, "reason": "ok"}\n```')
        assert v is not None and v.aligned is True

    def test_missing_aligned_returns_none(self) -> None:
        assert parse_plan_check_verdict('{"reason": "no verdict"}') is None

    def test_string_aligned_returns_none(self) -> None:
        """A non-bool aligned ("true", 1) is a parse failure, not a verdict."""
        assert parse_plan_check_verdict('{"aligned": "true"}') is None
        assert parse_plan_check_verdict('{"aligned": 1}') is None

    def test_garbage_returns_none(self) -> None:
        assert parse_plan_check_verdict("not json at all") is None

    def test_empty_returns_none(self) -> None:
        assert parse_plan_check_verdict("") is None

    def test_missing_reason_defaults_empty(self) -> None:
        v = parse_plan_check_verdict('{"aligned": true}')
        assert v is not None and v.reason == ""

    def test_non_string_reason_coerced(self) -> None:
        v = parse_plan_check_verdict('{"aligned": false, "reason": 42}')
        assert v is not None and v.reason == "42"


# --- run_plan_check (mocked core.llm, tagger test pattern) ---


def _prompt_of(mock_complete: MagicMock) -> str:
    messages = mock_complete.call_args[0][0]
    return messages[0].content


class TestRunPlanCheck:
    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_success(self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock) -> None:
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text='{"aligned": true, "reason": "covered by step 1"}',
            usage={"prompt_tokens": 50, "completion_tokens": 10},
        )
        mock_adapter_cls.return_value = mock_adapter

        verdict = run_plan_check(_make_context(), model="gemini/gemini-3.5-flash", plan_text="# Plan\nStep 1.")

        assert verdict == PlanCheckVerdict(aligned=True, reason="covered by step 1")
        prompt = _prompt_of(mock_adapter.complete)
        assert "# Plan\nStep 1." in prompt
        assert "Write" in prompt
        assert "src/main.py" in prompt

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_parse_failure_returns_none(self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock) -> None:
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="I think it looks fine!")
        mock_adapter_cls.return_value = mock_adapter

        assert run_plan_check(_make_context(), model="test/model", plan_text="plan") is None

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_llm_error_returns_none(self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock) -> None:
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("LLM down")
        mock_adapter_cls.return_value = mock_adapter

        assert run_plan_check(_make_context(), model="test/model", plan_text="plan") is None

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_truncates_with_head_tail_and_metadata(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": true}')
        mock_adapter_cls.return_value = mock_adapter

        plan = "PLAN_HEAD\n" + ("p" * 8000) + "\nPLAN_TAIL"
        content = "CONTENT_HEAD\n" + ("x" * 8000) + "\nCONTENT_TAIL"
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={},
            repo_root="/workspace",
            session_name="test-session",
            target_path="src/main.py",
            new_content=content,
        )
        run_plan_check(ctx, model="test/model", plan_text=plan, budget_tokens=1_000)

        prompt = _prompt_of(mock_adapter.complete)
        assert "PLAN_HEAD" in prompt
        assert "PLAN_TAIL" in prompt
        assert "CONTENT_HEAD" in prompt
        assert "CONTENT_TAIL" in prompt
        assert "- truncated: true" in prompt
        assert "omitted" in prompt
        assert len(prompt) <= 1_000 * 4

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_diff_hunk_headers_survive_truncation(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": true}')
        mock_adapter_cls.return_value = mock_adapter

        diff = (
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -120,6 +120,9 @@ def important():\n" + ("+ filler\n" * 3000)
        )
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Edit",
            tool_name="Edit",
            tool_args={"file_path": "src/main.py", "old_string": "old", "new_string": "new"},
            repo_root="/workspace",
            session_name="test-session",
            target_path="src/main.py",
            new_content="new",
            raw_diff=diff,
        )
        run_plan_check(ctx, model="test/model", plan_text="plan", budget_tokens=1_000)

        prompt = _prompt_of(mock_adapter.complete)
        assert "Hunk/file headers preserved" in prompt
        assert "@@ -120,6 +120,9 @@ def important():" in prompt

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_edit_prompt_includes_old_and_new_fragments(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": true}')
        mock_adapter_cls.return_value = mock_adapter

        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Edit",
            tool_name="Edit",
            tool_args={"file_path": "src/main.py", "old_string": "old_call()", "new_string": "new_call()"},
            repo_root="/workspace",
            session_name="test-session",
            target_path="src/main.py",
            new_content="new_call()",
        )
        run_plan_check(ctx, model="test/model", plan_text="plan")

        prompt = _prompt_of(mock_adapter.complete)
        assert "Matched/replaced fragment (old_string)" in prompt
        assert "old_call()" in prompt
        assert "Replacement fragment (new_string)" in prompt
        assert "new_call()" in prompt

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_write_prompt_includes_target_existence_context(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock, tmp_path: Path
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": true}')
        mock_adapter_cls.return_value = mock_adapter

        target = tmp_path / "src" / "main.py"
        target.parent.mkdir()
        target.write_text("old")
        ctx = ActionContext(
            origin="claude_code",
            event="PreToolUse.Write",
            tool_name="Write",
            tool_args={"file_path": str(target), "content": "new"},
            repo_root=str(tmp_path),
            session_name="test-session",
            target_path=str(target),
            new_content="new",
        )
        run_plan_check(ctx, model="test/model", plan_text="plan")

        prompt = _prompt_of(mock_adapter.complete)
        assert str(target) in prompt
        assert "- target_exists: true" in prompt
        assert "- existing_size_bytes: 3" in prompt
        assert "- write_mode: overwrite_existing_file" in prompt

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_default_route_uses_openrouter_gemini_35(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": true}')
        mock_adapter_cls.return_value = mock_adapter

        policy = PlanCheckPolicy(config=_make_config(plan_override_path=None))
        route = resolve_plan_check_route(policy._config)
        assert route.model == DEFAULT_PLAN_CHECK_MODEL
        assert route.provider == "openrouter"
        assert DEFAULT_PLAN_CHECK_BUDGET_TOKENS == 32_000

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_emits_session_tagged_usage_event(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock, monkeypatch
    ) -> None:
        """A plan check emits a session-tagged plan-check event with exact tokens."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_pc")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_pc")
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text='{"aligned": true}', usage={"prompt_tokens": 9, "completion_tokens": 4}
        )
        mock_adapter_cls.return_value = mock_adapter

        run_plan_check(_make_context(), model="gemini/gemini-3.5-flash", plan_text="plan")

        from forge.core.usage.ledger import read_usage_events

        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert (e.command, e.session, e.provider) == ("plan-check", "test-session", "gemini")
        assert e.status == "success"
        assert e.measurement_source == "provider_usage_exact"
        assert (e.input_tokens, e.output_tokens) == (9, 4)

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_parse_failure_emits_error_event(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock, monkeypatch
    ) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_pc")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_pc")
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="garbage")
        mock_adapter_cls.return_value = mock_adapter

        run_plan_check(_make_context(), model="test/model", plan_text="plan")

        from forge.core.usage.ledger import read_usage_events

        e = read_usage_events()[0]
        assert (e.command, e.status, e.failure_type) == ("plan-check", "error", "parse_error")

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_exception_emits_error_event(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock, monkeypatch
    ) -> None:
        monkeypatch.setenv("FORGE_RUN_ID", "run_pc")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_pc")
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("boom")
        mock_adapter_cls.return_value = mock_adapter

        run_plan_check(_make_context(), model="test/model", plan_text="plan")

        from forge.core.usage.ledger import read_usage_events

        e = read_usage_events()[0]
        assert (e.command, e.status, e.failure_type) == ("plan-check", "error", "exception")
        assert e.session == "test-session"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_proxy_target_forwards_request_id(
        self, mock_adapter_cls: MagicMock, mock_get_client: MagicMock, monkeypatch
    ) -> None:
        """When the resolved target IS a Forge proxy, forward X-Request-ID and join."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_pc")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_pc")
        monkeypatch.setattr("forge.core.usage.resolve_client_base_url", lambda _m: "http://localhost:8084")
        monkeypatch.setattr("forge.core.usage.target_is_forge_proxy", lambda _u: True)
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text='{"aligned": true}', usage={"prompt_tokens": 1, "completion_tokens": 1}
        )
        mock_adapter_cls.return_value = mock_adapter

        run_plan_check(_make_context(), model="gemini/gemini-3.5-flash", plan_text="plan")

        forwarded = mock_adapter.complete.call_args.kwargs["hyperparams"].extra["openai"]["extra_headers"][
            "X-Request-ID"
        ]
        assert forwarded.startswith("req_")

        from forge.core.usage.ledger import read_usage_events

        e = read_usage_events()[0]
        assert e.source_refs is not None
        assert e.source_refs.cost_request_id == forwarded


# --- applies_to ---


class TestPlanCheckAppliesTo:
    def test_write_with_cascade(self) -> None:
        policy = PlanCheckPolicy(config=_make_config())
        assert policy.applies_to(_make_context("Write")) is True

    def test_edit_with_cascade(self) -> None:
        policy = PlanCheckPolicy(config=_make_config())
        assert policy.applies_to(_make_context("Edit")) is True

    def test_read_tool_excluded(self) -> None:
        policy = PlanCheckPolicy(config=_make_config())
        assert policy.applies_to(_make_context("Read")) is False

    def test_cascade_off(self) -> None:
        policy = PlanCheckPolicy(config=_make_config(cascade=False))
        assert policy.applies_to(_make_context("Write")) is False

    def test_no_resume_id(self) -> None:
        policy = PlanCheckPolicy(config=_make_config(resume_id=None))
        assert policy.applies_to(_make_context("Write")) is False

    def test_suspended(self) -> None:
        policy = PlanCheckPolicy(config=_make_config(suspended=True))
        assert policy.applies_to(_make_context("Write")) is False

    def test_no_config(self) -> None:
        policy = PlanCheckPolicy(config=None)
        assert policy.applies_to(_make_context("Write")) is False


# --- _evaluate verdict mapping ---


class TestPlanCheckEvaluate:
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_aligned_allows_cleanly(self, mock_check: MagicMock, tmp_path: Path) -> None:
        mock_check.return_value = PlanCheckVerdict(aligned=True, reason="ok")
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path))

        decision = policy.evaluate(_make_context())
        assert decision.decision == "allow"
        assert decision.warnings == []
        assert decision.violations == []

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_not_aligned_escalates_with_reason(self, mock_check: MagicMock, tmp_path: Path) -> None:
        mock_check.return_value = PlanCheckVerdict(aligned=False, reason="touches files outside the plan")
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path))

        decision = policy.evaluate(_make_context())
        _assert_escalation(decision, "semantic.plan_check.uncertain")
        assert decision.violations[0].message == "touches files outside the plan"

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_not_aligned_empty_reason_gets_default(self, mock_check: MagicMock, tmp_path: Path) -> None:
        mock_check.return_value = PlanCheckVerdict(aligned=False, reason="")
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path))

        decision = policy.evaluate(_make_context())
        _assert_escalation(decision, "semantic.plan_check.uncertain")
        assert decision.violations[0].message

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_checker_failure_escalates(self, mock_check: MagicMock, tmp_path: Path) -> None:
        """run_plan_check returning None (LLM/parse error) escalates, never allows."""
        mock_check.return_value = None
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path))

        decision = policy.evaluate(_make_context())
        _assert_escalation(decision, "semantic.plan_check.error")

    def test_plan_path_unset_escalates(self) -> None:
        policy = PlanCheckPolicy(config=_make_config(plan_override_path=None))
        decision = policy.evaluate(_make_context())
        _assert_escalation(decision, "semantic.plan_check.no_plan")

    def test_plan_file_missing_escalates(self, tmp_path: Path) -> None:
        policy = PlanCheckPolicy(config=_make_config(plan_override_path=str(tmp_path / "gone.md")))
        decision = policy.evaluate(_make_context())
        _assert_escalation(decision, "semantic.plan_check.no_plan")

    def test_plan_file_empty_escalates(self, tmp_path: Path) -> None:
        plan = tmp_path / "empty.md"
        plan.write_text("")
        policy = PlanCheckPolicy(config=_make_config(plan_override_path=str(plan)))
        decision = policy.evaluate(_make_context())
        _assert_escalation(decision, "semantic.plan_check.no_plan")

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_reason_clamped(self, mock_check: MagicMock, tmp_path: Path) -> None:
        """Verbose model reasons are clamped before persisting into the decision log."""
        mock_check.return_value = PlanCheckVerdict(aligned=False, reason="r" * 5000)
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path))

        decision = policy.evaluate(_make_context())
        assert len(decision.violations[0].message) == _MAX_REASON_CHARS

    @patch("forge.policy.semantic.plan_check.load_plan_override")
    def test_unexpected_exception_escalates(self, mock_load: MagicMock, tmp_path: Path) -> None:
        """An unexpected raise must become needs_review, not propagate to fail-open."""
        mock_load.side_effect = RuntimeError("disk on fire")
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path))

        decision = policy.evaluate(_make_context())
        _assert_escalation(decision, "semantic.plan_check.error")

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_never_denies_or_warns(self, mock_check: MagicMock, tmp_path: Path) -> None:
        """Across all verdict shapes, tier-1 emits only allow or needs_review."""
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path))
        for verdict in (PlanCheckVerdict(True, "x"), PlanCheckVerdict(False, "y"), None):
            mock_check.return_value = verdict
            decision = policy.evaluate(_make_context())
            assert decision.decision in ("allow", "needs_review")
            assert decision.warnings == []

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_provider_default_and_budget_passed_to_checker(self, mock_check: MagicMock, tmp_path: Path) -> None:
        mock_check.return_value = PlanCheckVerdict(aligned=True)
        policy = PlanCheckPolicy(
            config=_config_with_plan(tmp_path, checker_provider="litellm_local", checker_budget_tokens=64_000)
        )

        decision = policy.evaluate(_make_context())

        assert decision.decision == "allow"
        assert mock_check.call_args.kwargs["model"] == "gemini/gemini-3.5-flash"
        assert mock_check.call_args.kwargs["provider"] == "litellm_local"
        assert mock_check.call_args.kwargs["budget_tokens"] == 64_000


# --- Cache behavior ---


class TestPlanCheckCache:
    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_clean_allow_cached(self, mock_check: MagicMock, tmp_path: Path) -> None:
        mock_check.return_value = PlanCheckVerdict(aligned=True)
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path, throttle_seconds=60))

        policy.evaluate(_make_context())
        assert mock_check.call_count == 1

        result = policy.evaluate(_make_context())
        assert mock_check.call_count == 1
        assert result.cached is True
        assert result.decision == "allow"

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_needs_review_not_cached(self, mock_check: MagicMock, tmp_path: Path) -> None:
        mock_check.return_value = PlanCheckVerdict(aligned=False, reason="unsure")
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path, throttle_seconds=60))

        policy.evaluate(_make_context())
        policy.evaluate(_make_context())
        assert mock_check.call_count == 2

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_plan_change_invalidates_cache(self, mock_check: MagicMock, tmp_path: Path) -> None:
        """Rewriting the plan file changes the fingerprint, so the cached allow misses."""
        mock_check.return_value = PlanCheckVerdict(aligned=True)
        config = _config_with_plan(tmp_path, throttle_seconds=60)
        policy = PlanCheckPolicy(config=config)

        policy.evaluate(_make_context())
        assert mock_check.call_count == 1

        Path(str(config.plan_override_path)).write_text("# Plan v2\nDo something rather different.")
        policy.evaluate(_make_context())
        assert mock_check.call_count == 2

    @patch("forge.policy.semantic.plan_check.run_plan_check")
    def test_cache_expires_after_throttle(self, mock_check: MagicMock, tmp_path: Path) -> None:
        mock_check.return_value = PlanCheckVerdict(aligned=True)
        policy = PlanCheckPolicy(config=_config_with_plan(tmp_path, throttle_seconds=0))

        policy.evaluate(_make_context())
        policy.evaluate(_make_context())
        assert mock_check.call_count == 2

    def test_state_round_trip(self) -> None:
        from forge.core.state import now_iso

        policy = PlanCheckPolicy(config=_make_config())
        policy._cache.update("key1", aligned=True)
        state = policy.get_state()
        assert "key1" in state["cache"]

        restored = PlanCheckPolicy(config=_make_config())
        restored.set_state(state)
        assert restored._cache.check("key1") is not None

        restored.set_state({"cache": {"key2": {"aligned": True, "checked_at": now_iso()}}})
        assert restored._cache.check("key1") is None
        assert restored._cache.check("key2") is not None
