"""Tests for supervisor shadow sampling -- drain side (Slice 2).

Covers:
- classify_shadow(): the four statuses, with parse-failure distinguished from a real
  low-confidence inconclusive (Finding 3)
- reconstruct_context()/reconstruct_config(): a captured candidate rebuilds the SAME
  frontier SUPERVISOR_PROMPT it would have produced at hook time (capture/check split)
- run_shadow_candidate(): atomic-claim at-most-once, status persisted, never enforces,
  single supervisor-shadow ledger emission
- run_shadow_for_session(): drains pending candidates; idempotent re-drain is a no-op
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from forge.core.reactive.session_runner import SessionResult
from forge.core.telemetry.upstream import read_upstream_outcomes
from forge.policy.semantic.shadow import capture_candidate
from forge.policy.semantic.shadow_runner import (
    STATUS_AGREE,
    STATUS_DISAGREE,
    STATUS_ERROR,
    STATUS_INCONCLUSIVE,
    classify_shadow,
    reconstruct_config,
    reconstruct_context,
    run_shadow_candidate,
    run_shadow_for_session,
)
from forge.policy.semantic.supervisor import (
    _PLAN_OVERRIDE_PREAMBLE,
    SUPERVISOR_PROMPT,
    SupervisorRun,
    load_plan_override,
)
from forge.policy.semantic.verdict import SupervisorVerdict, verdict_to_decision
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.models import SupervisorConfig

ALIGNED_JSON = '```json\n{"verdict": "aligned", "confidence": 0.95, "violations": []}\n```'
DIVERGENT_BLOCKING_JSON = (
    '```json\n{"verdict": "divergent", "confidence": 0.9, "violations": ['
    '{"severity": "high", "evidence": "ignored the plan", "citations": ["Step 2"]}]}\n```'
)


# --- Fixtures ---


def _ctx(**kw: object) -> ActionContext:
    return ActionContext(
        origin="claude_code",
        event="PreToolUse.Write",
        tool_name=str(kw.get("tool_name", "Write")),
        tool_args=dict(kw.get("tool_args", {"file_path": "f.py"})),  # type: ignore[call-overload]
        repo_root="/repo",
        session_name="sess",
        target_path=str(kw.get("target_path", "f.py")),
        new_content=kw.get("new_content", "print('hi')"),  # type: ignore[arg-type]
        raw_diff=kw.get("raw_diff"),  # type: ignore[arg-type]
    )


def _cfg(tmp_path: Path, **kw: object) -> SupervisorConfig:
    plan = tmp_path / "plan.md"
    if not plan.exists():
        plan.write_text("# Plan\nStep 1: do the thing.\nStep 2: do the other thing.")
    defaults: dict[str, object] = {
        "resume_id": "rid",
        "forge_root": str(tmp_path),
        "plan_override_path": str(plan),
        "cascade": True,
        "direct": True,  # skip proxy routing in the frontier path (hermetic)
        "shadow_sample_rate": 1.0,
    }
    defaults.update(kw)
    return SupervisorConfig(**defaults)  # type: ignore[arg-type]


def _capture(ctx: ActionContext, cfg: SupervisorConfig, cache_key: str = "ck1") -> Path:
    out = capture_candidate(
        cfg,
        ctx,
        cache_key=cache_key,
        tier1_reason="looks aligned",
        checker_model="google/gemini-3.5-flash",
        checker_provider="openrouter",
        checker_budget_tokens=32000,
        checker_prompt_version=1,
    )
    assert out is not None
    return out


def _frontier_prompt(config: SupervisorConfig, context: ActionContext) -> str:
    """Replicate run_supervisor_check's prompt assembly (the fidelity reference)."""
    prompt = SUPERVISOR_PROMPT.format(
        tool_name=context.tool_name,
        target_path=context.target_path or "N/A",
        content=(context.raw_diff or context.new_content or "")[:2000],
    )
    plan_content = load_plan_override(config)
    if plan_content:
        prompt = _PLAN_OVERRIDE_PREAMBLE.format(plan_content=plan_content) + "\n\n" + prompt
    return prompt


def _run(verdict: SupervisorVerdict | None, *, run_ok: bool, parsed: bool) -> SupervisorRun:
    decision = (
        verdict_to_decision(verdict)
        if verdict is not None
        else PolicyDecision(decision="allow", policy_id="semantic.supervisor")
    )
    return SupervisorRun(decision=decision, verdict=verdict, run_ok=run_ok, parsed=parsed)


# --- classify_shadow ---


class TestClassifyShadow:
    def test_aligned_is_agree(self) -> None:
        run = _run(SupervisorVerdict(verdict="aligned", confidence=0.95), run_ok=True, parsed=True)
        assert classify_shadow(run) == STATUS_AGREE

    def test_high_confidence_cited_divergence_is_disagree(self) -> None:
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.9,
            violations=[{"severity": "high", "evidence": "x", "citations": ["Step 2"]}],
        )
        run = _run(verdict, run_ok=True, parsed=True)
        assert run.decision.decision == "deny"  # the supervisor's own block bar
        assert classify_shadow(run) == STATUS_DISAGREE

    def test_low_confidence_divergence_is_inconclusive(self) -> None:
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.4,
            violations=[{"severity": "low", "evidence": "maybe", "citations": ["Step 2"]}],
        )
        run = _run(verdict, run_ok=True, parsed=True)
        assert run.decision.decision == "warn"
        assert classify_shadow(run) == STATUS_INCONCLUSIVE

    def test_uncited_divergence_is_inconclusive(self) -> None:
        verdict = SupervisorVerdict(
            verdict="divergent",
            confidence=0.99,
            violations=[{"severity": "high", "evidence": "no cite", "citations": []}],
        )
        run = _run(verdict, run_ok=True, parsed=True)
        assert classify_shadow(run) == STATUS_INCONCLUSIVE

    def test_run_failed_is_error(self) -> None:
        run = _run(None, run_ok=False, parsed=False)
        assert classify_shadow(run) == STATUS_ERROR

    def test_parse_failure_is_error_not_inconclusive(self) -> None:
        """Finding 3: an unparseable frontier response collapses to divergent+0.0 warn,
        but parsed=False must classify as error -- NOT a real low-confidence inconclusive."""
        fallback = SupervisorVerdict(verdict="divergent", confidence=0.0, violations=[{"citations": []}])
        run = _run(fallback, run_ok=True, parsed=False)
        # The bare verdict would look inconclusive; the parsed flag rescues the distinction.
        assert run.decision.decision == "warn"
        assert classify_shadow(run) == STATUS_ERROR


# --- reconstruction fidelity ---


class TestReconstruction:
    def test_context_round_trips_raw_fields(self, tmp_path: Path) -> None:
        ctx = _ctx(new_content="body", raw_diff="@@ -1 +1 @@", tool_args={"file_path": "f.py", "k": 2})
        path = _capture(ctx, _cfg(tmp_path))
        candidate = json.loads(path.read_text())
        rebuilt = reconstruct_context(candidate)
        assert rebuilt.tool_name == ctx.tool_name
        assert rebuilt.target_path == ctx.target_path
        assert rebuilt.new_content == ctx.new_content
        assert rebuilt.raw_diff == ctx.raw_diff
        assert rebuilt.tool_args == ctx.tool_args
        assert rebuilt.session_name == ctx.session_name

    def test_config_points_plan_at_frozen_sidecar(self, tmp_path: Path) -> None:
        path = _capture(_ctx(), _cfg(tmp_path))
        candidate = json.loads(path.read_text())
        rebuilt = reconstruct_config(candidate, path.parent)
        # Not the live plan -- the frozen copy beside the candidate.
        assert rebuilt.plan_override_path is not None
        assert rebuilt.plan_override_path == str(path.parent / candidate["plan_snapshot_file"])
        assert Path(rebuilt.plan_override_path).is_file()

    def test_rebuilds_identical_supervisor_prompt(self, tmp_path: Path) -> None:
        ctx = _ctx(raw_diff="@@ -1 +2 @@\n+changed", new_content="ignored when raw_diff present")
        cfg = _cfg(tmp_path)
        expected = _frontier_prompt(cfg, ctx)

        path = _capture(ctx, cfg)
        candidate = json.loads(path.read_text())
        rebuilt_ctx = reconstruct_context(candidate)
        rebuilt_cfg = reconstruct_config(candidate, path.parent)
        assert _frontier_prompt(rebuilt_cfg, rebuilt_ctx) == expected

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_drain_feeds_frontier_the_expected_prompt(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Stronger than the rebuild check: drive the REAL run_supervisor_check and assert the
        prompt it actually hands run_claude_session matches the reference -- so a drift in
        production prompt assembly (not just the test helper) fails here."""
        mock_run.return_value = SessionResult(stdout=ALIGNED_JSON, stderr="", returncode=0)
        ctx = _ctx(raw_diff="@@ -1 +2 @@\n+changed")
        cfg = _cfg(tmp_path)
        expected = _frontier_prompt(cfg, ctx)

        run_shadow_candidate(_capture(ctx, cfg))

        mock_run.assert_called_once()
        actual = mock_run.call_args.args[0] if mock_run.call_args.args else mock_run.call_args.kwargs["prompt"]
        assert actual == expected


# --- run_shadow_candidate (frontier mocked) ---


class TestRunShadowCandidate:
    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_aligned_finalizes_as_done_agree(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = SessionResult(stdout=ALIGNED_JSON, stderr="", returncode=0)
        path = _capture(_ctx(), _cfg(tmp_path))

        status = run_shadow_candidate(path)

        assert status == STATUS_AGREE
        assert not path.exists()  # claimed + finalized
        done = path.with_suffix(".done")
        assert done.is_file()
        record = json.loads(done.read_text())
        assert record["status"] == STATUS_AGREE
        assert record["frontier_verdict"] == "aligned"
        assert record["run_ok"] is True and record["parsed"] is True

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_divergent_blocking_finalizes_as_disagree(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = SessionResult(stdout=DIVERGENT_BLOCKING_JSON, stderr="", returncode=0)
        path = _capture(_ctx(), _cfg(tmp_path))

        status = run_shadow_candidate(path)

        assert status == STATUS_DISAGREE
        record = json.loads(path.with_suffix(".done").read_text())
        assert record["status"] == STATUS_DISAGREE
        assert record["frontier_verdict"] == "divergent"
        outcomes = read_upstream_outcomes(session="sess", command="supervisor-shadow")
        assert len(outcomes) == 1
        assert outcomes[0].operation == "policy.shadow_drain"
        assert outcomes[0].status == "deny"
        assert outcomes[0].reason_code == STATUS_DISAGREE

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_unparseable_frontier_is_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = SessionResult(stdout="not json at all", stderr="", returncode=0)
        path = _capture(_ctx(), _cfg(tmp_path))

        status = run_shadow_candidate(path)

        assert status == STATUS_ERROR
        record = json.loads(path.with_suffix(".done").read_text())
        assert record["status"] == STATUS_ERROR
        assert record["parsed"] is False
        outcomes = read_upstream_outcomes(session="sess", command="supervisor-shadow")
        assert len(outcomes) == 1
        assert outcomes[0].status == "error"
        assert outcomes[0].reason_code == STATUS_ERROR

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_at_most_once_atomic_claim(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """A re-spawned worker that lost the claim race makes no second frontier call."""
        mock_run.return_value = SessionResult(stdout=ALIGNED_JSON, stderr="", returncode=0)
        path = _capture(_ctx(), _cfg(tmp_path))

        first = run_shadow_candidate(path)
        second = run_shadow_candidate(path)  # the .json is gone -> claim fails

        assert first == STATUS_AGREE
        assert second is None
        mock_run.assert_called_once()

    @patch("forge.core.usage.emit_usage_for_session_result")
    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_single_supervisor_shadow_ledger_row(
        self, mock_run: MagicMock, mock_emit: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = SessionResult(stdout=ALIGNED_JSON, stderr="", returncode=0)
        path = _capture(_ctx(), _cfg(tmp_path))

        run_shadow_candidate(path)

        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["command"] == "supervisor-shadow"

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_never_enforces(self, mock_run: MagicMock, tmp_path: Path) -> None:
        """Even a blocking verdict only records -- the drain returns a status, never raises/blocks."""
        mock_run.return_value = SessionResult(stdout=DIVERGENT_BLOCKING_JSON, stderr="", returncode=0)
        path = _capture(_ctx(), _cfg(tmp_path))
        # No exception, and the candidate is finalized rather than left blocking anything.
        assert run_shadow_candidate(path) == STATUS_DISAGREE


# --- run_shadow_for_session ---


class TestRunShadowForSession:
    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert run_shadow_for_session("sess", str(tmp_path)) == {}

    @patch("forge.policy.semantic.supervisor.run_claude_session")
    def test_drains_all_then_idempotent_redrain(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = SessionResult(stdout=ALIGNED_JSON, stderr="", returncode=0)
        cfg = _cfg(tmp_path)
        for i in range(3):
            _capture(_ctx(new_content=f"v{i}"), cfg, cache_key=f"ck{i}")

        counts = run_shadow_for_session("sess", str(tmp_path))
        assert counts == {STATUS_AGREE: 3}
        assert mock_run.call_count == 3

        # Re-drain: every candidate is now .done, no pending *.json remains.
        again = run_shadow_for_session("sess", str(tmp_path))
        assert again == {}
        assert mock_run.call_count == 3  # no extra frontier calls


# --- deterministic post-claim failures finalize as .done error (no orphaned .processing) ---


class TestPostClaimFailure:
    def _shadow_dir(self, tmp_path: Path, session: str = "sess") -> Path:
        d = tmp_path / ".forge" / "artifacts" / session / "shadow"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_unreadable_candidate_finalizes_as_error(self, tmp_path: Path) -> None:
        bad = self._shadow_dir(tmp_path) / "deadbeef.json"
        bad.write_text("{ not valid json")

        status = run_shadow_candidate(bad)

        assert status == STATUS_ERROR
        assert not bad.exists()
        assert not bad.with_suffix(".processing").exists()  # NOT orphaned
        done = bad.with_suffix(".done")
        assert done.is_file()
        assert json.loads(done.read_text())["status"] == STATUS_ERROR

    def test_reconstruction_failure_finalizes_as_error(self, tmp_path: Path) -> None:
        # Missing required fields (tool_name/session_name) makes reconstruct_context raise
        # KeyError; the claimed candidate must still be finalized, not stranded.
        cand = self._shadow_dir(tmp_path) / "abc123.json"
        cand.write_text(json.dumps({"schema_version": 1}))

        status = run_shadow_candidate(cand)

        assert status == STATUS_ERROR
        assert not cand.with_suffix(".processing").exists()
        record = json.loads(cand.with_suffix(".done").read_text())
        assert record["status"] == STATUS_ERROR

    def test_errored_candidate_not_phantom_pending(self, tmp_path: Path) -> None:
        """An errored candidate is .done (terminal), so a re-drain finds no pending *.json."""
        cand = self._shadow_dir(tmp_path) / "ee.json"
        cand.write_text("{bad")
        run_shadow_candidate(cand)
        # run_shadow_for_session only sweeps *.json; the errored one is .done, so nothing reruns.
        assert run_shadow_for_session("sess", str(tmp_path)) == {}
