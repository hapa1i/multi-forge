"""Structured output extraction from LLM responses.

Extracts JSON objects from LLM text responses that may contain
code fences, prose, or raw JSON. Used by verdict parsing,
workflow policy checkers, and any component that needs structured
LLM output.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from forge.core.reactive.headless_json import usd_to_micros

_log = logging.getLogger(__name__)

# Patterns tried in order: ```json ... ```, then ``` ... ```
_CODE_FENCE_PATTERNS = [
    re.compile(r"```json\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE),
    re.compile(r"```\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE),
]


def extract_json_from_response(response: str) -> dict[str, Any] | None:
    """Extract a JSON object from an LLM response.

    Tries code fences first (````` ```json ````` , then ````` ``` ````` ),
    then falls back to parsing the entire response as raw JSON.
    Returns the first successfully parsed JSON object.

    Args:
        response: Raw text response from the LLM.

    Returns:
        Parsed dict if extraction succeeds, None otherwise.
        Callers decide their own fail behavior (fail-open, warn, etc.).
    """
    if not response:
        return None

    # Try code fences
    for pattern in _CODE_FENCE_PATTERNS:
        matches = pattern.findall(response)
        for match in matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue

    # Fallback: raw JSON
    try:
        data = json.loads(response.strip())
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    _log.debug("Could not extract JSON from response (len=%d)", len(response))
    return None


@dataclass(frozen=True)
class HeadlessEnvelope:
    """Parsed `claude -p --output-format json` envelope (Phase 5).

    ``result_text`` is the unwrapped model text consumers read; the metric fields
    are the runtime's self-reported cost/usage. ``parsed`` and
    ``cost_micro_usd is not None`` are INDEPENDENT facts: a parsed envelope may
    carry exact tokens with no cost (direct OAuth). ``parsed=False`` means the
    fallback fired and ``result_text`` is the raw stdout (today's behavior).
    """

    result_text: str
    cost_micro_usd: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    is_error: bool = False
    parsed: bool = False


def _coerce_token_count(value: Any) -> int | None:
    """An int token count, or None. Rejects bool (JSON ``true`` is not a count)."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _find_result_object(stdout: str) -> dict[str, Any] | None:
    """Locate the terminal ``type=="result"`` object across the shapes Claude emits.

    Claude Code 2.1.x `--output-format json` emits a JSON ARRAY of events
    ``[system, assistant, result]`` (cost/usage in the LAST ``result`` element);
    the docs also describe a single ``result`` object. Returns None on anything else
    (caller falls back to raw text).

    Forge requests only ``--output-format json`` today. ``claude -p`` also supports
    ``stream-json`` (realtime NDJSON), but Forge consumes headless output in batch,
    where ``json`` is equivalent and simpler. A future streaming mode must add NDJSON
    parsing here AND thread the format from the caller (see ``prepare_json_argv``);
    do not request ``stream-json`` until both halves are wired, or cost/usage silently
    drop.
    """
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        results = [x for x in data if isinstance(x, dict) and x.get("type") == "result"]
        return results[-1] if results else None
    if isinstance(data, dict):
        return data  # documented single-object shape; the result-string check gates it
    return None


def parse_headless_envelope(stdout: str) -> HeadlessEnvelope:
    """Parse a `claude -p --output-format json` envelope. NEVER raises.

    On any non-envelope input (crash, empty, non-JSON, JSON without a usable
    ``result`` string), returns ``parsed=False`` with ``result_text=stdout`` so
    existing text consumers see exactly today's raw output. On a valid envelope,
    unwraps ``.result`` and lifts the runtime's self-reported cost/usage.
    """
    raw = stdout or ""
    if not raw.strip():
        return HeadlessEnvelope(result_text=raw)

    result_obj = _find_result_object(raw)
    if not isinstance(result_obj, dict):
        return HeadlessEnvelope(result_text=raw)

    result_text = result_obj.get("result")
    if not isinstance(result_text, str):
        # No usable model text -> don't claim a parse that would drop the output.
        return HeadlessEnvelope(result_text=raw)

    usage = result_obj.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    return HeadlessEnvelope(
        result_text=result_text,
        cost_micro_usd=usd_to_micros(result_obj.get("total_cost_usd")),
        input_tokens=_coerce_token_count(usage.get("input_tokens")),
        output_tokens=_coerce_token_count(usage.get("output_tokens")),
        # cache_read is the conventional "cached" count (cache hits over fresh input),
        # matching the proxy's cache-hit semantics; cache_creation is a separate cost.
        cached_tokens=_coerce_token_count(usage.get("cache_read_input_tokens")),
        is_error=bool(result_obj.get("is_error")),
        parsed=True,
    )
