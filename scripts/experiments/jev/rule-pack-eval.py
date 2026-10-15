"""Prepare the wrapper corpus or evaluate saved responses offline; no live mode."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from forge.core.judgments.openrouter import DEFAULT_MODEL, build_payload, encode_payload
from forge.core.judgments.types import (
    JudgmentError,
    JudgmentResponse,
    NoulAnswer,
    partial_metadata,
)
from forge.policy.rule_pack.definitions import (
    APPLICABILITY,
    CONTRACT_VERSION,
    RULE_DEFINITION,
    RULE_ID,
    RULE_VERSION,
    questions,
)
from forge.policy.rule_pack.outcomes import (
    DECISION_VERSION,
    Assessment,
    DecisionThresholds,
    Outcome,
    assess_response,
)

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Provenance(Record):
    kind: Literal["constructed", "historical"]
    origin: Text


class Action(Record):
    origin: Literal["claude_code", "codex"]
    tool_name: Literal["Write", "Edit", "apply_patch"]
    tool_input: dict[str, Any]


class ScopeFacts(Record):
    surface: Literal["internal", "public_preview", "public_stable", "unknown"]
    compatibility_decision: Literal["not_approved", "approved", "unknown"]
    basis: Text  # Reviewer notes, never model evidence or part of the annotation identity.


class Proposal(Record):
    outcome: Outcome
    reason: Text


class QuestionAnswers(Record):
    coverage: bool | None
    compatibility_retention: bool | None
    independent_boundary: bool | None


class Adjudication(Record):
    outcome: Outcome
    reviewer: Text
    review_reference: Text
    case_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    question_answers: QuestionAnswers | None = None


class Case(Record):
    id: Text
    family: Text
    split: Literal["calibration", "held_out"]
    provenance: Provenance
    action: Action
    scope_facts: ScopeFacts
    reconstruction: Text
    proposal: Proposal
    adjudication: Adjudication | None


class Corpus(Record):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    rule_id: Literal["coding_standards.compatibility-wrapper"]
    rule_version: Literal["draft-2"]
    evidence_contract_version: Annotated[int, Field(strict=True, ge=3, le=3)]
    cases: Annotated[list[Case], Field(min_length=1, max_length=500)]


class EvaluationSettings(Record):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    decision_version: Literal["draft-1"]
    thresholds: DecisionThresholds


class SavedPrediction(Record):
    case_id: Text
    case_sha256: Digest
    payload_sha256: Digest
    repetition: Annotated[int, Field(ge=1, le=100)]
    response: dict[str, Any] | None = None
    failure: Text | None = None
    latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def one_result(self) -> Self:
        if (self.response is None) == (self.failure is None):
            raise ValueError("Supply exactly one saved response or failure")
        return self


class SavedPredictions(Record):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    source_kind: Literal["fixture", "capture"]
    source_reference: Text
    corpus_sha256: Digest
    prompt_sha256: Digest
    split: Literal["calibration", "held_out"]
    repetitions: Annotated[int, Field(ge=1, le=100)]
    predictions: Annotated[list[SavedPrediction], Field(max_length=5000)]


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def prompt_digest() -> str:
    """Track question wording independently from human semantic adjudications."""
    return _digest({name: question.model_dump() for name, question in questions().items()})


def case_digest(case: Case) -> str:
    """Bind annotations to semantic meaning and evidence, not prompts or dataset bookkeeping."""
    value = {
        "rule_id": RULE_ID,
        "rule_version": RULE_VERSION,
        "evidence_contract_version": CONTRACT_VERSION,
        "rule_definition": RULE_DEFINITION,
        "applicability": APPLICABILITY,
        "semantic_criteria": {
            name: question.model_dump(exclude={"instructions"}) for name, question in questions().items()
        },
        "action": case.action.model_dump(),
        "scope_facts": case.scope_facts.model_dump(exclude={"basis"}),
        "provenance": case.provenance.model_dump(),
    }
    return _digest(value)


def corpus_digest(corpus: Corpus) -> str:
    """Bind prediction artifacts to dataset membership and splits independently of human labels."""
    return _digest(
        sorted(
            (
                {"id": case.id, "family": case.family, "split": case.split, "case_sha256": case_digest(case)}
                for case in corpus.cases
            ),
            key=lambda item: item["id"],
        )
    )


def host_decision(case: Case) -> tuple[str, str] | None:
    """Apply authoritative fixture facts before preparing any model request."""
    facts = case.scope_facts
    outcome = APPLICABILITY[facts.surface][facts.compatibility_decision]
    if outcome == "invalid":
        raise ValueError("Internal approved exceptions are not defined by coding standards section 5")
    if outcome == "unavailable":
        reason = "unknown_surface" if facts.surface == "unknown" else "unknown_compatibility_decision"
        return outcome, reason
    if outcome == "not_applicable":
        reason = "stable_surface" if facts.surface == "public_stable" else "approved_preview_exception"
        return outcome, reason
    if case.action.tool_name == "Write":
        # This fixture schema carries proposed content only, with no attributed prior-interface evidence.
        return "unavailable", "write_without_prior_interface_evidence"
    return None


def prepare(corpus: Corpus, *, include_payloads: bool = False) -> dict[str, Any]:
    """Validate shape and grouping without claiming semantic coverage or label correctness."""
    seen: set[str] = set()
    groups: dict[str, str] = {}
    counts: Counter[str] = Counter()
    preparation_counts: Counter[str] = Counter()
    prepared = []
    for case in corpus.cases:
        if case.id in seen:
            raise ValueError(f"Duplicate case id: {case.id}")
        seen.add(case.id)
        _validate_action(case.action)
        if case.provenance.kind == "historical":
            if not re.fullmatch(r"[a-f0-9]{40}", case.provenance.origin):
                raise ValueError("Historical examples require a full originating commit hash")
            group = "historical:" + case.provenance.origin
        else:
            group = "constructed:" + case.family
        if group in groups and groups[group] != case.split:
            raise ValueError(f"Source family crosses calibration/held-out splits: {group}")
        groups[group] = case.split
        digest = case_digest(case)
        if case.adjudication and case.adjudication.case_sha256 != digest:
            raise ValueError(f"Stale adjudication for {case.id}")
        label_status = "adjudicated" if case.adjudication else "unadjudicated"
        counts[f"{case.provenance.kind}/{case.split}/{label_status}"] += 1
        entry: dict[str, Any] = {
            "id": case.id,
            "case_sha256": digest,
            "label_status": label_status,
        }
        decision = host_decision(case)
        if decision is not None:
            outcome, reason = decision
            entry.update(preparation="host_decision", host_outcome=outcome, host_reason=reason)
            preparation_counts[f"host_decision/{outcome}"] += 1
        else:
            # Free-text reviewer notes can disclose the proposed answer even outside the proposal field.
            state = {
                "action": case.action.model_dump(),
                "scope_facts": case.scope_facts.model_dump(exclude={"basis"}),
            }
            payload = build_payload(DEFAULT_MODEL, state, questions())
            encoded = encode_payload(payload)
            entry.update(
                preparation="model_input",
                payload_sha256=hashlib.sha256(encoded).hexdigest(),
                request_bytes=len(encoded),
            )
            preparation_counts["model_input"] += 1
            if include_payloads:
                entry["payload"] = payload
        prepared.append(entry)
    blockers = [
        "numeric_quality_gates_unset",
        "no_predictions_or_quality_evaluation",
        "live_execution_not_implemented",
    ]
    if any(case.adjudication is None for case in corpus.cases):
        blockers.append("human_adjudication_incomplete")
    if not any(case.provenance.kind == "historical" for case in corpus.cases):
        blockers.append("no_historical_evidence")
    return {
        "rule_id": RULE_ID,
        "rule_version": RULE_VERSION,
        "evidence_contract_version": CONTRACT_VERSION,
        "prompt_sha256": prompt_digest(),
        "mode": "offline_preparation",
        "max_physical_requests": 0,
        "quality_accepted": False,
        "blockers": blockers,
        "cohorts": dict(sorted(counts.items())),
        "preparation_counts": dict(sorted(preparation_counts.items())),
        "source_groups": len(groups),
        "cases": prepared,
    }


def evaluate(corpus: Corpus, saved: SavedPredictions, settings: EvaluationSettings) -> dict[str, Any]:
    """Score bounded saved observations; never dispatch or promote proposed labels to truth."""
    report = prepare(corpus)
    if saved.corpus_sha256 != corpus_digest(corpus) or saved.prompt_sha256 != prompt_digest():
        raise ValueError("Saved predictions do not match the corpus membership/splits or prompt")
    prepared = {item["id"]: item for item in report["cases"]}
    cases = {case.id: case for case in corpus.cases if case.split == saved.split}
    if not cases:
        raise ValueError("Selected split contains no cases")
    observations: dict[tuple[str, int], dict[str, Any]] = {}
    for prediction in saved.predictions:
        case = cases.get(prediction.case_id)
        if case is None:
            raise ValueError(f"Prediction outside selected split: {prediction.case_id}")
        expected = prepared[case.id]
        if expected["preparation"] != "model_input":
            raise ValueError(f"Host-decided case must not have a model prediction: {case.id}")
        if prediction.case_sha256 != expected["case_sha256"] or prediction.payload_sha256 != expected["payload_sha256"]:
            raise ValueError(f"Stale prediction evidence or payload: {case.id}")
        key = (case.id, prediction.repetition)
        if prediction.repetition > saved.repetitions or key in observations:
            raise ValueError(f"Duplicate or out-of-plan repetition: {case.id}")
        assessment = Assessment("unavailable", "jev_saved_failure")
        probabilities = {}
        if prediction.response is not None:
            try:
                response = JudgmentResponse.model_validate(prediction.response)
                assessment = assess_response(response, settings.thresholds)
                if assessment.reason != "jev_invalid_response":
                    probabilities = {
                        name: answer.noul for name, answer in response.answers.items() if isinstance(answer, NoulAnswer)
                    }
            except ValueError:
                assessment = Assessment("unavailable", "jev_invalid_response")
        usage = partial_metadata(prediction.response).get("usage")
        observations[key] = {
            **asdict(assessment),
            "diagnostic": assessment.diagnostic,
            "observed": True,
            "probabilities": probabilities,
            "latency_ms": prediction.latency_ms,
            "cost": usage.cost if usage else None,
            "model": partial_metadata(prediction.response).get("model"),
        }

    cohorts = {}
    assessed_cases = []
    for kind in ("constructed", "historical"):
        selected = [case for case in cases.values() if case.provenance.kind == kind]
        if not selected:
            continue
        model_cases = [case for case in selected if prepared[case.id]["preparation"] == "model_input"]
        host_cases = [prepared[case.id] for case in selected if prepared[case.id]["preparation"] == "host_decision"]
        repetitions = {}
        for repetition in range(1, saved.repetitions + 1):
            rows = []
            for case in model_cases:
                result = observations.get(
                    (case.id, repetition),
                    {
                        "outcome": "unavailable",
                        "reason": "jev_missing_saved_response",
                        "diagnostic": "No saved response is available for this planned observation.",
                        "observed": False,
                        "probabilities": {},
                        "latency_ms": None,
                        "cost": None,
                        "model": None,
                    },
                )
                rows.append((case, result))
                assessed_cases.append(
                    {
                        "id": case.id,
                        "repetition": repetition,
                        "case_sha256": prepared[case.id]["case_sha256"],
                        "expected_outcome": case.adjudication.outcome if case.adjudication else None,
                        **result,
                    }
                )
            repetitions[str(repetition)] = _summarize(rows)
        cohorts[f"{kind}/{saved.split}"] = {
            "cases": len(selected),
            "model_cases": len(model_cases),
            "source_groups": len(
                {case.provenance.origin if kind == "historical" else case.family for case in selected}
            ),
            "host_decisions": dict(Counter(item["host_outcome"] for item in host_cases)),
            "repetitions": repetitions,
        }
    varied = [
        case.id
        for case in cases.values()
        if len({row["outcome"] for (case_id, _), row in observations.items() if case_id == case.id}) > 1
    ]
    return {
        "mode": "offline_evaluation",
        "source_kind": saved.source_kind,
        "source_reference": saved.source_reference,
        "max_physical_requests": 0,
        "rule_id": RULE_ID,
        "rule_version": RULE_VERSION,
        "evidence_contract_version": CONTRACT_VERSION,
        "decision_version": DECISION_VERSION,
        "corpus_sha256": saved.corpus_sha256,
        "prompt_sha256": saved.prompt_sha256,
        "settings_sha256": _digest(settings.model_dump()),
        "predictions_sha256": _digest(saved.model_dump()),
        "adjudications_sha256": _digest(
            {case.id: case.adjudication.model_dump() if case.adjudication else None for case in cases.values()}
        ),
        "settings": settings.model_dump(),
        "split": saved.split,
        "quality_accepted": False,
        "blockers": [
            "quality_gates_not_approved",
            "runtime_fact_resolution_unimplemented",
            "native_delivery_unverified",
        ]
        + (["fixture_predictions_are_not_quality_evidence"] if saved.source_kind == "fixture" else [])
        + (["human_adjudication_incomplete"] if any(case.adjudication is None for case in cases.values()) else [])
        + (["missing_saved_responses"] if any(not row["observed"] for row in assessed_cases) else [])
        + (["no_model_candidates"] if not assessed_cases else [])
        + (
            ["no_historical_evidence"]
            if not any(case.provenance.kind == "historical" for case in cases.values())
            else []
        ),
        "cohorts": cohorts,
        "observed_outcome_variation": sorted(varied),
        "cases": assessed_cases,
    }


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    """Describe binomial counts without treating repeated attempts as independent examples."""
    if not denominator:
        return {"numerator": numerator, "denominator": 0, "value": None, "wilson_95": None}
    value = numerator / denominator
    z = 1.959963984540054
    scale = 1 + z * z / denominator
    center = (value + z * z / (2 * denominator)) / scale
    spread = z * math.sqrt(value * (1 - value) / denominator + z * z / (4 * denominator * denominator)) / scale
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
        "wilson_95": [max(0.0, center - spread), min(1.0, center + spread)],
    }


def _summarize(rows: list[tuple[Case, dict[str, Any]]]) -> dict[str, Any]:
    outcomes = Counter(row["outcome"] for _, row in rows)
    confusion: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    questions_report = {}
    for case, row in rows:
        if case.adjudication is None:
            counts["unadjudicated"] += 1
            continue
        truth = case.adjudication.outcome
        confusion[f"{truth}/{row['outcome']}"] += 1
        if truth in {"warning", "no_warning"}:
            counts[truth] += 1
            if row["outcome"] not in {"warning", "no_warning"}:
                counts[f"{truth}_abstentions"] += 1
    for name in questions():
        pairs = [
            (row["probabilities"][name], getattr(case.adjudication.question_answers, name))
            for case, row in rows
            if case.adjudication is not None
            and case.adjudication.question_answers is not None
            and name in row["probabilities"]
            and getattr(case.adjudication.question_answers, name) is not None
        ]
        bins = []
        for index in range(10):
            bucket = [(p, label) for p, label in pairs if min(int(p * 10), 9) == index]
            if bucket:
                bins.append(
                    {
                        "lower": index / 10,
                        "upper": (index + 1) / 10,
                        "count": len(bucket),
                        "mean_probability": sum(p for p, _ in bucket) / len(bucket),
                        "true_fraction": sum(label for _, label in bucket) / len(bucket),
                    }
                )
        questions_report[name] = {
            "count": len(pairs),
            "brier_score": sum((p - label) ** 2 for p, label in pairs) / len(pairs) if pairs else None,
            "bins": bins,
        }
    latencies = sorted(row["latency_ms"] for _, row in rows if row["observed"] and row["latency_ms"] is not None)
    costs = [row["cost"] for _, row in rows if row["observed"] and row["cost"] is not None]
    observed = sum(row["observed"] for _, row in rows)
    negatives = counts["no_warning"] - counts["no_warning_abstentions"]
    positives = counts["warning"] - counts["warning_abstentions"]
    return {
        "expected": len(rows),
        "observed": observed,
        "missing": len(rows) - observed,
        "outcomes": dict(sorted(outcomes.items())),
        "confusion": dict(sorted(confusion.items())),
        "unadjudicated": counts["unadjudicated"],
        "labeled_positives": counts["warning"],
        "labeled_negatives": counts["no_warning"],
        "positive_abstentions": counts["warning_abstentions"],
        "negative_abstentions": counts["no_warning_abstentions"],
        "assessed_coverage": _rate(outcomes["warning"] + outcomes["no_warning"], len(rows)),
        "warning_rate": _rate(outcomes["warning"], len(rows)),
        "assessed_false_positive_rate": _rate(confusion["no_warning/warning"], negatives),
        "assessed_miss_rate": _rate(confusion["warning/no_warning"], positives),
        "effective_miss_rate": _rate(counts["warning"] - confusion["warning/warning"], counts["warning"]),
        "questions": questions_report,
        "latency_ms": {
            "known": len(latencies),
            "unknown": observed - len(latencies),
            "p50": latencies[math.ceil(len(latencies) * 0.5) - 1] if latencies else None,
            "p95": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else None,
        },
        "reported_cost_usd": {
            "known": len(costs),
            "unknown": len(rows) - len(costs),
            "known_subtotal": math.fsum(costs),
            "total": math.fsum(costs) if rows and len(costs) == len(rows) else None,
        },
    }


def _safe_path(path: Any) -> None:
    if (
        not isinstance(path, str)
        or not path
        or PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
        or "\\" in path
        or re.match(r"^[a-zA-Z]:", path)
        or any(ord(char) < 32 for char in path)
    ):
        raise ValueError("Fixture actions require safe repository-relative paths")


def _validate_action(action: Action) -> None:
    raw = action.tool_input
    if action.tool_name == "apply_patch":
        from forge.cli.hooks.codex_patch import parse_apply_patch

        if action.origin != "codex" or set(raw) != {"command"} or not isinstance(raw["command"], str):
            raise ValueError("Codex fixtures require a complete apply_patch command")
        operations = parse_apply_patch(raw["command"])
        if not operations:
            raise ValueError("Unparseable or empty apply_patch fixture")
        for operation in operations:
            _safe_path(operation.path)
            if operation.source_path:
                _safe_path(operation.source_path)
        return
    if action.origin != "claude_code":
        raise ValueError("Write/Edit fixture origin must be claude_code")
    _safe_path(raw.get("file_path"))
    fields = (
        {"file_path", "content"}
        if action.tool_name == "Write"
        else {"file_path", "old_string", "new_string", "replace_all"}
    )
    if set(raw) != fields or any(not isinstance(raw[name], str) for name in fields - {"replace_all"}):
        raise ValueError("Incomplete or unexpected Write/Edit tool input")
    if action.tool_name == "Edit" and (not raw["old_string"] or type(raw["replace_all"]) is not bool):
        raise ValueError("Edit fixtures require nonempty old_string and boolean replace_all")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path, max_bytes: int) -> Any:
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"{path.name} exceeds its {max_bytes}-byte offline input limit")
    return json.loads(raw, object_pairs_hook=_unique_object)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument(
        "--include-payloads",
        action="store_true",
        help="Include complete offline request bodies for review",
    )
    parser.add_argument(
        "--predictions", type=Path, help="Evaluate saved fixture or captured responses without dispatch"
    )
    parser.add_argument("--settings", type=Path, help="Explicit decision version and per-question threshold bands")
    parser.add_argument(
        "--prediction-template", action="store_true", help="Print an empty, identity-bound fixture manifest"
    )
    parser.add_argument(
        "--split", choices=("calibration", "held_out"), help="Split for a prediction template (default: calibration)"
    )
    args = parser.parse_args()
    if bool(args.predictions) != bool(args.settings):
        parser.error("--predictions and --settings are required together")
    if args.prediction_template and (args.predictions or args.include_payloads):
        parser.error("--prediction-template cannot be combined with evaluation or --include-payloads")
    if args.split and not args.prediction_template:
        parser.error("--split is only valid with --prediction-template; evaluation uses the saved manifest's split")
    if args.predictions and args.include_payloads:
        parser.error("--include-payloads applies only to preparation")
    try:
        corpus = Corpus.model_validate(_read_json(args.corpus, 1_000_000))
        if args.predictions:
            saved = SavedPredictions.model_validate(_read_json(args.predictions, 10_000_000))
            settings = EvaluationSettings.model_validate(_read_json(args.settings, 10_000))
            report = evaluate(corpus, saved, settings)
        elif args.prediction_template:
            prepare(corpus)
            report = SavedPredictions(
                schema_version=1,
                source_kind="fixture",
                source_reference="unfilled-local-fixture",
                corpus_sha256=corpus_digest(corpus),
                prompt_sha256=prompt_digest(),
                split=args.split or "calibration",
                repetitions=1,
                predictions=[],
            ).model_dump()
        else:
            report = prepare(corpus, include_payloads=args.include_payloads)
        print(
            json.dumps(
                report,
                indent=2,
                allow_nan=False,
            )
        )
    except (OSError, ValueError, JudgmentError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
