"""Human review records stay separate from authored proposals and saved predictions."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json"


@pytest.fixture
def evaluator(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-eval.py"
    spec = importlib.util.spec_from_file_location("jev_rule_pack_review_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def corpus(evaluator):
    raw = json.loads(CORPUS.read_text())
    raw["cases"] = [
        case
        for case in raw["cases"]
        if case["id"] in {"module-forwarding", "module-direct-update", "stable-alias", "write-without-history"}
    ]
    return evaluator.Corpus.model_validate(raw)


def complete(packet, case_id="module-forwarding", outcome="warning"):
    packet["reviewer"] = "synthetic test reviewer"
    packet["review_reference"] = "unit-test-only human-review fixture"
    review = next(row["review"] for row in packet["cases"] if row["id"] == case_id)
    review.update(status="adjudicated", outcome=outcome)
    review["question_answers"] = {"coverage": True, "compatibility_retention": True, "independent_boundary": None}
    review["notes"] = "Synthetic adjudication for contract testing only."
    return review


def import_packet(evaluator, corpus, packet):
    return evaluator.import_review(corpus, evaluator.ReviewPacket.model_validate(packet))


def seed_adjudication(evaluator, corpus):
    case = corpus.cases[0]
    case.adjudication = evaluator.Adjudication(
        outcome="no_warning",
        reviewer="PREVIOUS_REVIEWER_SENTINEL",
        review_reference="PREVIOUS_REFERENCE_SENTINEL",
        case_sha256=evaluator.case_digest(case),
        question_answers=None,
    )
    return case


def test_review_export_withholds_authored_rationales_and_existing_labels(evaluator, corpus):
    case = seed_adjudication(evaluator, corpus)
    case.proposal.reason = "PROPOSED_REASON_SENTINEL"
    case.scope_facts.basis = "SCOPE_RATIONALE_SENTINEL"
    case.reconstruction = "RECONSTRUCTION_SENTINEL"
    packet = evaluator.review_packet(corpus)
    serialized = json.dumps(packet)
    for sentinel in (
        "PREVIOUS_REVIEWER_SENTINEL",
        "PREVIOUS_REFERENCE_SENTINEL",
        "PROPOSED_REASON_SENTINEL",
        "SCOPE_RATIONALE_SENTINEL",
        "RECONSTRUCTION_SENTINEL",
    ):
        assert sentinel not in serialized
    assert packet["reviewer"] is None and packet["review_reference"] is None
    assert packet["rule"]["definition"] == evaluator.RULE_DEFINITION
    for source, row in zip(corpus.cases, packet["cases"], strict=True):
        assert row["action"] == source.action.model_dump()
        assert row["scope_facts"] == source.scope_facts.model_dump(exclude={"basis"})
        assert row["case_sha256"] == evaluator.case_digest(source)
        assert row["review"] == {
            "status": "pending",
            "outcome": None,
            "question_answers": {name: None for name in evaluator.questions()},
            "notes": "",
            "replace_existing": False,
        }
        assert not {"proposal", "adjudication", "host_outcome", "predictions", "reconstruction"} & row.keys()


def test_exported_rule_copy_cannot_mutate_shared_applicability(evaluator, corpus):
    packet = evaluator.review_packet(corpus)
    packet["rule"]["applicability"]["internal"]["not_approved"] = "not_applicable"
    assert evaluator.APPLICABILITY["internal"]["not_approved"] != "not_applicable"


def test_pending_reviews_preserve_existing_labels_without_inventing_missing_labels(evaluator, corpus):
    seed_adjudication(evaluator, corpus)
    packet = evaluator.review_packet(corpus)
    packet["cases"][1]["review"]["notes"] = "Awaiting a human decision."
    assert import_packet(evaluator, corpus, packet) == corpus.model_dump()


def test_import_changes_only_explicit_human_adjudication_and_keeps_source_metadata(evaluator, corpus):
    original = corpus.model_dump()
    packet = evaluator.review_packet(corpus)
    review = complete(packet)
    imported = import_packet(evaluator, corpus, packet)
    assert corpus.model_dump() == original
    expected = copy.deepcopy(original)
    expected["cases"][0]["adjudication"] = {
        "outcome": "warning",
        "reviewer": packet["reviewer"],
        "review_reference": packet["review_reference"],
        "case_sha256": packet["cases"][0]["case_sha256"],
        "question_answers": review["question_answers"],
    }
    assert imported == expected
    assert evaluator.Corpus.model_validate(imported).cases[0].adjudication.outcome == "warning"
    assert "Synthetic adjudication" not in json.dumps(imported)


def test_existing_adjudication_requires_an_explicit_replacement(evaluator, corpus):
    case = seed_adjudication(evaluator, corpus)
    original = case.adjudication.model_dump()
    packet = evaluator.review_packet(corpus)
    review = complete(packet)
    with pytest.raises(ValueError, match="replace_existing=true"):
        import_packet(evaluator, corpus, packet)
    assert case.adjudication.model_dump() == original
    review["replace_existing"] = True
    result = import_packet(evaluator, corpus, packet)
    assert result["cases"][0]["adjudication"]["outcome"] == "warning"
    assert case.adjudication.model_dump() == original


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["cases"].append(copy.deepcopy(data["cases"][0])),
        lambda data: data["cases"].pop(),
        lambda data: data["cases"][0].update(id="unknown-case"),
        lambda data: data["cases"][0].update(case_sha256="0" * 64),
        lambda data: data["cases"][0]["action"]["tool_input"].update(new_string="# altered evidence"),
        lambda data: data["cases"][0]["action"]["tool_input"].update(replace_all=0),
        lambda data: data["cases"][0]["scope_facts"].update(surface="public_stable"),
        lambda data: data["cases"][0].update(family="other-family"),
        lambda data: data["cases"][0].update(split="held_out"),
        lambda data: data["cases"][0]["provenance"].update(origin="altered-provenance"),
        lambda data: data["rule"].update(definition="Altered rule"),
        lambda data: data["rule"].update(evidence_contract_version=float(data["rule"]["evidence_contract_version"])),
        lambda data: data.update(corpus_sha256="0" * 64),
        lambda data: data.update(schema_version=2),
        lambda data: data["rule"]["questions"]["coverage"]["criteria"].update(true="Altered criterion"),
        lambda data: data["cases"][0].update(proposal={"outcome": "warning"}),
    ],
)
def test_import_rejects_unbound_membership_contract_and_evidence(evaluator, corpus, mutation):
    original = corpus.model_dump()
    packet = evaluator.review_packet(corpus)
    complete(packet)
    mutation(packet)
    with pytest.raises(ValueError):
        import_packet(evaluator, corpus, packet)
    assert corpus.model_dump() == original


def test_source_evidence_edit_invalidates_its_prepared_review(evaluator, corpus):
    packet = evaluator.review_packet(corpus)
    complete(packet)
    corpus.cases[0].action.tool_input["new_string"] += "\n# Evidence changed after export.\n"
    with pytest.raises(ValueError, match="stale for module-forwarding"):
        import_packet(evaluator, corpus, packet)


@pytest.mark.parametrize("status", ["excluded", "disputed"])
def test_unresolved_reviews_block_import_without_deleting_rows_or_notes(evaluator, corpus, status):
    packet = evaluator.review_packet(corpus)
    complete(packet)
    packet["cases"][1]["review"].update(status=status, notes="Unresolved scope or disagreement; retain for resolution.")
    original = copy.deepcopy(packet)
    with pytest.raises(ValueError, match="module-direct-update.*revise the source corpus and regenerate"):
        import_packet(evaluator, corpus, packet)
    assert packet == original
    assert all(case.adjudication is None for case in corpus.cases)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda review: review.update(outcome="warning"),
        lambda review: review["question_answers"].update(coverage=False),
        lambda review: review.update(replace_existing=True),
        lambda review: review.update(status="adjudicated"),
        lambda review: review.update(status="excluded"),
        lambda review: review.update(status="disputed"),
        lambda review: review.update(status="ambiguous"),
    ],
)
def test_ambiguous_review_states_are_not_importable(evaluator, corpus, mutation):
    packet = evaluator.review_packet(corpus)
    mutation(packet["cases"][0]["review"])
    with pytest.raises(ValueError):
        import_packet(evaluator, corpus, packet)


@pytest.mark.parametrize("field", ["reviewer", "review_reference"])
def test_labeled_reviews_require_attribution(evaluator, corpus, field):
    packet = evaluator.review_packet(corpus)
    complete(packet)
    packet[field] = None
    with pytest.raises(ValueError, match="human reviewer and review_reference"):
        import_packet(evaluator, corpus, packet)


def test_model_candidates_require_question_fields_but_unknown_answers_can_stay_null(evaluator, corpus):
    packet = evaluator.review_packet(corpus)
    review = complete(packet)
    review["question_answers"] = None
    with pytest.raises(ValueError, match="all three human question-answer fields"):
        import_packet(evaluator, corpus, packet)
    review["question_answers"] = {name: None for name in evaluator.questions()}
    assert (
        import_packet(evaluator, corpus, packet)["cases"][0]["adjudication"]["question_answers"]
        == review["question_answers"]
    )


def test_host_questions_can_be_omitted_only_with_a_recorded_justification(evaluator, corpus):
    packet = evaluator.review_packet(corpus)
    review = complete(packet, "stable-alias", "not_applicable")
    review.update(question_answers=None, notes="")
    with pytest.raises(ValueError, match="explain omitted host-case"):
        import_packet(evaluator, corpus, packet)
    review["notes"] = "Stable surface is outside this rule; no model questions apply."
    result = import_packet(evaluator, corpus, packet)
    host = next(case for case in result["cases"] if case["id"] == "stable-alias")
    assert host["adjudication"]["question_answers"] is None


@pytest.mark.parametrize("bad", [1, "true"])
def test_human_boolean_labels_are_strict(evaluator, corpus, bad):
    packet = evaluator.review_packet(corpus)
    complete(packet)["question_answers"]["coverage"] = bad
    with pytest.raises(ValueError):
        import_packet(evaluator, corpus, packet)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "\ud800"])
def test_packet_requires_finite_utf8_json(evaluator, corpus, bad):
    packet = evaluator.review_packet(corpus)
    packet["rule"]["extra"] = bad
    with pytest.raises(ValueError, match="finite UTF-8 JSON"):
        import_packet(evaluator, corpus, packet)


def test_cli_exports_and_imports_without_auth_network_or_source_writes(
    evaluator, corpus, tmp_path, monkeypatch, capsys
):
    def unexpected(*args, **kwargs):
        pytest.fail("Review must not resolve auth or instantiate a provider client")

    monkeypatch.setattr("forge.core.llm.credentials.CredentialManager.default", unexpected)
    monkeypatch.setattr("forge.core.judgments.OpenRouterJudgmentClient.__init__", unexpected)
    source = tmp_path / "corpus.json"
    source.write_text(corpus.model_dump_json())
    original = source.read_bytes()
    monkeypatch.setattr(sys, "argv", ["eval", str(source), "--review-packet"])
    assert evaluator.main() == 0
    packet = json.loads(capsys.readouterr().out)
    complete(packet)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(packet))
    original_review = review_path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["eval", str(source), "--import-review", str(review_path)])
    assert evaluator.main() == 0
    output = capsys.readouterr()
    imported = json.loads(output.out)
    assert output.err == ""
    assert imported["cases"][0]["adjudication"]["outcome"] == "warning"
    assert source.read_bytes() == original and review_path.read_bytes() == original_review


@pytest.mark.parametrize(
    "other",
    [["--include-payloads"], ["--prediction-template"], ["--split", "held_out"], ["--import-review", "review.json"]],
)
def test_review_cli_refuses_ambiguous_operation_combinations(evaluator, tmp_path, monkeypatch, capsys, other):
    monkeypatch.setattr(sys, "argv", ["eval", str(tmp_path / "unused.json"), "--review-packet", *other])
    with pytest.raises(SystemExit) as error:
        evaluator.main()
    assert error.value.code == 2
    assert "Choose one review operation" in capsys.readouterr().err


def test_review_file_size_limit_precedes_parsing(evaluator, corpus, tmp_path, monkeypatch, capsys):
    source = tmp_path / "corpus.json"
    source.write_text(corpus.model_dump_json())
    oversized = tmp_path / "oversized-review.json"
    oversized.write_text(" " * 4_000_001)
    monkeypatch.setattr(sys, "argv", ["eval", str(source), "--import-review", str(oversized)])
    with pytest.raises(SystemExit) as error:
        evaluator.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == "" and "4000000-byte offline input limit" in output.err


@pytest.mark.parametrize("field,limit", [("reviewer", 256), ("review_reference", 1024)])
def test_review_attribution_is_bounded_before_it_can_expand_into_every_case(evaluator, corpus, field, limit):
    packet = evaluator.review_packet(corpus)
    complete(packet)
    packet[field] = "x" * (limit + 1)
    with pytest.raises(ValueError, match=field):
        import_packet(evaluator, corpus, packet)
    packet[field] = "x" * limit
    imported = import_packet(evaluator, corpus, packet)
    assert imported["cases"][0]["adjudication"][field] == packet[field]


def test_bounded_attribution_cannot_produce_an_unreadable_amplified_corpus(evaluator, corpus):
    template = corpus.cases[0].model_copy(deep=True)
    template.action.tool_input.update(old_string="def old(): return 1\n", new_string="def old(): return new()\n")
    template.scope_facts.basis = template.reconstruction = template.proposal.reason = "Synthetic fixture."
    template.provenance.origin = "unit-test"
    corpus.cases = [template.model_copy(update={"id": f"case-{index}"}, deep=True) for index in range(500)]
    assert len(corpus.model_dump_json().encode()) < evaluator.MAX_CORPUS_BYTES
    packet = evaluator.review_packet(corpus)
    for case in corpus.cases:
        complete(packet, case.id)
    packet["reviewer"] = "r" * 256
    packet["review_reference"] = "f" * 1024
    with pytest.raises(ValueError, match="Imported corpus exceeds.*no corpus was emitted"):
        import_packet(evaluator, corpus, packet)
    assert all(case.adjudication is None for case in corpus.cases)


@pytest.mark.parametrize("adjudicated", [False, True])
def test_import_output_limit_uses_printed_encoding_and_never_emits_partial_json(
    evaluator, corpus, tmp_path, monkeypatch, capsys, adjudicated
):
    # UTF-8 input fits, but default pretty JSON emits each non-ASCII character as a six-byte escape.
    corpus.cases[0].scope_facts.basis = "é" * 180_000
    source = tmp_path / "compact-corpus.json"
    source.write_text(corpus.model_dump_json())
    original = source.read_bytes()
    assert len(original) < evaluator.MAX_CORPUS_BYTES
    assert len(json.dumps(corpus.model_dump(), indent=2).encode()) > evaluator.MAX_CORPUS_BYTES
    packet = evaluator.review_packet(corpus)
    if adjudicated:
        complete(packet)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(packet))
    monkeypatch.setattr(sys, "argv", ["eval", str(source), "--import-review", str(review_path)])
    with pytest.raises(SystemExit) as error:
        evaluator.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "1000000-byte corpus input limit" in output.err and "no corpus was emitted" in output.err
    assert source.read_bytes() == original
