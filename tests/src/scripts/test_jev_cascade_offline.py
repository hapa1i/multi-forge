"""A3 fixture admission never treats missing coverage or human labels as model evidence."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/experiments/jev/cascade-offline.py"
CORPUS_PATH = ROOT / "docs/board/doing/jev_cascade/evidence/cascade-corpus.json"


@pytest.fixture
def cascade(monkeypatch):
    spec = importlib.util.spec_from_file_location("jev_cascade_offline_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def sample_corpus():
    return {
        "schema_version": 1,
        "contract_version": "draft-1",
        "families": [
            {
                "id": "text-input",
                "split": "calibration",
                "plan_version": "test-only-v1",
                "plan_text": "Reject blank input with ValueError. Strip surrounding whitespace from accepted input.",
                "clauses": [
                    {
                        "id": "reject-blank",
                        "text": "Reject blank input with ValueError.",
                        "question": {
                            "id": "blank-result",
                            "instructions": "Does the proposed function reject blank input with ValueError?",
                            "criteria": {
                                "true": "Blank input raises ValueError.",
                                "false": "Blank input does not raise ValueError or the evidence is insufficient.",
                            },
                        },
                    },
                    {
                        "id": "strip-accepted",
                        "text": "Strip surrounding whitespace from accepted input.",
                        "question": {
                            "id": "strip-result",
                            "instructions": "Does the proposed function strip surrounding whitespace from its result?",
                            "criteria": {
                                "true": "The result has surrounding whitespace removed.",
                                "false": "The result retains surrounding whitespace or the evidence is insufficient.",
                            },
                        },
                    },
                ],
            }
        ],
        "cases": [
            {
                "id": "complete-edit",
                "family": "text-input",
                "authority": "current",
                "action": {
                    "tool_name": "Edit",
                    "operations": [
                        {
                            "path": "src/example.py",
                            "kind": "edit",
                            "before": "def normalize(text):\n    return text\n",
                            "after": (
                                "def normalize(text):\n"
                                "    if not text.strip():\n"
                                "        raise ValueError('blank')\n"
                                "    return text.strip()\n"
                            ),
                        }
                    ],
                    "complete": True,
                    "truncated": False,
                    "external_context_required": False,
                },
                "coverage": [
                    {
                        "clause_id": "reject-blank",
                        "disposition": "question",
                        "question_id": "blank-result",
                        "rationale": "The changed function directly handles blank input.",
                    },
                    {
                        "clause_id": "strip-accepted",
                        "disposition": "question",
                        "question_id": "strip-result",
                        "rationale": "The changed function returns accepted input.",
                    },
                ],
            }
        ],
    }


@pytest.fixture
def raw():
    return sample_corpus()


def fixture_review(cascade, *, raw=None, **changes):
    """Invented unit-test labels exercise the gate; they are not retained human adjudications."""
    corpus = cascade.Corpus.model_validate(raw if raw is not None else sample_corpus())
    case, family = corpus.cases[0], corpus.families[0]
    return cascade.Review.model_validate(
        {
            "case_sha256": cascade.case_digest(case, family),
            "status": "reviewed",
            "reviewer": "Synthetic unit-test reviewer",
            "authority_sufficient": True,
            "action_complete": True,
            "coverage_complete": True,
            "questions_atomic": True,
            "answers": {"blank-result": True, "strip-result": True},
            "expected_route": "allow",
            "notes": "Test-only labels; no quality or runtime claim.",
            **changes,
        }
    )


def compose(cascade, raw, *, review=None, probabilities=None, **kwargs):
    corpus = cascade.Corpus.model_validate(raw)
    case, family = corpus.cases[0], corpus.families[0]
    return cascade.compose(
        case,
        family,
        review if review is not None else fixture_review(cascade, raw=raw),
        ({"blank-result": 1.0, "strip-result": 1.0} if probabilities is None else probabilities),
        evidence_sha256=kwargs.pop("evidence_sha256", cascade.case_digest(case, family)),
        minimum_true=kwargs.pop("minimum_true", 0.9),
        **kwargs,
    )


def test_missing_clause_escalates_even_when_every_available_question_is_certain(cascade, raw):
    raw["cases"][0]["coverage"].pop()
    route, reasons = compose(cascade, raw, probabilities={"blank-result": 1.0})
    assert route == "escalate"
    assert "unmapped_plan_clause" in reasons


@pytest.mark.parametrize("authority", ["missing", "ambiguous", "stale"])
def test_uncertain_plan_authority_cannot_be_repaired_by_probabilities(cascade, raw, authority):
    raw["cases"][0]["authority"] = authority
    assert compose(cascade, raw) == ("escalate", [f"plan_authority_{authority}"])


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"complete": False}, "incomplete_action"),
        ({"truncated": True}, "incomplete_action"),
        ({"external_context_required": True}, "external_context_required"),
    ],
)
def test_incomplete_action_evidence_stays_escalated(cascade, raw, change, reason):
    raw["cases"][0]["action"].update(change)
    assert compose(cascade, raw) == ("escalate", [reason])


def test_an_uncovered_sibling_operation_prevents_an_allow(cascade, raw):
    action = raw["cases"][0]["action"]
    action["tool_name"] = "apply_patch"
    action["operations"].append(
        {
            "path": "src/sibling.py",
            "kind": "edit",
            "before": "limit = 4\n",
            "after": "limit = 0\n",
        }
    )
    route, reasons = compose(cascade, raw)
    assert route == "escalate"
    assert "multiple_operations_unsupported" in reasons


def test_deletion_and_historyless_write_are_unsupported(cascade, raw):
    action = raw["cases"][0]["action"]
    action["tool_name"] = "apply_patch"
    action["operations"][0].update(kind="delete", after=None)
    route, reasons = compose(cascade, raw)
    assert route == "escalate" and "deletion_unsupported" in reasons
    action["tool_name"] = "Write"
    action["operations"][0].update(kind="write", before=None, after="def normalize(text): return text\n")
    assert compose(cascade, raw) == ("escalate", ["tool_shape_unsupported"])


def test_unsupported_or_entirely_irrelevant_ledger_does_not_create_an_allow(cascade, raw):
    rows = raw["cases"][0]["coverage"]
    rows[0].update(disposition="unsupported", question_id=None)
    assert "unsupported_plan_clause" in compose(cascade, raw)[1]
    for row in rows:
        row.update(disposition="irrelevant", question_id=None)
    assert compose(cascade, raw) == ("escalate", ["no_semantic_questions"])


@pytest.mark.parametrize(
    "field",
    [
        "authority_sufficient",
        "action_complete",
        "coverage_complete",
        "questions_atomic",
    ],
)
@pytest.mark.parametrize("value", [False, None])
def test_each_human_evidence_confirmation_is_required(cascade, raw, field, value):
    review = fixture_review(cascade, **{field: value})
    assert compose(cascade, raw, review=review) == (
        "escalate",
        ["human_evidence_review_incomplete"],
    )


@pytest.mark.parametrize("status", ["pending", "disputed"])
def test_unreviewed_or_disputed_evidence_cannot_allow(cascade, raw, status):
    assert compose(cascade, raw, review=fixture_review(cascade, status=status)) == (
        "escalate",
        ["human_evidence_review_incomplete"],
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"answers": {"blank-result": None, "strip-result": True}},
        {"answers": {}},
        {"expected_route": None},
        {"answers": {"blank-result": True}},
        {"answers": {"blank-result": True, "strip-result": True, "invented": True}},
    ],
)
def test_incomplete_or_unknown_review_answers_prevent_allow(cascade, raw, changes):
    route, reasons = compose(cascade, raw, review=fixture_review(cascade, **changes))
    assert route == "escalate"
    assert reasons


def test_human_label_values_do_not_choose_the_composed_outcome(cascade, raw):
    contradictory_truth = fixture_review(
        cascade,
        answers={"blank-result": False, "strip-result": False},
        expected_route="escalate",
    )
    assert compose(cascade, raw) == ("allow", [])
    assert compose(cascade, raw, review=contradictory_truth) == ("allow", [])
    assert compose(cascade, raw, probabilities={"blank-result": 0.0, "strip-result": 1.0}) == (
        "escalate",
        ["insufficient_agreement"],
    )


def test_existing_deny_and_unrelated_review_survive_an_otherwise_allowing_candidate(cascade, raw):
    assert compose(cascade, raw, existing_deny=True, unrelated_review=True) == (
        "deny",
        ["existing_deny"],
    )
    assert compose(cascade, raw, unrelated_review=True) == (
        "escalate",
        ["unrelated_review_unresolved"],
    )


@pytest.mark.parametrize("probability", [True, "1.0", -0.01, 1.01, float("nan"), float("inf"), None])
def test_invalid_probabilities_are_unavailable_not_alignment(cascade, raw, probability):
    assert compose(cascade, raw, probabilities={"blank-result": probability, "strip-result": 1.0}) == (
        "escalate",
        ["invalid_probability"],
    )


@pytest.mark.parametrize("probabilities", [{}, {"blank-result": 1.0}, {"blank-result": 1.0, "invented": 1.0}])
def test_missing_or_unknown_question_results_escalate(cascade, raw, probabilities):
    assert compose(cascade, raw, probabilities=probabilities) == (
        "escalate",
        ["judgment_unavailable"],
    )


@pytest.mark.parametrize("probabilities", [["blank-result", "strip-result"], [{"blank-result": 1.0}], True, "answer"])
def test_malformed_probability_containers_do_not_raise_or_allow(cascade, raw, probabilities):
    assert compose(cascade, raw, probabilities=probabilities) == ("escalate", ["judgment_unavailable"])


def test_absent_judgment_is_distinct_from_low_agreement(cascade, raw):
    corpus = cascade.Corpus.model_validate(raw)
    case, family = corpus.cases[0], corpus.families[0]
    assert cascade.compose(
        case,
        family,
        fixture_review(cascade),
        None,
        evidence_sha256=cascade.case_digest(case, family),
        minimum_true=0.9,
    ) == ("escalate", ["judgment_unavailable"])


@pytest.mark.parametrize("minimum", [True, None, "0.9", float("nan"), float("inf"), 0.5, 1.01])
def test_composition_requires_an_explicit_finite_band(cascade, raw, minimum):
    with pytest.raises(ValueError, match="minimum_true"):
        compose(cascade, raw, minimum_true=minimum)


@pytest.mark.parametrize("value,route", [(0.899, "escalate"), (0.9, "allow"), (1.0, "allow")])
def test_every_question_must_meet_the_selected_band(cascade, raw, value, route):
    assert compose(cascade, raw, probabilities={"blank-result": 1.0, "strip-result": value})[0] == route


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["families"][0].update(plan_version="test-only-v2"),
        lambda value: value["families"][0].update(plan_text="A different authoritative plan."),
        lambda value: value["families"][0]["clauses"][0]["question"].update(instructions="A changed question."),
        lambda value: value["cases"][0]["action"]["operations"][0].update(after="def normalize(text): return text\n"),
        lambda value: value["cases"][0]["coverage"][0].update(rationale="A changed coverage decision."),
    ],
)
def test_plan_question_action_and_coverage_changes_invalidate_prior_evidence(cascade, raw, mutation):
    corpus = cascade.Corpus.model_validate(raw)
    previous_hash = cascade.case_digest(corpus.cases[0], corpus.families[0])
    mutation(raw)
    assert compose(cascade, raw, evidence_sha256=previous_hash) == (
        "escalate",
        ["stale_evidence_identity"],
    )


def test_changed_guard_or_contract_cannot_reuse_a_prior_evidence_hash(cascade, raw, monkeypatch):
    corpus = cascade.Corpus.model_validate(raw)
    case, family = corpus.cases[0], corpus.families[0]
    original = cascade.case_digest(case, family)
    monkeypatch.setattr(cascade, "GUARD", cascade.GUARD + " Added requirement.")
    assert cascade.case_digest(case, family) != original
    monkeypatch.setattr(cascade, "CONTRACT_VERSION", "draft-2")
    assert cascade.case_digest(case, family) != original


def test_review_of_one_case_cannot_admit_a_pending_sibling_with_identical_question_ids(cascade, raw):
    first_review = fixture_review(cascade, raw=raw)
    assert compose(cascade, raw, review=first_review) == ("allow", [])
    sibling = copy.deepcopy(raw["cases"][0])
    sibling["id"] = "pending-sibling"
    sibling["action"]["operations"][0]["after"] = "def normalize(text):\n    return text\n"
    raw["cases"].append(sibling)
    corpus = cascade.Corpus.model_validate(raw)
    case, family = corpus.cases[1], corpus.families[0]
    assert set(first_review.answers) == set(cascade.questions_for(case, family))
    assert first_review.case_sha256 != cascade.case_digest(case, family)
    route, reasons = cascade.compose(
        case,
        family,
        first_review,
        {"blank-result": 1.0, "strip-result": 1.0},
        evidence_sha256=cascade.case_digest(case, family),
        minimum_true=0.9,
    )
    assert (route, reasons) == ("escalate", ["stale_human_review_identity"])
    report = cascade.prepare(corpus, {item.id: first_review for item in corpus.cases})
    assert report["cases"][0]["human_evidence_ready"] is True
    assert report["cases"][1]["human_evidence_ready"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["cases"][0]["action"]["operations"][0].update(after="def normalize(text): return text\n"),
        lambda value: value["families"][0].update(plan_text="Accept blank text without raising an error."),
        lambda value: value["families"][0].update(plan_version="test-only-v2"),
        lambda value: value["families"][0]["clauses"][0]["question"].update(instructions="Does blank input succeed?"),
    ],
)
def test_current_model_evidence_does_not_refresh_an_old_human_review(cascade, raw, mutation):
    old_review = fixture_review(cascade, raw=raw)
    mutation(raw)
    route, reasons = compose(cascade, raw, review=old_review)
    assert (route, reasons) == ("escalate", ["stale_human_review_identity"])
    corpus = cascade.Corpus.model_validate(raw)
    report = cascade.prepare(corpus, {corpus.cases[0].id: old_review})
    assert report["cases"][0]["human_evidence_ready"] is False


def test_review_packet_refuses_a_review_copied_between_same_family_cases(cascade, raw):
    second = copy.deepcopy(raw["cases"][0])
    second["id"] = "second-case"
    raw["cases"].append(second)
    corpus = cascade.Corpus.model_validate(raw)
    packet = cascade.review_packet(corpus)
    packet["reviews"]["complete-edit"] = fixture_review(cascade, raw=raw).model_dump()
    cascade.validate_reviews(corpus, packet)
    packet["reviews"]["second-case"] = copy.deepcopy(packet["reviews"]["complete-edit"])
    with pytest.raises(ValueError, match="review case identity changed: second-case"):
        cascade.validate_reviews(corpus, packet)


@pytest.mark.parametrize("identity", ["", "short", "g" * 64, None, 7])
def test_review_requires_a_well_formed_case_digest(cascade, identity):
    with pytest.raises(ValidationError):
        fixture_review(cascade, case_sha256=identity)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda packet: packet.update(contract_version="draft-2"),
        lambda packet: packet.update(corpus_sha256="0" * 64),
        lambda packet: packet["case_sha256"].update({"complete-edit": "0" * 64}),
        lambda packet: packet["corpus"].update(schema_version=True),
        lambda packet: packet["corpus"]["cases"][0]["action"].update(complete=1),
        lambda packet: packet["corpus"]["cases"][0]["action"]["operations"][0].update(after="changed\n"),
        lambda packet: packet["reviews"].update({"invented-case": {}}),
        lambda packet: packet["reviews"]["complete-edit"].update(case_sha256="0" * 64),
        lambda packet: packet["reviews"]["complete-edit"]["answers"].update({"invented-question": True}),
        lambda packet: packet["reviews"]["complete-edit"]["answers"].update({"blank-result": "true"}),
    ],
)
def test_review_packets_bind_exact_json_types_evidence_and_membership(cascade, raw, mutation):
    corpus = cascade.Corpus.model_validate(raw)
    packet = cascade.review_packet(corpus)
    mutation(packet)
    before = copy.deepcopy(packet)
    with pytest.raises((ValueError, ValidationError)):
        cascade.validate_reviews(corpus, packet)
    assert packet == before


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version=True),
        lambda value: value["cases"].append(copy.deepcopy(value["cases"][0])),
        lambda value: value["families"].append(copy.deepcopy(value["families"][0])),
        lambda value: value["families"][0]["clauses"].append(copy.deepcopy(value["families"][0]["clauses"][0])),
        lambda value: value["cases"][0]["coverage"].append(copy.deepcopy(value["cases"][0]["coverage"][0])),
        lambda value: value["cases"][0].update(family="missing-family"),
        lambda value: value["cases"][0]["coverage"][0].update(clause_id="missing-clause"),
        lambda value: value["cases"][0]["coverage"][0].update(question_id="strip-result"),
        lambda value: value["cases"][0]["action"].update(tool_name="Write"),
        lambda value: value["cases"][0]["action"]["operations"][0].update(path="../outside.py"),
        lambda value: value["cases"][0]["action"].update(complete=1),
        lambda value: value["families"][0]["clauses"][0]["question"]["criteria"].pop("false"),
    ],
)
def test_corpus_rejects_duplicate_invalid_and_misbound_records(cascade, raw, mutation):
    mutation(raw)
    with pytest.raises(ValidationError):
        cascade.Corpus.model_validate(raw)


def test_preparation_preserves_pending_review_and_cannot_claim_quality(cascade, raw):
    corpus = cascade.Corpus.model_validate(raw)
    packet = cascade.review_packet(corpus)
    original = copy.deepcopy(packet)
    reviews = cascade.validate_reviews(corpus, packet)
    report = cascade.prepare(corpus, reviews)
    assert packet == original
    assert all(row.status == "pending" for row in reviews.values())
    assert all(row.case_sha256 == packet["case_sha256"][case_id] for case_id, row in reviews.items())
    assert all(answer is None for row in reviews.values() for answer in row.answers.values())
    assert report["quality_accepted"] is False
    assert report["max_physical_requests"] == 0
    assert report["semantic_deterministic_baseline"] == "plan_bound_structural_certificates"
    assert report["calibration_preflight"]["status"] == "stop"
    assert report["cases"][0]["declared_admission"] == "candidate_pending_review"
    assert report["cases"][0]["always_escalate_control"] == "escalate"
    assert report["cases"][0]["human_evidence_ready"] is False
    reviewed = {corpus.cases[0].id: fixture_review(cascade)}
    complete = cascade.prepare(corpus, reviewed)
    assert complete["quality_accepted"] is False and complete["max_physical_requests"] == 0
    assert complete["cases"][0]["human_evidence_ready"] is True


@pytest.mark.parametrize(
    "source",
    [
        b'{"duplicate":1,"duplicate":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":1e400}',
        b'"\\ud800"',
    ],
)
def test_noncanonical_json_never_gets_an_identity(cascade, tmp_path, source):
    path = tmp_path / "invalid.json"
    path.write_bytes(source)
    with pytest.raises((ValueError, UnicodeError)):
        cascade.load_json(path)


@pytest.mark.parametrize("kind", ["nan", "surrogate", "deep", "oversize", "duplicate", "invalid-schema"])
def test_cli_errors_are_bounded_diagnostics_without_tracebacks(cascade, raw, tmp_path, monkeypatch, capsys, kind):
    path = tmp_path / "input.json"
    inputs = {
        "nan": b'{"value":NaN}',
        "surrogate": b'"\\ud800"',
        "deep": b"[" * 5_000 + b"0" + b"]" * 5_000,
        "oversize": b" " * (cascade.MAX_BYTES + 1),
        "duplicate": b'{"schema_version":1,"schema_version":1}',
        "invalid-schema": b'{"schema_version":99}',
    }
    path.write_bytes(inputs[kind])
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(path)])
    with pytest.raises(SystemExit) as error:
        cascade.main()
    assert error.value.code == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert "error:" in result.err
    assert "Traceback" not in result.err
    assert len(result.err) < 8_000


def test_cli_exports_validates_and_renders_to_stdout_only(cascade, raw, tmp_path, monkeypatch, capsys):
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(raw))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(corpus_path), "--review-packet"])
    cascade.main()
    result = capsys.readouterr()
    assert result.err == ""
    packet = json.loads(result.out)
    packet_path = tmp_path / "review.json"
    packet_path.write_text(result.out)
    original = [corpus_path.read_bytes(), packet_path.read_bytes()]
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(corpus_path), "--review", str(packet_path)])
    cascade.main()
    result = capsys.readouterr()
    assert result.err == ""
    assert json.loads(result.out)["max_physical_requests"] == 0
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(corpus_path), "--render-family", "text-input"])
    cascade.main()
    result = capsys.readouterr()
    assert result.err == ""
    assert "# A3 review: text-input" in result.out
    assert packet["case_sha256"]["complete-edit"] in result.out
    assert "Human review (pending)" in result.out
    assert [corpus_path.read_bytes(), packet_path.read_bytes()] == original


def test_cli_has_no_capture_execution_option(cascade, raw, tmp_path, monkeypatch, capsys):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(path), "--live"])
    with pytest.raises(SystemExit) as error:
        cascade.main()
    assert error.value.code == 2
    assert "unrecognized arguments: --live" in capsys.readouterr().err


def test_clean_subprocess_cannot_resolve_credentials_dispatch_or_execute_action_code(raw, tmp_path):
    marker = tmp_path / "ACTION_MUST_NOT_EXECUTE"
    raw["cases"][0]["action"]["operations"][0][
        "after"
    ] = f"from pathlib import Path\nPath({str(marker)!r}).write_text('unexpected')\n"
    corpus_path = tmp_path / "synthetic.json"
    corpus_path.write_text(json.dumps(raw))
    bootstrap = """
import runpy
import socket
import sys

def forbidden(*args, **kwargs):
    raise AssertionError("Offline preparation attempted a credential/provider/network operation")

socket.create_connection = forbidden
socket.socket.connect = forbidden
import httpx
from forge.core.llm.credentials import CredentialManager
from forge.core.judgments import OpenRouterJudgmentClient
CredentialManager.default = staticmethod(forbidden)
CredentialManager.get_credentials = forbidden
OpenRouterJudgmentClient.__init__ = forbidden
httpx.Client.__init__ = forbidden
httpx.AsyncClient.__init__ = forbidden
sys.argv = [sys.argv[1], sys.argv[2], "--review-packet"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""
    environment = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "FORGE_HOME": str(tmp_path / "forge"),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONPATH": str(ROOT / "src"),
    }
    result = subprocess.run(
        [sys.executable, "-c", bootstrap, str(SCRIPT), str(corpus_path)],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["reviews"]["complete-edit"]["status"] == "pending"
    assert not marker.exists()


def test_retained_corpus_has_bounded_family_splits_and_no_human_labels(cascade):
    corpus = cascade.Corpus.model_validate(cascade.load_json(CORPUS_PATH))
    assert len(corpus.families) == 4
    assert len(corpus.cases) == 24
    assert sorted(family.split for family in corpus.families) == [
        "calibration",
        "calibration",
        "held_out",
        "held_out",
    ]
    assert all(sum(case.family == family.id for case in corpus.cases) == 6 for family in corpus.families)
    packet = cascade.review_packet(corpus)
    reviews = cascade.validate_reviews(corpus, packet)
    assert all(review.status == "pending" and review.expected_route is None for review in reviews.values())
    assert all(answer is None for review in reviews.values() for answer in review.answers.values())
