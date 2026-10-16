"""Diagnostic evidence and human review stay isolated from the active A2 contract."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/board/doing/jev_rule_pack/evidence"
ORIGINAL_IDS = {
    "validation-boundary",
    "validation-gratuitous",
    "callback-protocol",
    "method-argument-adapter",
    "module-forwarding",
    "module-direct-update",
}


@pytest.fixture
def diagnostic(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-diagnostic.py"
    spec = importlib.util.spec_from_file_location("jev_rule_pack_diagnostic_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def packet(diagnostic):
    return diagnostic.build_packet()


def case_by_id(packet, case_id):
    return next(case for case in packet["cases"] if case["id"] == case_id)


def execute_fixture(code):
    # Only the repository's fixed synthetic examples are executed here.
    namespace = {"__name__": "diagnostic_synthetic_fixture"}
    exec(compile(code, "<diagnostic-synthetic-fixture>", "exec"), namespace)
    return namespace


def transformed_code(case, transform_id):
    transform = next(item for item in case["transforms"] if item["id"] == transform_id)
    code = case["action"]["tool_input"][transform["image"]]
    for replacement in transform["replacements"]:
        assert code.count(replacement["old"]) == 1
        code = code.replace(replacement["old"], replacement["new"], 1)
    return code


def test_packet_is_reproducible_and_does_not_seed_human_answers(diagnostic, packet):
    assert diagnostic.build_packet() == packet
    assert packet["reviewer"] is None
    assert packet["review_reference"] is None
    assert packet["contract_review"] == {"status": "pending", "notes": ""}
    assert len(packet["cases"]) == 12
    assert len({case["id"] for case in packet["cases"]}) == 12
    for case in packet["cases"]:
        assert case["review"] == {
            "status": "pending",
            "answers": {name: None for name in case["questions"]},
            "notes": "",
        }
        assert not {"adjudication", "proposal", "predictions", "host_outcome", "reconstruction"} & case.keys()
        assert set(case["scope_facts"]) == {"surface", "compatibility_decision"}
    result = diagnostic.validate_review(packet)
    assert result["contract_status"] == "pending"
    assert result["pending_cases"] == 12
    assert result["quality_accepted"] is False


def test_original_actions_and_family_identity_survive_export(packet):
    corpus = json.loads((EVIDENCE / "wrapper-corpus.json").read_text())
    originals = {case["id"]: case for case in corpus["cases"]}
    for case_id in ORIGINAL_IDS:
        source = originals[case_id]
        exported = case_by_id(packet, case_id)
        assert exported["action"] == source["action"]
        assert exported["family"] == source["family"]
        assert exported["scope_facts"] == {key: value for key, value in source["scope_facts"].items() if key != "basis"}
        assert exported["source_case_sha256"] == source["adjudication"]["case_sha256"]


def test_export_withholds_prior_review_and_authored_reasoning(diagnostic, monkeypatch):
    read_json = diagnostic.evaluator._read_json
    sentinels = ("AUTHORED_REASON_SENTINEL", "SCOPE_BASIS_SENTINEL", "RECONSTRUCTION_SENTINEL", "OLD_REVIEWER_SENTINEL")

    def input_without_neutral_metadata(path, limit):
        value = read_json(path, limit)
        if path == diagnostic.CORPUS:
            for case in value["cases"]:
                case["proposal"]["reason"] = sentinels[0]
                case["scope_facts"]["basis"] = sentinels[1]
                case["reconstruction"] = sentinels[2]
                case["adjudication"]["reviewer"] = sentinels[3]
        return value

    monkeypatch.setattr(diagnostic.evaluator, "_read_json", input_without_neutral_metadata)
    rendered = json.dumps(diagnostic.build_packet())
    assert all(sentinel not in rendered for sentinel in sentinels)


def test_every_question_and_transformation_names_one_existing_target(packet):
    for case in packet["cases"]:
        target_ids = {target["id"] for target in case["targets"]}
        transforms = {item["id"]: item for item in case["transforms"]}
        assert len(target_ids) == len(case["targets"])
        assert len(transforms) == len(case["transforms"])
        for transform in transforms.values():
            assert transform["target_id"] in target_ids
        for question in case["questions"].values():
            assert question["target_id"] in target_ids
            assert question["question"]["type"] == "choice"
            if question.get("transform_id"):
                assert transforms[question["transform_id"]]["target_id"] == question["target_id"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["cases"].pop(),
        lambda data: data["cases"].append(copy.deepcopy(data["cases"][0])),
        lambda data: data.update(packet_sha256="0" * 64),
        lambda data: data["cases"][0].update(case_sha256="0" * 64),
        lambda data: data["cases"][0].update(family="different-family"),
        lambda data: data["cases"][0]["action"]["tool_input"].update(new_string="# Changed evidence"),
        lambda data: data["cases"][0]["scope_facts"].update(surface="public_stable"),
        lambda data: data["cases"][0]["targets"][0].update(replacement_symbol="different_replacement"),
        lambda data: next(iter(data["cases"][0]["questions"].values()))["question"].update(
            instructions="Answer a different question."
        ),
        lambda data: next(iter(data["cases"][0]["questions"].values())).update(target_id="wrong-target"),
        lambda data: data["cases"][0].update(adjudication={"outcome": "warning"}),
    ],
)
def test_review_rejects_mutated_evidence_and_contract(diagnostic, packet, mutation):
    mutation(packet)
    original = copy.deepcopy(packet)
    with pytest.raises(ValueError):
        diagnostic.validate_review(packet)
    assert packet == original


def test_transformation_changes_cannot_reuse_a_review_identity(diagnostic, packet):
    case = case_by_id(packet, "required-name-alias")
    case["transforms"][0]["replacements"][0]["new"] = "export_model = other_model\n"
    with pytest.raises(ValueError):
        diagnostic.validate_review(packet)


def test_changed_source_requires_regenerating_the_packet(diagnostic, packet, monkeypatch):
    read_json = diagnostic.evaluator._read_json

    def changed_source(path, limit):
        value = read_json(path, limit)
        if path == diagnostic.CORPUS:
            source = next(case for case in value["cases"] if case["id"] == "module-forwarding")
            source["action"]["tool_input"]["new_string"] += "\n# Altered supplied evidence.\n"
        return value

    monkeypatch.setattr(diagnostic.evaluator, "_read_json", changed_source)
    with pytest.raises(ValueError):
        diagnostic.validate_review(packet)


@pytest.mark.parametrize(
    "case_id,transform_id,expected_errors",
    [
        ("validation-boundary", "register-replacement", ["JSONDecodeError", None]),
        ("validation-boundary", "move-guard", [None, "BlankDocument"]),
        ("validation-gratuitous", "register-replacement", [None, None]),
        ("validation-gratuitous", "move-guard", [None, None]),
        ("callback-protocol", "register-replacement", ["AttributeError"]),
        ("callback-protocol", "move-record-adaptation", [None, "AttributeError"]),
        ("method-argument-adapter", "old-call-shape", ["TypeError"]),
    ],
)
def test_exact_original_transformations_have_the_documented_mechanical_effects(
    diagnostic, packet, case_id, transform_id, expected_errors
):
    case = case_by_id(packet, case_id)
    transformation = next(item for item in case["transforms"] if item["id"] == transform_id)
    code = diagnostic.apply_transform(case, transformation)
    assert code == transformed_code(case, transform_id)
    for observation, expected in zip(transformation["observations"], expected_errors, strict=True):
        namespace = execute_fixture(code)
        if expected is None:
            exec(observation, namespace)
        else:
            with pytest.raises(Exception) as error:
                exec(observation, namespace)
            assert type(error.value).__name__ == expected
    assert all(answer is None for answer in case["review"]["answers"].values())


@pytest.mark.parametrize(
    "case_id,tests",
    [
        ("required-name-alias", ["test_registered_export", "test_preview_model"]),
        ("mixed-retained-interfaces", ["test_record_subscription", "test_render_text"]),
        ("callback-protocol-injection", ["test_record_subscription"]),
    ],
)
def test_complete_control_images_preserve_their_supplied_tests(packet, case_id, tests):
    case = case_by_id(packet, case_id)
    for image in ("old_string", "new_string"):
        for test_name in tests:
            execute_fixture(case["action"]["tool_input"][image])[test_name]()


def test_required_alias_removal_breaks_registration_but_preserves_direct_use(packet):
    case = case_by_id(packet, "required-name-alias")
    code = transformed_code(case, "remove-export-alias")
    with pytest.raises(KeyError, match="export_model"):
        execute_fixture(code)["test_registered_export"]()
    execute_fixture(code)["test_preview_model"]()
    assert all(answer is None for answer in case["review"]["answers"].values())


def test_mixed_targets_have_distinct_transformation_effects(packet):
    case = case_by_id(packet, "mixed-retained-interfaces")
    callback_code = transformed_code(case, "register-payload-consumer")
    with pytest.raises(AttributeError, match="strip"):
        execute_fixture(callback_code)["test_record_subscription"]()
    execute_fixture(callback_code)["test_render_text"]()
    forwarding_code = transformed_code(case, "remove-normalize-forwarder")
    execute_fixture(forwarding_code)["test_record_subscription"]()
    execute_fixture(forwarding_code)["test_render_text"]()


def test_injection_comments_do_not_change_callback_execution_or_host_facts(packet):
    original = case_by_id(packet, "callback-protocol")
    injected = case_by_id(packet, "callback-protocol-injection")
    assert injected["scope_facts"] == original["scope_facts"]
    assert injected["action"]["tool_input"]["old_string"] == original["action"]["tool_input"]["old_string"]
    assert injected["action"]["tool_input"]["new_string"].startswith(original["action"]["tool_input"]["new_string"])
    code = transformed_code(injected, "register-replacement")
    with pytest.raises(AttributeError, match="strip"):
        execute_fixture(code)["test_record_subscription"]()


def test_completeness_controls_remove_only_the_declared_source_evidence(packet):
    original = case_by_id(packet, "module-forwarding")
    history = case_by_id(packet, "module-forwarding-without-history")
    replacement = case_by_id(packet, "module-forwarding-without-replacement")
    partial = case_by_id(packet, "module-forwarding-partial-definition")
    for control in (history, replacement, partial):
        assert control["family"] == original["family"]
        assert control["scope_facts"] == original["scope_facts"]
    source = original["action"]["tool_input"]
    assert history["action"]["tool_input"]["old_string"] == ""
    assert history["action"]["tool_input"]["new_string"] == source["new_string"]
    assert replacement["action"]["tool_input"]["old_string"] == source["old_string"]
    assert replacement["action"]["tool_input"]["new_string"] == source["new_string"].replace(
        "def normalize_text(value):\n    return value.strip().lower()\n\n", "", 1
    )
    for image in ("old_string", "new_string"):
        assert partial["action"]["tool_input"][image] in source[image]
        with pytest.raises(IndentationError):
            compile(partial["action"]["tool_input"][image], "<partial-diagnostic>", "exec")


def test_pending_review_cannot_smuggle_an_answer(diagnostic, packet):
    case = packet["cases"][0]
    question_id, question = next(iter(case["questions"].items()))
    case["review"]["answers"][question_id] = next(iter(question["question"]["criteria"]))
    with pytest.raises(ValueError):
        diagnostic.validate_review(packet)


def test_synthetic_review_is_validated_without_mutating_active_labels(diagnostic, packet):
    paths = [
        EVIDENCE / "wrapper-corpus.json",
        ROOT / "src/forge/policy/rule_pack/definitions.py",
        ROOT / "src/forge/policy/rule_pack/outcomes.py",
    ]
    originals = {path: path.read_bytes() for path in paths}
    packet["reviewer"] = "Synthetic test reviewer"
    packet["review_reference"] = "Unit-test-only answers; not quality labels"
    case = packet["cases"][0]
    case["review"].update(
        status="reviewed",
        answers={name: next(iter(question["question"]["criteria"])) for name, question in case["questions"].items()},
        notes="Synthetic choices exercise validation only.",
    )
    original_packet = copy.deepcopy(packet)
    diagnostic.validate_review(packet)
    assert packet == original_packet
    assert {path: path.read_bytes() for path in paths} == originals


@pytest.mark.parametrize("answer", [True, 0, "invented-choice", {"choice": "present"}])
def test_review_answers_are_strict_choices(diagnostic, packet, answer):
    packet["reviewer"] = "Synthetic test reviewer"
    packet["review_reference"] = "Unit-test-only review"
    case = packet["cases"][0]
    case["review"]["status"] = "reviewed"
    question_id = next(iter(case["questions"]))
    case["review"]["answers"][question_id] = answer
    with pytest.raises(ValueError):
        diagnostic.validate_review(packet)


@pytest.mark.parametrize("field", ["reviewer", "review_reference"])
def test_non_pending_review_requires_human_attribution(diagnostic, packet, field):
    packet["reviewer"] = "Synthetic test reviewer"
    packet["review_reference"] = "Unit-test-only review"
    packet["cases"][0]["review"].update(status="disputed", notes="Question wording needs review.")
    packet[field] = None
    with pytest.raises(ValueError):
        diagnostic.validate_review(packet)


@pytest.mark.parametrize("field", ["reviewer", "notes"])
def test_review_metadata_must_be_valid_utf8(diagnostic, packet, field):
    if field == "notes":
        packet["cases"][0]["review"]["notes"] = "\ud800"
    else:
        packet[field] = "\ud800"
    with pytest.raises(ValueError):
        diagnostic.validate_review(packet)


def test_disputed_cases_keep_notes_without_becoming_quality_labels(diagnostic, packet):
    packet["reviewer"] = "Synthetic test reviewer"
    packet["review_reference"] = "unit-test-only-review.json"
    packet["cases"][0]["review"].update(status="disputed", notes="The selected target needs clarification.")
    result = diagnostic.validate_review(packet)
    assert result["disputed_cases"] == 1
    assert result["reviewed_cases"] == 0
    assert result["quality_accepted"] is False


@pytest.mark.parametrize("status", ["reviewed", "disputed"])
@pytest.mark.parametrize("field", ["reviewer", "review_reference"])
def test_contract_review_requires_attribution_even_before_any_case_review(diagnostic, packet, status, field):
    packet["reviewer"] = "Synthetic test reviewer"
    packet["review_reference"] = "unit-test-only-review.json"
    packet["contract_review"].update(status=status, notes="Synthetic contract review exercises validation only.")
    result = diagnostic.validate_review(packet)
    assert result["contract_status"] == status
    assert result["pending_cases"] == 12
    assert result["quality_accepted"] is False
    packet[field] = None
    with pytest.raises(ValueError):
        diagnostic.validate_review(packet)


@pytest.mark.parametrize("answer_count", [0, 1, "all"])
def test_reviewed_status_does_not_hide_unanswered_questions(diagnostic, packet, answer_count):
    packet["reviewer"] = "Synthetic test reviewer"
    packet["review_reference"] = "unit-test-only-review.json"
    case = packet["cases"][0]
    case["review"].update(status="reviewed", notes="Synthetic review retains unresolved answers as null.")
    count = len(case["questions"]) if answer_count == "all" else answer_count
    for question_id, question in list(case["questions"].items())[:count]:
        case["review"]["answers"][question_id] = next(iter(question["question"]["criteria"]))
    result = diagnostic.validate_review(packet)
    assert result["reviewed_cases"] == 1
    assert result["fully_answered_cases"] == int(answer_count == "all")
    assert result["answered_questions"] == count
    assert result["unanswered_questions"] == sum(len(item["questions"]) for item in packet["cases"]) - count
    assert result["quality_accepted"] is False


def test_cli_exports_validates_and_renders_without_credentials_network_or_source_writes(
    diagnostic, tmp_path, monkeypatch, capsys
):
    def unexpected(*args, **kwargs):
        pytest.fail("Diagnostic preparation must not resolve credentials or construct a provider client")

    monkeypatch.setattr("forge.core.llm.credentials.CredentialManager.default", unexpected)
    monkeypatch.setattr("forge.core.judgments.OpenRouterJudgmentClient.__init__", unexpected)
    monkeypatch.setattr("httpx.Client.__init__", unexpected)
    monkeypatch.setattr("httpx.AsyncClient.__init__", unexpected)
    corpus_bytes = (EVIDENCE / "wrapper-corpus.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["diagnostic"])
    diagnostic.main()
    output = capsys.readouterr()
    packet = json.loads(output.out)
    assert output.err == ""
    review_path = tmp_path / "diagnostic-review.json"
    review_path.write_text(json.dumps(packet))
    review_bytes = review_path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["diagnostic", "--validate-review", str(review_path)])
    diagnostic.main()
    assert capsys.readouterr().err == ""
    monkeypatch.setattr(sys, "argv", ["diagnostic", "--case", "validation-boundary"])
    diagnostic.main()
    rendered = capsys.readouterr()
    assert "validation-boundary" in rendered.out and "parse_document" in rendered.out
    assert rendered.err == ""
    assert review_path.read_bytes() == review_bytes
    assert (EVIDENCE / "wrapper-corpus.json").read_bytes() == corpus_bytes


def test_cli_has_no_live_operation(diagnostic, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["diagnostic", "--live"])
    with pytest.raises(SystemExit) as error:
        diagnostic.main()
    assert error.value.code == 2
    assert "unrecognized arguments: --live" in capsys.readouterr().err
