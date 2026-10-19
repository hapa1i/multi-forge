"""Draft-3 wording reopens only affected judgments and preserves original human evidence."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / "docs/board/paused/jev_rule_pack/evidence/diagnostic-review-2026-10-17-batch-6.json"
CHANGED = {
    "prior_definition",
    "proposed_definition",
    "replacement_definition",
    "consumer_constraint",
    "replacement_satisfies",
}


@pytest.fixture
def diagnostic(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "jev_diagnostic_precedence_regression", ROOT / "scripts/experiments/jev/rule-pack-diagnostic.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_draft2_human_ledger_requires_explicit_carry_and_keeps_all_original_records(diagnostic):
    original_bytes = LEGACY.read_bytes()
    previous = json.loads(original_bytes)
    original = copy.deepcopy(previous)
    assert diagnostic.reviews.validate_packet(previous)["answered_questions"] == 92
    with pytest.raises(ValueError, match="explicitly carry"):
        diagnostic.validate_review(previous)
    current = diagnostic.build_packet()
    assert current["diagnostic_version"] == "draft-3"
    assert current["contract"] == previous["contract"]
    carried = diagnostic.carry_review(previous)
    result = diagnostic.validate_review(carried)
    assert result["answered_questions"] == 32
    assert result["unanswered_questions"] == 63
    assert result["reviewed_cases"] == 0
    assert result["fully_answered_cases"] == 0
    assert result["carried_cases"] == 12
    assert result["contract_status"] == "pending"
    assert result["quality_accepted"] is False
    reopened = originally_pending = retained = 0
    receipt = next(iter(carried["review_sources"].values()))
    assert receipt["packet_sha256"] == previous["packet_sha256"]
    assert receipt["contract_review"] == previous["contract_review"]
    for old_case, new_case, carried_case in zip(previous["cases"], current["cases"], carried["cases"], strict=True):
        assert old_case["id"] == new_case["id"] == carried_case["id"]
        for field in ("action", "scope_facts", "targets", "transforms"):
            assert old_case[field] == new_case[field]
        assert set(old_case["questions"]) == set(new_case["questions"])
        assert receipt["cases"][old_case["id"]]["review"] == old_case["review"]
        assert carried_case["review"]["notes"] == ""
        assert carried_case["review_source"] is None
        for key, old_question in old_case["questions"].items():
            old_answer = old_case["review"]["answers"][key]
            changed = key.split(".", 1)[1] in CHANGED
            assert (old_question != new_case["questions"][key]) is changed
            new_answer = carried_case["review"]["answers"][key]
            if changed or old_answer is None:
                assert new_answer is None
                assert key not in carried_case["answer_sources"]
                reopened += old_answer is not None
                originally_pending += old_answer is None
            else:
                assert new_answer == old_answer
                assert carried_case["answer_sources"][key] in carried["review_sources"]
                retained += 1
    assert (reopened, originally_pending, retained) == (60, 3, 32)
    assert previous == original
    assert LEGACY.read_bytes() == original_bytes
