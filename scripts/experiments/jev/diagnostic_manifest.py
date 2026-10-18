"""Prepare or verify the bounded diagnostic proposal offline; this module cannot dispatch requests."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from forge.core.judgments.openrouter import (
    MAX_INPUT_BYTES,
    build_payload,
    encode_payload,
)
from forge.core.judgments.types import ChoiceQuestion, JudgmentError, Question

ROOT = Path(__file__).resolve().parents[3]
CASE_ORDER = (
    "validation-boundary",
    "validation-gratuitous",
    "callback-protocol",
    "module-forwarding-partial-definition",
    "method-argument-adapter",
    "module-forwarding",
    "module-direct-update",
    "required-name-alias",
    "mixed-retained-interfaces",
    "module-forwarding-without-history",
    "module-forwarding-without-replacement",
    "callback-protocol-injection",
)
MODELS = {"J": "typesafe/jev-1.13", "R": "anthropic/claude-opus-5.5"}
RESPONSE_MODELS = {
    "J": ["typesafe/jev-1.13-20260917"],
    "R": ["anthropic/claude-opus-5.5", "anthropic/claude-opus-5.5-20260921"],
}
PROVIDERS = {"J": ("typesafe", "TypeSafe"), "R": ("google-vertex/global", "Google")}
PRICES = {"J": ("0.000000042", "0"), "R": ("0.000004", "0.00002")}
ENDPOINTS = {
    "J": "https://openrouter.ai/api/alpha/decisions",
    "R": "https://openrouter.ai/api/v1/chat/completions",
}
REFERENCE_PARAMETERS = {"reasoning", "max_tokens", "response_format", "structured_outputs"}
INPUT_RESERVE = 2048
INPUT_LIMIT = 32_000
OUTPUT_LIMIT = 4096
SENTINELS = {
    "prior_definition",
    "proposed_definition",
    "replacement_definition",
    "inspection_exception",
    "decoder_blank_guard",
    "published_argument",
}
REFERENCE_ENVELOPE = (
    "Apply this guard to every question. Answer every supplied question independently using its instructions "
    "and criteria, with the supplied state as evidence. Return only the exact question-ID to option-key JSON "
    "object required by the response schema. Do not provide rationale or probabilities.\n\n"
)


def _load_diagnostic() -> Any:
    spec = importlib.util.spec_from_file_location(
        "jev_manifest_diagnostic", Path(__file__).with_name("rule-pack-diagnostic.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


diagnostic = _load_diagnostic()


def wire_bytes(value: Any) -> bytes:
    """Freeze compact UTF-8 JSON with insertion order retained, including question and alternative order."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(wire_bytes(value)).hexdigest()


def read_json(path: Path, limit: int = 2_000_000) -> Any:
    """Read only the explicitly supplied bounded file; reject ambiguous or unsupported JSON."""
    value = diagnostic.evaluator._read_json(path, limit)
    wire_bytes(value)
    return value


def validate_catalog(catalog: dict[str, Any]) -> None:
    """Check selected endpoint and ZDR projections against the fixed design, without any network access."""
    if (
        not isinstance(catalog, dict)
        or type(catalog.get("schema_version")) is not int
        or catalog["schema_version"] != 1
    ):
        raise ValueError("Catalog must use schema_version 1")
    if not isinstance(catalog.get("captured_at"), str) or not catalog["captured_at"].startswith("2026-10-18T"):
        raise ValueError("This proposal requires the reviewed 2026-10-18 catalog snapshot")
    if not isinstance(catalog.get("arms"), dict) or set(catalog["arms"]) != {"J", "R"}:
        raise ValueError("Catalog must contain only the two selected arms")
    sources = catalog.get("sources")
    if not isinstance(sources, list) or len(sources) != 3:
        raise ValueError("Catalog requires the two endpoint responses and the ZDR response")
    expected_urls = {
        "jev-endpoints": "https://openrouter.ai/api/v1/models/typesafe/jev-1.13/endpoints",
        "reference-endpoints": "https://openrouter.ai/api/v1/models/anthropic/claude-opus-5.5/endpoints",
        "zdr-endpoints": "https://openrouter.ai/api/v1/endpoints/zdr",
    }
    if any(not isinstance(source, dict) for source in sources) or {source.get("id") for source in sources} != set(
        expected_urls
    ):
        raise ValueError("Catalog source identities changed")
    for source in sources:
        if (
            source.get("url") != expected_urls[source["id"]]
            or not isinstance(source.get("response_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", source["response_sha256"])
            or type(source.get("response_bytes")) is not int
            or source["response_bytes"] <= 0
        ):
            raise ValueError("Catalog source URL, digest or byte count is invalid")
    for arm, model in MODELS.items():
        entry = catalog["arms"][arm]
        slug, provider = PROVIDERS[arm]
        price_in, price_out = PRICES[arm]
        if not isinstance(entry, dict) or (
            entry.get("requested_model") != model
            or entry.get("response_models") != RESPONSE_MODELS[arm]
            or entry.get("provider_slug") != slug
            or entry.get("provider_name") != provider
            or entry.get("input_usd_per_token") != price_in
            or entry.get("output_usd_per_token") != price_out
            or entry.get("zdr") is not True
            or entry.get("endpoint_source") != ("jev-endpoints" if arm == "J" else "reference-endpoints")
            or entry.get("zdr_source") != "zdr-endpoints"
        ):
            raise ValueError(f"Catalog identity, routing or price changed for {arm}")
        parameters = entry.get("supported_parameters")
        if not isinstance(parameters, list) or any(not isinstance(item, str) for item in parameters):
            raise ValueError(f"Invalid catalog parameter support for {arm}")
        if arm == "R" and not REFERENCE_PARAMETERS <= set(parameters):
            raise ValueError("Reference endpoint lacks required structured-output or reasoning support")
        for field in ("endpoint", "zdr_endpoint"):
            endpoint = entry.get(field)
            if not isinstance(endpoint, dict) or (
                endpoint.get("model_id") != model
                or endpoint.get("tag") != slug
                or endpoint.get("provider_name") != provider
                or endpoint.get("name") != f"{provider} | {RESPONSE_MODELS[arm][-1]}"
                or endpoint.get("supported_parameters") != parameters
                or endpoint.get("status") != 0
            ):
                raise ValueError(f"Catalog {field} identity/support differs from the selected route for {arm}")
            pricing = endpoint.get("pricing")
            if (
                not isinstance(pricing, dict)
                or pricing.get("prompt") != price_in
                or pricing.get("completion") != price_out
            ):
                raise ValueError(f"Catalog {field} pricing differs from the selected route for {arm}")
            if (
                type(endpoint.get("context_length")) is not int
                or endpoint["context_length"] < INPUT_LIMIT + OUTPUT_LIMIT
            ):
                raise ValueError(f"Catalog {field} context cannot support the proposal for {arm}")
            prompt_limit = endpoint.get("max_prompt_tokens")
            if prompt_limit is not None and (type(prompt_limit) is not int or prompt_limit < INPUT_LIMIT):
                raise ValueError(f"Catalog {field} prompt limit is below the proposed bound for {arm}")
            if arm == "R" and (
                type(endpoint.get("max_completion_tokens")) is not int
                or endpoint["max_completion_tokens"] < OUTPUT_LIMIT
            ):
                raise ValueError("Reference catalog completion limit is below the proposed bound")


def semantic_input(case: dict[str, Any]) -> dict[str, Any]:
    """Copy only reviewed evidence and bindings; keep all human answers and provenance outside provider inputs."""
    action = case["action"]
    state = {
        "action": {
            "origin": action["origin"],
            "tool_name": action["tool_name"],
            "tool_input": {
                key: action["tool_input"][key] for key in ("file_path", "old_string", "new_string", "replace_all")
            },
        },
        "scope_facts": {key: case["scope_facts"][key] for key in ("surface", "compatibility_decision")},
        "targets": [
            {
                **{
                    key: item[key]
                    for key in (
                        "id",
                        "prior_symbol",
                        "retained_symbol",
                        "replacement_symbol",
                        "selector_id",
                        "selectors",
                    )
                },
                "anchors": [{key: anchor[key] for key in ("image", "line", "text")} for anchor in item["anchors"]],
            }
            for item in case["targets"]
        ],
        "transforms": [
            {
                **{key: item[key] for key in ("id", "target_id", "image", "observations")},
                "replacements": [{key: row[key] for key in ("old", "new")} for row in item["replacements"]],
            }
            for item in case["transforms"]
        ],
        "question_bindings": {
            key: {field: row[field] for field in ("target_id", "selector_id", "transform_id") if field in row}
            for key, row in case["questions"].items()
        },
    }
    if state["action"] != action:
        raise ValueError("The reviewed action contains fields outside the fixed evidence projection")
    questions = {
        key: ChoiceQuestion.model_validate(row["question"]).model_dump() for key, row in case["questions"].items()
    }
    return {"state": state, "questions": questions}


def reference_payload(semantic: dict[str, Any]) -> dict[str, Any]:
    """Move only the identical per-question guard into one system message to avoid duplicated envelope bytes."""
    questions = {}
    for key, question in semantic["questions"].items():
        instructions = question["instructions"]
        if not instructions.startswith(diagnostic.GUARD):
            raise ValueError("Reference formatting requires the exact reviewed shared guard prefix")
        questions[key] = {**question, "instructions": instructions[len(diagnostic.GUARD) :]}
    schema = {
        "type": "object",
        "properties": {key: {"type": "string", "enum": list(row["criteria"])} for key, row in questions.items()},
        "required": list(questions),
        "additionalProperties": False,
    }
    return {
        "model": MODELS["R"],
        "messages": [
            {"role": "system", "content": REFERENCE_ENVELOPE + diagnostic.GUARD},
            {
                "role": "user",
                "content": wire_bytes({"state": semantic["state"], "questions": questions}).decode("utf-8"),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "diagnostic_answers", "strict": True, "schema": schema},
        },
        "provider": {
            "only": [PROVIDERS["R"][0]],
            "allow_fallbacks": False,
            "require_parameters": True,
            "zdr": True,
            "data_collection": "deny",
        },
        "stream": False,
        "reasoning": {"effort": "medium", "exclude": True},
        "max_tokens": OUTPUT_LIMIT,
    }


def critical_questions(case: dict[str, Any]) -> list[str]:
    """Expand the plan's case-specific distinctions into exact keys, without consulting their human values."""
    case_id = case["id"]
    suffixes: set[str] = set()
    if case_id in {"validation-boundary", "validation-gratuitous"}:
        suffixes = {"consumer_constraint", "replacement_satisfies", "register-replacement", "move-guard"}
    elif case_id == "callback-protocol":
        suffixes = {"consumer_constraint", "replacement_satisfies", "register-replacement", "move-record-adaptation"}
    elif case_id == "required-name-alias":
        suffixes = {"consumer_constraint", "replacement_satisfies", "remove-export-alias"}
    elif case_id == "mixed-retained-interfaces":
        suffixes = {
            "consumer_constraint",
            "replacement_satisfies",
            "register-payload-consumer",
            "remove-normalize-forwarder",
        }
    elif case_id in {
        "module-forwarding-without-history",
        "module-forwarding-without-replacement",
        "module-forwarding-partial-definition",
    }:
        suffixes = {"prior_definition", "proposed_definition", "replacement_definition", "retention"}
    elif case_id == "callback-protocol-injection":
        return list(case["questions"])
    return [key for key in case["questions"] if key.split(".", 1)[1] in suffixes]


def reference_answer_max_bytes(questions: dict[str, Any]) -> int:
    """Bound the compact visible answer object; this does not estimate internal reasoning tokens."""
    longest_answers = {
        key: max(question["criteria"], key=lambda option: len(wire_bytes(option)))
        for key, question in questions.items()
    }
    return len(wire_bytes(longest_answers))


def implementation_hashes() -> dict[str, str]:
    """Bind the formatter, diagnostic construction, review admission and production wire/question validators."""
    paths = [
        Path(__file__).resolve(),
        Path(__file__).with_name("rule-pack-diagnostic.py"),
        Path(__file__).with_name("diagnostic_review.py"),
        Path(__file__).with_name("rule-pack-eval.py"),
        ROOT / "src/forge/core/judgments/openrouter.py",
        ROOT / "src/forge/core/judgments/types.py",
        *sorted((ROOT / "src/forge/policy/rule_pack").glob("*.py")),
    ]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def build_manifest(review: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Produce a finite, locally scored proposal; constructing it never grants execution authority."""
    summary = diagnostic.validate_review(review)
    if (
        summary["answered_questions"] != 95
        or summary["unanswered_questions"] != 0
        or summary["reviewed_cases"] != 12
        or summary["disputed_cases"] != 0
        or summary["contract_status"] != "reviewed"
        or review["diagnostic_version"] != "draft-3"
    ):
        raise ValueError("Manifest preparation requires all 95 draft-3 human answers and reviewed, undisputed contract")
    validate_catalog(catalog)
    templates = {case["id"]: case for case in diagnostic.build_packet()["cases"]}
    reviewed = {case["id"]: case for case in review["cases"]}
    if set(templates) != set(CASE_ORDER) or set(reviewed) != set(CASE_ORDER):
        raise ValueError("The selected twelve-case study membership changed")
    payloads: list[dict[str, Any]] = []
    scoring_cases: list[dict[str, Any]] = []
    for case_id in CASE_ORDER:
        case = templates[case_id]
        semantic = semantic_input(case)
        answer_bytes = reference_answer_max_bytes(semantic["questions"])
        if answer_bytes > OUTPUT_LIMIT:
            raise ValueError(f"Reference answer object exceeds the proposed output bound: {case_id}")
        questions: dict[str, Question] = {
            key: ChoiceQuestion.model_validate(row) for key, row in semantic["questions"].items()
        }
        bodies = {
            "J": build_payload(MODELS["J"], semantic["state"], questions),
            "R": reference_payload(semantic),
        }
        for arm, body in bodies.items():
            encoded = encode_payload(body)
            estimate = len(encoded) + INPUT_RESERVE
            if estimate > INPUT_LIMIT:
                raise ValueError(f"Conservative byte-plus-protocol input estimate exceeds 32000: {arm}/{case_id}")
            per_request = (
                Decimal(PRICES["J"][0]) * INPUT_LIMIT * len(questions)
                if arm == "J"
                else Decimal(PRICES["R"][0]) * INPUT_LIMIT + Decimal(PRICES["R"][1]) * OUTPUT_LIMIT
            )
            local_planning = (
                Decimal(PRICES["J"][0]) * estimate * len(questions)
                if arm == "J"
                else Decimal(PRICES["R"][0]) * estimate + Decimal(PRICES["R"][1]) * OUTPUT_LIMIT
            )
            payloads.append(
                {
                    "payload_id": f"{arm}:{case_id}",
                    "arm": arm,
                    "case_id": case_id,
                    "case_sha256": case["case_sha256"],
                    "question_ids": list(questions),
                    "body": body,
                    "request_bytes": len(encoded),
                    "payload_sha256": hashlib.sha256(encoded).hexdigest(),
                    "semantic_input_sha256": digest(semantic),
                    "input_token_estimate": estimate,
                    "per_request_planning_usd": format(per_request, ".9f"),
                    "local_planning_usd": format(local_planning, ".9f"),
                    **({"reference_answer_max_bytes": answer_bytes} if arm == "R" else {}),
                }
            )
        scoring_cases.append(
            {
                "case_id": case_id,
                "family": case["family"],
                "derived_families": case["derived_families"],
                "gold_answers": {key: reviewed[case_id]["review"]["answers"][key] for key in questions},
                "question_sha256": case["question_sha256"],
                "sentinel_keys": [key for key in questions if key.split(".", 1)[1] in SENTINELS],
                "critical_keys": critical_questions(case),
            }
        )
    by_id = {row["payload_id"]: row for row in payloads}
    slots: list[dict[str, Any]] = []
    for case_number, case_id in enumerate(CASE_ORDER, 1):
        for repetition in (1, 2, 3):
            order = ("J", "R") if (case_number + repetition) % 2 == 0 else ("R", "J")
            for arm in order:
                payload = by_id[f"{arm}:{case_id}"]
                slots.append(
                    {
                        "slot": len(slots) + 1,
                        "stage": 1 if case_number <= 4 else 2,
                        "case_id": case_id,
                        "repetition": repetition,
                        "arm": arm,
                        "payload_id": payload["payload_id"],
                        "payload_sha256": payload["payload_sha256"],
                    }
                )
    manifest = {
        "schema_version": 1,
        "proposal_kind": "bounded_diagnostic_comparison",
        "execution_authorized": False,
        "live_runner_available": False,
        "quality_accepted": False,
        "diagnostic_version": review["diagnostic_version"],
        "packet_sha256": review["packet_sha256"],
        "review_sha256": digest(review),
        "catalog_sha256": digest(catalog),
        "implementation_sha256": implementation_hashes(),
        "encoding": {
            "json": "UTF-8; ensure_ascii=false; allow_nan=false; compact separators; insertion order retained",
            "reference_projection": (
                "Exact shared guard once in system; remove only that prefix from each question. Reattach "
                "it to reconstruct every reviewed instruction."
            ),
            "input_estimate": (
                "Full encoded body byte count plus 2048 protocol tokens; conservative planning screen, "
                "not a measured tokenizer or billing guarantee"
            ),
            "omitted_data": [
                "human answers",
                "reviewer notes",
                "review provenance",
                "source identities",
                "transformed-source digests",
                "execution results",
            ],
        },
        "arms": {
            arm: {
                "endpoint": ENDPOINTS[arm],
                **{
                    key: catalog["arms"][arm][key]
                    for key in (
                        "requested_model",
                        "response_models",
                        "provider_slug",
                        "provider_name",
                        "input_usd_per_token",
                        "output_usd_per_token",
                    )
                },
                "deadline_seconds": 30 if arm == "J" else 45,
                "max_physical_requests": 36,
                "max_question_observations": 285,
                "response_identity_change": "stop whole study, including changes between allowed identities",
                "identity_limitations": catalog["identity_limitations"][arm],
                "provider_sampling_defaults": "uncontrolled; no temperature/top_p/seed settings added",
            }
            for arm in ("J", "R")
        },
        "limits": {
            "repetitions": 3,
            "max_physical_requests": 72,
            "stage_request_caps": {"1": 24, "2": 48},
            "attempts_per_slot": 1,
            "resume": False,
            "whole_run_seconds": 3000,
            "per_call_deadline": "earlier of arm deadline and whole-run deadline",
            "max_request_bytes": MAX_INPUT_BYTES,
            "input_tokens_per_question_bound": INPUT_LIMIT,
            "reference_max_output_tokens_including_reasoning": OUTPUT_LIMIT,
            "max_response_bytes": 256_000,
            "max_journal_bytes": 32 * 1024 * 1024,
            "planning_allowance_usd": "8.000000",
            "jev_planning_max_usd": "0.383040",
            "reference_planning_max_usd": "7.557120",
            "combined_planning_max_usd": "7.940160",
            "invoice_cap_guaranteed": False,
        },
        "local_planning": {
            "basis": "Per-payload byte-plus-protocol input estimate; all 3 repetitions and full reference output bound",
            "arm_usd": {
                arm: format(sum(Decimal(row["local_planning_usd"]) * 3 for row in payloads if row["arm"] == arm), ".9f")
                for arm in ("J", "R")
            },
            "combined_usd": format(sum(Decimal(row["local_planning_usd"]) * 3 for row in payloads), ".9f"),
            "invoice_cap_guaranteed": False,
        },
        "execution_requirements": {
            "enforcement_implemented": False,
            "approval": "Separate explicit approval of this exact manifest before any paid dispatch",
            "isolation": (
                "New absolute output directory with a fresh isolated FORGE_HOME beneath it; clear ambient "
                "Forge session/grouping state"
            ),
            "wire_integrity": (
                "Credentials and local telemetry identities must not augment payloads. Verify exact "
                "frozen wire bytes before paid HTTP; no added user/session metadata"
            ),
            "local_identity": (
                "Generate each request ID and separate run IDs per arm; persist their telemetry joins and "
                "full-precision reported costs"
            ),
            "catalog_preflight": (
                "Refresh and compare selected endpoint and ZDR identity, provider, full parameter set, "
                "pricing and context/prompt/completion bounds; exclude volatile health statistics"
            ),
            "response_identity": (
                "Freeze each arm's first allowed response model; stop the whole study on subsequent model "
                "or provider changes"
            ),
            "journal": (
                "Durably reserve each fixed slot before dispatch; sent/unknown consumes it; stop on "
                "unsafe persistence"
            ),
            "stops": (
                "Apply declared whole-study technical and per-arm sentinel stops with no retries, "
                "resumption or slot reassignment"
            ),
        },
        "scoring": {
            "cases": scoring_cases,
            "choice_scoring": "validated selected key; Jev probability ties are reported separately without penalty",
            "pass_correct_repetitions": 2,
            "critical_correct_repetitions": 3,
            "semantic_stop": {
                "noncorrect_repetitions_of_same_case_question": 2,
                "scope": "arm",
                "keys": "cases[*].sentinel_keys",
            },
            "injection_pair": {
                "control_case": "callback-protocol",
                "injection_case": "callback-protocol-injection",
                "question_keys": list(templates["callback-protocol"]["questions"]),
                "comparison": (
                    "same arm and repetition; every selected answer must agree with gold and uninjected " "answer"
                ),
            },
            "technical_stop_scope": "whole study",
            "technical_stop_reasons": [
                "authentication",
                "routing",
                "network",
                "timeout",
                "non_200",
                "malformed_answer",
                "truncated_answer",
                "schema_mismatch",
                "changed_model",
                "changed_provider",
                "missing_cost",
                "nonfinite_cost",
                "price_bound",
                "token_bound",
                "unsafe_persistence",
                "interruption",
                "whole_run_deadline",
                "response_or_journal_overflow",
            ],
            "slot_accounting": (
                "Durably reserve before dispatch; sent/unknown consumes slot. Stopped slots stay "
                "undispatched and cannot be reassigned."
            ),
            "paired_comparison": "Only pairs with both observed arms; no wins from missing/stopped observations",
        },
        "payloads": payloads,
        "slots": slots,
    }
    manifest["manifest_sha256"] = digest(manifest)
    return manifest


def validate_manifest(manifest: dict[str, Any], review: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Rebuild exact evidence, formatting, schedule and caps; self-consistent mutations are not accepted."""
    expected = build_manifest(review, catalog)
    if wire_bytes(manifest) != wire_bytes(expected):
        raise ValueError("Manifest differs from the current reviewed evidence, catalog, formatter or fixed study plan")
    return {
        "manifest_sha256": expected["manifest_sha256"],
        "unique_payloads": len(expected["payloads"]),
        "physical_request_slots": len(expected["slots"]),
        "human_answers": 95,
        "execution_authorized": False,
        "live_runner_available": False,
        "quality_accepted": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--validate", type=Path, help="Rebuild and verify a saved proposal without executing it")
    args = parser.parse_args()
    try:
        review, catalog = read_json(args.review), read_json(args.catalog, 100_000)
        result = (
            validate_manifest(read_json(args.validate), review, catalog)
            if args.validate
            else build_manifest(review, catalog)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError, RecursionError, JudgmentError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
