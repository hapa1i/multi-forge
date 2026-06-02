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
from dataclasses import dataclass, field
from typing import Any

from forge.proxy.audit_logger import hash_system_prompt

# Anthropic requires extended-thinking budget_tokens >= 1024 and < max_tokens.
_ANTHROPIC_MIN_THINKING_BUDGET = 1024

# Effort floor -> minimum thinking.budget_tokens (Anthropic units). Mirrors the
# inversion of server._BUDGET_THRESHOLDS; test_intercept pins them consistent so
# the two tables cannot silently drift.
_EFFORT_BUDGET_FLOOR: dict[str, int] = {
    "minimal": 1,
    "low": 500,
    "medium": 2_000,
    "high": 10_000,
    "xhigh": 25_000,
}


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


# --- Reasoning-effort pin (in Anthropic thinking-budget units) ---------------


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
    ``_max_effort``): a configured floor force-ENABLES thinking even when the client
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
    reasoning_floor_effort: str | None = None,
) -> OverrideResult:
    """Build, validate, and apply the override plan to ``raw_body`` (mutated in place).

    Applies guards, then cache-aware augment, then the reasoning pin — all to the
    system prompt / generation params only. Enforces the mutation-safety invariant
    (messages fingerprint unchanged). Returns the mutated body plus a redacted
    mutation record, or a block decision (body left unmutated).
    """
    guards = system_prompt_guards or []
    before_fp = messages_fingerprint(raw_body.get("messages"))
    system_hash_before = hash_system_prompt(raw_body.get("system"))
    mutations: list[dict[str, Any]] = []
    warnings: list[str] = []

    # 1) Guards (block short-circuits before any mutation).
    system, guard_outcome = apply_guards(raw_body.get("system"), guards)
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

    if guard_outcome.stripped_count or system_prompt_augment:
        raw_body["system"] = system

    # 3) Reasoning-effort pin (Anthropic thinking-budget units).
    new_thinking, pinned, budget_before, budget_after = pin_reasoning(
        raw_body.get("thinking"), reasoning_floor_effort, raw_body.get("max_tokens")
    )
    if pinned:
        raw_body["thinking"] = new_thinking
        mutations.append(
            {
                "target": "thinking",
                "action": "reasoning_pin",
                "effort_floor": reasoning_floor_effort,
                "budget_before": budget_before,
                "budget_after": budget_after,
            }
        )

    # 4) Mutation-safety invariant: historical messages must be byte-identical.
    after_fp = messages_fingerprint(raw_body.get("messages"))
    if before_fp != after_fp:
        raise RuntimeError("mutation-safety invariant violated: override altered historical messages")

    if not mutations:
        return OverrideResult(body=raw_body, warnings=warnings)

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
