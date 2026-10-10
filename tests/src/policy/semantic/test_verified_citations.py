"""Source-only feedback uses the exact reviewed snapshot, never a fresh path read."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from forge.policy.semantic.plan_source import PlanSnapshot, read_plan
from forge.policy.semantic.verdict import (
    SupervisorVerdict,
    verdict_to_decision,
    verify_citations,
)
from forge.policy.store import serialize_decision
from forge.policy.types import Violation
from forge.session.models import SupervisorConfig


def test_changed_file_cannot_change_verified_passage(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    original = "Approved plan\nUse the fixed interface.\n"
    plan.write_text(original)
    snapshot = read_plan(SupervisorConfig(plan_override_path=str(plan)))
    plan.write_text("Changed plan; use a different interface.")
    quotes = verify_citations([" Use the fixed interface. \n", "use a different interface.", "plan.md"], snapshot)
    assert [asdict(q) for q in quotes] == [
        {
            "source": str(plan),
            "digest": hashlib.sha256(original.encode()).hexdigest(),
            "start": 14,
            "end": 38,
            "text": "Use the fixed interface.",
        }
    ]


@pytest.mark.parametrize("confidence, expected", [(0.5, "warn"), (0.95, "deny")])
@pytest.mark.parametrize("citation, verified", [("exact\nquote", True), ("exact quote", False), ("invented", False)])
def test_quote_verification_does_not_change_block_threshold(confidence, expected, citation, verified) -> None:
    snapshot = PlanSnapshot("/approved/plan.md", "exact\nquote", "a" * 64)
    decision = verdict_to_decision(
        SupervisorVerdict(
            "divergent",
            confidence,
            [
                {
                    "evidence": "private reviewer prose",
                    "suggested_fix": "private fix",
                    "citations": [citation],
                    "source": "/wrong/plan.md",
                    "digest": "forged",
                }
            ],
        ),
        snapshot=snapshot,
    )
    assert decision.decision == expected
    finding = (decision.violations or decision.warning_findings)[0]
    assert bool(finding.verified_citations) is verified
    assert finding.citations == [citation]
    persisted = serialize_decision(decision)
    records = persisted["violations"] or persisted["warning_findings"]
    assert records[0]["message"] == "private reviewer prose"
    if verified:
        assert records[0]["verified_citations"][0]["source"] == snapshot.path
        assert records[0]["verified_citations"][0]["digest"] == snapshot.digest


def test_old_record_and_unavailable_snapshot_authorize_no_quote() -> None:
    old = Violation(
        **json.loads(
            '{"rule_id":"semantic.supervisor.alignment","message":"old","severity":"low","citations":["quote"]}'
        )
    )
    assert old.provenance == "unknown"
    assert old.verified_citations == []
    for snapshot in (None, PlanSnapshot("/missing", None, None), PlanSnapshot(None, "quote", None)):
        assert verify_citations(["quote"], snapshot) == []


def test_verification_deduplicates_and_preserves_internal_whitespace() -> None:
    snapshot = PlanSnapshot("/plan", "use  two spaces", "d" * 64)
    assert len(verify_citations([" use  two spaces\n", "use  two spaces", "use two spaces", ""], snapshot)) == 1
