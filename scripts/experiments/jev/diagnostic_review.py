"""Self-contained review identities and explicit answer carry-forward for diagnostics."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from forge.core.judgments.types import ChoiceQuestion

PACKET_FIELDS = {
    "schema_version",
    "diagnostic_version",
    "contract",
    "cases",
    "packet_sha256",
    "reviewer",
    "review_reference",
    "contract_review",
}
CASE_FIELDS = {
    "id",
    "family",
    "derived_families",
    "source_case_id",
    "source_case_sha256",
    "action",
    "scope_facts",
    "targets",
    "transforms",
    "questions",
    "case_sha256",
    "review",
}
PACKET_V2 = {"review_sources", "contract_review_source"}
CASE_V2 = {"question_sha256", "answer_sources", "review_source"}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def case_semantics(case: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in case.items()
        if key not in {"source_case_id", "source_case_sha256", "case_sha256", "review"} | CASE_V2
    }


def semantic_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Diagnostic judgment identity deliberately excludes active-rule/source provenance."""
    return {
        "diagnostic_version": packet["diagnostic_version"],
        "contract": {key: value for key, value in packet["contract"].items() if key != "active_reference"},
        "cases": [case_semantics(case) for case in packet["cases"]],
    }


def question_hashes(packet: dict[str, Any], case: dict[str, Any]) -> dict[str, str]:
    context = {
        "case_id": case["id"],
        "action": case["action"],
        "scope_facts": case["scope_facts"],
        "targets": case["targets"],
        "transforms": case["transforms"],
        "contract": {
            key: value for key, value in packet["contract"].items() if key not in {"active_reference", "routing"}
        },
    }
    return {
        key: digest({"context": context, "question_id": key, "question": row}) for key, row in case["questions"].items()
    }


def stamp_packet(packet: dict[str, Any]) -> None:
    """Stamp a newly authored schema-2 packet, never a human source ledger."""
    packet["schema_version"] = 2
    packet.setdefault("review_sources", {})
    packet.setdefault("contract_review_source", None)
    for case in packet["cases"]:
        case["question_sha256"] = question_hashes(packet, case)
        case["case_sha256"] = digest(case_semantics(case))
        case.setdefault("answer_sources", {})
        case.setdefault("review_source", None)
    packet["packet_sha256"] = digest(semantic_packet(packet))


def _legacy_immutable(packet: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(packet)
    for key in ("reviewer", "review_reference", "packet_sha256", "contract_review"):
        value.pop(key)
    for case in value["cases"]:
        case.pop("review")
    return value


def _review(review: Any, questions: dict[str, Any] | None, name: str, *, carried: bool = False) -> None:
    fields = {"status", "notes"} | ({"answers"} if questions is not None else set())
    statuses = {"pending", "reviewed", "disputed"} | ({"carried"} if carried else set())
    if not isinstance(review, dict) or set(review) != fields:
        raise ValueError(f"Invalid review fields: {name}")
    if not isinstance(review["status"], str) or review["status"] not in statuses:
        raise ValueError(f"Invalid review status: {name}")
    if not isinstance(review["notes"], str) or len(review["notes"]) > 4000:
        raise ValueError(f"Invalid review notes: {name}")
    if review["status"] in {"reviewed", "disputed"} and not review["notes"].strip():
        raise ValueError(f"Reviewed/disputed cases require notes: {name}")
    if review["status"] == "carried" and review["notes"]:
        raise ValueError(f"Carried answers retain source notes without claiming a new human review: {name}")
    if questions is None:
        return
    if not isinstance(review["answers"], dict) or set(review["answers"]) != set(questions):
        raise ValueError(f"Invalid answer fields: {name}")
    for key, answer in review["answers"].items():
        if answer is not None and (not isinstance(answer, str) or answer not in questions[key]["question"]["criteria"]):
            raise ValueError(f"Invalid answer: {name}/{key}")
        if review["status"] not in {"reviewed", "carried"} and answer is not None:
            raise ValueError(f"Unreviewed case cannot carry answers: {name}")


def validate_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Validate a source against its own identities, without substituting today's provenance."""
    digest(packet)
    if not isinstance(packet, dict) or type(packet.get("schema_version")) is not int:
        raise ValueError("A diagnostic review must be a versioned object")
    version = packet["schema_version"]
    if version not in {1, 2} or set(packet) != PACKET_FIELDS | (PACKET_V2 if version == 2 else set()):
        raise ValueError("Unexpected diagnostic packet fields or schema version")
    cases = packet["cases"]
    if (
        not isinstance(cases, list)
        or not cases
        or len(cases) > 500
        or not all(isinstance(case, dict) for case in cases)
    ):
        raise ValueError("A diagnostic review must contain a bounded list of case objects")
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate diagnostic case ID")
    contract = packet["contract"]
    if not isinstance(contract, dict) or set(contract) != {
        "purpose",
        "target_origin",
        "split",
        "guard",
        "active_reference",
        "routing",
    }:
        raise ValueError("Invalid diagnostic contract")
    _review(packet["contract_review"], None, "contract_review")
    reviewed = disputed = carried = answered = complete = total = 0
    for case in cases:
        name = case["id"]
        if set(case) != CASE_FIELDS | (CASE_V2 if version == 2 else set()):
            raise ValueError(f"Unexpected case fields: {name}")
        questions = case["questions"]
        if not isinstance(questions, dict) or not questions or len(questions) > 100:
            raise ValueError(f"Invalid questions: {name}")
        for row in questions.values():
            ChoiceQuestion.model_validate(row["question"])
        expected_case = (
            digest(case_semantics(case))
            if version == 2
            else digest({key: value for key, value in case.items() if key not in {"case_sha256", "review"}})
        )
        if case["case_sha256"] != expected_case:
            raise ValueError(f"Stale diagnostic case hash: {name}")
        if version == 2 and case["question_sha256"] != question_hashes(packet, case):
            raise ValueError(f"Stale diagnostic question hashes: {name}")
        _review(case["review"], questions, name, carried=version == 2)
        status = case["review"]["status"]
        reviewed += status == "reviewed"
        disputed += status == "disputed"
        carried += status == "carried"
        count = sum(answer is not None for answer in case["review"]["answers"].values())
        answered += count
        complete += count == len(questions)
        total += len(questions)
    expected_hash = digest(semantic_packet(packet) if version == 2 else _legacy_immutable(packet))
    if packet["packet_sha256"] != expected_hash:
        raise ValueError("Stale diagnostic packet hash")
    has_review = reviewed or disputed or carried or packet["contract_review"]["status"] != "pending"
    for key in ("reviewer", "review_reference"):
        value = packet[key]
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 256):
            raise ValueError(f"Invalid {key}")
        if has_review and value is None:
            raise ValueError("A reviewed ledger requires a human reviewer and review_reference")
    reference = packet["review_reference"]
    if reference and (PurePosixPath(reference).is_absolute() or ".." in PurePosixPath(reference).parts):
        raise ValueError("review_reference must stay relative to the evidence directory")
    if version == 2:
        _validate_sources(packet)
    return {
        "packet_sha256": packet["packet_sha256"],
        "contract_status": packet["contract_review"]["status"],
        "reviewed_cases": reviewed,
        "carried_cases": carried,
        "fully_answered_cases": complete,
        "answered_questions": answered,
        "unanswered_questions": total - answered,
        "disputed_cases": disputed,
        "pending_cases": len(cases) - reviewed - disputed - carried,
        "quality_accepted": False,
    }


def _validate_sources(packet: dict[str, Any]) -> None:
    sources = packet["review_sources"]
    if not isinstance(sources, dict) or len(sources) > 32:
        raise ValueError("Invalid or excessive review sources")
    for key, receipt in sources.items():
        receipt_fields = {
            "schema_version",
            "diagnostic_version",
            "packet_sha256",
            "semantic_packet_sha256",
            "reviewer",
            "review_reference",
            "contract_review",
            "active_reference",
            "cases",
            "receipt_sha256",
        }
        if (
            not isinstance(key, str)
            or len(key) != 64
            or not isinstance(receipt, dict)
            or set(receipt) != receipt_fields
            or not isinstance(receipt["cases"], dict)
        ):
            raise ValueError("Invalid review source fields")
        for source in receipt["cases"].values():
            if (
                not isinstance(source, dict)
                or set(source)
                != {
                    "case_sha256",
                    "semantic_case_sha256",
                    "source_case_id",
                    "source_case_sha256",
                    "question_sha256",
                    "review",
                }
                or not isinstance(source["question_sha256"], dict)
                or not isinstance(source["review"], dict)
                or set(source["review"]) != {"status", "answers", "notes"}
                or not isinstance(source["review"]["answers"], dict)
            ):
                raise ValueError("Invalid review source case fields")
        if receipt.get("receipt_sha256") != digest({k: v for k, v in receipt.items() if k != "receipt_sha256"}):
            raise ValueError("Review source receipt changed")
    referenced = set()
    for case in packet["cases"]:
        bindings = case["answer_sources"]
        if not isinstance(bindings, dict) or not set(bindings) <= set(case["questions"]):
            raise ValueError(f"Invalid answer source fields: {case['id']}")
        if case["review"]["status"] == "carried" and set(bindings) != {
            key for key, value in case["review"]["answers"].items() if value is not None
        }:
            raise ValueError(f"Carried answers require source attribution: {case['id']}")
        for key, source_id in bindings.items():
            receipt = sources.get(source_id)
            source = receipt and receipt["cases"].get(case["id"])
            if (
                not source
                or source["question_sha256"].get(key) != case["question_sha256"][key]
                or (
                    case["review"]["answers"][key] is None
                    or source["review"]["answers"].get(key) != case["review"]["answers"][key]
                )
            ):
                raise ValueError(f"Carried answer differs from its reviewed source: {case['id']}/{key}")
            referenced.add(source_id)
        source_id = case["review_source"]
        if source_id is not None:
            receipt = sources.get(source_id)
            source = receipt and receipt["cases"].get(case["id"])
            if (
                not source
                or source["semantic_case_sha256"] != digest(case_semantics(case))
                or source["question_sha256"] != case["question_sha256"]
                or source["review"] != case["review"]
            ):
                raise ValueError(f"Carried case review differs from its source: {case['id']}")
            referenced.add(source_id)
    source_id = packet["contract_review_source"]
    if source_id is not None:
        receipt = sources.get(source_id)
        if (
            not receipt
            or receipt["semantic_packet_sha256"] != digest(semantic_packet(packet))
            or (receipt["contract_review"] != packet["contract_review"])
        ):
            raise ValueError("Carried contract review differs from its source")
        referenced.add(source_id)
    if set(sources) != referenced:
        raise ValueError("Review sources must be referenced, without recursive history")


def _source_receipt(source: dict[str, Any]) -> dict[str, Any]:
    receipt = {
        "schema_version": source["schema_version"],
        "diagnostic_version": source["diagnostic_version"],
        "packet_sha256": source["packet_sha256"],
        "semantic_packet_sha256": digest(semantic_packet(source)),
        "reviewer": source["reviewer"],
        "review_reference": source["review_reference"],
        "contract_review": source["contract_review"],
        "active_reference": source["contract"]["active_reference"],
        "cases": {
            case["id"]: {
                "case_sha256": case["case_sha256"],
                "semantic_case_sha256": digest(case_semantics(case)),
                "source_case_id": case["source_case_id"],
                "source_case_sha256": case["source_case_sha256"],
                "question_sha256": question_hashes(source, case),
                "review": case["review"],
            }
            for case in source["cases"]
        },
    }
    receipt["receipt_sha256"] = digest(receipt)
    return copy.deepcopy(receipt)


def carry_review(source: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Reuse only semantically identical human answers; preserve their original review provenance."""
    validate_packet(source)
    validate_packet(current)
    if (
        current["schema_version"] != 2
        or current["contract_review"] != {"status": "pending", "notes": ""}
        or current["review_sources"]
        or any(case["review"]["status"] != "pending" for case in current["cases"])
    ):
        raise ValueError("Carry-forward requires a fresh schema-2 destination packet")
    result = copy.deepcopy(current)
    result["reviewer"], result["review_reference"] = (
        source["reviewer"],
        source["review_reference"],
    )
    new_source_id = digest(source)
    available = copy.deepcopy(source.get("review_sources", {}))
    available[new_source_id] = _source_receipt(source)
    needed = set()
    old_cases = {case["id"]: case for case in source["cases"]}
    for case in result["cases"]:
        old = old_cases.get(case["id"])
        if old is None:
            continue
        old_hashes = question_hashes(source, old)
        for key, answer in old["review"]["answers"].items():
            if answer is not None and old_hashes[key] == case["question_sha256"].get(key):
                case["review"]["answers"][key] = answer
                source_id = old.get("answer_sources", {}).get(key, new_source_id)
                case["answer_sources"][key] = source_id
                needed.add(source_id)
        if (
            case_semantics(old) == case_semantics(case)
            and old_hashes == case["question_sha256"]
            and old["review"]["status"] != "pending"
        ):
            case["review"] = copy.deepcopy(old["review"])
            if old["review"]["status"] != "carried":
                source_id = old.get("review_source") or new_source_id
                case["review_source"] = source_id
                needed.add(source_id)
        elif case["answer_sources"]:
            case["review"]["status"] = "carried"
    if semantic_packet(source) == semantic_packet(result) and source["contract_review"]["status"] != "pending":
        result["contract_review"] = copy.deepcopy(source["contract_review"])
        source_id = source.get("contract_review_source") or new_source_id
        result["contract_review_source"] = source_id
        needed.add(source_id)
    result["review_sources"] = {key: available[key] for key in sorted(needed)}
    validate_packet(result)
    return result
