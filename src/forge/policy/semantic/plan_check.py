"""Cheap tier-1 plan-alignment check (the supervisor cascade's first tier).

A stateless ``core.llm`` call evaluates an action against the approved-plan
snapshot text. Clearly aligned actions short-circuit (allow); anything
uncertain -- including every checker failure -- escalates as ``needs_review``
for the frontier supervisor (the engine's registered resolver) to decide.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from forge.core.reactive.structured_output import extract_json_from_response
from forge.core.reactive.throttle import ThrottleCache, compute_cache_key
from forge.policy.deterministic.base import StatefulDeterministicPolicy
from forge.policy.semantic.supervisor import load_plan_override, plan_fingerprint
from forge.policy.types import ActionContext, PolicyDecision, Violation
from forge.session.models import SupervisorConfig

_log = logging.getLogger(__name__)

# gemini/* routes to the litellm_local provider, so the default must be a model the
# local LiteLLM backend serves (src/forge/config/defaults/backends/litellm.yaml).
DEFAULT_PLAN_CHECK_MODEL = "gemini/gemini-2.5-flash"

PLAN_CHECK_INTENT = (
    "Fast first-pass alignment check against the approved plan. Clearly aligned "
    "actions proceed immediately; anything uncertain escalates to the frontier "
    "supervisor for a full review."
)

_MAX_CONTENT_CHARS = 2000  # supervisor/tagger parity
_MAX_PLAN_CHARS = 16000
# Reasons persist into the manifest decision log (MAX_DECISION_LOG entries), so an
# unbounded model response must not bloat confirmed.policy.decisions.
_MAX_REASON_CHARS = 500

PLAN_CHECK_PROMPT = """You are a fast plan-alignment pre-checker. A thorough supervisor \
will review anything you are not sure about, so never guess "aligned".

## Approved Plan
{plan_text}

## Action Being Evaluated
Tool: {tool_name}
Target: {target_path}
Content/Diff (truncated):
```
{content}
```

## Rules
- "aligned": true ONLY if this action is clearly consistent with the approved plan.
- If uncertain, only partially covered by the plan, or potentially divergent: "aligned": false.
- You cannot block anything; "aligned": false only requests a deeper review.

## Response Format (strict JSON in a code fence)
```json
{{"aligned": true, "reason": "one sentence"}}
```
"""


@dataclass
class PlanCheckVerdict:
    """Parsed tier-1 verdict: a binary routing choice plus a short rationale."""

    aligned: bool
    reason: str = ""


def parse_plan_check_verdict(response: str) -> PlanCheckVerdict | None:
    """Parse the checker's JSON verdict. None on any parse failure (caller escalates)."""
    data = extract_json_from_response(response)
    if not isinstance(data, dict):
        return None
    aligned = data.get("aligned")
    if not isinstance(aligned, bool):
        return None
    reason = data.get("reason")
    return PlanCheckVerdict(aligned=aligned, reason=str(reason) if reason is not None else "")


def run_plan_check(context: ActionContext, *, model: str, plan_text: str) -> PlanCheckVerdict | None:
    """One cheap ``core.llm`` call: is this action clearly aligned with the plan?

    Mirrors ``tag_action``'s call mechanics (client, X-Request-ID forwarding,
    usage emission). Returns None on ANY error -- the caller maps None to
    ``needs_review``, so a checker failure escalates instead of blocking.

    Must NOT be called from inside an event loop (SyncAdapter constraint).
    """
    try:
        from forge.core.llm import Message, SyncAdapter, get_client
        from forge.core.usage import (
            emit_direct_llm_usage,
            mint_request_id,
            resolve_client_base_url,
            target_is_forge_proxy,
            with_forge_request_id,
        )

        prompt = PLAN_CHECK_PROMPT.format(
            plan_text=plan_text[:_MAX_PLAN_CHARS],
            tool_name=context.tool_name,
            target_path=context.target_path or "N/A",
            content=(context.raw_diff or context.new_content or "")[:_MAX_CONTENT_CHARS],
        )

        client = get_client(model)
        adapter = SyncAdapter(client)

        # Same exact-cost join as the tagger: forward an X-Request-ID only when the
        # client provably targets a Forge proxy (a dangling ref is worse than none).
        request_id = mint_request_id() if target_is_forge_proxy(resolve_client_base_url(model)) else None
        hp = with_forge_request_id(None, request_id) if request_id else None

        start = time.monotonic()
        response = adapter.complete([Message(role="user", content=prompt)], hyperparams=hp)
        latency_ms = (time.monotonic() - start) * 1000

        verdict = parse_plan_check_verdict(response.text)

        # Session-tagged (unlike the tagger) so `forge activity` shows a plan-check row.
        emit_direct_llm_usage(
            command="plan-check",
            model=model,
            provider=model.split("/", 1)[0] if "/" in model else None,
            usage=response.usage,
            status="success" if verdict is not None else "error",
            failure_type=None if verdict is not None else "parse_error",
            cost_request_id=request_id,
            latency_ms=latency_ms,
            session=context.session_name,
        )

        return verdict

    except Exception as e:
        _log.warning("run_plan_check failed (model=%s): %s", model, e)
        from forge.core.usage import emit_direct_llm_usage

        emit_direct_llm_usage(
            command="plan-check",
            model=model,
            provider=model.split("/", 1)[0] if "/" in model else None,
            status="error",
            failure_type="exception",
            session=context.session_name,
        )
        return None


class PlanCheckPolicy(StatefulDeterministicPolicy):
    """Tier-1 cascade policy: cheap plan-alignment pre-check.

    Emits only ``allow`` or ``needs_review`` -- never deny/warn, and never
    ``decision.warnings``: the hook prints composite all_warnings on the allow
    path, so a warning here would surface tier-1 noise on every successfully
    resolved escalation. Reasons ride in low-severity violations instead (they
    persist into the decision log without printing on resolved allows).

    State tracked:
    - cache: ThrottleCache entries for clean allows only
    """

    def __init__(self, config: SupervisorConfig | None = None) -> None:
        self._config = config
        ttl = config.throttle_seconds if config else 30
        self._cache = ThrottleCache(ttl_seconds=ttl)

    @property
    def policy_id(self) -> str:
        return "semantic.plan_check"

    @property
    def description(self) -> str:
        return "Cheap tier-1 plan-alignment check (escalates uncertainty to the supervisor)"

    @property
    def intent(self) -> str:
        return PLAN_CHECK_INTENT

    def applies_to(self, context: ActionContext) -> bool:
        """Apply to Write/Edit when the cascade is enabled and not suspended."""
        if context.tool_name not in ("Write", "Edit"):
            return False
        if self._config is None or self._config.resume_id is None:
            return False
        if not self._config.cascade:
            return False
        return not self._config.suspended

    def _evaluate(self, context: ActionContext) -> PolicyDecision:
        try:
            return self._check(context)
        except Exception as e:
            # A raise would hit the engine's fail-open and wrongly become allow;
            # tier-1 failures must escalate to the supervisor instead.
            _log.warning("Plan check failed unexpectedly: %s", e)
            return self._needs_review("semantic.plan_check.error", f"Plan check failed: {e}")

    def _check(self, context: ActionContext) -> PolicyDecision:
        config = self._config
        if config is None or not config.resume_id or config.suspended or not config.cascade:
            # Unreachable when wiring is correct: applies_to gates the same fields.
            return self._allow()

        plan_text = load_plan_override(config)
        if plan_text is None:
            _log.warning(
                "Plan check: plan text unavailable (path=%s); escalating to supervisor",
                config.plan_override_path,
            )
            return self._needs_review(
                "semantic.plan_check.no_plan",
                "Approved plan snapshot unavailable; escalating to supervisor",
            )

        cache_key = compute_cache_key(context.tool_name, context.target_path, context.new_content)
        # plan_override_path is non-None here (load_plan_override returned content)
        cache_key = cache_key + "|plan:" + plan_fingerprint(str(config.plan_override_path), config.forge_root)

        cached = self._cache.check(cache_key)
        if cached is not None:
            _log.debug("Using cached plan-check verdict for %s", cache_key)
            decision = self._allow()  # only clean allows are ever cached
            decision.cached = True
            return decision

        model = config.checker_model or DEFAULT_PLAN_CHECK_MODEL
        verdict = run_plan_check(context, model=model, plan_text=plan_text)

        if verdict is None:
            return self._needs_review(
                "semantic.plan_check.error",
                "Plan check produced no verdict; escalating to supervisor",
            )

        if verdict.aligned:
            _log.debug("Plan check aligned: %s", verdict.reason)
            self._cache.update(cache_key, aligned=True)
            return self._allow()

        return self._needs_review(
            "semantic.plan_check.uncertain",
            verdict.reason or "Plan check could not confirm alignment",
        )

    def _needs_review(self, rule_id: str, message: str) -> PolicyDecision:
        """Escalation decision: reason as a low-severity violation, never a warning."""
        return PolicyDecision(
            decision="needs_review",
            policy_id=self.policy_id,
            violations=[
                Violation(
                    rule_id=rule_id,
                    message=message[:_MAX_REASON_CHARS],
                    severity="low",
                )
            ],
        )

    def get_state(self) -> dict[str, Any]:
        """Return cache state for persistence."""
        return {"cache": self._cache.get_state()}

    def set_state(self, state: dict[str, Any]) -> None:
        """Restore cache state from persistence."""
        self._cache.set_state(state.get("cache", {}))
