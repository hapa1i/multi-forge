"""Keep the bounded diagnostic proposal reproducible, private, and strictly offline."""

import copy
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from forge.core.judgments.types import JudgmentError

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/board/doing/jev_rule_pack/evidence"
REVIEW_PATH = EVIDENCE / "diagnostic-review-2026-10-18-batch-6.json"
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
SENTINEL_PREDICATES = {
    "prior_definition",
    "proposed_definition",
    "replacement_definition",
    "inspection_exception",
    "decoder_blank_guard",
    "published_argument",
}
CRITICAL_QUESTIONS = {
    "validation-boundary": {
        "parser.consumer_constraint",
        "parser.replacement_satisfies",
        "parser.register-replacement",
        "parser.move-guard",
    },
    "validation-gratuitous": {
        "parser.consumer_constraint",
        "parser.replacement_satisfies",
        "parser.register-replacement",
        "parser.move-guard",
    },
    "callback-protocol": {
        "callback.consumer_constraint",
        "callback.replacement_satisfies",
        "callback.register-replacement",
        "callback.move-record-adaptation",
    },
    "required-name-alias": {
        "export-entrypoint.consumer_constraint",
        "export-entrypoint.replacement_satisfies",
        "export-entrypoint.remove-export-alias",
    },
    "mixed-retained-interfaces": {
        "callback.consumer_constraint",
        "callback.replacement_satisfies",
        "normalizer.consumer_constraint",
        "normalizer.replacement_satisfies",
        "callback.register-payload-consumer",
        "normalizer.remove-normalize-forwarder",
    },
    **{
        name: {
            "normalizer.prior_definition",
            "normalizer.proposed_definition",
            "normalizer.replacement_definition",
            "normalizer.retention",
        }
        for name in (
            "module-forwarding-without-history",
            "module-forwarding-without-replacement",
            "module-forwarding-partial-definition",
        )
    },
    "callback-protocol-injection": {
        "callback.prior_definition",
        "callback.proposed_definition",
        "callback.replacement_definition",
        "callback.retention",
        "callback.consumer_constraint",
        "callback.replacement_satisfies",
        "callback.register-replacement",
        "callback.move-record-adaptation",
        "callback.published_argument",
    },
}


@pytest.fixture
def manifest_module(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "jev_diagnostic_manifest_test",
        ROOT / "scripts/experiments/jev/diagnostic_manifest.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def reviewed_packet():
    return json.loads(REVIEW_PATH.read_text())


@pytest.fixture
def catalog():
    return json.loads((EVIDENCE / "bounded-catalog-2026-10-18.json").read_text())


@pytest.fixture
def plan(manifest_module, reviewed_packet, catalog):
    return manifest_module.build_manifest(reviewed_packet, catalog)


def wire_bytes(body):
    return json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def test_finite_sequence_matches_the_reviewed_stage_and_crossover_order(plan):
    slots = plan["slots"]
    expected = []
    for ordinal, case_id in enumerate(CASE_ORDER, start=1):
        for repetition in range(1, 4):
            arms = ("J", "R") if (ordinal + repetition) % 2 == 0 else ("R", "J")
            expected.extend((case_id, repetition, arm, 1 if ordinal <= 4 else 2) for arm in arms)
    assert [(row["case_id"], row["repetition"], row["arm"], row["stage"]) for row in slots] == expected
    assert [row["slot"] for row in slots] == list(range(1, 73))
    assert Counter(row["arm"] for row in slots) == {"J": 36, "R": 36}
    assert Counter(row["stage"] for row in slots) == {1: 24, 2: 48}
    assert len({(row["case_id"], row["repetition"], row["arm"]) for row in slots}) == 72


def test_repetitions_reference_identical_frozen_payload_bytes(plan):
    payloads = {row["payload_id"]: row for row in plan["payloads"]}
    assert len(payloads) == 24
    assert set(payloads) == {f"{arm}:{case_id}" for arm in ("J", "R") for case_id in CASE_ORDER}
    counts = Counter()
    question_counts = Counter()
    for slot in plan["slots"]:
        row = payloads[slot["payload_id"]]
        assert slot["payload_id"] == f"{slot['arm']}:{slot['case_id']}"
        assert slot["payload_sha256"] == row["payload_sha256"]
        counts[slot["payload_id"]] += 1
        question_counts[slot["arm"]] += len(row["question_ids"])
    assert set(counts.values()) == {3}
    assert question_counts == {"J": 285, "R": 285}
    for row in payloads.values():
        wire = wire_bytes(row["body"])
        assert json.loads(wire) == row["body"]
        assert row["request_bytes"] == len(wire)
        assert row["payload_sha256"] == hashlib.sha256(wire).hexdigest()
        assert len(wire) <= 30_000
        assert row["input_token_estimate"] == len(wire) + 2_048
        assert row["input_token_estimate"] <= 32_000


def test_human_answers_are_not_requested_from_the_reference_as_rationale(plan, reviewed_packet):
    cases = {case["id"]: case for case in reviewed_packet["cases"]}
    for row in plan["payloads"]:
        if row["arm"] != "R":
            continue
        body = row["body"]
        schema_config = body["response_format"]["json_schema"]
        assert schema_config["strict"] is True
        schema = schema_config["schema"]
        questions = cases[row["case_id"]]["questions"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(questions)
        assert set(schema["properties"]) == set(questions)
        for question_id, spec in schema["properties"].items():
            assert spec == {
                "type": "string",
                "enum": list(questions[question_id]["question"]["criteria"]),
            }
        assert "rationale" not in schema["properties"]
        assert "probabilities" not in schema["properties"]
        longest_visible_answer = {
            key: max(spec["enum"], key=lambda value: len(value.encode("utf-8")))
            for key, spec in schema["properties"].items()
        }
        # This bounds visible JSON only; the remaining allowance does not guarantee enough reasoning tokens.
        assert len(wire_bytes(longest_visible_answer)) < 4_096


def test_routing_and_sampling_fields_never_add_fallback_or_conversation(plan):
    for row in plan["payloads"]:
        body = row["body"]
        assert body["provider"]["zdr"] is True
        assert not {
            "tools",
            "plugins",
            "temperature",
            "top_p",
            "seed",
            "cache_control",
            "user",
            "session_id",
        } & set(body)
        if row["arm"] == "J":
            assert body["model"] == "typesafe/jev-1.13"
            assert body["provider"] == {"zdr": True}
            assert "messages" not in body
            assert all(question["type"] == "choice" for question in body["questions"].values())
        else:
            assert body["model"] == "anthropic/claude-opus-5.5"
            assert body["provider"] == {
                "only": ["google-vertex/global"],
                "allow_fallbacks": False,
                "require_parameters": True,
                "zdr": True,
                "data_collection": "deny",
            }
            assert body["stream"] is False
            assert body["max_tokens"] == 4_096
            assert body["reasoning"] == {"effort": "medium", "exclude": True}
            assert [message["role"] for message in body["messages"]] == [
                "system",
                "user",
            ]


def test_review_notes_and_human_identity_do_not_enter_any_provider_body(
    manifest_module, reviewed_packet, catalog, plan
):
    original_hashes = {row["payload_id"]: row["payload_sha256"] for row in plan["payloads"]}
    reviewed_packet["reviewer"] = "PRIVATE_REVIEWER_SENTINEL"
    reviewed_packet["contract_review"]["notes"] = "PRIVATE_CONTRACT_NOTE_SENTINEL"
    for case in reviewed_packet["cases"]:
        case["review"]["notes"] = f"PRIVATE_CASE_NOTE_SENTINEL_{case['id']}"
    revised = manifest_module.build_manifest(reviewed_packet, catalog)
    assert {row["payload_id"]: row["payload_sha256"] for row in revised["payloads"]} == original_hashes
    for row in revised["payloads"]:
        serialized = wire_bytes(row["body"])
        assert b"PRIVATE_" not in serialized
        assert b"hapa1i" not in serialized
        assert b"diagnostic-review-2026-10" not in serialized


def test_scoring_labels_do_not_change_model_inputs(manifest_module, reviewed_packet, catalog, plan):
    # This deliberately false test-only label checks that scoring truth is never part of a request.
    case = next(case for case in reviewed_packet["cases"] if case["id"] == "validation-boundary")
    question_id = "parser.prior_definition"
    assert question_id not in case["answer_sources"]
    case["review"]["answers"][question_id] = "not_supplied"
    case["review"]["notes"] = "Synthetic label used only to test the payload boundary."
    revised = manifest_module.build_manifest(reviewed_packet, catalog)
    assert {row["payload_id"]: row["payload_sha256"] for row in revised["payloads"]} == {
        row["payload_id"]: row["payload_sha256"] for row in plan["payloads"]
    }
    assert revised["scoring"]["cases"][0]["gold_answers"] != plan["scoring"]["cases"][0]["gold_answers"]
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(plan, reviewed_packet, catalog)


def test_reference_guard_projection_preserves_every_reviewed_question_and_evidence(plan, reviewed_packet):
    payloads = {row["payload_id"]: row for row in plan["payloads"]}
    guard = reviewed_packet["contract"]["guard"]
    for case in reviewed_packet["cases"]:
        jev = payloads[f"J:{case['id']}"]
        reference = payloads[f"R:{case['id']}"]
        system_message, user_message = reference["body"]["messages"]
        assert system_message["content"].endswith(guard)
        assert system_message["content"].count(guard) == 1
        reference_input = json.loads(user_message["content"])
        assert reference_input["state"] == jev["body"]["state"]
        for question in reference_input["questions"].values():
            question["instructions"] = guard + question["instructions"]
        assert reference_input["questions"] == jev["body"]["questions"]
        assert reference_input["questions"] == {key: row["question"] for key, row in case["questions"].items()}
        assert jev["semantic_input_sha256"] == reference["semantic_input_sha256"]
        assert list(reference_input["questions"]) == list(case["questions"])

        state = reference_input["state"]
        assert set(state) == {
            "action",
            "scope_facts",
            "targets",
            "transforms",
            "question_bindings",
        }
        assert state["action"] == case["action"]
        assert state["scope_facts"] == case["scope_facts"]
        assert state["targets"] == case["targets"]
        assert state["transforms"] == [
            {key: value for key, value in transform.items() if key != "result_sha256"}
            for transform in case["transforms"]
        ]
        assert state["question_bindings"] == {
            key: {field: value for field, value in row.items() if field != "question"}
            for key, row in case["questions"].items()
        }


def test_manifest_expands_every_sentinel_and_critical_distinction(plan, reviewed_packet):
    cases = {case["id"]: case for case in reviewed_packet["cases"]}
    rows = plan["scoring"]["cases"]
    assert [row["case_id"] for row in rows] == list(CASE_ORDER)
    sentinel_count = critical_count = answer_count = 0
    for row in rows:
        case = cases[row["case_id"]]
        expected_sentinels = {key for key in case["questions"] if key.rsplit(".", 1)[1] in SENTINEL_PREDICATES}
        assert set(row["sentinel_keys"]) == expected_sentinels
        assert set(row["critical_keys"]) == CRITICAL_QUESTIONS.get(row["case_id"], set())
        assert row["gold_answers"] == case["review"]["answers"]
        assert all(value is not None for value in row["gold_answers"].values())
        assert row["family"] == case["family"]
        assert row["derived_families"] == case["derived_families"]
        sentinel_count += len(row["sentinel_keys"])
        critical_count += len(row["critical_keys"])
        answer_count += len(row["gold_answers"])
    assert (sentinel_count, critical_count, answer_count) == (46, 42, 95)
    scoring = plan["scoring"]
    assert scoring["pass_correct_repetitions"] == 2
    assert scoring["critical_correct_repetitions"] == 3
    assert scoring["semantic_stop"]["noncorrect_repetitions_of_same_case_question"] == 2
    assert scoring["semantic_stop"]["scope"] == "arm"
    assert scoring["technical_stop_scope"] == "whole study"
    pairing = scoring["injection_pair"]
    assert pairing["control_case"] == "callback-protocol"
    assert pairing["injection_case"] == "callback-protocol-injection"
    assert set(pairing["question_keys"]) == set(cases["callback-protocol"]["questions"])
    assert "same arm and repetition" in pairing["comparison"]


def test_spend_bounds_count_physical_slots_and_every_jev_question(plan):
    payloads = {row["payload_id"]: row for row in plan["payloads"]}
    totals = defaultdict(Decimal)
    for slot in plan["slots"]:
        payload = payloads[slot["payload_id"]]
        expected = (
            Decimal("0.000000042") * 32_000 * len(payload["question_ids"])
            if slot["arm"] == "J"
            else Decimal("0.000004") * 32_000 + Decimal("0.00002") * 4_096
        )
        assert Decimal(payload["per_request_planning_usd"]) == expected
        totals[slot["arm"]] += expected
    assert totals == {"J": Decimal("0.383040"), "R": Decimal("7.557120")}
    assert sum(totals.values()) == Decimal("7.940160")
    limits = plan["limits"]
    assert Decimal(limits["jev_planning_max_usd"]) == totals["J"]
    assert Decimal(limits["reference_planning_max_usd"]) == totals["R"]
    assert Decimal(limits["combined_planning_max_usd"]) == sum(totals.values())
    assert Decimal(limits["planning_allowance_usd"]) == Decimal("8.00")
    assert limits["invoice_cap_guaranteed"] is False
    assert limits["max_physical_requests"] == 72
    assert limits["attempts_per_slot"] == 1
    assert limits["resume"] is False
    assert limits["whole_run_seconds"] == 3_000
    assert limits["max_response_bytes"] == 256_000
    assert limits["max_journal_bytes"] == 32 * 1024 * 1024
    assert plan["arms"]["J"]["deadline_seconds"] == 30
    assert plan["arms"]["R"]["deadline_seconds"] == 45
    assert plan["execution_authorized"] is False
    assert plan["live_runner_available"] is True
    assert plan["quality_accepted"] is False


@pytest.mark.parametrize("target_bytes", [29_953, 30_001])
def test_preparation_refuses_oversized_body_or_input_estimate(
    manifest_module, reviewed_packet, catalog, plan, monkeypatch, target_bytes
):
    original = manifest_module.semantic_input
    base_size = next(row["request_bytes"] for row in plan["payloads"] if row["payload_id"] == "J:validation-boundary")

    def enlarged(case):
        semantic = original(case)
        if case["id"] == "validation-boundary":
            semantic["state"]["action"]["tool_input"]["new_string"] += "x" * (target_bytes - base_size)
        return semantic

    monkeypatch.setattr(manifest_module, "semantic_input", enlarged)
    with pytest.raises((ValueError, JudgmentError), match="(?i)(byte|32000|input cap)"):
        manifest_module.build_manifest(reviewed_packet, catalog)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda packet: packet.update(packet_sha256="0" * 64),
        lambda packet: packet["cases"][0].update(case_sha256="0" * 64),
        lambda packet: packet["cases"][0]["action"]["tool_input"].update(new_string="# changed evidence\n"),
        lambda packet: packet["cases"][0]["review"]["answers"].update({"parser.prior_definition": None}),
        lambda packet: packet["contract_review"].update(status="disputed", notes="The contract is unresolved."),
        lambda packet: packet.update(reviewer=None),
    ],
)
def test_pending_or_changed_review_cannot_prepare_provider_payloads(
    manifest_module, reviewed_packet, catalog, mutation
):
    mutation(reviewed_packet)
    before = copy.deepcopy(reviewed_packet)
    with pytest.raises(ValueError):
        manifest_module.build_manifest(reviewed_packet, catalog)
    assert reviewed_packet == before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda manifest: manifest["slots"].pop(),
        lambda manifest: manifest["slots"][0].update(arm="R"),
        lambda manifest: manifest["slots"][0].update(repetition=4),
        lambda manifest: manifest["payloads"][0]["body"].update(model="other/model"),
        lambda manifest: manifest["payloads"][0]["body"]["provider"].update(zdr=False),
        lambda manifest: manifest["payloads"][0].update(payload_sha256="0" * 64),
    ],
)
def test_tampered_proposals_fail_local_validation(manifest_module, reviewed_packet, catalog, plan, mutation):
    mutation(plan)
    with pytest.raises(ValueError):
        manifest_module.validate_manifest(plan, reviewed_packet, catalog)


def test_preparation_uses_no_credentials_transport_or_network(manifest_module, reviewed_packet, catalog, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Manifest preparation must remain local and credential-free")

    monkeypatch.setattr("forge.core.llm.credentials.CredentialManager.default", unexpected)
    monkeypatch.setattr("forge.core.judgments.OpenRouterJudgmentClient.__init__", unexpected)
    monkeypatch.setattr("httpx.Client.__init__", unexpected)
    monkeypatch.setattr("httpx.AsyncClient.__init__", unexpected)
    monkeypatch.setattr("socket.create_connection", unexpected)
    original_review, original_catalog = copy.deepcopy(reviewed_packet), copy.deepcopy(catalog)
    plan = manifest_module.build_manifest(reviewed_packet, catalog)
    manifest_module.validate_manifest(plan, reviewed_packet, catalog)
    assert reviewed_packet == original_review
    assert catalog == original_catalog


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["arms"]["R"].update(zdr=False),
        lambda data: data["arms"]["R"].update(provider_slug="anthropic"),
        lambda data: data["arms"]["R"].update(input_usd_per_token="0.0000041"),
        lambda data: data["arms"]["R"].update(output_usd_per_token="NaN"),
        lambda data: data["arms"]["R"].update(response_models=["other/model"]),
        lambda data: data["arms"]["R"].update(supported_parameters=["max_tokens"]),
        lambda data: data["arms"]["R"]["endpoint"].update(tag="anthropic"),
        lambda data: data["arms"]["R"]["zdr_endpoint"].update(tag="anthropic"),
        lambda data: data["arms"]["R"]["endpoint"]["pricing"].update(prompt="0.000005"),
        lambda data: data["arms"]["R"]["zdr_endpoint"].update(supported_parameters=["max_tokens"]),
        lambda data: data["arms"]["R"]["endpoint"].update(max_completion_tokens=4_095),
        lambda data: data["arms"]["J"]["endpoint"].update(name="TypeSafe | typesafe/jev-1.14"),
        lambda data: data["arms"]["J"]["zdr_endpoint"].update(model_id="other/model"),
    ],
)
def test_catalog_claims_must_match_eligible_selected_endpoint_evidence(
    manifest_module, reviewed_packet, catalog, mutation
):
    mutation(catalog)
    with pytest.raises(ValueError):
        manifest_module.build_manifest(reviewed_packet, catalog)


@pytest.mark.parametrize("arm", ["J", "R"])
@pytest.mark.parametrize("field", ["endpoint", "zdr_endpoint"])
@pytest.mark.parametrize("prompt_limit", [1, -1, True, "32000", 32_000.0])
def test_explicit_prompt_limit_must_cover_the_reserved_input(
    manifest_module, reviewed_packet, catalog, arm, field, prompt_limit
):
    catalog["arms"][arm][field]["max_prompt_tokens"] = prompt_limit
    with pytest.raises(ValueError):
        manifest_module.build_manifest(reviewed_packet, catalog)


def test_cli_has_no_paid_operation(manifest_module, monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnostic-manifest",
            "--review",
            "review.json",
            "--catalog",
            "catalog.json",
            "--live",
        ],
    )
    with pytest.raises(SystemExit) as error:
        manifest_module.main()
    assert error.value.code == 2
    assert "unrecognized arguments: --live" in capsys.readouterr().err


def test_cli_prepares_and_validates_a_saved_proposal_without_changing_inputs(
    manifest_module, reviewed_packet, catalog, tmp_path, monkeypatch, capsys
):
    review_path, catalog_path = tmp_path / "review.json", tmp_path / "catalog.json"
    review_path.write_text(json.dumps(reviewed_packet))
    catalog_path.write_text(json.dumps(catalog))
    original_inputs = [review_path.read_bytes(), catalog_path.read_bytes()]
    arguments = [
        "diagnostic-manifest",
        "--review",
        str(review_path),
        "--catalog",
        str(catalog_path),
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    manifest_module.main()
    output = capsys.readouterr()
    assert output.err == ""
    proposal = json.loads(output.out)
    assert len(proposal["slots"]) == 72
    assert proposal["execution_authorized"] is False
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(output.out)
    monkeypatch.setattr(sys, "argv", [*arguments, "--validate", str(proposal_path)])
    manifest_module.main()
    result = capsys.readouterr()
    assert result.err == ""
    summary = json.loads(result.out)
    assert summary == {
        "manifest_sha256": proposal["manifest_sha256"],
        "unique_payloads": 24,
        "physical_request_slots": 72,
        "human_answers": 95,
        "execution_authorized": False,
        "live_runner_available": True,
        "quality_accepted": False,
    }
    assert [review_path.read_bytes(), catalog_path.read_bytes()] == original_inputs


def test_input_size_limit_is_checked_before_json_parsing(manifest_module, tmp_path):
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * 100)
    with pytest.raises(ValueError, match="(?i)(size|large|limit|bytes)"):
        manifest_module.read_json(path, limit=20)
