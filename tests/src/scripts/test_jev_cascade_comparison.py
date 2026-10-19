"""Compare offline controls without treating human labels as predictions or paid approval."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/board/retired/jev_cascade/evidence"
SCRIPT = ROOT / "scripts/experiments/jev/cascade-offline.py"


@pytest.fixture
def study(monkeypatch):
    spec = importlib.util.spec_from_file_location("jev_cascade_comparison_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    corpus = module.Corpus.model_validate(module.load_json(EVIDENCE / "cascade-corpus.json"))
    reviews = module.validate_reviews(corpus, module.load_json(EVIDENCE / "human-review-ledger.json"))
    return module, corpus, reviews


def test_completed_cohort_has_no_incremental_positive_opportunity(study):
    module, corpus, reviews = study
    report = module.prepare(corpus, reviews)
    overall = report["comparison"]["overall"]
    assert overall["cases"] == overall["labelled_cases"] == 24
    assert overall["host_exclusions"] == overall["model_candidates"] == 12
    assert overall["human_expected_allows"] == overall["eligible_divergent_cases"] == 6
    assert overall["controls"] == {
        "always_escalate_control": {"correct_allow": 0, "false_allow": 0, "missed_allow": 6, "correct_escalation": 18},
        "deterministic_control": {"correct_allow": 6, "false_allow": 0, "missed_allow": 0, "correct_escalation": 18},
    }
    assert overall["incremental_positive_cases"] == []
    assert len(overall["distinct_allow_certificates"]) == 4
    for split in report["comparison"]["by_split"].values():
        assert split["cases"] == 12
        assert split["host_exclusions"] == split["model_candidates"] == 6
        assert split["human_expected_allows"] == split["eligible_divergent_cases"] == 3
        assert split["incremental_positive_cases"] == []
    preflight = report["calibration_preflight"]
    assert preflight["status"] == "stop"
    assert set(preflight["blockers"]) == {f"no_incremental_positive:{f.id}" for f in corpus.families}
    assert preflight["conditional_slots_by_split"] == {"calibration": 18, "held_out": 18}
    assert preflight["selected_minimum_true"] is None
    assert not preflight["paid_capture_authorized"] and not preflight["selection_implemented"]
    assert not report["quality_accepted"] and report["max_physical_requests"] == 0


def test_host_exclusions_are_separate_from_evidence_ready(study):
    module, corpus, reviews = study
    report = module.prepare(corpus, reviews)
    assert sum(row["human_evidence_ready"] for row in report["cases"]) == 13
    row = next(row for row in report["cases"] if row["id"] == "data-transformation-04")
    assert row["human_evidence_ready"] and not row["model_candidate"]
    assert row["deterministic_control"]["route"] == "escalate"
    assert row["human_expected_route"] == "escalate"


def test_pending_labels_do_not_create_a_no_benefit_conclusion(study):
    module, corpus, _ = study
    pending = module.validate_reviews(corpus, module.review_packet(corpus))
    report = module.prepare(corpus, pending)
    assert report["comparison"]["overall"]["labelled_cases"] == 0
    assert report["comparison"]["overall"]["unlabelled_cases"] == 24
    assert report["calibration_preflight"]["blockers"] == ["human_review_incomplete"]
    assert all(row["deterministic_control"]["route"] == "escalate" for row in report["cases"])


def test_altered_labels_change_comparison_not_baseline_prediction(study):
    module, corpus, reviews = study
    key = "file-operation-01"
    reviews[key] = reviews[key].model_copy(
        update={"answers": {question: False for question in reviews[key].answers}, "expected_route": "escalate"}
    )
    report = module.prepare(corpus, reviews)
    row = next(row for row in report["cases"] if row["id"] == key)
    assert row["deterministic_control"]["route"] == "allow"
    assert report["comparison"]["overall"]["controls"]["deterministic_control"]["false_allow"] == 1
    assert report["calibration_preflight"]["blockers"] == [f"deterministic_false_allow:{key}"]


def test_inconsistent_human_route_cannot_enable_capture_proposal(study):
    module, corpus, reviews = study
    key = "bounded-processing-02"
    reviews[key] = reviews[key].model_copy(update={"expected_route": "allow"})
    report = module.prepare(corpus, reviews)
    assert f"human_route_answer_conflict:{key}" in report["calibration_preflight"]["blockers"]


def test_passing_offline_gate_selects_no_threshold_and_authorizes_no_calls(study, monkeypatch):
    module, corpus, reviews = study
    monkeypatch.setattr(
        module,
        "deterministic_assessment",
        lambda *args: {"route": "escalate", "reasons": ["synthetic_test_abstention"], "certificate": None},
    )
    report = module.prepare(corpus, reviews)
    preflight = report["calibration_preflight"]
    assert preflight["status"] == "ready_for_capture_proposal" and not preflight["blockers"]
    assert preflight["candidate_minimum_true"] == [0.60, 0.70, 0.80, 0.90, 0.95, 0.99, 1.00]
    assert all(preflight["incremental_positive_cases_by_family"].values())
    assert preflight["selected_minimum_true"] is None
    assert not preflight["paid_capture_authorized"]
    assert report["max_physical_requests"] == 0
