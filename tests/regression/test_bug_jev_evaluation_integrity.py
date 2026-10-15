"""Saved evaluations must preserve capture identity and expose unusable evidence."""

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json"
MODEL = "typesafe/jev-1.13-20260917"


@pytest.fixture
def evaluator(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-eval.py"
    spec = importlib.util.spec_from_file_location("jev_evaluation_integrity_regression", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _label(evaluator, case, outcome):
    case.adjudication = evaluator.Adjudication(
        outcome=outcome,
        reviewer="regression fixture author",
        review_reference="synthetic labels for tests only",
        case_sha256=evaluator.case_digest(case),
        question_answers={
            "coverage": True,
            "compatibility_retention": outcome == "warning",
            "independent_boundary": False,
        },
    )


def _response_size(prediction):
    prediction["response_bytes"] = len(json.dumps(prediction["response"]).encode())


@pytest.fixture
def inputs(evaluator):
    raw = json.loads(CORPUS.read_text())
    raw["cases"] = [
        case
        for case in raw["cases"]
        if case["id"] in {"module-forwarding", "module-direct-update", "decorator-instrumentation"}
    ]
    corpus = evaluator.Corpus.model_validate(raw)
    for case in corpus.cases:
        _label(
            evaluator,
            case,
            "warning" if case.id == "module-forwarding" else "no_warning",
        )
    prepared = {row["id"]: row for row in evaluator.prepare(corpus)["cases"]}
    saved = {
        "schema_version": 2,
        "source_kind": "fixture",
        "source_reference": "synthetic integrity regression",
        "expected_model": MODEL,
        "corpus_sha256": evaluator.corpus_digest(corpus),
        "prompt_sha256": evaluator.prompt_digest(),
        "split": "calibration",
        "repetitions": 1,
        "predictions": [],
    }
    for case in corpus.cases:
        if case.split != "calibration":
            continue
        response = {
            "model": MODEL,
            "usage": {"input_tokens": 1, "output_tokens": 0, "cost": 0.000001},
            "answers": {
                "coverage": {"type": "noul", "noul": 1.0},
                "compatibility_retention": {
                    "type": "noul",
                    "noul": 1.0 if case.id == "module-forwarding" else 0.0,
                },
                "independent_boundary": {"type": "noul", "noul": 0.0},
            },
        }
        row = {
            "case_id": case.id,
            "case_sha256": prepared[case.id]["case_sha256"],
            "payload_sha256": prepared[case.id]["payload_sha256"],
            "repetition": 1,
            "response": response,
            "status_code": 200,
            "latency_ms": 2.0,
        }
        _response_size(row)
        saved["predictions"].append(row)
    settings = evaluator.EvaluationSettings.model_validate(
        {
            "schema_version": 1,
            "decision_version": evaluator.DECISION_VERSION,
            "thresholds": {name: {"false_max": 0.1, "true_min": 0.9} for name in evaluator.questions()},
        }
    )
    return corpus, saved, settings


def _evaluate(evaluator, inputs):
    corpus, saved, settings = inputs
    return evaluator.evaluate(corpus, evaluator.SavedPredictions.model_validate(saved), settings)


def _metrics(report):
    return report["cohorts"]["constructed/calibration"]["repetitions"]["1"]


def test_held_out_edit_preserves_separately_bound_calibration_capture(evaluator, inputs):
    corpus, saved, _ = inputs
    before = _evaluate(evaluator, inputs)
    held_out = next(case for case in corpus.cases if case.split == "held_out")
    held_out.action.tool_input["new_string"] += "\n# Corrected held-out fixture comment.\n"
    held_out.adjudication = None
    assert evaluator.corpus_digest(corpus) == saved["corpus_sha256"]
    after = _evaluate(evaluator, inputs)
    assert after["cases"] == before["cases"]
    assert after["predictions_sha256"] == before["predictions_sha256"]


@pytest.mark.parametrize("model", ["typesafe/jev-1.13-20261101", "other/model"])
def test_snapshot_changes_cannot_be_pooled_as_repeated_input_variation(evaluator, inputs, model):
    _, saved, _ = inputs
    saved["repetitions"] = 2
    rotated = copy.deepcopy(saved["predictions"][0])
    rotated["repetition"] = 2
    rotated["response"]["model"] = model
    _response_size(rotated)
    saved["predictions"].append(rotated)
    with pytest.raises(ValueError, match=rotated["case_id"]):
        _evaluate(evaluator, inputs)


def test_host_conflicts_and_host_only_families_are_visible(evaluator, inputs):
    corpus, saved, _ = inputs
    raw = json.loads(CORPUS.read_text())
    for source in raw["cases"]:
        if source["id"] not in {"stable-alias", "write-without-history"}:
            continue
        case = evaluator.Case.model_validate(source)
        case.split = "calibration"
        case.family = "host-only-" + case.id
        _label(evaluator, case, "warning")
        corpus.cases.append(case)
    saved["corpus_sha256"] = evaluator.corpus_digest(corpus)
    report = _evaluate(evaluator, inputs)
    hosts = {row["id"]: row for row in report["host_cases"]}
    assert hosts["stable-alias"]["outcome"] == "not_applicable"
    assert hosts["write-without-history"]["outcome"] == "unavailable"
    assert all(row["expected_outcome"] == "warning" and row["diagnostic"] for row in hosts.values())
    assert "host_adjudication_conflicts" in report["blockers"]
    assert _metrics(report)["pipeline_effective_miss_rate"]["numerator"] == 2
    assert _metrics(report)["pipeline_effective_miss_rate"]["denominator"] == 3
    cohort = report["cohorts"]["constructed/calibration"]
    assert cohort["source_groups"] == 1
    assert cohort["host_only_source_groups"] == 2


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), "\ud800", {"not-json"}])
def test_invalid_response_encoding_names_the_case_before_digesting(evaluator, inputs, invalid):
    _, saved, _ = inputs
    prediction = saved["predictions"][0]
    prediction["response"]["provider_extra"] = invalid
    with pytest.raises(ValueError, match=prediction["case_id"]):
        evaluator.SavedPredictions.model_validate(saved)


def test_infrastructure_failures_and_insufficient_evidence_remain_distinct(evaluator, inputs):
    _, saved, _ = inputs
    failed, insufficient = saved["predictions"]
    failed.pop("response")
    failed.pop("status_code")
    failed.pop("response_bytes")
    failed["failure"] = "authentication"
    insufficient["response"]["answers"]["coverage"]["noul"] = 0.0
    _response_size(insufficient)
    report = _evaluate(evaluator, inputs)
    by_id = {row["id"]: row for row in report["cases"]}
    assert by_id[failed["case_id"]]["failure"] == "authentication"
    metrics = _metrics(report)
    assert metrics["saved_failures"] == {"authentication": 1}
    assert metrics["unavailable_reasons"] == {
        "jev_insufficient_evidence": 1,
        "jev_saved_failure": 1,
    }


@pytest.mark.parametrize(
    ("constant", "header", "new_value"),
    [
        ("RULE_ID", "rule_id", "coding_standards.changed-rule"),
        ("RULE_VERSION", "rule_version", "draft-3"),
        ("CONTRACT_VERSION", "evidence_contract_version", 4),
    ],
)
def test_corpus_headers_follow_current_shared_contract(evaluator, inputs, monkeypatch, constant, header, new_value):
    corpus, _, _ = inputs
    raw = corpus.model_dump()
    monkeypatch.setattr(evaluator, constant, new_value)
    with pytest.raises(ValueError):
        evaluator.Corpus.model_validate(raw)
    raw[header] = new_value
    assert getattr(evaluator.Corpus.model_validate(raw), header) == new_value


def test_settings_reject_previous_combiner_version(evaluator, inputs, monkeypatch):
    _, _, settings = inputs
    raw = settings.model_dump()
    monkeypatch.setattr(evaluator, "DECISION_VERSION", "draft-2")
    with pytest.raises(ValueError):
        evaluator.EvaluationSettings.model_validate(raw)
    raw["decision_version"] = "draft-2"
    assert evaluator.EvaluationSettings.model_validate(raw).decision_version == "draft-2"


def test_missing_observations_count_as_unknown_latency(evaluator, inputs):
    _, saved, _ = inputs
    saved["predictions"] = []
    metrics = _metrics(_evaluate(evaluator, inputs))
    assert metrics["latency_ms"] == {"known": 0, "unknown": 2, "p50": None, "p95": None}
    assert metrics["reported_cost_usd"]["unknown"] == 2


def test_rejected_answer_contract_never_reaches_calibration(evaluator, inputs, monkeypatch):
    _, saved, _ = inputs
    invalid = saved["predictions"][0]
    invalid["response"]["answers"]["unrequested"] = {"type": "noul", "noul": 0.5}
    _response_size(invalid)
    original = evaluator.assess_response

    def assert_valid(response, thresholds):
        assert "unrequested" not in response.answers, "Contract validation must precede assessment"
        return original(response, thresholds)

    monkeypatch.setattr(evaluator, "assess_response", assert_valid)
    report = _evaluate(evaluator, inputs)
    rejected = next(row for row in report["cases"] if row["id"] == invalid["case_id"])
    assert rejected["outcome"] == "unavailable" and rejected["probabilities"] == {}
    assert all(metric["count"] == 1 for metric in _metrics(report)["questions"].values())


@pytest.mark.parametrize("field,value", [("status_code", 500), ("response_bytes", 256_001)])
def test_wire_failures_are_not_scored_as_valid_answers(evaluator, inputs, field, value):
    _, saved, _ = inputs
    invalid = saved["predictions"][0]
    invalid[field] = value
    report = _evaluate(evaluator, inputs)
    rejected = next(row for row in report["cases"] if row["id"] == invalid["case_id"])
    assert rejected["outcome"] == "unavailable" and rejected["probabilities"] == {}
    assert all(metric["count"] == 1 for metric in _metrics(report)["questions"].values())


def test_original_wire_size_controls_admission_after_float_reserialization(evaluator, inputs):
    _, saved, _ = inputs
    prediction = saved["predictions"][0]
    body = json.dumps(prediction["response"], separators=(",", ":"))
    wire = (body[:-1] + ',"provider_extra":[' + ",".join(["1e-6"] * 45_000) + "]}").encode()
    prediction["response"] = json.loads(wire)
    prediction["response_bytes"] = len(wire)
    assert len(wire) <= evaluator.MAX_RESPONSE_BYTES
    # Parsing expands the exponent spelling on serialization; that is not the original HTTP body size.
    assert len(json.dumps(prediction["response"], separators=(",", ":")).encode()) > evaluator.MAX_RESPONSE_BYTES
    report = _evaluate(evaluator, inputs)
    row = next(row for row in report["cases"] if row["id"] == prediction["case_id"])
    assert row["outcome"] == "warning"
    assert all(metric["count"] == 2 for metric in _metrics(report)["questions"].values())


def test_report_binds_the_evaluator_and_shared_modules(evaluator, inputs):
    report = _evaluate(evaluator, inputs)
    assert len(report["evaluator_sha256"]) == 64
    sources = report["evaluator_sources"]
    paths = {
        "rule-pack-eval.py": Path(evaluator.__file__),
        "forge.policy.rule_pack.definitions": ROOT / "src/forge/policy/rule_pack/definitions.py",
        "forge.policy.rule_pack.outcomes": ROOT / "src/forge/policy/rule_pack/outcomes.py",
    }
    for name, path in paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sources[name]


@pytest.mark.parametrize("numerator,denominator,bound", [(0, 3, 0), (10, 10, 1)])
def test_wilson_interval_includes_its_extreme_point_estimate(evaluator, numerator, denominator, bound):
    rate = evaluator._rate(numerator, denominator)
    assert rate["wilson_95"][bound] == rate["value"]


def _cli_paths(tmp_path, inputs):
    corpus, saved, settings = inputs
    paths = []
    for name, value in (
        ("corpus", corpus.model_dump()),
        ("predictions", saved),
        ("settings", settings.model_dump()),
    ):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value))
        paths.append(path)
    return paths


def test_overflow_is_a_cli_error_instead_of_a_traceback(evaluator, inputs, tmp_path, monkeypatch, capsys):
    _, saved, _ = inputs
    for prediction in saved["predictions"]:
        prediction["response"]["usage"]["cost"] = 1e308
        _response_size(prediction)
    corpus, predictions, settings = _cli_paths(tmp_path, inputs)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval",
            str(corpus),
            "--predictions",
            str(predictions),
            "--settings",
            str(settings),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        evaluator.main()
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "error:" in error and "Traceback" not in error


@pytest.mark.parametrize("input_name", ["predictions", "settings"])
def test_nested_input_is_a_cli_error_instead_of_a_traceback(
    evaluator, inputs, tmp_path, monkeypatch, capsys, input_name
):
    corpus, predictions, settings = _cli_paths(tmp_path, inputs)
    target = predictions if input_name == "predictions" else settings
    # Predictions reach the decoder's nesting guard; the smaller settings cap rejects them before parsing.
    target.write_text("[" * 50_000 + "0" + "]" * 50_000)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval",
            str(corpus),
            "--predictions",
            str(predictions),
            "--settings",
            str(settings),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        evaluator.main()
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert target.name in error and "Traceback" not in error


def test_template_refuses_a_split_without_model_cases(evaluator, inputs, tmp_path, monkeypatch, capsys):
    corpus, _, _ = inputs
    corpus.cases = [case for case in corpus.cases if case.split == "held_out"]
    path = tmp_path / "held-out-only.json"
    path.write_text(corpus.model_dump_json())
    monkeypatch.setattr(
        sys,
        "argv",
        ["eval", str(path), "--prediction-template", "--expected-model", MODEL],
    )
    with pytest.raises(SystemExit) as exc:
        evaluator.main()
    assert exc.value.code == 2
    assert "calibration" in capsys.readouterr().err


def test_impossible_plan_is_rejected_before_creating_placeholder_rows(evaluator, inputs):
    corpus, saved, _ = inputs
    original = corpus.cases[0]
    corpus.cases = [original.model_copy(deep=True) for _ in range(51)]
    for index, case in enumerate(corpus.cases):
        case.id = f"planned-{index}"
    saved["corpus_sha256"] = evaluator.corpus_digest(corpus)
    saved["repetitions"] = 100
    saved["predictions"] = []
    with pytest.raises(ValueError, match="5.?000|5000"):
        _evaluate(evaluator, inputs)
