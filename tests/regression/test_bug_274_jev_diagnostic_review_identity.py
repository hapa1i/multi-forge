"""Unrelated provenance and questions must not discard reviewed diagnostic answers."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/board/paused/jev_rule_pack/evidence"


@pytest.fixture
def diagnostic(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "jev_diagnostic_identity_regression",
        ROOT / "scripts/experiments/jev/rule-pack-diagnostic.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(diagnostic):
    # Synthetic schema-1 review matches current semantics; these choices are validation fixtures, not human labels.
    packet = diagnostic.build_packet()
    packet["schema_version"] = 1
    packet.pop("review_sources")
    packet.pop("contract_review_source")
    packet["reviewer"] = "Synthetic identity-test reviewer"
    packet["review_reference"] = "synthetic-identity-review.json"
    packet["contract_review"] = {"status": "reviewed", "notes": "Synthetic contract review for identity tests."}
    nulls = {
        ("module-forwarding-without-history", "normalizer.consumer_constraint"),
        ("module-forwarding-without-history", "normalizer.replacement_satisfies"),
        ("module-forwarding-without-replacement", "normalizer.replacement_satisfies"),
    }
    for case in packet["cases"]:
        for key in diagnostic.reviews.CASE_V2:
            case.pop(key)
        case["review"] = {
            "status": "reviewed",
            "answers": {
                key: None if (case["id"], key) in nulls else next(iter(row["question"]["criteria"]))
                for key, row in case["questions"].items()
            },
            "notes": "Synthetic choices exercise identity validation, not semantic accuracy.",
        }
        case["case_sha256"] = diagnostic.digest(
            {key: value for key, value in case.items() if key not in {"case_sha256", "review"}}
        )
    immutable = copy.deepcopy(packet)
    for key in ("reviewer", "review_reference", "packet_sha256", "contract_review"):
        immutable.pop(key)
    for case in immutable["cases"]:
        case.pop("review")
    packet["packet_sha256"] = diagnostic.digest(immutable)
    return packet


def test_unchanged_legacy_ledger_can_be_validated_without_rewriting_it(diagnostic, source):
    before = copy.deepcopy(source)
    result = diagnostic.validate_review(source)
    assert result["answered_questions"] == 92
    assert result["unanswered_questions"] == 3
    assert result["contract_status"] == "reviewed"
    assert source == before


@pytest.mark.parametrize("provenance", ["active_prompt", "source_case", "rule_version"])
def test_unrelated_active_provenance_preserves_answers_notes_and_old_identities(
    diagnostic, source, monkeypatch, provenance
):
    old = copy.deepcopy(source)
    if provenance == "active_prompt":
        monkeypatch.setattr(diagnostic.evaluator, "prompt_digest", lambda: "a" * 64)
    elif provenance == "source_case":
        monkeypatch.setattr(diagnostic.evaluator, "case_digest", lambda case: "b" * 64)
    else:
        monkeypatch.setattr(diagnostic.evaluator, "RULE_VERSION", "future-active-rule")
        read_json = diagnostic.evaluator._read_json

        def new_corpus_header(path, limit):
            value = read_json(path, limit)
            if path == diagnostic.CORPUS:
                value["rule_version"] = "future-active-rule"
            return value

        monkeypatch.setattr(diagnostic.evaluator, "_read_json", new_corpus_header)
    assert diagnostic.validate_review(source)["answered_questions"] == 92
    result = diagnostic.carry_review(source)
    summary = diagnostic.validate_review(result)
    assert summary["answered_questions"] == 92
    assert summary["contract_status"] == "reviewed"
    assert summary["quality_accepted"] is False
    assert len(result["review_sources"]) == 1
    receipt = next(iter(result["review_sources"].values()))
    assert receipt["packet_sha256"] == source["packet_sha256"]
    assert receipt["active_reference"] == source["contract"]["active_reference"]
    assert receipt["reviewer"] == source["reviewer"]
    assert receipt["review_reference"] == source["review_reference"]
    for actual, previous in zip(result["cases"], source["cases"], strict=True):
        assert actual["review"] == previous["review"]
        recorded = receipt["cases"][actual["id"]]
        assert recorded["case_sha256"] == previous["case_sha256"]
        assert recorded["source_case_sha256"] == previous["source_case_sha256"]
    assert source == old


def test_changed_question_reuses_only_other_answers_without_claiming_a_new_case_review(diagnostic, source):
    current = diagnostic.build_packet()
    case = current["cases"][0]
    changed_key = next(iter(case["questions"]))
    case["questions"][changed_key]["question"]["instructions"] += " Changed semantic comparison."
    diagnostic.reviews.stamp_packet(current)
    result = diagnostic.reviews.carry_review(source, current)
    summary = diagnostic.reviews.validate_packet(result)
    assert summary["answered_questions"] == 91
    assert summary["contract_status"] == "pending"
    assert summary["carried_cases"] == 1
    assert result["cases"][0]["review"]["status"] == "carried"
    assert result["cases"][0]["review"]["notes"] == ""
    assert result["cases"][0]["review"]["answers"][changed_key] is None
    for key, previous in source["cases"][0]["review"]["answers"].items():
        if key != changed_key:
            assert result["cases"][0]["review"]["answers"][key] == previous
    receipt = next(iter(result["review_sources"].values()))
    assert receipt["cases"][case["id"]]["review"] == source["cases"][0]["review"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda packet: packet["cases"][0]["action"]["tool_input"].update(new_string="Changed supplied action"),
        lambda packet: packet["cases"][0]["scope_facts"].update(surface="public_stable"),
        lambda packet: packet["cases"][0]["targets"][0].update(selectors=["different_consumer"]),
        lambda packet: packet["cases"][0]["targets"][0]["anchors"][0].update(line=999),
        lambda packet: packet["cases"][0]["transforms"][0]["observations"].append("other_test()"),
        lambda packet: packet["cases"][0]["transforms"][0]["replacements"][0].update(new="other_registration"),
    ],
)
def test_changed_shared_case_context_invalidates_every_answer_in_that_case(diagnostic, source, mutation):
    current = diagnostic.build_packet()
    mutation(current)
    diagnostic.reviews.stamp_packet(current)
    result = diagnostic.reviews.carry_review(source, current)
    assert all(answer is None for answer in result["cases"][0]["review"]["answers"].values())
    assert result["cases"][0]["review"]["status"] == "pending"
    assert result["cases"][1]["review"] == source["cases"][1]["review"]
    assert result["contract_review"]["status"] == "pending"


def test_guard_change_invalidates_every_answer(diagnostic, source):
    current = diagnostic.build_packet()
    current["contract"]["guard"] += " Different authority boundary."
    diagnostic.reviews.stamp_packet(current)
    result = diagnostic.reviews.carry_review(source, current)
    summary = diagnostic.reviews.validate_packet(result)
    assert summary["answered_questions"] == 0
    assert summary["contract_status"] == "pending"
    assert result["review_sources"] == {}


@pytest.mark.parametrize("change", ["routing", "membership", "version"])
def test_contract_review_resets_without_unnecessarily_losing_unchanged_answers(diagnostic, source, change):
    current = diagnostic.build_packet()
    if change == "routing":
        current["contract"]["routing"] += " Proposed routing revision."
    elif change == "membership":
        current["cases"].pop()
    else:
        current["diagnostic_version"] = "next-draft"
    diagnostic.reviews.stamp_packet(current)
    result = diagnostic.reviews.carry_review(source, current)
    assert result["contract_review"] == {"status": "pending", "notes": ""}
    assert result["cases"][0]["review"] == source["cases"][0]["review"]
    assert diagnostic.reviews.validate_packet(result)["answered_questions"] > 0


@pytest.mark.parametrize("change", ["question", "case_hash", "packet_hash"])
def test_legacy_source_tampering_is_rejected_before_any_answer_is_carried(diagnostic, source, change):
    if change == "question":
        source["cases"][0]["questions"]["parser.retention"]["question"]["instructions"] = "Tampered question"
    elif change == "case_hash":
        source["cases"][0]["case_sha256"] = "0" * 64
    else:
        source["packet_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        diagnostic.carry_review(source)


def test_carry_receipts_are_flat_and_answer_bindings_are_verified(diagnostic, source):
    result = diagnostic.carry_review(source)
    original_receipts = copy.deepcopy(result["review_sources"])
    for _ in range(4):
        result = diagnostic.carry_review(result)
    assert result["review_sources"] == original_receipts
    assert diagnostic.validate_review(result)["answered_questions"] == 92
    case = result["cases"][0]
    case["review"]["answers"]["parser.prior_definition"] = "not_supplied"
    with pytest.raises(ValueError, match="source"):
        diagnostic.validate_review(result)


def test_changed_source_receipt_notes_are_rejected(diagnostic, source):
    result = diagnostic.carry_review(source)
    receipt = next(iter(result["review_sources"].values()))
    receipt["cases"][source["cases"][0]["id"]]["review"]["notes"] = "Fabricated human explanation"
    with pytest.raises(ValueError, match="receipt changed"):
        diagnostic.validate_review(result)


def test_cli_carry_emits_a_new_ledger_without_modifying_source(diagnostic, source, tmp_path, monkeypatch, capsys):
    path = tmp_path / "review.json"
    path.write_text(json.dumps(source))
    original = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["diagnostic", "--carry-review", str(path)])
    diagnostic.main()
    output = capsys.readouterr()
    migrated = json.loads(output.out)
    assert output.err == ""
    assert migrated["schema_version"] == 2
    assert diagnostic.validate_review(migrated)["answered_questions"] == 92
    assert path.read_bytes() == original


def test_new_human_review_can_fill_missing_answer_and_correct_a_carried_answer(diagnostic, source):
    current = diagnostic.build_packet()
    changed_key = "parser.prior_definition"
    corrected_key = "parser.proposed_definition"
    current["cases"][0]["questions"][changed_key]["question"]["instructions"] += " Revised structural wording."
    diagnostic.reviews.stamp_packet(current)
    result = diagnostic.reviews.carry_review(source, current)
    receipt_before = copy.deepcopy(result["review_sources"])
    case = result["cases"][0]
    result["reviewer"] = "Synthetic follow-up human reviewer"
    result["review_reference"] = "synthetic-follow-up-review.json"
    case["review"].update(status="reviewed", notes="Synthetic new review fills and corrects two answers.")
    case["review"]["answers"][changed_key] = "complete"
    case["review"]["answers"][corrected_key] = "not_supplied"
    # Changed human judgments are explicitly reattributed; unaffected answers keep their original sources.
    case["answer_sources"].pop(corrected_key)
    case["review_source"] = None
    result["contract_review"] = {"status": "reviewed", "notes": "Synthetic follow-up contract review."}
    result["contract_review_source"] = None
    summary = diagnostic.reviews.validate_packet(result)
    assert summary["answered_questions"] == 92
    assert summary["carried_cases"] == 0
    assert summary["contract_status"] == "reviewed"
    assert result["review_sources"] == receipt_before
    assert "parser.retention" in case["answer_sources"]


@pytest.mark.parametrize("malformed", [None, [], "not-a-case", {"review": {}}])
def test_malformed_source_receipt_cases_fail_with_a_validation_error(diagnostic, source, malformed):
    result = diagnostic.carry_review(source)
    receipt = next(iter(result["review_sources"].values()))
    receipt["cases"][source["cases"][0]["id"]] = malformed
    receipt["receipt_sha256"] = diagnostic.digest(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    with pytest.raises(ValueError, match="source case fields"):
        diagnostic.validate_review(result)
