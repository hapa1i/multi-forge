"""Regression for D004: only normalized citations may satisfy the block bar.

Root cause: the semantic converter tested the raw citation value for truthiness
but stored a separately normalized list. A truthy string or other invalid shape
could deny while the emitted violation displayed no citations.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from forge.policy.semantic.verdict import (
    parse_supervisor_verdict_with_status,
    verdict_to_decision,
)

pytestmark = pytest.mark.regression


def _decision(citations: Any):
    response = json.dumps(
        {
            "verdict": "divergent",
            "confidence": 0.95,
            "violations": [{"evidence": "Changed the plan", "citations": citations}],
        }
    )
    return verdict_to_decision(parse_supervisor_verdict_with_status(response)[0])


@pytest.mark.parametrize(
    "citations",
    ["Plan section 2", {"section": 2}, 7, True, [123], [None], [""]],
    ids=["string", "mapping", "integer", "boolean", "integer-list", "null-list", "blank-list"],
)
def test_invalid_citations_cannot_satisfy_block_bar(citations: Any) -> None:
    decision = _decision(citations)

    assert decision.decision == "warn"
    assert decision.violations == []


def test_mixed_citation_list_blocks_only_with_the_normalized_strings() -> None:
    decision = _decision([None, "", 7, "Plan section 2"])

    assert decision.decision == "deny"
    assert decision.violations[0].citations == ["Plan section 2"]
