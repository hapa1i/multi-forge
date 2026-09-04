"""Override-mode mutation pipeline (Phase 2 audit proxy, MUTATE half).

Pure helpers that build, validate, and apply a mutation plan to the CURRENT
request's control surfaces only — the system prompt and generation parameters —
never historical messages. The mutation-safety invariant (preserve
``messages[0..n-1]`` byte-for-byte, especially ``thinking``/``redacted_thinking``
blocks) is enforced by fingerprinting the messages list before and after apply
and raising if it changed.

These helpers operate on the RAW Anthropic body dict (the passthrough path), so
mutations are signature-safe: signed reasoning in historical turns is untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from forge.core.models.model_reference import strip_transport_model_suffix
from forge.proxy.audit_logger import hash_system_prompt
from forge.proxy.reasoning import EFFORT_RANK, max_effort, raise_effort_to_supported

# Anthropic requires extended-thinking budget_tokens >= 1024 and < max_tokens.
_ANTHROPIC_MIN_THINKING_BUDGET = 1024

# Effort floor -> minimum thinking.budget_tokens (Anthropic units). Mirrors the
# inversion of reasoning.BUDGET_THRESHOLDS; test_intercept pins them consistent
# so the two tables cannot silently drift.
_EFFORT_BUDGET_FLOOR: dict[str, int] = {
    "minimal": 1,
    "low": 500,
    "medium": 2_000,
    "high": 10_000,
    "xhigh": 25_000,
}


# Effort floors an override-mode proxy can actually enforce, weakest to
# strongest. The native path pins ``output_config.effort``; the legacy path maps
# the floor to a thinking budget through _EFFORT_BUDGET_FLOOR. Values outside
# this tuple are configuration errors rather than silently normalized floors.
SUPPORTED_FLOOR_EFFORTS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh", "max")

# Accepted spellings for "no floor". Normalizing these upward would pin the
# lowest supported level and invert the operator's intent, so they resolve to
# None (leave the client's own reasoning fields alone) instead.
_NO_FLOOR_EFFORTS = frozenset({"none", "disable"})


class ReasoningOverrideError(ValueError):
    """Raised when a client's reasoning fields cannot be honored under override mode."""


class ReasoningConfigError(ReasoningOverrideError):
    """Raised when the proxy's configured effort floor is invalid.

    Subclasses ReasoningOverrideError so existing fail-closed handlers keep
    catching it; responders that distinguish blame catch this first and report a
    configuration fault instead of telling the client to fix its request body.
    """


def _validate_reasoning_floor_effort(value: object | None) -> str | None:
    """Return an enforceable effort floor, or None when no floor is configured."""

    if value is None:
        return None
    if isinstance(value, str) and value in _NO_FLOOR_EFFORTS:
        return None
    if not isinstance(value, str) or value not in SUPPORTED_FLOOR_EFFORTS:
        supported = ", ".join(SUPPORTED_FLOOR_EFFORTS)
        raise ReasoningConfigError(
            f"reasoning effort floor must be one of: {supported} "
            f"(or {', '.join(sorted(_NO_FLOOR_EFFORTS))} for no floor)"
        )
    return value


# --- Mutation-safety fingerprint ---------------------------------------------


def messages_fingerprint(messages: Any) -> str:
    """SHA256 over the messages list (all content blocks, byte-faithful).

    Override never writes messages, so this is invariant across apply — the
    check is a tripwire against a bug that rewrites a historical thinking block.
    """
    canonical = json.dumps(messages, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- System-prompt mutations -------------------------------------------------


def _system_to_blocks(system: Any) -> list[dict[str, Any]]:
    """Normalize an Anthropic ``system`` (str | list[block]) to a text-block list."""
    if system is None:
        return []
    if isinstance(system, str):
        return [{"type": "text", "text": system}] if system else []
    if isinstance(system, list):
        return [b for b in system if isinstance(b, dict)]
    return []


def _compile(pattern: Any) -> re.Pattern[str] | None:
    """Compile a guard pattern, returning None for non-str / invalid regex.

    Config validation rejects bad guards up front; this is a defensive no-op so a
    malformed guard reaching the hot path degrades to "no match" rather than raising.
    """
    if not isinstance(pattern, str) or not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error:
        return None


def insert_augment_cache_aware(system: Any, augment: str) -> tuple[Any, bool]:
    """Insert ``augment`` as a system text block, cache-aware.

    Returns ``(new_system, cache_invalidation_expected)``. With a ``cache_control``
    marker, insert right after the last one so the cached prefix is byte-identical
    (no invalidation). Without a marker (string/markerless system), append and flag
    expected invalidation — there is no safe post-cache anchor.
    """
    if not augment:
        return system, False
    blocks = _system_to_blocks(system)
    aug_block = {"type": "text", "text": augment}
    last_cache_idx = -1
    for i, block in enumerate(blocks):
        if block.get("cache_control") is not None:
            last_cache_idx = i
    if last_cache_idx >= 0:
        new_blocks = blocks[: last_cache_idx + 1] + [aug_block] + blocks[last_cache_idx + 1 :]
        return new_blocks, False
    return blocks + [aug_block], True


@dataclass
class GuardOutcome:
    """Result of evaluating system-prompt guards (no plaintext retained)."""

    blocked: bool = False
    blocked_pattern: str | None = None
    warned_patterns: list[str] = field(default_factory=list)
    stripped_count: int = 0


def apply_guards(system: Any, guards: list[dict[str, str]]) -> tuple[Any, GuardOutcome]:
    """Evaluate warn/block/strip guards per text block, validate-before-mutate.

    All ``block`` guards are checked FIRST (no mutation); a match returns blocked
    with the system untouched. Only then are ``strip`` (removes matches per block)
    and ``warn`` applied. Matching is per-block for every action, so semantics do
    not differ between block/warn/strip.
    """
    outcome = GuardOutcome()
    blocks = _system_to_blocks(system)

    # Pass 1: block guards (validation only — never mutate, so a later block cannot
    # leave a half-stripped body behind).
    for guard in guards:
        if guard.get("action") == "block":
            rx = _compile(guard.get("pattern"))
            if rx is not None and any(rx.search(block.get("text", "")) for block in blocks):
                outcome.blocked = True
                outcome.blocked_pattern = guard.get("pattern")
                return system, outcome

    # Pass 2: strip + warn (mutation).
    for guard in guards:
        action = guard.get("action", "warn")
        pattern = guard.get("pattern")
        rx = _compile(pattern)
        if rx is None or not isinstance(pattern, str):
            continue
        if action == "strip":
            for block in blocks:
                if block.get("text"):
                    new_text, n = rx.subn("", block["text"])
                    if n:
                        block["text"] = new_text
                        outcome.stripped_count += n
        elif action == "warn":
            if any(rx.search(block.get("text", "")) for block in blocks):
                outcome.warned_patterns.append(pattern)

    # Preserve the original shape when nothing was stripped (byte-fidelity).
    if outcome.stripped_count == 0:
        return system, outcome
    return blocks, outcome


# --- Reasoning-effort pin helpers --------------------------------------------


def effort_to_budget_floor(effort: str | None) -> int | None:
    """Map a reasoning_effort floor to its minimum thinking.budget_tokens."""
    if not effort:
        return None
    return _EFFORT_BUDGET_FLOOR.get(effort)


def pin_reasoning(thinking: Any, floor_effort: str | None, max_tokens: Any) -> tuple[Any, bool, int | None, int | None]:
    """Raise thinking.budget_tokens to the effort floor (never lower it).

    Returns ``(new_thinking, changed, budget_before, budget_after)``. Clamps to a
    valid Anthropic range (>=1024, < max_tokens); skips when max_tokens is too small
    to host any thinking budget.

    Floor semantics (intentional, consistent with the translated path's
    ``max_effort``): a configured floor force-ENABLES thinking even when the client
    omitted it or set ``type='disabled'`` — the tier override is a guarantee, not a
    suggestion. Unknown sibling keys on the inbound ``thinking`` dict are preserved
    (forward-safe for passthrough).
    """
    floor = effort_to_budget_floor(floor_effort)
    if not floor:
        return thinking, False, None, None
    current = thinking.get("budget_tokens") if isinstance(thinking, dict) else None
    current_int = int(current) if isinstance(current, (int, float)) and current > 0 else None
    if current_int is not None and current_int >= floor:
        return thinking, False, current_int, current_int

    target = max(floor, _ANTHROPIC_MIN_THINKING_BUDGET)
    if isinstance(max_tokens, int):
        if max_tokens <= _ANTHROPIC_MIN_THINKING_BUDGET:
            return thinking, False, current_int, current_int  # can't host thinking
        target = min(target, max_tokens - 1)
    pinned = dict(thinking) if isinstance(thinking, dict) else {}
    pinned["type"] = "enabled"
    pinned["budget_tokens"] = int(target)
    return pinned, True, current_int, int(target)


def _native_effort_support(model: Any) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None] | None:
    """Return native Anthropic effort/thinking metadata for a catalogued request model."""

    if not isinstance(model, str) or not model:
        return None

    from forge.core.models import ModelCatalogError, get_model_spec

    lookup_model = strip_transport_model_suffix(model)
    candidates = (lookup_model, lookup_model.split("/", 1)[-1]) if "/" in lookup_model else (lookup_model,)
    for candidate in candidates:
        try:
            spec = get_model_spec(candidate)
        except ModelCatalogError:
            continue
        if spec.native_thinking_param == "output_config.effort":
            return spec.litellm_reasoning_efforts, spec.thinking_modes
        return None
    return None


def _normalize_native_effort_floor(
    floor_effort: str,
    supported_efforts: tuple[str, ...] | None,
) -> str:
    """Normalize a native effort floor upward without weakening the guarantee."""

    normalized = raise_effort_to_supported(floor_effort, supported_efforts)
    if normalized is None:
        raise ReasoningOverrideError(
            f"reasoning effort floor {floor_effort!r} cannot be represented safely "
            f"(model supports: {', '.join(supported_efforts or ())})"
        )
    return normalized


def pin_native_effort(
    output_config: Any,
    floor_effort: str,
    *,
    supported_efforts: tuple[str, ...] | None,
) -> tuple[Any, bool, str | None, str]:
    """Raise ``output_config.effort`` to a model-aware floor without lowering it."""

    if output_config is not None and not isinstance(output_config, dict):
        raise ReasoningOverrideError("output_config must be an object when a passthrough reasoning floor is configured")
    pinned = dict(output_config) if isinstance(output_config, dict) else {}
    current = pinned.get("effort")
    if current is not None and not isinstance(current, str):
        raise ReasoningOverrideError("output_config.effort must be a string")
    if current is not None and current not in EFFORT_RANK:
        raise ReasoningOverrideError(f"unsupported output_config.effort {current!r}")
    if supported_efforts is not None and current is not None and current not in supported_efforts:
        raise ReasoningOverrideError(
            f"output_config.effort {current!r} is not supported by this model "
            f"(supported: {', '.join(supported_efforts)})"
        )

    effective_floor = _normalize_native_effort_floor(floor_effort, supported_efforts)
    target = max_effort(current, effective_floor)
    assert target is not None
    if current == target:
        return output_config, False, current, target
    pinned["effort"] = target
    return pinned, True, current, target


# --- Orchestration -----------------------------------------------------------


@dataclass
class OverrideResult:
    """Outcome of applying the override plan to a raw Anthropic body."""

    body: dict[str, Any]
    blocked: bool = False
    blocked_reason: str | None = None
    mutation_record: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


def apply_override(
    raw_body: dict[str, Any],
    *,
    system_prompt_augment: str = "",
    system_prompt_guards: list[dict[str, str]] | None = None,
    reasoning_floor_effort: object | None = None,
) -> OverrideResult:
    """Build, validate, and apply the override plan to ``raw_body`` (mutated in place).

    Applies guards, then cache-aware augment, then the reasoning pin — all to the
    system prompt / generation params only. Enforces the mutation-safety invariant
    (messages fingerprint unchanged). Returns the mutated body plus a redacted
    mutation record, or a block decision (body left unmutated).
    """
    reasoning_floor_effort = _validate_reasoning_floor_effort(reasoning_floor_effort)

    # Request/model compatibility is independent of whether the operator set a
    # reasoning floor. Validate it before guard planning, whose list-form
    # normalization may reuse mutable system-block dictionaries.
    native_support = _native_effort_support(raw_body.get("model"))
    if native_support is not None:
        _, thinking_modes = native_support
        thinking = raw_body.get("thinking")
        if thinking_modes == ("adaptive",) and isinstance(thinking, dict):
            thinking_type = thinking.get("type")
            if thinking_type == "enabled" or "budget_tokens" in thinking:
                raise ReasoningOverrideError(
                    f"model {raw_body.get('model')!r} requires adaptive thinking; "
                    "remove manual thinking.type/budget_tokens"
                )

    guards = system_prompt_guards or []
    before_fp = messages_fingerprint(raw_body.get("messages"))
    system_hash_before = hash_system_prompt(raw_body.get("system"))
    mutations: list[dict[str, Any]] = []
    warnings: list[str] = []
    pending_reasoning: tuple[str, Any] | None = None
    removed_sampling_parameters: list[str] = []

    # 1) Guards (block short-circuits before any mutation).
    system, guard_outcome = apply_guards(deepcopy(raw_body.get("system")), guards)
    if guard_outcome.blocked:
        return OverrideResult(
            body=raw_body,
            blocked=True,
            blocked_reason=f"system_prompt_guard blocked request (pattern hash {_pattern_hash(guard_outcome.blocked_pattern)})",
            mutation_record={
                "blocked": True,
                "mutations": [
                    {
                        "target": "system_prompt",
                        "action": "block",
                        "pattern_hash": _pattern_hash(guard_outcome.blocked_pattern),
                    }
                ],
            },
        )

    for pattern in guard_outcome.warned_patterns:
        warnings.append(f"system_prompt_guard matched (warn): {_pattern_hash(pattern)}")
        mutations.append({"target": "system_prompt", "action": "warn", "pattern_hash": _pattern_hash(pattern)})
    if guard_outcome.stripped_count:
        mutations.append({"target": "system_prompt", "action": "strip", "stripped_count": guard_outcome.stripped_count})

    # 2) Cache-aware system-prompt augment.
    cache_invalidation = False
    if system_prompt_augment:
        system, cache_invalidation = insert_augment_cache_aware(system, system_prompt_augment)
        mutations.append(
            {
                "target": "system_prompt",
                "action": "augment",
                "augment_len": len(system_prompt_augment),
                "cache_invalidation_expected": cache_invalidation,
            }
        )
        if cache_invalidation:
            warnings.append("system_prompt_augment: no post-cache anchor, expected cache invalidation")

    # 3) Reasoning-effort pin. Newer Claude models expose a native effort
    # control; older/unknown models retain the legacy thinking-budget mapping.
    if native_support is not None and reasoning_floor_effort is not None:
        supported_efforts, _ = native_support
        output_config, pinned, effort_before, effort_after = pin_native_effort(
            raw_body.get("output_config"),
            reasoning_floor_effort,
            supported_efforts=supported_efforts,
        )
        if pinned:
            removed_sampling_parameters = sorted(
                parameter for parameter in ("temperature", "top_p", "top_k") if parameter in raw_body
            )
            pending_reasoning = ("output_config", output_config)
            mutations.append(
                {
                    "target": "output_config.effort",
                    "action": "reasoning_pin",
                    "effort_floor": reasoning_floor_effort,
                    "effort_before": effort_before,
                    "effort_after": effort_after,
                    "removed_sampling_parameters": removed_sampling_parameters,
                }
            )
    elif reasoning_floor_effort is not None:
        if effort_to_budget_floor(reasoning_floor_effort) is None:
            raise ReasoningOverrideError(
                f"reasoning effort floor {reasoning_floor_effort!r} cannot be represented safely for "
                f"passthrough model {raw_body.get('model')!r}"
            )
        new_thinking, pinned, budget_before, budget_after = pin_reasoning(
            raw_body.get("thinking"), reasoning_floor_effort, raw_body.get("max_tokens")
        )
        if pinned:
            removed_sampling_parameters = sorted(
                parameter for parameter in ("temperature", "top_p", "top_k") if parameter in raw_body
            )
            pending_reasoning = ("thinking", new_thinking)
            mutations.append(
                {
                    "target": "thinking",
                    "action": "reasoning_pin",
                    "effort_floor": reasoning_floor_effort,
                    "budget_before": budget_before,
                    "budget_after": budget_after,
                    "removed_sampling_parameters": removed_sampling_parameters,
                }
            )

    # 4) Apply the validated plan to a candidate body, then enforce the
    # mutation-safety invariant before committing it to the caller's object.
    candidate_body = dict(raw_body)
    if guard_outcome.stripped_count or system_prompt_augment:
        candidate_body["system"] = system
    if pending_reasoning is not None:
        field_name, value = pending_reasoning
        candidate_body[field_name] = value
        for parameter in removed_sampling_parameters:
            candidate_body.pop(parameter)

    after_fp = messages_fingerprint(candidate_body.get("messages"))
    if before_fp != after_fp:
        raise RuntimeError("mutation-safety invariant violated: override altered historical messages")

    if not mutations:
        return OverrideResult(body=raw_body, warnings=warnings)

    raw_body.clear()
    raw_body.update(candidate_body)
    return OverrideResult(
        body=raw_body,
        mutation_record={
            "blocked": False,
            "system_prompt_hash_before": system_hash_before,
            "system_prompt_hash_after": hash_system_prompt(raw_body.get("system")),
            "mutations": mutations,
        },
        warnings=warnings,
    )


def _pattern_hash(value: str | None) -> str | None:
    if value is None:
        return None
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
