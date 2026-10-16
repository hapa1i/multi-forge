"""Moving a board card must preserve retained human reviews and evaluation identity."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
LEDGERS = ("human-review-2026-10-16.json",) + tuple(
    f"human-review-2026-10-16-batch-{batch}.json" for batch in range(2, 9)
)


@pytest.fixture
def evaluator(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-eval.py"
    spec = importlib.util.spec_from_file_location("jev_review_relocation_regression", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _replay(evaluator, evidence):
    original = json.loads((evidence / "wrapper-corpus.json").read_text())
    corpus = evaluator.Corpus.model_validate(original)
    for case in corpus.cases:
        case.adjudication = None
    for name in LEDGERS:
        packet = evaluator.ReviewPacket.model_validate_json((evidence / name).read_text())
        assert packet.review_reference == name
        corpus = evaluator.Corpus.model_validate(evaluator.import_review(corpus, packet))
    assert corpus.model_dump() == original
    for case in corpus.cases:
        assert case.adjudication is not None
        reference = case.adjudication.review_reference
        assert reference in LEDGERS
        packet = evaluator.ReviewPacket.model_validate_json((evidence / reference).read_text())
        reviewed = next(row for row in packet.cases if row.id == case.id)
        assert reviewed.review.status == "adjudicated"
        assert reviewed.case_sha256 == evaluator.case_digest(case)
    return corpus


def _reports(evaluator, corpus):
    # Empty observations exercise report identity without creating model or human answers.
    settings = evaluator.EvaluationSettings.model_validate(
        {
            "schema_version": 1,
            "decision_version": evaluator.DECISION_VERSION,
            "thresholds": {name: {"false_max": 0.1, "true_min": 0.9} for name in evaluator.questions()},
        }
    )
    reports = {}
    for split in ("calibration", "held_out"):
        saved = evaluator.SavedPredictions(
            schema_version=2,
            source_kind="fixture",
            source_reference="relocation regression with no observations",
            expected_model="typesafe/jev-1.13-20260917",
            corpus_sha256=evaluator.corpus_digest(corpus),
            prompt_sha256=evaluator.prompt_digest(),
            split=split,
            repetitions=1,
            predictions=[],
        )
        reports[split] = evaluator.evaluate(corpus, saved, settings)
    return reports


def test_retained_reviews_and_evaluation_identity_survive_card_closeout(evaluator, tmp_path):
    sources = list((ROOT / "docs/board").glob("*/jev_rule_pack/evidence"))
    assert len(sources) == 1
    card = tmp_path / "docs/board/doing/jev_rule_pack"
    evidence = card / "evidence"
    shutil.copytree(sources[0], evidence)
    before = _replay(evaluator, evidence)
    prepared = evaluator.prepare(before, include_payloads=True)
    reports = _reports(evaluator, before)
    ledger_bytes = {name: (evidence / name).read_bytes() for name in LEDGERS}

    closed_card = tmp_path / "docs/board/done/jev_rule_pack"
    closed_card.parent.mkdir(parents=True)
    card.rename(closed_card)
    relocated = closed_card / "evidence"
    assert not card.exists()
    after = _replay(evaluator, relocated)

    assert after.model_dump() == before.model_dump()
    assert {name: (relocated / name).read_bytes() for name in LEDGERS} == ledger_bytes
    assert evaluator.corpus_digest(after) == evaluator.corpus_digest(before)
    assert evaluator.review_packet(after) == evaluator.review_packet(before)
    # Preparation includes every case/prompt/payload hash; reports include adjudication hashes for both splits.
    assert evaluator.prepare(after, include_payloads=True) == prepared
    assert _reports(evaluator, after) == reports
