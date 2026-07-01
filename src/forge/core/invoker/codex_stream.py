"""Reducer for the ``codex exec --json`` event stream (Phase 5b).

``codex exec --json`` prints a JSONL *event stream* (one ``{"type": ...}`` object per
line), not a single result envelope like ``claude -p --output-format json``. This
module reduces that stream to the three things the invoker needs:

- ``final_text``  -- the assistant's answer (concatenated ``agent_message`` items);
- token counts    -- lifted from the terminal ``turn.completed.usage``;
- ``is_error``    -- whether the turn failed (an ``error`` or ``turn.failed`` event);
- ``thread_id``   -- the resume/session id from the leading ``thread.started`` event
  (probe stage 61 paired it with the rollout filename's ``<session_id>``).

The shape is pinned to a recorded fixture (``tests/fixtures/codex/``), not the docs:
when the binary disagrees with a doc, the fixture wins. See that directory's README
for the authoritative stream shape (codex-cli 0.137.0).

The stream is external subprocess output (a system boundary): malformed lines are
skipped best-effort (a stray non-JSON log line must not lose the whole answer), but a
failed turn is always surfaced as ``is_error`` so the caller cannot read a failure as
success.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# Event ``type`` values we react to. Others (``turn.started``, reasoning items,
# tool items) carry no data the invoker needs and are ignored.
_AGENT_MESSAGE = "agent_message"
_ITEM_COMPLETED = "item.completed"
_TURN_COMPLETED = "turn.completed"
_THREAD_STARTED = "thread.started"
_ERROR_EVENTS = ("error", "turn.failed")


@dataclass(frozen=True)
class CodexStreamResult:
    """Reduced outcome of one ``codex exec --json`` stream.

    ``cached_tokens`` is the cache-read subset of ``input_tokens`` (Codex reports it
    as ``cached_input_tokens``). Token fields are ``None`` when the stream carried no
    ``turn.completed.usage`` (e.g. a failed turn). ``error_message`` is the first
    provider error string, kept for diagnostics; ``is_error`` is the decision flag.
    ``thread_id`` is the ``codex exec resume`` id (None when the stream never opened
    a thread, e.g. an immediate CLI failure).
    """

    final_text: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    is_error: bool
    error_message: str | None
    thread_id: str | None = None


def parse_codex_jsonl_stream(stdout: str) -> CodexStreamResult:
    """Reduce a ``codex exec --json`` JSONL event stream to a :class:`CodexStreamResult`."""
    texts: list[str] = []
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    is_error = False
    error_message: str | None = None
    thread_id: str | None = None

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            # System boundary: one bad line (stray log output) must not discard the
            # whole answer. Skip it and keep reducing the rest of the stream.
            continue
        if not isinstance(event, dict):
            continue

        etype = event.get("type")
        if etype == _ITEM_COMPLETED:
            text = _agent_message_text(event.get("item"))
            if text is not None:
                texts.append(text)
        elif etype == _TURN_COMPLETED:
            usage = event.get("usage")
            if isinstance(usage, dict):
                # Last-wins: a one-shot `codex exec` emits exactly one terminal
                # turn.completed, so this assigns once. If a future multi-turn stream emits
                # several, this keeps the LAST (the final cumulative figure). Revisit to sum
                # only if probes show per-turn *incremental* usage instead.
                input_tokens = _as_int(usage.get("input_tokens"))
                output_tokens = _as_int(usage.get("output_tokens"))
                cached_tokens = _as_int(usage.get("cached_input_tokens"))
                # NOTE: `reasoning_output_tokens` is a SUBSET of `output_tokens` (Responses
                # usage is inclusive), so it is deliberately NOT lifted -- adding it would
                # double-count. There is no HeadlessResult field for it.
        elif etype == _THREAD_STARTED:
            # First-wins: one stream opens one thread; a resumed stream re-announces
            # the SAME id (probe 60b), so later events could only confirm the first.
            if thread_id is None:
                candidate = event.get("thread_id")
                if isinstance(candidate, str) and candidate:
                    thread_id = candidate
        elif etype in _ERROR_EVENTS:
            is_error = True
            if error_message is None:
                error_message = _extract_error_message(event)

    return CodexStreamResult(
        final_text="\n".join(texts),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        is_error=is_error,
        error_message=error_message,
        thread_id=thread_id,
    )


def _agent_message_text(item: object) -> str | None:
    """Return the text of an ``item.completed`` item iff it is an ``agent_message``."""
    if isinstance(item, dict) and item.get("type") == _AGENT_MESSAGE:
        text = item.get("text")
        if isinstance(text, str):
            return text
    return None


def _extract_error_message(event: dict[str, object]) -> str | None:
    """Pull the provider error string from an ``error`` or ``turn.failed`` event.

    ``error`` carries ``message`` at the top level; ``turn.failed`` nests it under
    ``error.message``. Both values are the provider's (already stringified) error. An
    empty/whitespace message is treated as absent (returns None) so the caller supplies a
    generic fallback rather than surfacing a blank error.
    """
    message = event.get("message")
    if isinstance(message, str) and message.strip():
        return message
    nested = event.get("error")
    if isinstance(nested, dict):
        nested_message = nested.get("message")
        if isinstance(nested_message, str) and nested_message.strip():
            return nested_message
    return None


# Subscription-exhaustion classification (T7). Codex collapses its structured
# ``usage_limit_exceeded`` discriminator to human prose at the ``exec`` boundary
# (``ThreadErrorEvent`` carries only ``message``; no status/``error.type`` survives --
# see tests/fixtures/codex/README.md), so detection is a conservative string match.
# Anchors are the stable ``Display`` literals from openai/codex ``protocol/src/error.rs``
# (main @ db887d0): ``UsageLimitReached`` (every plan branch shares "hit your usage
# limit"), workspace credits depleted, workspace spend cap, ``QuotaExceeded``,
# ``UsageNotIncluded``. Casefolded substring -> tolerant of upstream copy drift.
_EXHAUSTION_MESSAGE_ANCHORS = (
    "hit your usage limit",
    "out of credits",
    "spend cap",
    "quota exceeded. check your plan",
    "to use codex with your chatgpt plan, upgrade to plus",
)
# Raw-leak path: an untyped provider error reaches ``message`` as a stringified JSON
# envelope (e.g. the 400 fixture). These nested ``error.type`` values are exhaustion;
# ``rate_limit_exceeded`` is deliberately absent -- a per-minute RPM throttle is
# transient and must not trip T7's sticky session-long lane degrade.
_EXHAUSTION_ERROR_TYPES = frozenset({"usage_limit_reached", "insufficient_quota"})


def is_subscription_exhausted(error_message: str) -> bool:
    """Return True iff a codex error string signals subscription-quota exhaustion.

    Conservative by design: a transient rate limit, a generic API error, or a network
    blip returns False, so T7's sticky lane degrade never trips on a recoverable
    failure. Matches both shapes the boundary can produce -- the human prose of the
    typed ``UsageLimitReached`` path and the stringified-JSON envelope of the raw-leak
    path (nested ``error.type``). Input is the string ``_extract_error_message``
    produces; see ``tests/fixtures/codex/README.md`` for why no ``status``/``error.type``
    survives the ``exec`` boundary.
    """
    if not error_message:
        return False
    text = error_message.casefold()
    if any(anchor in text for anchor in _EXHAUSTION_MESSAGE_ANCHORS):
        return True
    return _error_type_is_exhaustion(error_message)


def _error_type_is_exhaustion(error_message: str) -> bool:
    """Match the nested ``error.type`` of a stringified-JSON provider error envelope.

    Best-effort: returns False on any non-JSON or non-dict message (the human-prose
    path is already handled by the message anchors).
    """
    try:
        payload = json.loads(error_message)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    error_type = error.get("type")
    return isinstance(error_type, str) and error_type.casefold() in _EXHAUSTION_ERROR_TYPES


def _as_int(value: object) -> int | None:
    """Coerce a usage value to int, tolerating absent/non-numeric fields (boundary)."""
    if isinstance(value, bool):  # bool is an int subclass; a usage count is never a bool
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
