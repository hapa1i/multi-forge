"""Check admission, exact accounting and fixed-label scoring without provider requests."""

import copy
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from forge.core.reactive.env import RunIdentity

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def results():
    spec = importlib.util.spec_from_file_location(
        "diagnostic_results_test",
        ROOT / "scripts/experiments/jev/diagnostic_results.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def plan():
    return json.loads((ROOT / "docs/board/retired/jev_rule_pack/evidence/bounded-capture-manifest.json").read_text())


def provider_body(plan, arm, case_id="validation-boundary"):
    payload = next(row for row in plan["payloads"] if row["arm"] == arm and row["case_id"] == case_id)
    gold = next(case["gold_answers"] for case in plan["scoring"]["cases"] if case["case_id"] == case_id)
    body = {
        "id": "fixture-provider-id",
        "provider": plan["arms"][arm]["provider_name"],
        "model": plan["arms"][arm]["response_models"][0],
    }
    if arm == "J":
        body["answers"] = {
            key: {
                "type": "choice",
                "choice": choice,
                "confidence": 1.0,
                "probabilities": {
                    option: float(option == choice) for option in payload["body"]["questions"][key]["criteria"]
                },
            }
            for key, choice in gold.items()
        }
        body["usage"] = {"input_tokens": 100, "output_tokens": 30, "cost": 0.000042}
    else:
        body["choices"] = [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(gold)},
            }
        ]
        body["usage"] = {"prompt_tokens": 100, "completion_tokens": 30, "cost": 0.001}
    return payload, body


def admit(results, plan, arm, body, payload=None, status=200, observed_model=None):
    if payload is None:
        payload = provider_body(plan, arm)[0]
    return results.assess_response(json.dumps(body).encode(), status, arm, payload, plan, observed_model)


def all_correct(plan):
    cases = {case["case_id"]: case for case in plan["scoring"]["cases"]}
    return [
        {
            **slot,
            "dispatched": True,
            "latency_ms": 1000,
            "request_id": f"request-{slot['slot']}",
            "event_id": f"evt-event-{slot['slot']}",
            "downstream_event_id": f"event-{slot['slot']}",
            "result": {
                "failure": None,
                "choices": dict(cases[slot["case_id"]]["gold_answers"]),
                "ties": [],
                "usage": {"cost": "0.001", "input_tokens": 100, "output_tokens": 30},
            },
        }
        for slot in plan["slots"]
    ]


@pytest.mark.parametrize("arm", ["J", "R"])
def test_valid_response_retains_only_allowlisted_fields_and_exact_reported_cost(results, plan, arm):
    payload, body = provider_body(plan, arm)
    body["private_provider_extension"] = "PRIVATE_SENTINEL"
    body["usage"]["unused_provider_field"] = "PRIVATE_SENTINEL"
    raw = json.dumps(body).replace(str(body["usage"]["cost"]), "0.000000499999999999999999999999999999999999")
    assessment = results.assess_response(raw.encode(), 200, arm, payload, plan)
    assert assessment["failure"] is None
    assert assessment["usage"]["cost"] == "4.99999999999999999999999999999999999E-7"
    assert assessment["provider_response_id"] == "fixture-provider-id"
    assert set(assessment["choices"]) == set(payload["question_ids"])
    assert "PRIVATE_SENTINEL" not in json.dumps(assessment)
    assert "answers" not in assessment and "response_body" not in assessment


def test_selected_choice_counts_even_when_reported_probabilities_tie(results, plan):
    payload, body = provider_body(plan, "J")
    key = "parser.prior_definition"
    options = list(body["answers"][key]["probabilities"])
    body["answers"][key]["probabilities"] = {option: 1 / len(options) for option in options}
    body["answers"][key]["confidence"] = 1 / len(options)
    assessment = admit(results, plan, "J", body, payload)
    assert assessment["failure"] is None
    assert assessment["ties"] == [key]
    assert assessment["choices"][key] == body["answers"][key]["choice"]


@pytest.mark.parametrize("arm", ["J", "R"])
@pytest.mark.parametrize(
    "cost,code",
    [
        (None, "missing_cost"),
        (True, "missing_cost"),
        ("0.01", "missing_cost"),
        (-0.01, "nonfinite_cost"),
        (float("nan"), "nonfinite_cost"),
        (float("inf"), "nonfinite_cost"),
        (2.0, "price_bound"),
    ],
)
def test_invalid_cost_stops_but_keeps_independent_tokens(results, plan, arm, cost, code):
    payload, body = provider_body(plan, arm)
    body["usage"]["cost"] = cost
    assessment = admit(results, plan, arm, body, payload)
    assert assessment["failure"] == code
    assert assessment["choices"] == {}
    assert assessment["usage"]["input_tokens"] == 100
    assert ("cost" in assessment["usage"]) == (code == "price_bound")


@pytest.mark.parametrize("arm", ["J", "R"])
@pytest.mark.parametrize(
    "field,value,code",
    [
        ("provider", "Another Provider", "changed_provider"),
        ("provider", None, "changed_provider"),
        ("model", "other/model", "changed_model"),
    ],
)
def test_identity_requires_expected_provider_and_allowed_model(results, plan, arm, field, value, code):
    payload, body = provider_body(plan, arm)
    body[field] = value
    assessment = admit(results, plan, arm, body, payload)
    assert assessment["failure"] == code
    assert assessment["usage"]["cost"]


def test_model_may_not_change_between_allowed_response_names(results, plan):
    payload, body = provider_body(plan, "R")
    body["model"] = plan["arms"]["R"]["response_models"][1]
    assert admit(results, plan, "R", body, payload)["failure"] is None
    assert (
        admit(
            results,
            plan,
            "R",
            body,
            payload,
            observed_model=plan["arms"]["R"]["response_models"][0],
        )["failure"]
        == "changed_model"
    )


@pytest.mark.parametrize(
    "arm,field,value",
    [
        ("J", "input_tokens", 320_001),
        ("R", "prompt_tokens", 32_001),
        ("R", "completion_tokens", 4097),
    ],
)
def test_reserved_token_bounds_stop_after_retaining_reported_usage(results, plan, arm, field, value):
    payload, body = provider_body(plan, arm)
    body["usage"][field] = value
    assessment = admit(results, plan, arm, body, payload)
    assert assessment["failure"] == "token_bound"
    assert value in assessment["usage"].values()


@pytest.mark.parametrize(
    "field,value",
    [("input_tokens", True), ("input_tokens", -1), ("output_tokens", "5")],
)
def test_invalid_counts_do_not_discard_valid_cost(results, plan, field, value):
    payload, body = provider_body(plan, "J")
    body["usage"][field] = value
    assessment = admit(results, plan, "J", body, payload)
    assert assessment["failure"] == "schema_mismatch"
    assert field not in assessment["usage"]
    assert Decimal(assessment["usage"]["cost"]) == Decimal("0.000042")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda body: body["answers"].pop("parser.prior_definition"),
        lambda body: body["answers"]["parser.prior_definition"].update(choice="invented"),
        lambda body: body["answers"]["parser.prior_definition"].update(probabilities={"invented": 1.0}),
        lambda body: body["answers"]["parser.prior_definition"].update(confidence=True),
    ],
)
def test_jev_uses_existing_typed_question_contract(results, plan, mutation):
    payload, body = provider_body(plan, "J")
    mutation(body)
    assessment = admit(results, plan, "J", body, payload)
    assert assessment["failure"] == "schema_mismatch"
    assert assessment["choices"] == {}
    assert assessment["usage"]["cost"]


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda b: b["choices"].append(copy.deepcopy(b["choices"][0])),
            "schema_mismatch",
        ),
        (lambda b: b["choices"][0].update(finish_reason="length"), "truncated_answer"),
        (
            lambda b: b["choices"][0].update(finish_reason="tool_calls"),
            "malformed_answer",
        ),
        (
            lambda b: b["choices"][0]["message"].update(tool_calls=[{}]),
            "malformed_answer",
        ),
        (lambda b: b["choices"][0]["message"].update(refusal="No"), "malformed_answer"),
        (lambda b: b["choices"][0]["message"].update(content=[]), "schema_mismatch"),
        (lambda b: b["choices"][0]["message"].update(content="{}"), "schema_mismatch"),
        (
            lambda b: b["choices"][0]["message"].update(content="```json\n{}\n```"),
            "malformed_answer",
        ),
    ],
)
def test_reference_requires_single_finished_exact_answer_object(results, plan, mutation, code):
    payload, body = provider_body(plan, "R")
    mutation(body)
    assessment = admit(results, plan, "R", body, payload)
    assert assessment["failure"] == code
    assert assessment["choices"] == {}
    assert assessment["usage"]["cost"]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"model":"one","model":"two"}',
        b'"\\ud800"',
        b"\xff",
        b"[" * 40 + b"0" + b"]" * 40,
        b'{"usage":',
        b'{"usage":{"cost":1,"cost":2}}',
    ],
)
def test_ambiguous_invalid_unicode_and_deep_json_are_rejected_without_raw_content(results, plan, raw):
    assessment = results.assess_response(raw, 200, "J", plan["payloads"][0], plan)
    assert assessment["failure"] == "malformed_answer"
    assert assessment["usage"] == {}


def test_duplicate_reference_answer_keys_retain_valid_outer_accounting(results, plan):
    payload, body = provider_body(plan, "R")
    body["choices"][0]["message"]["content"] = '{"x":"yes","x":"no"}'
    assessment = admit(results, plan, "R", body, payload)
    assert assessment["failure"] == "malformed_answer"
    assert assessment["usage"]["cost"] == "0.001"


def test_nonfinite_extra_fields_are_rejected_without_losing_accounting(results, plan):
    payload, body = provider_body(plan, "J")
    body["extra"] = float("nan")
    assessment = admit(results, plan, "J", body, payload)
    assert assessment["failure"] == "malformed_answer"
    assert assessment["usage"]["cost"]


@pytest.mark.parametrize("number", ["1e-999999999", "1e999999999"])
def test_short_decimal_exponent_cannot_force_unbounded_accounting_memory(results, plan, number):
    payload, body = provider_body(plan, "R")
    raw = json.dumps(body).replace("0.001", number).encode()
    assessment = results.assess_response(raw, 200, "R", payload, plan)
    assert assessment["failure"] == "malformed_answer"
    assert assessment["choices"] == {}


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication"),
        (403, "authentication"),
        (429, "non_200"),
        (503, "non_200"),
    ],
)
def test_http_failure_retains_valid_accounting(results, plan, status, code):
    payload, body = provider_body(plan, "R")
    assessment = admit(results, plan, "R", body, payload, status=status)
    assert assessment["failure"] == code
    assert assessment["usage"]["cost"]


@pytest.mark.parametrize("status,code", [(401, "authentication"), (503, "non_200")])
def test_http_failure_classification_survives_non_json_error_body(results, plan, status, code):
    assessment = results.assess_response(b"<html>error</html>", status, "J", plan["payloads"][0], plan)
    assert assessment["failure"] == code
    assert assessment["usage"] == {}


def test_oversized_response_stops_before_parse(results, plan):
    assessment = results.assess_response(
        b" " * (plan["limits"]["max_response_bytes"] + 1),
        200,
        "J",
        plan["payloads"][0],
        plan,
    )
    assert assessment["failure"] == "response_or_journal_overflow"


def test_complete_report_has_planned_observed_denominators_and_no_quality_acceptance(results, plan):
    attempts = all_correct(plan)
    report = results.build_report(plan, attempts, local_seconds={"J": 1.5, "R": 2.5})
    assert report["complete"] and report["decision"] == "investigate further"
    assert report["quality_accepted"] is False
    assert report["paired_comparison"]["observed"] == 285
    for arm in report["arms"].values():
        assert arm["outcome"] == "pass"
        assert arm["agreement"] == {
            "planned": 285,
            "observed": 285,
            "correct": 285,
            "agreement_fraction": 1.0,
            "probability_ties": 0,
        }
        assert len(arm["questions"]) == 95
        assert len(arm["cases"]) == 12
        assert arm["families"]["module-rename"]["case_count"] == 5
        assert arm["derived_families"]["module-rename"]["case_count"] == 6
        assert arm["predicate_groups"]["prior_definition"]["observed"] > 0
        assert arm["planned_requests"] == arm["dispatched_requests"] == 36


def test_critical_requires_three_correct_but_other_questions_allow_one_error(results, plan):
    attempts = all_correct(plan)
    first = attempts[0]
    first["result"]["choices"]["parser.prior_definition"] = "not_supplied"
    assert results.build_report(plan, attempts)["arms"]["J"]["outcome"] == "pass"
    first["result"]["choices"]["parser.consumer_constraint"] = "invented-for-report-test"
    assert results.build_report(plan, attempts)["arms"]["J"]["outcome"] == "fail"


def test_semantic_stop_counts_second_same_sentinel_error_and_not_ties_or_failures(results, plan):
    attempts = all_correct(plan)[:6]
    rows = [row for row in attempts if row["arm"] == "J"]
    key = "parser.prior_definition"
    rows[0]["result"]["choices"][key] = "partial"
    rows[1]["result"]["choices"][key] = "not_supplied"
    rows[2]["result"]["ties"] = [key]
    stopped = results.semantic_stop(plan, attempts, "J")
    assert stopped == [
        {
            "case_id": "validation-boundary",
            "question_id": key,
            "noncorrect_observations": 2,
        }
    ]
    assert results.semantic_stop(plan, attempts, "R") == []
    rows[1]["result"]["failure"] = "schema_mismatch"
    assert results.semantic_stop(plan, attempts, "J") == []


def test_injection_must_match_uninjected_answer_in_the_same_repetition(results, plan):
    attempts = all_correct(plan)
    control = next(
        row
        for row in attempts
        if row["arm"] == "R" and row["case_id"] == "callback-protocol" and row["repetition"] == 2
    )
    control["result"]["choices"]["callback.prior_definition"] = "not_supplied"
    report = results.build_report(plan, attempts)
    assert report["arms"]["R"]["outcome"] == "fail"
    question = next(
        row
        for row in report["arms"]["R"]["questions"]
        if row["case_id"] == "callback-protocol-injection" and row["question_id"] == "callback.prior_definition"
    )
    assert question["correct"] == 3
    assert question["passed"] is False
    assert [row["injection_pair_correct"] for row in question["observations"]] == [
        True,
        False,
        True,
    ]


def test_missing_arm_never_supplies_comparison_wins_and_unknown_cost_is_not_zero(results, plan):
    attempts = all_correct(plan)
    attempts = [row for row in attempts if row["arm"] == "R"]
    attempts[0]["result"].update(failure="timeout", choices={}, usage={})
    report = results.build_report(plan, attempts, stop_reason="timeout")
    assert report["arms"]["J"]["outcome"] == "unknown"
    assert report["arms"]["R"]["outcome"] == "unknown"
    assert report["paired_comparison"]["observed"] == 0
    assert report["paired_comparison"]["R_only_correct"] == 0
    assert report["decision"] == "revise"
    assert report["unknown_cost_attempts"] == 1
    assert Decimal(report["known_spend_usd"]) == Decimal("0.035")
    assert report["arms"]["R"]["technical_failure_count"] == 1
    assert report["arms"]["R"]["latency"]["timeout_count"] == 1


def test_latency_median_nearest_rank_p95_and_strict_five_second_threshold(results, plan):
    attempts = all_correct(plan)[:6]
    j_rows = [row for row in attempts if row["arm"] == "J"]
    for row, latency in zip(j_rows, (1000, 5000, 9000)):
        row["latency_ms"] = latency
    latency = results.build_report(plan, attempts)["arms"]["J"]["latency"]
    assert latency["p50_ms"] == 5000
    assert latency["p95_nearest_rank_ms"] == latency["max_ms"] == 9000
    assert latency["exceeding_5s_count"] == 1
    assert latency["exceeding_5s_fraction"] == 1 / 3


def test_report_refuses_duplicate_or_moved_slots(results, plan):
    attempts = all_correct(plan)
    with pytest.raises(ValueError, match="twice"):
        results.build_report(plan, attempts + [attempts[0]])
    attempts[0]["repetition"] = 3
    with pytest.raises(ValueError, match="frozen slot"):
        results.build_report(plan, attempts)


@pytest.mark.parametrize("failure", ["network", "timeout", "interruption", "unsafe_persistence"])
def test_outer_attempt_failure_overrides_valid_body_for_scoring_and_stops(results, plan, failure):
    attempts = all_correct(plan)
    attempt = attempts[0]
    attempt["failure"] = failure
    attempt["result"]["choices"]["parser.prior_definition"] = "partial"
    report = results.build_report(plan, attempts, stop_reason=failure)
    assert report["arms"]["J"]["technical_failures"] == {failure: 1}
    assert report["arms"]["J"]["outcome"] == "unknown"
    assert report["arms"]["J"]["agreement"]["observed"] == 275
    assert report["paired_comparison"]["observed"] == 275
    assert results.semantic_stop(plan, [attempt], "J") == []
    assert report["arms"]["J"]["latency"]["timeout_count"] == int(failure == "timeout")


def test_both_semantic_stops_are_not_a_technical_interruption(results, plan):
    attempts = all_correct(plan)[:4]
    for attempt in attempts:
        attempt["result"]["choices"]["parser.prior_definition"] = "not_supplied"
    report = results.build_report(plan, attempts, stop_reason="both_arms_semantic_stop")
    assert report["decision"] == "stop"
    assert {arm["outcome"] for arm in report["arms"].values()} == {"fail"}
    assert all(arm["technical_failure_count"] == 0 for arm in report["arms"].values())


def test_spend_summary_preserves_all_provider_decimal_digits(results, plan):
    attempts = all_correct(plan)[:2]
    attempts[0]["result"]["usage"]["cost"] = "0.000000499999999999999999999999999999999999"
    attempts[1]["result"]["usage"]["cost"] = "0.000000000000000000000000000000000000000001"
    report = results.build_report(plan, attempts)
    assert Decimal(report["known_spend_usd"]) == Decimal("0.0000005")


def test_telemetry_uses_existing_schema_and_rounding_without_float_precision_loss(results, plan, monkeypatch):
    downstream, usage_events = [], []
    monkeypatch.setattr("forge.core.judgments.usage.write_downstream_record", downstream.append)
    monkeypatch.setattr("forge.core.judgments.usage.log_usage_event", usage_events.append)
    attempt = all_correct(plan)[0]
    attempt["result"].update(
        model=plan["arms"]["J"]["response_models"][0],
        provider="TypeSafe",
        provider_response_id="provider-id",
    )
    cost = "0.000000499999999999999999999999999999999999"
    attempt["result"]["usage"]["cost"] = cost
    identity = RunIdentity(run_id="run-j", root_run_id="run-root", parent_run_id="run-root")
    results.emit_telemetry(attempt, plan, identity)
    assert len(downstream) == len(usage_events) == 1
    assert downstream[0].request_id == attempt["request_id"]
    assert downstream[0].downstream_event_id == attempt["downstream_event_id"]
    assert downstream[0].forge_run_id == "run-j"
    assert downstream[0].cost_micros == 0
    assert usage_events[0].cost_micro_usd == 0
    assert attempt["result"]["usage"]["cost"] == cost
