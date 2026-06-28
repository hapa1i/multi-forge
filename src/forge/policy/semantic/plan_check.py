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
from pathlib import Path
from typing import Any, cast

from forge.core.llm.detection import ProviderType, detect_provider
from forge.core.reactive.structured_output import extract_json_from_response
from forge.core.reactive.throttle import ThrottleCache, compute_cache_key
from forge.policy.deterministic.base import StatefulDeterministicPolicy
from forge.policy.semantic.supervisor import (
    load_plan_override,
    normalize_checker_provider_arg,
    plan_fingerprint,
)
from forge.policy.types import ActionContext, PolicyDecision, Violation
from forge.session.models import LaneRecord, SupervisorConfig

_log = logging.getLogger(__name__)

DEFAULT_PLAN_CHECK_PROVIDER: ProviderType = "openrouter"
DEFAULT_PLAN_CHECK_MODELS_BY_PROVIDER: dict[ProviderType, str] = {
    "openrouter": "google/gemini-3.5-flash",
    "litellm_local": "gemini/gemini-3.5-flash",
    "litellm_remote": "gemini/gemini-3.5-flash",
}
DEFAULT_PLAN_CHECK_MODEL = DEFAULT_PLAN_CHECK_MODELS_BY_PROVIDER[DEFAULT_PLAN_CHECK_PROVIDER]
DEFAULT_PLAN_CHECK_BUDGET_TOKENS = 32_000

# Bumped whenever PLAN_CHECK_PROMPT changes. Shadow-sampling records carry this so a prompt edit does not silently
# blend pre- and post-change verdicts into one false-aligned estimate.
CHECKER_PROMPT_VERSION = 1

# Provider-agnostic budgeting: exact tokenizers differ across OpenRouter, Gemini,
# and LiteLLM-served models, so use a conservative chars/token approximation.
_APPROX_CHARS_PER_TOKEN = 4
_PROMPT_OVERHEAD_RESERVE_CHARS = 600
_PLAN_BUDGET_FRACTION = 0.70
_MIN_ACTION_CHARS = 4_000
_OPENROUTER_MODEL_PREFIXES = (
    "deepseek/",
    "google/",
    "minimax/",
    "moonshotai/",
    "openrouter/",
    "qwen/",
    "z-ai/",
)

PLAN_CHECK_INTENT = (
    "Fast first-pass alignment check against the approved plan. Clearly aligned "
    "actions proceed immediately; anything uncertain escalates to the frontier "
    "supervisor for a full review."
)

# Reasons persist into the manifest decision log (MAX_DECISION_LOG entries), so an
# unbounded model response must not bloat confirmed.policy.decisions.
_MAX_REASON_CHARS = 500

PLAN_CHECK_PROMPT = """You are a fast plan-alignment pre-checker. A thorough supervisor \
will review anything you are not sure about, so never guess "aligned".

## Approved Plan
Metadata:
{plan_metadata}

{plan_text}

## Action Being Evaluated
Tool: {tool_name}
Target: {target_path}
Metadata:
{action_metadata}

{action_text}

## Rules
- "aligned": true ONLY if this action is clearly consistent with the approved plan.
- If uncertain, only partially covered by the plan, or potentially divergent: "aligned": false.
- If the plan or action metadata says truncated=true, return "aligned": true only when the visible excerpts are still
  sufficient to prove alignment. Otherwise return "aligned": false.
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


@dataclass(frozen=True)
class _PlanCheckRoute:
    """Resolved checker route."""

    model: str
    provider: ProviderType | None


@dataclass(frozen=True)
class _PackedText:
    """A prompt section excerpt plus truncation metadata."""

    text: str
    original_chars: int
    included_chars: int
    truncated: bool
    strategy: str

    @property
    def metadata(self) -> str:
        return "\n".join(
            [
                f"- original_chars: {self.original_chars}",
                f"- included_chars: {self.included_chars}",
                f"- truncated: {str(self.truncated).lower()}",
                f"- selection_strategy: {self.strategy}",
            ]
        )


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


def _normalize_checker_provider(provider: str | None) -> ProviderType | None:
    """Normalize user-facing provider strings to core.llm provider names.

    Shares the dash->underscore transform with the launch/policy write path
    (``normalize_checker_provider_arg``); adds membership validation here.
    """
    normalized = normalize_checker_provider_arg(provider)
    if normalized is None:
        return None
    if normalized not in DEFAULT_PLAN_CHECK_MODELS_BY_PROVIDER:
        raise ValueError(
            f"Unsupported checker provider {provider!r}; expected one of "
            f"{', '.join(sorted(DEFAULT_PLAN_CHECK_MODELS_BY_PROVIDER))}"
        )
    return normalized  # type: ignore[return-value]


def resolve_plan_check_route(config: SupervisorConfig | None) -> _PlanCheckRoute:
    """Resolve the effective checker model/provider route."""
    provider = _normalize_checker_provider(config.checker_provider if config else None)
    model = config.checker_model if config else None

    if model is None:
        provider = provider or DEFAULT_PLAN_CHECK_PROVIDER
        return _PlanCheckRoute(
            model=DEFAULT_PLAN_CHECK_MODELS_BY_PROVIDER[provider],
            provider=provider,
        )

    if provider is not None:
        return _PlanCheckRoute(model=model, provider=provider)

    try:
        detect_provider(model)
    except ValueError:
        if model.lower().startswith(_OPENROUTER_MODEL_PREFIXES):
            return _PlanCheckRoute(model=model, provider="openrouter")
        raise

    return _PlanCheckRoute(model=model, provider=None)


def _budget_tokens(config: SupervisorConfig | None) -> int:
    value = config.checker_budget_tokens if config else None
    if value is None:
        return DEFAULT_PLAN_CHECK_BUDGET_TOKENS
    return max(1, int(value))


def _budget_chars(budget_tokens: int) -> int:
    return max(1, budget_tokens * _APPROX_CHARS_PER_TOKEN)


def _prompt_shell_chars(context: ActionContext) -> int:
    """Approximate non-plan/action prompt overhead for whole-prompt budgeting."""
    return len(
        PLAN_CHECK_PROMPT.format(
            plan_metadata="",
            plan_text="",
            tool_name=context.tool_name,
            target_path=context.target_path or "N/A",
            action_metadata="",
            action_text="",
        )
    )


def _head_tail_excerpt(text: str, budget_chars: int, *, preserve_hunk_headers: bool = False) -> _PackedText:
    """Return a head+tail excerpt, optionally pinning diff hunk headers."""
    original_chars = len(text)
    if original_chars <= budget_chars:
        return _PackedText(
            text=text,
            original_chars=original_chars,
            included_chars=original_chars,
            truncated=False,
            strategy="full",
        )

    hunk_headers = ""
    if preserve_hunk_headers:
        hunk_lines = [line for line in text.splitlines() if line.startswith(("diff --git ", "@@ ", "--- ", "+++ "))]
        if hunk_lines:
            header_budget = max(500, budget_chars // 4)
            hunk_headers = "\n".join(hunk_lines)
            if len(hunk_headers) > header_budget:
                hunk_headers = _head_tail_excerpt(hunk_headers, header_budget).text
            hunk_headers = "Hunk/file headers preserved from the full diff:\n" + hunk_headers + "\n\n"

    marker_template = "\n\n[... omitted {omitted_chars} chars from the middle ...]\n\n"
    available = max(1, budget_chars - len(hunk_headers) - len(marker_template.format(omitted_chars=0)))
    head_chars = max(1, available // 2)
    tail_chars = max(1, available - head_chars)
    omitted = max(0, original_chars - head_chars - tail_chars)
    marker = marker_template.format(omitted_chars=omitted)
    excerpt = hunk_headers + text[:head_chars] + marker + text[-tail_chars:]
    return _PackedText(
        text=excerpt,
        original_chars=original_chars,
        included_chars=len(excerpt),
        truncated=True,
        strategy="head+tail" + ("+hunk_headers" if hunk_headers else ""),
    )


def _target_metadata(context: ActionContext) -> list[str]:
    lines = []
    target = context.target_path or context.tool_args.get("file_path") or context.tool_args.get("path")
    if not isinstance(target, str) or not target:
        return ["- target_exists: unknown"]

    path = Path(target)
    if not path.is_absolute():
        path = Path(context.repo_root) / path

    try:
        stat = path.stat()
    except FileNotFoundError:
        lines.append("- target_exists: false")
        if context.tool_name == "Write":
            lines.append("- write_mode: create_new_file")
    except OSError as e:
        lines.append("- target_exists: unknown")
        lines.append(f"- target_stat_error: {e}")
    else:
        lines.append("- target_exists: true")
        lines.append(f"- existing_size_bytes: {stat.st_size}")
        if context.tool_name == "Write":
            lines.append("- write_mode: overwrite_existing_file")
    return lines


def _build_action_source(context: ActionContext) -> tuple[str, bool, str]:
    """Build the action text before final prompt-budget packing."""
    target_lines = _target_metadata(context)
    header = "\n".join(target_lines)

    if context.raw_diff:
        body = "Unified diff:\n```diff\n" + context.raw_diff + "\n```"
        return header + "\n\n" + body, True, "raw_diff"

    if context.tool_name == "Edit":
        old_string = context.tool_args.get("old_string")
        new_string = context.tool_args.get("new_string", context.new_content)
        old_text = old_string if isinstance(old_string, str) else ""
        new_text = new_string if isinstance(new_string, str) else ""
        body = "\n\n".join(
            [
                "Matched/replaced fragment (old_string):\n```\n" + old_text + "\n```",
                "Replacement fragment (new_string):\n```\n" + new_text + "\n```",
            ]
        )
        return header + "\n\n" + body, False, "edit_fragments"

    content = context.tool_args.get("content")
    if not isinstance(content, str):
        content = context.new_content or ""
    body = "Write content:\n```\n" + content + "\n```"
    return header + "\n\n" + body, False, "write_content"


def _pack_prompt_sections(
    plan_text: str, context: ActionContext, *, budget_tokens: int
) -> tuple[_PackedText, _PackedText]:
    # Treat checker_budget_tokens as the approximate whole-prompt budget, then
    # split the remaining room between the approved plan and action context.
    total_chars = max(1, _budget_chars(budget_tokens) - _prompt_shell_chars(context) - _PROMPT_OVERHEAD_RESERVE_CHARS)
    plan_budget = int(total_chars * _PLAN_BUDGET_FRACTION)
    action_budget = max(1, total_chars - plan_budget)
    if total_chars >= _MIN_ACTION_CHARS * 2 and action_budget < _MIN_ACTION_CHARS:
        action_budget = _MIN_ACTION_CHARS
        plan_budget = max(1, total_chars - action_budget)

    packed_plan = _head_tail_excerpt(plan_text, plan_budget)
    unused_plan = max(0, plan_budget - packed_plan.included_chars)
    action_source, preserve_hunks, action_strategy = _build_action_source(context)
    packed_action = _head_tail_excerpt(action_source, action_budget + unused_plan, preserve_hunk_headers=preserve_hunks)
    if packed_action.strategy == "full":
        packed_action = _PackedText(
            text=packed_action.text,
            original_chars=packed_action.original_chars,
            included_chars=packed_action.included_chars,
            truncated=packed_action.truncated,
            strategy=action_strategy,
        )
    else:
        packed_action = _PackedText(
            text=packed_action.text,
            original_chars=packed_action.original_chars,
            included_chars=packed_action.included_chars,
            truncated=packed_action.truncated,
            strategy=f"{action_strategy}+{packed_action.strategy}",
        )
    return packed_plan, packed_action


def _provider_label(model: str, provider: ProviderType | None) -> str:
    return provider or (model.split("/", 1)[0] if "/" in model else "unknown")


def _effective_provider(model: str, provider: ProviderType | None) -> ProviderType | None:
    """The provider a direct call resolves to: explicit if given, else detected.

    ``resolve_plan_check_route`` leaves ``provider`` None when the model string itself
    encodes the provider, so the OpenRouter user-injection gate must detect it here
    rather than trust a literal ``provider == "openrouter"``.
    """
    if provider is not None:
        return provider
    try:
        return detect_provider(model)
    except ValueError:
        return None


def _client_base_url(model: str, provider: ProviderType | None) -> str | None:
    if provider is not None:
        from forge.core.llm.credentials import resolve_provider_base_url

        return resolve_provider_base_url(provider)

    from forge.core.usage import resolve_client_base_url

    return resolve_client_base_url(model)


def run_plan_check(
    context: ActionContext,
    *,
    model: str,
    plan_text: str,
    provider: ProviderType | None = None,
    budget_tokens: int = DEFAULT_PLAN_CHECK_BUDGET_TOKENS,
    reasoning_effort: str | None = None,
) -> PlanCheckVerdict | None:
    """One cheap ``core.llm`` call: is this action clearly aligned with the plan?

    Mirrors ``tag_action``'s call mechanics (client, X-Request-ID forwarding,
    usage emission). Returns None on ANY error -- the caller maps None to
    ``needs_review``, so a checker failure escalates instead of blocking.

    Must NOT be called from inside an event loop (SyncAdapter constraint).
    """
    try:
        from forge.core.llm import (
            Message,
            ModelHyperparameters,
            SyncAdapter,
            get_client,
        )
        from forge.core.llm.types import ReasoningEffort
        from forge.core.usage import (
            emit_direct_llm_usage,
            mint_request_id,
            resolve_direct_provider_user,
            target_is_forge_proxy,
            with_forge_request_id,
            with_openrouter_user,
        )

        packed_plan, packed_action = _pack_prompt_sections(plan_text, context, budget_tokens=budget_tokens)

        prompt = PLAN_CHECK_PROMPT.format(
            plan_metadata=packed_plan.metadata,
            plan_text=packed_plan.text,
            tool_name=context.tool_name,
            target_path=context.target_path or "N/A",
            action_metadata=packed_action.metadata,
            action_text=packed_action.text,
        )

        client = get_client(model, provider=provider)
        adapter = SyncAdapter(client)

        # Same exact-cost join as the tagger: forward an X-Request-ID only when the
        # client provably targets a Forge proxy (a dangling ref is worse than none).
        request_id = mint_request_id() if target_is_forge_proxy(_client_base_url(model, provider)) else None
        # OpenRouter `user` grouping: opt-in (global toggle, resolved inside) and
        # OpenRouter-only -- the field is an OpenRouter feature, so gate on the route.
        provider_user = (
            resolve_direct_provider_user("plan-check") if _effective_provider(model, provider) == "openrouter" else None
        )
        # Compose hyperparams by chaining the additive wrappers: each deep-copies and
        # adds only its own key, preserving siblings. Stays None when nothing applies,
        # preserving the prior "no hyperparams" behavior.
        # reasoning_effort is validated upstream (CLI Choice + SupervisorConfig.__post_init__).
        hp: ModelHyperparameters | None = (
            ModelHyperparameters(reasoning_effort=cast(ReasoningEffort, reasoning_effort)) if reasoning_effort else None
        )
        if request_id:
            hp = with_forge_request_id(hp, request_id)
        if provider_user:
            hp = with_openrouter_user(hp, provider_user)

        start = time.monotonic()
        response = adapter.complete([Message(role="user", content=prompt)], hyperparams=hp)
        latency_ms = (time.monotonic() - start) * 1000

        verdict = parse_plan_check_verdict(response.text)

        # Session-tagged (unlike the tagger) so `forge telemetry activity` shows a plan-check row.
        emit_direct_llm_usage(
            command="plan-check",
            model=model,
            provider=_provider_label(model, provider),
            usage=response.usage,
            status="success" if verdict is not None else "error",
            failure_type=None if verdict is not None else "parse_error",
            cost_request_id=request_id,
            latency_ms=latency_ms,
            session=context.session_name,
            provider_meta=response.provider_meta,
        )

        return verdict

    except Exception as e:
        _log.warning("run_plan_check failed (model=%s): %s", model, e)
        from forge.core.usage import emit_direct_llm_usage

        emit_direct_llm_usage(
            command="plan-check",
            model=model,
            provider=_provider_label(model, provider),
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

    def __init__(self, config: SupervisorConfig | None = None, *, lane_record: LaneRecord | None = None) -> None:
        self._config = config
        # The supervisor's consumer-lane binding (epic consumer_lanes, T1b), threaded so a shadow
        # candidate is captured with the lane production would replay on (None => default claude).
        self._lane_record = lane_record
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

        route = resolve_plan_check_route(config)
        budget_tokens = _budget_tokens(config)

        cache_key = compute_cache_key(context.tool_name, context.target_path, context.new_content)
        # plan_override_path is non-None here (load_plan_override returned content)
        cache_key = cache_key + "|plan:" + plan_fingerprint(str(config.plan_override_path), config.forge_root)
        cache_key = (
            cache_key
            + f"|checker:{route.provider or 'auto'}:{route.model}"
            + f"|budget:{budget_tokens}"
            + f"|effort:{config.checker_effort or 'default'}"
            + "|target:"
            + ";".join(_target_metadata(context))
        )

        cached = self._cache.check(cache_key)
        if cached is not None:
            _log.debug("Using cached plan-check verdict for %s", cache_key)
            decision = self._allow()  # only clean allows are ever cached
            decision.cached = True
            return decision

        verdict = run_plan_check(
            context,
            model=route.model,
            provider=route.provider,
            plan_text=plan_text,
            budget_tokens=budget_tokens,
            reasoning_effort=config.checker_effort,
        )

        if verdict is None:
            return self._needs_review(
                "semantic.plan_check.error",
                "Plan check produced no verdict; escalating to supervisor",
            )

        if verdict.aligned:
            _log.debug("Plan check aligned: %s", verdict.reason)
            self._cache.update(cache_key, aligned=True)
            # Shadow-sample this FRESH allow (the cache-hit branch above is deliberately never sampled). Best-effort and
            # gated on rate > 0 so a default session does literal zero I/O here; capture never runs the frontier.
            if config.shadow_sample_rate > 0.0:
                try:
                    from forge.policy.semantic import shadow

                    if shadow.should_sample(config, context, cache_key):
                        shadow.capture_candidate(
                            config,
                            context,
                            cache_key=cache_key,
                            tier1_reason=verdict.reason,
                            checker_model=route.model,
                            checker_provider=route.provider,
                            checker_budget_tokens=budget_tokens,
                            checker_prompt_version=CHECKER_PROMPT_VERSION,
                            lane_record=self._lane_record,
                        )
                except Exception:  # best-effort audit: never block the hook
                    _log.debug("shadow capture failed", exc_info=True)
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
