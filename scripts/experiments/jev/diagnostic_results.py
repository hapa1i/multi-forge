"""Admit bounded diagnostic responses and report the frozen human-label comparison."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from decimal import Decimal, localcontext
from statistics import median
from typing import Any, cast

from forge.core.judgments.types import (
    ChoiceQuestion,
    JudgmentAttempt,
    JudgmentResponse,
    Question,
    ReportedUsage,
    validate_answers,
)
from forge.core.judgments.usage import emit_attempt as emit_judgment_attempt
from forge.core.reactive.env import RunIdentity

MAX_JSON_DEPTH = 32
# A short exponent can otherwise demand gigabytes when exact reported costs are summed.
MAX_DECIMAL_EXPONENT = 256_000


def assess_response(
    raw: bytes,
    status: int | None,
    arm: str,
    payload: dict[str, Any],
    plan: dict[str, Any],
    observed_model: str | None = None,
) -> dict[str, Any]:
    """Return only validated answers and independently valid accounting; never retain provider prose."""
    result: dict[str, Any] = {
        "failure": None,
        "status_code": status,
        "model": None,
        "provider": None,
        "provider_response_id": None,
        "usage": {},
        "choices": {},
        "ties": [],
    }
    if len(raw) > plan["limits"]["max_response_bytes"]:
        return {**result, "failure": "response_or_journal_overflow"}
    http_failure = "authentication" if status in {401, 403} else "non_200" if status != 200 else None
    try:
        body = _parse_json(raw)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        return {**result, "failure": http_failure or "malformed_answer"}
    if not isinstance(body, dict):
        return {**result, "failure": http_failure or "schema_mismatch"}
    _partial_metadata(body, arm, result)
    usage = result["usage"]
    raw_usage = body.get("usage")
    raw_cost = raw_usage.get("cost") if isinstance(raw_usage, dict) else None
    failure: str | None
    if http_failure:
        failure = http_failure
    elif raw_cost is None:
        failure = "missing_cost"
    elif not isinstance(raw_cost, (int, Decimal)) or isinstance(raw_cost, bool):
        failure = "missing_cost"
    elif not Decimal(raw_cost).is_finite() or raw_cost < 0:
        failure = "nonfinite_cost"
    elif Decimal(usage["cost"]) > Decimal(payload["per_request_planning_usd"]):
        failure = "price_bound"
    elif result["provider"] != plan["arms"][arm]["provider_name"]:
        failure = "changed_provider"
    elif result["model"] not in plan["arms"][arm]["response_models"] or (
        observed_model is not None and result["model"] != observed_model
    ):
        failure = "changed_model"
    elif not {"input_tokens", "output_tokens"} <= usage.keys():
        failure = "schema_mismatch"
    elif usage["input_tokens"] > plan["limits"]["input_tokens_per_question_bound"] * (
        len(payload["question_ids"]) if arm == "J" else 1
    ) or (arm == "R" and usage["output_tokens"] > plan["limits"]["reference_max_output_tokens_including_reasoning"]):
        failure = "token_bound"
    else:
        failure = _admit_answers(body, arm, payload, result)
    result["failure"] = failure
    return result


def semantic_stop(plan: dict[str, Any], attempts: list[dict[str, Any]], arm: str) -> list[dict[str, Any]]:
    """Find repeated sentinel errors among valid selected answers, excluding technical failures and ties."""
    bad: Counter[tuple[str, str]] = Counter()
    cases = {case["case_id"]: case for case in plan["scoring"]["cases"]}
    for attempt in attempts:
        result = _result(attempt)
        if attempt["arm"] != arm or not attempt.get("dispatched", True) or result.get("failure"):
            continue
        case = cases[attempt["case_id"]]
        for key in case["sentinel_keys"]:
            if key in result.get("choices", {}) and result["choices"][key] != case["gold_answers"][key]:
                bad[(case["case_id"], key)] += 1
    threshold = plan["scoring"]["semantic_stop"]["noncorrect_repetitions_of_same_case_question"]
    return [
        {"case_id": case_id, "question_id": key, "noncorrect_observations": count}
        for (case_id, key), count in sorted(bad.items())
        if count >= threshold
    ]


def emit_telemetry(attempt: dict[str, Any], plan: dict[str, Any], identity: RunIdentity) -> None:
    """Use the production v2 attempt emitter while keeping exact provider cost until its microdollar rounding."""
    result = _result(attempt)
    usage = result.get("usage", {})
    exact_cost = Decimal(usage["cost"]) if "cost" in usage else None
    # ReportedUsage predates the experiment and annotates float. Its emitter uses Decimal(str(cost));
    # retaining a Decimal here avoids a lossy float round trip before its existing ROUND_HALF_UP owner.
    reported = ReportedUsage(
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cost=cast(float, exact_cost),
    )
    failure = result.get("failure") or attempt.get("failure")
    telemetry_failure = "ambiguous_timeout" if failure == "timeout" else failure
    with localcontext() as context:
        context.prec = max(28, len(exact_cost.as_tuple().digits) + 10) if exact_cost is not None else 28
        emit_judgment_attempt(
            JudgmentAttempt(
                request_id=attempt["request_id"],
                downstream_event_id=attempt["downstream_event_id"],
                requested_model=plan["arms"][attempt["arm"]]["requested_model"],
                latency_ms=attempt["latency_ms"],
                status_code=result.get("status_code"),
                failure=telemetry_failure,
                model=result.get("model"),
                provider=result.get("provider"),
                provider_response_id=result.get("provider_response_id"),
                usage=reported if usage else None,
            ),
            identity=identity,
            session=None,
            grouping=None,
            command=f"jev-diagnostic-{attempt['arm'].lower()}",
            direct=True,
        )


def build_report(
    plan: dict[str, Any],
    attempts: list[dict[str, Any]],
    *,
    stop_reason: str | None = None,
    stopped_arms: dict[str, Any] | None = None,
    local_seconds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Score fixed repetitions against existing human labels, leaving unfinished comparisons unknown."""
    indexed = _index_attempts(plan, attempts)
    arms = {}
    for arm in plan["arms"]:
        questions = _question_results(plan, indexed, arm)
        admitted = [row for row in attempts if row["arm"] == arm and row.get("dispatched", True)]
        semantic_failures = semantic_stop(plan, attempts, arm)
        complete = all(row["observed"] == row["planned"] for row in questions)
        passed = complete and all(row["passed"] for row in questions)
        outcome = "pass" if passed else "fail" if complete or semantic_failures else "unknown"
        costs = [Decimal(_result(row)["usage"]["cost"]) for row in admitted if _known_cost(row)]
        technical = [row for row in admitted if _result(row).get("failure")]
        arms[arm] = {
            "outcome": outcome,
            "complete": complete,
            "quality_accepted": False,
            "planned_requests": sum(slot["arm"] == arm for slot in plan["slots"]),
            "dispatched_requests": len(admitted),
            "undispatched_requests": sum(slot["arm"] == arm for slot in plan["slots"]) - len(admitted),
            "technical_failure_count": len(technical),
            "technical_failures": dict(Counter(_result(row)["failure"] for row in technical)),
            "sentinel_stops": semantic_failures,
            "stopped": bool(semantic_failures or (stopped_arms or {}).get(arm)),
            "known_spend_usd": str(_sum_costs(costs)),
            "unknown_cost_attempts": len(admitted) - len(costs),
            "local_seconds": (local_seconds or {}).get(arm),
            "latency": _latency(admitted),
            "questions": questions,
            "cases": _aggregate_questions(questions, "case_id"),
            "families": _aggregate_questions(questions, "family"),
            "derived_families": _aggregate_questions(questions, "derived_families"),
            "predicate_groups": _aggregate_questions(questions, "predicate_group"),
            "agreement": _agreement(questions),
        }
    complete = all(arm["complete"] for arm in arms.values())
    passing = [name for name, arm in arms.items() if arm["outcome"] == "pass"]
    if stop_reason and stop_reason != "both_arms_semantic_stop":
        decision, interpretation = (
            "revise",
            "Technical interruption leaves unfinished semantic claims unknown.",
        )
    elif passing:
        decision = "investigate further"
        interpretation = (
            "A separately approved feasibility step may investigate the passing arm; no runtime acceptance follows."
        )
    elif any(arm["outcome"] == "unknown" for arm in arms.values()):
        decision, interpretation = (
            "revise",
            "The incomplete comparison cannot establish an arm's diagnostic pass.",
        )
    else:
        decision, interpretation = (
            "stop",
            "Neither model/formulation pairing passes the frozen diagnostic screen.",
        )
    return {
        "schema_version": 1,
        "manifest_sha256": plan["manifest_sha256"],
        "quality_accepted": False,
        "complete": complete,
        "decision": decision,
        "interpretation": interpretation,
        "stop_reason": stop_reason,
        "arms": arms,
        "paired_comparison": _paired_results(plan, indexed),
        "known_spend_usd": str(_sum_costs([Decimal(row["known_spend_usd"]) for row in arms.values()])),
        "unknown_cost_attempts": sum(row["unknown_cost_attempts"] for row in arms.values()),
        "limitations": [
            "Synthetic cases and human-selected targets do not establish production accuracy or automatic selection.",
            "Repetitions are not independent cases; shared templates and prior exposure limit generalization.",
            "A reference success does not identify the cause of a Jev failure.",
            "Missing or stopped observations provide no paired wins; reported costs are not a guaranteed invoice cap.",
        ],
    }


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _result(attempt: dict[str, Any]) -> dict[str, Any]:
    value = attempt.get("result", attempt)
    return {**value, "failure": attempt.get("failure") or value.get("failure")}


def _sum_costs(values: list[Decimal]) -> Decimal:
    if not values:
        return Decimal(0)
    with localcontext() as context:
        context.prec = max(
            28,
            max(value.adjusted() for value in values)
            - min(int(value.as_tuple().exponent) for value in values)
            + len(str(len(values)))
            + 2,
        )
        return sum(values, Decimal(0))


def _parse_json(raw: bytes | str) -> Any:
    value = json.loads(
        raw.decode("utf-8") if isinstance(raw, bytes) else raw,
        object_pairs_hook=_pairs,
        parse_float=_decimal_value,
        parse_constant=Decimal,
    )
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError("JSON nesting limit exceeded")
        if isinstance(item, dict):
            pending.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif isinstance(item, list):
            pending.extend((part, depth + 1) for part in item)
        elif isinstance(item, str):
            item.encode("utf-8")
    return value


def _decimal_value(value: str) -> Decimal:
    number = Decimal(value)
    if abs(int(number.as_tuple().exponent)) > MAX_DECIMAL_EXPONENT:
        raise ValueError("JSON decimal exponent exceeds the bounded accounting limit")
    return number


def _partial_metadata(body: dict[str, Any], arm: str, result: dict[str, Any]) -> None:
    for source, target in (
        ("model", "model"),
        ("provider", "provider"),
        ("id", "provider_response_id"),
    ):
        value = body.get(source)
        if isinstance(value, str) and value.strip() and len(value) <= 256 and all(ord(char) >= 32 for char in value):
            result[target] = value
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return
    fields = (
        (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"))
        if arm == "J"
        else (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"))
    )
    for source, target in fields:
        value = usage.get(source)
        if type(value) is int and value >= 0:
            result["usage"][target] = value
    cost = usage.get("cost")
    if type(cost) is int or isinstance(cost, Decimal):
        amount = Decimal(cost)
        if amount.is_finite() and amount >= 0:
            result["usage"]["cost"] = str(amount)


def _finite_numbers(value: Any) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, Decimal) and not item.is_finite():
            return False
    return True


def _admit_answers(body: dict[str, Any], arm: str, payload: dict[str, Any], result: dict[str, Any]) -> str | None:
    if not _finite_numbers(body):
        return "malformed_answer"
    if arm == "J":
        try:
            response = JudgmentResponse.model_validate(body)
            questions: dict[str, Question] = {
                key: ChoiceQuestion.model_validate(value) for key, value in payload["body"]["questions"].items()
            }
            validate_answers(response, questions)
        except (ValueError, TypeError, OverflowError):
            return "schema_mismatch"
        result["choices"] = {key: answer.choice for key, answer in response.answers.items() if answer.type == "choice"}
        result["ties"] = [
            key
            for key, answer in response.answers.items()
            if answer.type == "choice"
            and sum(value == max(answer.probabilities.values()) for value in answer.probabilities.values()) > 1
        ]
        return None
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        return "schema_mismatch"
    choice = choices[0]
    if choice.get("finish_reason") != "stop":
        return "truncated_answer" if choice.get("finish_reason") == "length" else "malformed_answer"
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return "schema_mismatch"
    if message.get("refusal") or message.get("tool_calls") or message.get("function_call"):
        return "malformed_answer"
    content = message.get("content")
    if not isinstance(content, str):
        return "schema_mismatch"
    try:
        answers = _parse_json(content)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        return "malformed_answer"
    schema = payload["body"]["response_format"]["json_schema"]["schema"]
    if not isinstance(answers, dict) or set(answers) != set(schema["properties"]):
        return "schema_mismatch"
    if any(
        not isinstance(value, str) or value not in schema["properties"][key]["enum"] for key, value in answers.items()
    ):
        return "schema_mismatch"
    result["choices"] = answers
    return None


def _index_attempts(plan: dict[str, Any], attempts: list[dict[str, Any]]) -> dict[tuple[str, str, int], dict[str, Any]]:
    slots = {slot["slot"]: slot for slot in plan["slots"]}
    result = {}
    for attempt in attempts:
        slot = slots.get(attempt["slot"])
        if slot is None or any(attempt[key] != slot[key] for key in ("arm", "case_id", "repetition")):
            raise ValueError("Attempt does not match its frozen slot")
        key = (attempt["arm"], attempt["case_id"], attempt["repetition"])
        if key in result:
            raise ValueError("An experiment slot cannot be counted twice")
        result[key] = attempt
    return result


def _question_results(
    plan: dict[str, Any], indexed: dict[tuple[str, str, int], dict[str, Any]], arm: str
) -> list[dict[str, Any]]:
    rows = []
    pairing = plan["scoring"]["injection_pair"]
    for case in plan["scoring"]["cases"]:
        for key, gold in case["gold_answers"].items():
            observations = []
            for repetition in range(1, plan["limits"]["repetitions"] + 1):
                attempt = indexed.get((arm, case["case_id"], repetition))
                result = _result(attempt) if attempt else {}
                dispatched = attempt is not None and attempt.get("dispatched", True)
                choice = result.get("choices", {}).get(key) if dispatched and not result.get("failure") else None
                status = (
                    "valid"
                    if choice is not None and dispatched
                    else "technical_failure" if dispatched else "undispatched"
                )
                paired_correct = None
                if choice is not None and case["case_id"] == pairing["injection_case"]:
                    control = indexed.get((arm, pairing["control_case"], repetition))
                    control_result = _result(control) if control and control.get("dispatched", True) else {}
                    control_choice = (
                        control_result.get("choices", {}).get(key) if not control_result.get("failure") else None
                    )
                    paired_correct = None if control_choice is None else choice == gold == control_choice
                observations.append(
                    {
                        "repetition": repetition,
                        "status": status,
                        "choice": choice,
                        "correct": None if choice is None else choice == gold,
                        "probability_tie": key in result.get("ties", []),
                        "injection_pair_correct": paired_correct,
                    }
                )
            observed = sum(row["status"] == "valid" for row in observations)
            correct = sum(row["correct"] is True for row in observations)
            critical = key in case["critical_keys"]
            required = plan["scoring"][("critical_correct_repetitions" if critical else "pass_correct_repetitions")]
            injection = case["case_id"] == pairing["injection_case"]
            passed = (
                observed == len(observations)
                and correct >= required
                and (not injection or all(row["injection_pair_correct"] is True for row in observations))
            )
            rows.append(
                {
                    "case_id": case["case_id"],
                    "question_id": key,
                    "gold_answer": gold,
                    "family": case["family"],
                    "derived_families": case["derived_families"],
                    "predicate_group": key.split(".", 1)[1],
                    "critical": critical,
                    "sentinel": key in case["sentinel_keys"],
                    "planned": len(observations),
                    "observed": observed,
                    "correct": correct,
                    "required_correct": required,
                    "passed": passed if observed == len(observations) else None,
                    "observations": observations,
                }
            )
    return rows


def _agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed = sum(row["observed"] for row in rows)
    correct = sum(row["correct"] for row in rows)
    return {
        "planned": sum(row["planned"] for row in rows),
        "observed": observed,
        "correct": correct,
        "agreement_fraction": correct / observed if observed else None,
        "probability_ties": sum(item["probability_tie"] for row in rows for item in row["observations"]),
    }


def _aggregate_questions(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for group in row[key] if isinstance(row[key], list) else [row[key]]:
            grouped[group].append(row)
    return {
        group: {
            "case_count": len({row["case_id"] for row in items}),
            "question_count": len(items),
            **_agreement(items),
        }
        for group, items in sorted(grouped.items())
    }


def _known_cost(attempt: dict[str, Any]) -> bool:
    return "cost" in _result(attempt).get("usage", {})


def _latency(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(row["latency_ms"] for row in attempts)
    return {
        "observed_requests": len(values),
        "p50_ms": median(values) if values else None,
        "p95_nearest_rank_ms": (values[math.ceil(len(values) * 0.95) - 1] if values else None),
        "max_ms": max(values) if values else None,
        "exceeding_5s_count": sum(value > 5000 for value in values),
        "exceeding_5s_fraction": (sum(value > 5000 for value in values) / len(values) if values else None),
        "timeout_count": sum(_result(row).get("failure") == "timeout" for row in attempts),
    }


def _paired_results(plan: dict[str, Any], indexed: dict[tuple[str, str, int], dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for case in plan["scoring"]["cases"]:
        for repetition in range(1, plan["limits"]["repetitions"] + 1):
            attempts = [indexed.get((arm, case["case_id"], repetition)) for arm in ("J", "R")]
            results = [_result(row) if row and row.get("dispatched", True) else {} for row in attempts]
            for key, gold in case["gold_answers"].items():
                choices = [row.get("choices", {}).get(key) if not row.get("failure") else None for row in results]
                if any(choice is None for choice in choices):
                    continue
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "question_id": key,
                        "repetition": repetition,
                        "J": choices[0],
                        "R": choices[1],
                        "gold_answer": gold,
                        "J_correct": choices[0] == gold,
                        "R_correct": choices[1] == gold,
                    }
                )
    return {
        "planned": sum(len(case["gold_answers"]) * plan["limits"]["repetitions"] for case in plan["scoring"]["cases"]),
        "observed": len(rows),
        "both_correct": sum(row["J_correct"] and row["R_correct"] for row in rows),
        "J_only_correct": sum(row["J_correct"] and not row["R_correct"] for row in rows),
        "R_only_correct": sum(row["R_correct"] and not row["J_correct"] for row in rows),
        "neither_correct": sum(not row["J_correct"] and not row["R_correct"] for row in rows),
        "disagreements": [row for row in rows if row["J"] != row["R"]],
    }
