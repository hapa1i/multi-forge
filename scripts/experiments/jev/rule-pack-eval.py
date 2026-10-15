"""Prepare the wrapper corpus or evaluate saved responses offline; no live mode."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from forge.core.judgments import openrouter as judgment_client
from forge.core.judgments import types as judgment_types
from forge.core.judgments.openrouter import (
    DEFAULT_MODEL,
    MAX_RESPONSE_BYTES,
    build_payload,
    encode_payload,
)
from forge.core.judgments.types import (
    JudgmentError,
    JudgmentResponse,
    NoulAnswer,
    Question,
    partial_metadata,
    validate_answers,
)
from forge.policy.rule_pack import definitions, outcomes
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
    assess_applicability,
    assess_response,
)

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
MAX_OBSERVATIONS = 5000
MAX_CORPUS_BYTES = 1_000_000


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
    rule_id: Text
    rule_version: Text
    evidence_contract_version: Annotated[int, Field(ge=1)]
    cases: Annotated[list[Case], Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def current_contract(self) -> Self:
        self.validate_contract()
        return self

    def validate_contract(self) -> None:
        if (self.rule_id, self.rule_version, self.evidence_contract_version) != (
            RULE_ID,
            RULE_VERSION,
            CONTRACT_VERSION,
        ):
            raise ValueError("Corpus rule or evidence-contract version does not match the current definitions")


class EvaluationSettings(Record):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    decision_version: Text
    thresholds: DecisionThresholds

    @model_validator(mode="after")
    def current_decision(self) -> Self:
        self.validate_decision()
        return self

    def validate_decision(self) -> None:
        if self.decision_version != DECISION_VERSION:
            raise ValueError("Settings decision version does not match the current outcome combiner")


class SavedPrediction(Record):
    case_id: Text
    case_sha256: Digest
    payload_sha256: Digest
    repetition: Annotated[int, Field(ge=1, le=100)]
    response: dict[str, Any] | None = None
    failure: Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")] | None = None
    latency_ms: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    status_code: Annotated[int, Field(ge=100, le=599)] | None = None
    response_bytes: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def one_result(self) -> Self:
        if (self.response is None) == (self.failure is None):
            raise ValueError("Supply exactly one saved response or failure")
        if self.response is not None:
            if self.status_code is None or self.response_bytes is None:
                raise ValueError(f"Case {self.case_id}: a saved response requires HTTP status and wire byte size")
            try:
                _canonical_bytes(self.response)
            except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
                raise ValueError(
                    f"Case {self.case_id}: response must be finite, UTF-8 JSON with bounded nesting"
                ) from exc
        return self


class SavedPredictions(Record):
    schema_version: Annotated[int, Field(ge=2, le=2)]
    source_kind: Literal["fixture", "capture"]
    source_reference: Text
    expected_model: Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
    corpus_sha256: Digest
    prompt_sha256: Digest
    split: Literal["calibration", "held_out"]
    repetitions: Annotated[int, Field(ge=1, le=100)]
    predictions: Annotated[list[SavedPrediction], Field(max_length=MAX_OBSERVATIONS)]


class HumanReview(Record):
    status: Literal["pending", "adjudicated", "excluded", "disputed"]
    outcome: Outcome | None
    question_answers: QuestionAnswers | None
    notes: Annotated[str, Field(max_length=4000)]
    replace_existing: bool

    @model_validator(mode="after")
    def explicit_review_state(self) -> Self:
        if self.status == "adjudicated":
            if self.outcome is None:
                raise ValueError("Adjudicated rows require an explicit human outcome")
        elif (
            self.outcome is not None
            or (
                self.question_answers is not None
                and any(value is not None for value in self.question_answers.model_dump().values())
            )
            or self.replace_existing
        ):
            raise ValueError("Only adjudicated rows may set labels or replace an existing adjudication")
        if self.status in {"excluded", "disputed"} and not self.notes.strip():
            raise ValueError("Excluded or disputed rows require notes explaining the unresolved issue")
        return self


class ReviewCase(Record):
    id: Text
    case_sha256: Digest
    family: Text
    split: Literal["calibration", "held_out"]
    provenance: Provenance
    action: Action
    scope_facts: dict[str, str]
    review: HumanReview


class ReviewPacket(Record):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    kind: Literal["jev_rule_pack_human_review"]
    corpus_sha256: Digest
    rule: dict[str, Any]
    reviewer: Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")] | None
    review_reference: Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")] | None
    cases: Annotated[list[ReviewCase], Field(min_length=1, max_length=500)]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _format_output(value: Any) -> str:
    return json.dumps(value, indent=2, allow_nan=False)


def prompt_digest(question_set: dict[str, Question] | None = None) -> str:
    """Track question wording independently from human semantic adjudications."""
    return _digest({name: question.model_dump() for name, question in (question_set or questions()).items()})


def case_digest(case: Case, *, question_set: dict[str, Question] | None = None) -> str:
    """Bind annotations to semantic meaning and evidence, not prompts or dataset bookkeeping."""
    value = {
        "rule_id": RULE_ID,
        "rule_version": RULE_VERSION,
        "evidence_contract_version": CONTRACT_VERSION,
        "rule_definition": RULE_DEFINITION,
        "applicability": APPLICABILITY,
        "semantic_criteria": {
            name: question.model_dump(exclude={"instructions"})
            for name, question in (question_set or questions()).items()
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
            ({"id": case.id, "family": case.family, "split": case.split} for case in corpus.cases),
            key=lambda item: item["id"],
        )
    )


def review_packet(corpus: Corpus) -> dict[str, Any]:
    """Export complete action evidence without proposals, predictions, or previous labels."""
    prepared = {row["id"]: row for row in prepare(corpus)["cases"]}
    question_set = questions()
    return {
        "schema_version": 1,
        "kind": "jev_rule_pack_human_review",
        "corpus_sha256": corpus_digest(corpus),
        "rule": {
            "rule_id": RULE_ID,
            "rule_version": RULE_VERSION,
            "evidence_contract_version": CONTRACT_VERSION,
            "definition": RULE_DEFINITION,
            "applicability": copy.deepcopy(APPLICABILITY),
            "questions": {
                name: question.model_dump(exclude={"instructions"}) for name, question in question_set.items()
            },
        },
        "reviewer": None,
        "review_reference": None,
        "cases": [
            {
                "id": case.id,
                "case_sha256": prepared[case.id]["case_sha256"],
                "family": case.family,
                "split": case.split,
                "provenance": case.provenance.model_dump(),
                "action": case.action.model_dump(),
                "scope_facts": case.scope_facts.model_dump(exclude={"basis"}),
                "review": {
                    "status": "pending",
                    "outcome": None,
                    "question_answers": {name: None for name in question_set},
                    "notes": "",
                    "replace_existing": False,
                },
            }
            for case in corpus.cases
        ],
    }


def import_review(corpus: Corpus, packet: ReviewPacket) -> dict[str, Any]:
    """Apply explicit human decisions to a copy; pending rows retain any prior adjudication."""
    packet = ReviewPacket.model_validate(packet.model_dump())
    try:
        _canonical_bytes(packet.model_dump())
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("Review packet must contain finite UTF-8 JSON with bounded nesting") from exc
    expected = review_packet(corpus)
    if packet.corpus_sha256 != expected["corpus_sha256"] or _canonical_bytes(packet.rule) != _canonical_bytes(
        expected["rule"]
    ):
        raise ValueError("Review packet membership/splits or rule contract changed; regenerate the packet")
    expected_rows = {row["id"]: row for row in expected["cases"]}
    seen = set()
    for row in packet.cases:
        if row.id in seen:
            raise ValueError(f"Duplicate review case: {row.id}")
        seen.add(row.id)
        if row.id not in expected_rows:
            raise ValueError(f"Unknown review case: {row.id}")
        unchanged = {key: value for key, value in expected_rows[row.id].items() if key != "review"}
        if _canonical_bytes(row.model_dump(exclude={"review"})) != _canonical_bytes(unchanged):
            raise ValueError(f"Review evidence changed or is stale for {row.id}; regenerate the packet")
    missing = set(expected_rows) - seen
    if missing:
        raise ValueError(f"Review packet is missing cases: {', '.join(sorted(missing))}")
    unresolved = [row.id for row in packet.cases if row.review.status in {"excluded", "disputed"}]
    if unresolved:
        raise ValueError(
            f"Unresolved excluded/disputed cases: {', '.join(unresolved)}. Resolve their reviews, or revise the "
            "source corpus and regenerate the packet; no cases were excluded or labels imported."
        )
    reviewed = [row for row in packet.cases if row.review.status == "adjudicated"]
    updated = corpus.model_copy(deep=True)
    cases = {case.id: case for case in updated.cases}
    for row in reviewed:
        if packet.reviewer is None or packet.review_reference is None:
            raise ValueError("Adjudicated reviews require a human reviewer and review_reference")
        case = cases[row.id]
        if case.adjudication is not None and not row.review.replace_existing:
            raise ValueError(
                f"Case {row.id} already has an adjudication. Keep it with status=pending, or explicitly set "
                "replace_existing=true after reviewing the previous adjudication in the source corpus."
            )
        if row.review.question_answers is None:
            if host_decision(case) is None:
                raise ValueError(f"Case {row.id}: model candidates require all three human question-answer fields")
            if not row.review.notes.strip():
                raise ValueError(f"Case {row.id}: explain omitted host-case question answers in review notes")
        assert row.review.outcome is not None
        case.adjudication = Adjudication(
            outcome=row.review.outcome,
            reviewer=packet.reviewer,
            review_reference=packet.review_reference,
            case_sha256=row.case_sha256,
            question_answers=row.review.question_answers,
        )
    result = updated.model_dump()
    if len((_format_output(result) + "\n").encode("utf-8")) > MAX_CORPUS_BYTES:
        raise ValueError(
            f"Imported corpus exceeds the {MAX_CORPUS_BYTES}-byte corpus input limit in its emitted JSON form. "
            "Shorten reviewer/reference text or source metadata, or reduce the corpus and regenerate its review "
            "packet; no corpus was emitted."
        )
    return result


def host_decision(case: Case) -> tuple[str, str] | None:
    """Apply authoritative fixture facts before preparing any model request."""
    assessment = assess_applicability(
        surface=case.scope_facts.surface,
        compatibility_decision=case.scope_facts.compatibility_decision,
        tool_name=case.action.tool_name,
    )
    return (assessment.outcome, assessment.reason) if assessment else None


def prepare(corpus: Corpus, *, include_payloads: bool = False) -> dict[str, Any]:
    """Validate shape and grouping without claiming semantic coverage or label correctness."""
    corpus.validate_contract()
    seen: set[str] = set()
    groups: dict[str, str] = {}
    counts: Counter[str] = Counter()
    preparation_counts: Counter[str] = Counter()
    prepared = []
    request_questions = questions()
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
        digest = case_digest(case, question_set=request_questions)
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
            payload = build_payload(DEFAULT_MODEL, state, request_questions)
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
        "prompt_sha256": prompt_digest(request_questions),
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
    settings.validate_decision()
    report = prepare(corpus)
    if saved.corpus_sha256 != corpus_digest(corpus) or saved.prompt_sha256 != report["prompt_sha256"]:
        raise ValueError("Saved predictions do not match the corpus membership/splits or prompt")
    prepared = {item["id"]: item for item in report["cases"]}
    cases = {case.id: case for case in corpus.cases if case.split == saved.split}
    _validate_plan(report, saved.split, saved.repetitions, corpus)
    observations: dict[tuple[str, int], dict[str, Any]] = {}
    outcomes_by_case: dict[str, set[str]] = defaultdict(set)
    request_questions = questions()
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
        metadata = partial_metadata(prediction.response)
        if prediction.response is not None:
            model = prediction.response.get("model")
            if isinstance(model, str) and model != saved.expected_model:
                raise ValueError(f"Case {case.id}: reported model does not match declared expected_model")
            if (prediction.response_bytes or 0) > MAX_RESPONSE_BYTES:
                assessment = Assessment("unavailable", "jev_response_too_large")
                # A1 stops before parsing an oversized body, so its metadata is not accepted either.
                metadata = {}
            elif prediction.status_code != 200:
                assessment = Assessment("unavailable", "jev_transport_failure")
            else:
                try:
                    response = JudgmentResponse.model_validate(prediction.response)
                    validate_answers(response, request_questions)
                    assessment = assess_response(response, settings.thresholds)
                    probabilities = {
                        name: answer.noul for name, answer in response.answers.items() if isinstance(answer, NoulAnswer)
                    }
                except ValueError:
                    assessment = Assessment("unavailable", "jev_invalid_response")
        usage = metadata.get("usage")
        outcomes_by_case[case.id].add(assessment.outcome)
        observations[key] = {
            **asdict(assessment),
            "diagnostic": assessment.diagnostic,
            "observed": True,
            "probabilities": probabilities,
            "latency_ms": prediction.latency_ms,
            "cost": usage.cost if usage else None,
            "model": metadata.get("model"),
            "failure": prediction.failure,
            "status_code": prediction.status_code,
            "response_bytes": prediction.response_bytes,
        }

    cohorts = {}
    assessed_cases = []
    all_host_cases = []
    for kind in ("constructed", "historical"):
        selected = [case for case in cases.values() if case.provenance.kind == kind]
        if not selected:
            continue
        model_cases = [case for case in selected if prepared[case.id]["preparation"] == "model_input"]
        host_cases = []
        for case in selected:
            entry = prepared[case.id]
            if entry["preparation"] == "host_decision":
                expected = case.adjudication.outcome if case.adjudication else None
                host_cases.append(
                    {
                        "id": case.id,
                        "case_sha256": entry["case_sha256"],
                        "outcome": entry["host_outcome"],
                        "reason": entry["host_reason"],
                        "diagnostic": Assessment(entry["host_outcome"], entry["host_reason"]).diagnostic,
                        "expected_outcome": expected,
                        "matches_adjudication": entry["host_outcome"] == expected if expected is not None else None,
                    }
                )
        all_host_cases.extend(host_cases)
        repetitions = {}
        for repetition in range(1, saved.repetitions + 1):
            rows = []
            for case in model_cases:
                result = observations.get(
                    (case.id, repetition),
                    {
                        "outcome": "unavailable",
                        "reason": "jev_missing_saved_response",
                        "diagnostic": Assessment("unavailable", "jev_missing_saved_response").diagnostic,
                        "observed": False,
                        "probabilities": {},
                        "latency_ms": None,
                        "cost": None,
                        "model": None,
                        "failure": None,
                        "status_code": None,
                        "response_bytes": None,
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
            repetitions[str(repetition)] = _summarize(rows, host_cases)
        model_groups = {_source_group(case) for case in model_cases}
        host_groups = {_source_group(case) for case in selected if prepared[case.id]["preparation"] == "host_decision"}
        cohorts[f"{kind}/{saved.split}"] = {
            "cases": len(selected),
            "model_cases": len(model_cases),
            "source_groups": len(model_groups),
            "host_only_source_groups": len(host_groups - model_groups),
            "host_decisions": dict(Counter(item["outcome"] for item in host_cases)),
            "host_adjudication": {
                "unadjudicated": sum(item["expected_outcome"] is None for item in host_cases),
                "confusion": dict(
                    Counter(
                        f"{item['expected_outcome']}/{item['outcome']}"
                        for item in host_cases
                        if item["expected_outcome"] is not None
                    )
                ),
                "labeled_positives": sum(item["expected_outcome"] == "warning" for item in host_cases),
                "disagreements": sum(item["matches_adjudication"] is False for item in host_cases),
            },
            "repetitions": repetitions,
        }
    sources = _evaluator_sources()
    return {
        "mode": "offline_evaluation",
        "source_kind": saved.source_kind,
        "source_reference": saved.source_reference,
        "expected_model": saved.expected_model,
        "evaluator_sources": sources,
        "evaluator_sha256": _digest(sources),
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
        + (
            ["host_adjudication_conflicts"]
            if any(row["matches_adjudication"] is False for row in all_host_cases)
            else []
        )
        + (["missing_saved_responses"] if any(not row["observed"] for row in assessed_cases) else [])
        + (["no_model_candidates"] if not assessed_cases else [])
        + (
            ["no_historical_evidence"]
            if not any(case.provenance.kind == "historical" for case in cases.values())
            else []
        ),
        "cohorts": cohorts,
        "observed_outcome_variation": sorted(
            case_id for case_id, values in outcomes_by_case.items() if len(values) > 1
        ),
        "host_cases": all_host_cases,
        "cases": assessed_cases,
    }


def _validate_plan(prepared: dict[str, Any], split: str, repetitions: int, corpus: Corpus) -> None:
    selected_ids = {case.id for case in corpus.cases if case.split == split}
    candidates = sum(
        entry["id"] in selected_ids and entry["preparation"] == "model_input" for entry in prepared["cases"]
    )
    if not candidates:
        raise ValueError("Selected split contains no model-input cases")
    if candidates * repetitions > MAX_OBSERVATIONS:
        raise ValueError(f"Planned model cases times repetitions exceeds the {MAX_OBSERVATIONS}-observation limit")


def _source_group(case: Case) -> str:
    return case.provenance.origin if case.provenance.kind == "historical" else case.family


def _evaluator_sources() -> dict[str, str]:
    paths = {"rule-pack-eval.py": Path(__file__)}
    for module in (definitions, outcomes, judgment_types, judgment_client):
        if module.__file__ is None:
            raise ValueError(f"Cannot identify evaluator source for {module.__name__}")
        paths[module.__name__] = Path(module.__file__)
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


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
        "wilson_95": [
            0.0 if numerator == 0 else max(0.0, center - spread),
            1.0 if numerator == denominator else min(1.0, center + spread),
        ],
    }


def _summarize(rows: list[tuple[Case, dict[str, Any]]], host_cases: list[dict[str, Any]]) -> dict[str, Any]:
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
    try:
        subtotal = math.fsum(costs)
    except OverflowError as exc:
        raise ValueError("Reported costs exceed the supported numeric range") from exc
    negatives = counts["no_warning"] - counts["no_warning_abstentions"]
    positives = counts["warning"] - counts["warning_abstentions"]
    host_positives = sum(row["expected_outcome"] == "warning" for row in host_cases)
    return {
        "expected": len(rows),
        "observed": observed,
        "missing": len(rows) - observed,
        "outcomes": dict(sorted(outcomes.items())),
        "unavailable_reasons": dict(
            sorted(Counter(row["reason"] for _, row in rows if row["outcome"] == "unavailable").items())
        ),
        "saved_failures": dict(
            sorted(Counter(row["failure"] for _, row in rows if row["failure"] is not None).items())
        ),
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
        "pipeline_effective_miss_rate": _rate(
            counts["warning"] - confusion["warning/warning"] + host_positives, counts["warning"] + host_positives
        ),
        "questions": questions_report,
        "latency_ms": {
            "known": len(latencies),
            "unknown": len(rows) - len(latencies),
            "p50": latencies[math.ceil(len(latencies) * 0.5) - 1] if latencies else None,
            "p95": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else None,
        },
        "reported_cost_usd": {
            "known": len(costs),
            "unknown": len(rows) - len(costs),
            "known_subtotal": subtotal,
            "total": subtotal if rows and len(costs) == len(rows) else None,
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
    try:
        return json.loads(raw, object_pairs_hook=_unique_object)
    except RecursionError as exc:
        raise ValueError(f"{path.name}: excessive JSON nesting") from exc
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"{path.name}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Human review: export with --review-packet, fill reviewer/reference and each review block, then "
            "use --import-review PATH and save stdout to a NEW corpus file. Pending rows preserve prior labels; "
            "replacing an existing adjudication requires replace_existing=true. Excluded/disputed rows block "
            "import until resolved or the source corpus is revised and the packet regenerated. Scope basis and "
            "reconstruction notes stay in the source corpus, outside the packet. Retain the completed packet "
            "as the review record, including notes."
        ),
    )
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
    parser.add_argument("--expected-model", help="Required resolved model identity for a prediction template")
    parser.add_argument("--repetitions", type=int, help="Planned repetitions for a prediction template (default: 1)")
    parser.add_argument(
        "--review-packet", action="store_true", help="Export human-review evidence with labels and rationales withheld"
    )
    parser.add_argument(
        "--import-review", type=Path, help="Validate a completed packet and emit a new corpus on stdout"
    )
    args = parser.parse_args()
    if args.review_packet or args.import_review:
        if (args.review_packet and args.import_review) or any(
            (
                args.include_payloads,
                args.predictions,
                args.settings,
                args.prediction_template,
                args.split is not None,
                args.expected_model is not None,
                args.repetitions is not None,
            )
        ):
            parser.error("Choose one review operation without preparation, prediction, or evaluation options")
    if bool(args.predictions) != bool(args.settings):
        parser.error("--predictions and --settings are required together")
    if args.prediction_template and (args.predictions or args.include_payloads):
        parser.error("--prediction-template cannot be combined with evaluation or --include-payloads")
    if args.split and not args.prediction_template:
        parser.error("--split is only valid with --prediction-template; evaluation uses the saved manifest's split")
    if args.prediction_template and not args.expected_model:
        parser.error("--prediction-template requires --expected-model with a resolved model identity")
    if (args.expected_model is not None or args.repetitions is not None) and not args.prediction_template:
        parser.error("--expected-model and --repetitions apply only to --prediction-template")
    if args.predictions and args.include_payloads:
        parser.error("--include-payloads applies only to preparation")
    try:
        corpus = Corpus.model_validate(_read_json(args.corpus, MAX_CORPUS_BYTES))
        if args.review_packet:
            report = review_packet(corpus)
        elif args.import_review:
            packet = ReviewPacket.model_validate(_read_json(args.import_review, 4_000_000))
            report = import_review(corpus, packet)
        elif args.predictions:
            saved = SavedPredictions.model_validate(_read_json(args.predictions, 10_000_000))
            settings = EvaluationSettings.model_validate(_read_json(args.settings, 10_000))
            report = evaluate(corpus, saved, settings)
        elif args.prediction_template:
            prepared = prepare(corpus)
            manifest = SavedPredictions(
                schema_version=2,
                source_kind="fixture",
                source_reference="unfilled-local-fixture",
                expected_model=args.expected_model,
                corpus_sha256=corpus_digest(corpus),
                prompt_sha256=prompt_digest(),
                split=args.split or "calibration",
                repetitions=args.repetitions if args.repetitions is not None else 1,
                predictions=[],
            )
            _validate_plan(prepared, manifest.split, manifest.repetitions, corpus)
            report = manifest.model_dump()
        else:
            report = prepare(corpus, include_payloads=args.include_payloads)
        print(_format_output(report))
    except (OSError, ValueError, JudgmentError, RecursionError, OverflowError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
