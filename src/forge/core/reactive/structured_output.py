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
from typing import Any

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
