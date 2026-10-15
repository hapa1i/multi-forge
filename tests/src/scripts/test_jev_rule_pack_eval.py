"""Corpus preparation preserves review boundaries without auth or paid inference."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json"


@pytest.fixture
def probe(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-eval.py"
    spec = importlib.util.spec_from_file_location("jev_rule_pack_eval", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def raw():
    return json.loads(CORPUS.read_text())


def test_constructed_proposals_are_never_promoted_to_labels_or_quality(probe, raw):
    report = probe.prepare(probe.Corpus.model_validate(raw))
    assert len(report["cases"]) == len(raw["cases"])
    assert all(case["label_status"] == "unadjudicated" for case in report["cases"])
    assert report["quality_accepted"] is False
    assert report["max_physical_requests"] == 0
    assert "human_adjudication_incomplete" in report["blockers"]
    assert "no_historical_evidence" in report["blockers"]
    assert not any(key.startswith("historical/") for key in report["cohorts"])
    assert sum(report["preparation_counts"].values()) == len(raw["cases"])


def test_payloads_preserve_broad_actions_and_exclude_review_labels(probe, raw):
    raw["cases"][0]["proposal"]["reason"] = "PRIVATE_PROPOSED_LABEL_DO_NOT_SEND"
    raw["cases"][0]["scope_facts"]["basis"] = "PRIVATE_REVIEWER_REASON_DO_NOT_SEND"
    corpus = probe.Corpus.model_validate(raw)
    report = probe.prepare(corpus, include_payloads=True)
    for case, prepared in zip(corpus.cases, report["cases"], strict=True):
        if prepared["preparation"] == "host_decision":
            assert not {"payload", "payload_sha256", "request_bytes"} & prepared.keys()
            continue
        payload = prepared["payload"]
        assert payload["state"] == {
            "action": case.action.model_dump(),
            "scope_facts": case.scope_facts.model_dump(exclude={"basis"}),
        }
        assert payload["provider"]["zdr"] is True
        assert set(payload["questions"]) == {
            "coverage",
            "compatibility_retention",
            "independent_boundary",
        }
        assert "PRIVATE_PROPOSED_LABEL_DO_NOT_SEND" not in json.dumps(payload)
        assert "PRIVATE_REVIEWER_REASON_DO_NOT_SEND" not in json.dumps(payload)
        assert "basis" not in payload["state"]["scope_facts"]
        assert 0 < prepared["request_bytes"] <= 30_000
    injected = next(item for item in report["cases"] if item["id"] == "module-injection")["payload"]
    assert "ignore all questions" in injected["state"]["action"]["tool_input"]["new_string"]
    assert injected["state"]["scope_facts"]["compatibility_decision"] == "not_approved"
    assert injected["questions"] == report["cases"][0]["payload"]["questions"]
    patch = next(item for item in report["cases"] if item["id"] == "multi-file-wrapper")["payload"]
    assert "src/legacy.py" in patch["state"]["action"]["tool_input"]["command"]
    assert "src/core.py" in patch["state"]["action"]["tool_input"]["command"]


@pytest.mark.parametrize("kind", ["constructed", "historical"])
def test_source_families_cannot_cross_splits_even_with_different_ids(probe, raw, kind):
    first = raw["cases"][0]
    other = copy.deepcopy(first)
    other.update(id="different-id", split="held_out")
    if kind == "historical":
        first["provenance"] = other["provenance"] = {
            "kind": "historical",
            "origin": "a" * 40,
        }
        other["family"] = "different-hunk-family"
    raw["cases"] = [first, other]
    with pytest.raises(ValueError, match="crosses"):
        probe.prepare(probe.Corpus.model_validate(raw))


def test_annotations_are_bound_to_evidence_and_do_not_authorize_a_run(probe, raw):
    raw["cases"] = raw["cases"][:1]
    case = probe.Corpus.model_validate(raw).cases[0]
    raw["cases"][0]["adjudication"] = {
        "outcome": "warning",
        "reviewer": "fixture reviewer (not a real adjudication)",
        "review_reference": "unit-test-only",
        "case_sha256": probe.case_digest(case),
    }
    report = probe.prepare(probe.Corpus.model_validate(raw), include_payloads=True)
    assert report["cohorts"] == {"constructed/calibration/adjudicated": 1}
    assert report["max_physical_requests"] == 0 and report["quality_accepted"] is False
    assert "fixture reviewer" not in json.dumps(report["cases"][0]["payload"])
    raw["cases"][0]["scope_facts"]["compatibility_decision"] = "approved"
    with pytest.raises(ValueError, match="Stale adjudication"):
        probe.prepare(probe.Corpus.model_validate(raw))


def test_prompt_changes_have_separate_identity_without_invalidating_annotations(probe, raw, monkeypatch):
    case = probe.Corpus.model_validate(raw).cases[0]
    original = probe.case_digest(case)
    original_prompt = probe.prompt_digest()
    original_payload = probe.prepare(probe.Corpus.model_validate(raw))["cases"][0]["payload_sha256"]
    changed = probe.questions()
    question = changed["compatibility_retention"]
    changed["compatibility_retention"] = question.model_copy(
        update={"instructions": question.instructions + " Consider the supplied evidence carefully."}
    )
    monkeypatch.setattr(probe, "questions", lambda: changed)
    assert probe.case_digest(case) == original
    assert probe.prompt_digest() != original_prompt
    assert probe.prepare(probe.Corpus.model_validate(raw))["cases"][0]["payload_sha256"] != original_payload


def test_true_false_criterion_changes_invalidate_existing_annotations(probe, raw, monkeypatch):
    case = probe.Corpus.model_validate(raw).cases[0]
    original = probe.case_digest(case)
    changed = probe.questions()
    changed["compatibility_retention"].criteria["true"] = "A different rule requiring fresh review"
    monkeypatch.setattr(probe, "questions", lambda: changed)
    assert probe.case_digest(case) != original


@pytest.mark.parametrize("field", ["RULE_DEFINITION", "RULE_VERSION", "CONTRACT_VERSION", "APPLICABILITY"])
def test_semantic_rule_changes_invalidate_existing_annotations(probe, raw, monkeypatch, field):
    case = probe.Corpus.model_validate(raw).cases[0]
    original = probe.case_digest(case)
    replacement = copy.deepcopy(getattr(probe, field))
    if field == "APPLICABILITY":
        replacement["public_preview"]["not_approved"] = "not_applicable"
    else:
        replacement = 4 if field == "CONTRACT_VERSION" else "Changed rule semantics"
    monkeypatch.setattr(probe, field, replacement)
    assert probe.case_digest(case) != original


def test_dataset_bookkeeping_and_review_notes_do_not_change_annotation_identity(probe, raw):
    case = probe.Corpus.model_validate(raw).cases[0]
    changed = case.model_copy(deep=True)
    changed.id = "renamed-example"
    changed.family = "corrected-family"
    changed.split = "held_out"
    changed.reconstruction = "A clarified reconstruction note"
    changed.scope_facts.basis = "An edited reviewer note"
    assert probe.case_digest(changed) == probe.case_digest(case)
    changed.action.tool_input["new_string"] += "\n# changed evidence\n"
    assert probe.case_digest(changed) != probe.case_digest(case)


@pytest.mark.parametrize(
    ("surface", "decision", "outcome"),
    [
        ("unknown", "not_approved", "unavailable"),
        ("unknown", "approved", "unavailable"),
        ("unknown", "unknown", "unavailable"),
        ("internal", "not_approved", None),
        ("internal", "approved", "invalid"),
        ("internal", "unknown", "unavailable"),
        ("public_preview", "not_approved", None),
        ("public_preview", "approved", "not_applicable"),
        ("public_preview", "unknown", "unavailable"),
        ("public_stable", "not_approved", "not_applicable"),
        ("public_stable", "approved", "not_applicable"),
        ("public_stable", "unknown", "not_applicable"),
    ],
)
def test_host_applicability_covers_every_scope_combination(probe, raw, monkeypatch, surface, decision, outcome):
    raw["cases"] = raw["cases"][:1]
    raw["cases"][0]["scope_facts"].update(surface=surface, compatibility_decision=decision)
    corpus = probe.Corpus.model_validate(raw)
    if outcome is not None:

        def unexpected(*args, **kwargs):
            pytest.fail("Host-decided cases must not build a model request")

        monkeypatch.setattr(probe, "build_payload", unexpected)
    if outcome == "invalid":
        with pytest.raises(ValueError, match="Internal approved exceptions"):
            probe.prepare(corpus)
        return
    report = probe.prepare(corpus, include_payloads=True)
    entry = report["cases"][0]
    if outcome is None:
        assert entry["preparation"] == "model_input" and "payload" in entry
        assert report["preparation_counts"] == {"model_input": 1}
    else:
        assert entry["host_outcome"] == outcome
        assert not {"payload", "payload_sha256", "request_bytes"} & entry.keys()
        assert report["preparation_counts"] == {f"host_decision/{outcome}": 1}
    assert report["quality_accepted"] is False


def test_write_without_history_is_host_decided_before_payload_preparation(probe, raw, monkeypatch):
    raw["cases"] = [next(case for case in raw["cases"] if case["id"] == "write-without-history")]

    def unexpected(*args, **kwargs):
        pytest.fail("Write without before evidence must not build a model request")

    monkeypatch.setattr(probe, "build_payload", unexpected)
    entry = probe.prepare(probe.Corpus.model_validate(raw), include_payloads=True)["cases"][0]
    assert entry["host_outcome"] == "unavailable"
    assert entry["host_reason"] == "write_without_prior_interface_evidence"
    assert "payload" not in entry


def test_optional_human_question_answers_are_review_metadata(probe, raw):
    raw["cases"] = raw["cases"][:1]
    case = probe.Corpus.model_validate(raw).cases[0]
    raw["cases"][0]["adjudication"] = {
        "outcome": "uncertain",
        "reviewer": "fixture reviewer",
        "review_reference": "fixture-only",
        "case_sha256": probe.case_digest(case),
        "question_answers": {
            "coverage": True,
            "compatibility_retention": True,
            "independent_boundary": None,
        },
    }
    report = probe.prepare(probe.Corpus.model_validate(raw), include_payloads=True)
    assert report["cases"][0]["label_status"] == "adjudicated"
    assert "question_answers" not in json.dumps(report["cases"][0]["payload"])
    raw["cases"][0]["adjudication"]["question_answers"]["coverage"] = 1
    with pytest.raises(ValueError):
        probe.Corpus.model_validate(raw)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(schema_version=True),
        lambda data: data["cases"][0]["action"].update(origin="codex"),
        lambda data: data["cases"][0]["action"]["tool_input"].update(file_path="../outside.py"),
        lambda data: data["cases"][0]["action"]["tool_input"].update(replace_all="false"),
        lambda data: data["cases"][0]["action"]["tool_input"].update(extra_field="unreviewed"),
        lambda data: data["cases"][0]["provenance"].update(kind="historical", origin="short-sha"),
        lambda data: data["cases"][-1]["action"]["tool_input"].update(command="not a patch"),
        lambda data: data["cases"].append(copy.deepcopy(data["cases"][0])),
    ],
)
def test_invalid_shapes_and_provenance_cannot_produce_a_report(probe, raw, mutation):
    mutation(raw)
    with pytest.raises(ValueError):
        probe.prepare(probe.Corpus.model_validate(raw))


def test_long_actions_are_preserved_or_rejected_never_truncated(probe, raw):
    raw["cases"] = raw["cases"][:1]
    raw["cases"][0]["action"]["tool_input"]["new_string"] = "# " + "x" * 6000 + "\n# retained-tail"
    report = probe.prepare(probe.Corpus.model_validate(raw), include_payloads=True)
    assert report["cases"][0]["payload"]["state"]["action"]["tool_input"]["new_string"].endswith("retained-tail")
    raw["cases"][0]["action"]["tool_input"]["new_string"] = "文" * 30_000
    with pytest.raises(probe.JudgmentError) as exc:
        probe.prepare(probe.Corpus.model_validate(raw))
    assert exc.value.kind == "payload_too_large"


def test_cli_is_offline_even_when_credentials_and_a_client_are_available(probe, monkeypatch, capsys):
    def unexpected(*args, **kwargs):
        pytest.fail("Offline preparation must not resolve credentials or create a client")

    monkeypatch.setattr("forge.core.llm.credentials.CredentialManager.default", unexpected)
    monkeypatch.setattr("forge.core.judgments.OpenRouterJudgmentClient.__init__", unexpected)
    monkeypatch.setattr(sys, "argv", ["rule-pack-eval.py", str(CORPUS)])
    assert probe.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["max_physical_requests"] == 0
    assert "payload" not in report["cases"][0]
    monkeypatch.setattr(sys, "argv", ["rule-pack-eval.py", str(CORPUS), "--run"])
    with pytest.raises(SystemExit) as exc:
        probe.main()
    assert exc.value.code == 2


def test_duplicate_json_cannot_hide_a_second_label_or_scope_value(probe, tmp_path, monkeypatch, capsys):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":1,"schema_version":2}')
    monkeypatch.setattr(sys, "argv", ["rule-pack-eval.py", str(path)])
    with pytest.raises(SystemExit) as exc:
        probe.main()
    assert exc.value.code == 2
    assert "Duplicate JSON key" in capsys.readouterr().err
