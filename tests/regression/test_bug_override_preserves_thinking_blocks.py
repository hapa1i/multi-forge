"""Regression: override mode must never rewrite historical signed reasoning.

Bug class: signature corruption / silent loss. The mutation-safety invariant
(card 'Mutation safety invariant') says every historical message in [0..n-1] —
especially thinking/redacted_thinking blocks carrying signatures — must be
forwarded byte-for-byte. A mutation that touched messages would invalidate the
signature and break multi-turn continuity.

Affected files: src/forge/proxy/intercept.py
"""

from __future__ import annotations

import copy

import pytest

from forge.proxy import intercept

pytestmark = pytest.mark.regression

# A conversation whose history carries a signed thinking block + an opaque
# redacted_thinking block on the most recent assistant turn.
HISTORY = [
    {"role": "user", "content": [{"type": "text", "text": "first question"}]},
    {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "private chain of thought", "signature": "SIG-DO-NOT-MUTATE-abc123"},
            {"type": "redacted_thinking", "data": "OPAQUE-ENCRYPTED-PAYLOAD"},
            {"type": "text", "text": "answer one"},
        ],
    },
    {"role": "user", "content": [{"type": "text", "text": "new question"}]},
]


def _body():
    return {
        "model": "claude-opus-4-6",
        "max_tokens": 32000,
        "system": [{"type": "text", "text": "you are helpful", "cache_control": {"type": "ephemeral"}}],
        "messages": copy.deepcopy(HISTORY),
    }


def test_override_with_all_directives_preserves_history_byte_for_byte():
    body = _body()
    result = intercept.apply_override(
        body,
        system_prompt_augment="be extra careful",
        system_prompt_guards=[{"pattern": "helpful", "action": "warn"}],
        reasoning_floor_effort="high",
    )

    # Mutations did happen on control surfaces (proves the path is live, not skipped).
    assert result.mutation_record is not None
    assert body["thinking"]["budget_tokens"] == 10000
    assert body["system"][-1]["text"] == "be extra careful"

    # ...but every historical message is byte-identical, signatures intact.
    assert body["messages"] == HISTORY
    assistant = body["messages"][1]["content"]
    assert assistant[0] == {
        "type": "thinking",
        "thinking": "private chain of thought",
        "signature": "SIG-DO-NOT-MUTATE-abc123",
    }
    assert assistant[1] == {"type": "redacted_thinking", "data": "OPAQUE-ENCRYPTED-PAYLOAD"}


def test_blocked_override_does_not_touch_history():
    body = _body()
    result = intercept.apply_override(
        body, system_prompt_guards=[{"pattern": "helpful", "action": "block"}], reasoning_floor_effort="high"
    )
    assert result.blocked
    assert body["messages"] == HISTORY  # blocked request leaves everything untouched
    assert "thinking" not in body
