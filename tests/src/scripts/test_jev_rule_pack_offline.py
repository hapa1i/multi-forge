"""Bounded offline comparisons retain syntax limits without inventing quality or coverage evidence."""

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/experiments/jev/rule-pack-offline.py"


@pytest.fixture
def offline(monkeypatch):
    spec = importlib.util.spec_from_file_location("jev_rule_pack_offline", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs(offline):
    review = offline.evaluator._read_json(offline.REVIEW, offline.MAX_REVIEW_BYTES)
    corpus = offline.evaluator.Corpus.model_validate(
        offline.evaluator._read_json(offline.CORPUS, offline.evaluator.MAX_CORPUS_BYTES)
    )
    return review, corpus


@pytest.fixture
def report(offline, inputs):
    return offline.build_report(*inputs)


def diagnostic_rows(report):
    return {row["case_id"]: row for row in report["cases"] if row["cohort"] == "diagnostic"}


def lookups(row):
    return {lookup["role"]: lookup for lookup in row["syntactic_presence"][0]["lookups"]}


def test_full_frozen_cohorts_preserve_raw_baselines_and_input_identities(offline, inputs, report):
    review, corpus = inputs
    assert report["counts"] == {
        "diagnostic": {
            "cases": 12,
            "structural_ast": {"assessed/True": 8, "assessed/False": 1, "unavailable/None": 3},
        },
        "constructed": {
            "cases": 17,
            "structural_ast": {
                "assessed/True": 8,
                "assessed/False": 3,
                "host_decision/None": 4,
                "unavailable/None": 2,
            },
        },
    }
    compared = {row["id"]: row for row in offline.baseline.compare(corpus)["cases"]}
    diagnostics = {case["id"]: case for case in review["cases"]}
    for row in report["cases"]:
        if row["cohort"] == "constructed":
            expected = compared[row["case_id"]]
            assert row["marker_regex"] == expected["marker_regex"]
            assert row["structural_ast"] == expected["structural_ast"]
            assert row["case_sha256"] == expected["case_sha256"]
        else:
            case = diagnostics[row["case_id"]]
            action = offline.evaluator.Action.model_validate(case["action"])
            assert row["structural_ast"] == offline.baseline.structural_signal(action)
            assert row["marker_regex"] == offline.baseline.marker_signal(action)
            assert row["action_sha256"] == offline.evaluator._digest(case["action"])
    assert report["inputs"] == {
        "completed_review_sha256": offline.evaluator._digest(review),
        "diagnostic_packet_sha256": review["packet_sha256"],
        "constructed_corpus_sha256": offline.evaluator._digest(corpus.model_dump()),
    }


def test_missing_replacement_history_and_fragment_keep_distinct_unknowns(report):
    rows = diagnostic_rows(report)
    replacement = rows["module-forwarding-without-replacement"]
    assert replacement["structural_ast"]["reason"] == "replacement_definition_missing"
    assert lookups(replacement)["proposed"]["status"] == "declaration_found"
    assert lookups(replacement)["replacement"]["status"] == "not_found_in_supplied_image"
    history = rows["module-forwarding-without-history"]
    assert history["structural_ast"]["reason"] == "missing_complete_interface_definitions"
    assert lookups(history)["prior"]["status"] == "not_found_in_supplied_image"
    assert lookups(history)["replacement"]["status"] == "declaration_found"
    fragment = rows["module-forwarding-partial-definition"]
    assert fragment["structural_ast"]["reason"] == "unparseable_python_evidence"
    assert all(item["status"] == "unavailable" and item["declaration"] is None for item in lookups(fragment).values())
    for row in (replacement, history, fragment):
        assert row["structural_ast"]["flagged"] is None
        assert row["candidate_membership"]["selected_without_recognized_candidate"] == ["normalizer"]


def test_boundary_and_gratuitous_are_both_candidates_without_semantic_verdicts(report):
    rows = diagnostic_rows(report)
    boundary, gratuitous = rows["validation-boundary"], rows["validation-gratuitous"]
    assert boundary["structural_ast"] == gratuitous["structural_ast"]
    assert boundary["structural_ast"]["flagged"] is True
    for row in (boundary, gratuitous):
        assert all(item["status"] == "declaration_found" for item in lookups(row).values())
        assert row["marker_regex"]["flagged"] is False
        assert row["host_applicability"]["outcome"] is None
        assert row["candidate_membership"]["matched_target_ids"] == ["parser"]
        assert not {"expected_outcome", "quality", "coverage", "no_warning", "answers", "review"} & row.keys()


def test_additional_real_candidates_are_membership_differences_not_false_positives(report):
    rows = diagnostic_rows(report)
    for name in ("callback-protocol", "mixed-retained-interfaces", "callback-protocol-injection"):
        membership = rows[name]["candidate_membership"]
        assert membership["additional_candidates"] == [
            {"interface": "process_line", "target": "consume_payload", "shape": "forward_or_adapter"}
        ]
        assert "callback" in membership["matched_target_ids"]
        assert membership["selected_without_recognized_candidate"] == []
    assert rows["module-direct-update"]["structural_ast"]["flagged"] is False
    assert report["quality_accepted"] is False
    assert report["runtime_admitted"] is False
    assert report["max_physical_requests"] == 0
    assert "false positives" in " ".join(report["limitations"])
    assert "does not establish coverage, no_warning" in " ".join(report["limitations"])


def test_host_decisions_and_constructed_unavailability_are_preserved(report):
    rows = {row["case_id"]: row for row in report["cases"] if row["cohort"] == "constructed"}
    expected = {
        "stable-alias": ("not_applicable", "stable_surface"),
        "preview-approved-exception": ("not_applicable", "approved_preview_exception"),
        "unknown-public-status": ("unavailable", "unknown_surface"),
        "write-without-history": ("unavailable", "write_without_prior_interface_evidence"),
    }
    for name, (outcome, reason) in expected.items():
        assert rows[name]["host_applicability"] == {"status": "host_decision", "outcome": outcome, "reason": reason}
        assert rows[name]["structural_ast"]["status"] == "host_decision"
        assert rows[name]["marker_regex"]["status"] == "host_decision"
        assert rows[name]["syntactic_presence"] == []
    assert rows["partial-edit"]["structural_ast"]["flagged"] is None
    assert rows["multi-file-wrapper"]["structural_ast"]["reason"] == "unsupported_tool_shape"


def test_spans_locate_only_supplied_method_and_alias_syntax(inputs, report):
    rows = diagnostic_rows(report)
    cases = {case["id"]: case for case in inputs[0]["cases"]}
    for case_id in ("method-argument-adapter", "required-name-alias"):
        for lookup in lookups(rows[case_id]).values():
            span = lookup["declaration"]["span"]
            lines = cases[case_id]["action"]["tool_input"][lookup["image"]].splitlines()
            first = lines[span["start_line"] - 1].encode()[span["start_utf8_column"] :].decode()
            assert first.startswith("def ") or first == "export_model = dump_model"
            assert span["end_line"] >= span["start_line"]
            assert span["end_utf8_column"] <= len(lines[span["end_line"] - 1].encode())
    alias = lookups(rows["required-name-alias"])["proposed"]["declaration"]
    assert alias["kind"] == "alias"
    assert alias["target"] == "dump_model"


def test_lookup_hints_and_comments_cannot_manufacture_definitions(offline):
    action = SimpleNamespace(
        tool_name="Edit",
        tool_input={
            "file_path": "/unread/target.py",
            "old_string": "# def missing():\n",
            "new_string": "def actual():\n    pass\n",
        },
    )
    targets = [{"id": "hint", "prior_symbol": "missing", "retained_symbol": "missing", "replacement_symbol": "actual"}]
    result = offline.syntax_presence(action, targets)[0]["lookups"]
    assert [item["status"] for item in result] == [
        "not_found_in_supplied_image",
        "not_found_in_supplied_image",
        "declaration_found",
    ]
    assert all("coverage" not in item and "complete" not in item for item in result)


@pytest.mark.parametrize("binding", ["def actual():\n    pass\n", "from other import *\n"])
def test_ambiguous_bindings_keep_syntax_presence_unavailable(offline, binding):
    text = "def actual():\n    pass\n" + binding
    action = SimpleNamespace(tool_name="Edit", tool_input={"file_path": "a.py", "old_string": text, "new_string": text})
    target = {"id": "actual", "prior_symbol": "actual", "retained_symbol": "actual", "replacement_symbol": "actual"}
    result = offline.syntax_presence(action, [target])[0]["lookups"]
    assert all(item["status"] == "unavailable" and item["reason"].startswith("ambiguous_") for item in result)


def test_detectors_never_read_target_paths_or_dispatch_requests(offline, inputs, monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError("Offline inspection must use supplied strings only")

    monkeypatch.setattr(Path, "read_text", forbid)
    monkeypatch.setattr(Path, "read_bytes", forbid)
    monkeypatch.setattr(Path, "open", forbid)
    monkeypatch.setattr(httpx.Client, "send", forbid)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid)
    for case in inputs[0]["cases"]:
        action = offline.evaluator.Action.model_validate(case["action"])
        assert offline.syntax_presence(action, case["targets"])
        offline.baseline.structural_signal(action)
        offline.baseline.marker_signal(action)


def test_report_is_reproducible_read_only_and_hashes_current_sources(offline, inputs, report, monkeypatch):
    before = copy.deepcopy(inputs[0]), inputs[1].model_dump()

    def forbid(*args, **kwargs):
        raise AssertionError("Offline report must not dispatch requests")

    monkeypatch.setattr(httpx.Client, "send", forbid)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid)
    repeated = offline.build_report(*inputs)
    assert offline.evaluator._canonical_bytes(report) == offline.evaluator._canonical_bytes(repeated)
    assert before == (inputs[0], inputs[1].model_dump())
    assert report["sources"][SCRIPT.name] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert report["sources_sha256"] == offline.evaluator._digest(report["sources"])
    serialized = json.dumps(report)
    assert str(ROOT) not in serialized
    assert "reviewer" not in serialized and "review_reference" not in serialized


@pytest.mark.parametrize("mutation", ["reviewer", "answer", "action", "cohort"])
def test_frozen_audit_rejects_altered_labels_actions_and_membership(offline, inputs, mutation):
    review, corpus = inputs
    if mutation == "reviewer":
        review["reviewer"] = "another reviewer"
    elif mutation == "answer":
        answers = review["cases"][0]["review"]["answers"]
        answers[next(iter(answers))] = None
    elif mutation == "action":
        review["cases"][0]["action"]["tool_input"]["new_string"] += "\n# altered\n"
    else:
        corpus.cases.pop()
    with pytest.raises(ValueError):
        offline.build_report(review, corpus)


def test_cli_uses_bounded_loaders_and_emits_reproducible_repository_json(offline, monkeypatch, capsys, tmp_path):
    argv = [str(SCRIPT), "--review", str(offline.REVIEW), "--corpus", str(offline.CORPUS)]
    monkeypatch.setattr(sys, "argv", argv)
    assert offline.main() == 0
    first = capsys.readouterr()
    assert first.err == ""
    parsed = json.loads(first.out)
    assert parsed["max_physical_requests"] == 0
    assert first.out == json.dumps(parsed, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    assert offline.main() == 0
    assert capsys.readouterr().out == first.out
    large = tmp_path / "too-large.json"
    large.write_bytes(b" " * (offline.MAX_REVIEW_BYTES + 1))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--review", str(large), "--corpus", str(offline.CORPUS)])
    with pytest.raises(SystemExit) as exc:
        offline.main()
    assert exc.value.code == 2
    failed = capsys.readouterr()
    assert failed.out == "" and "Traceback" not in failed.err


def test_report_size_bound_refuses_instead_of_truncating(offline, inputs, monkeypatch):
    monkeypatch.setattr(offline, "MAX_REPORT_BYTES", 1)
    with pytest.raises(ValueError, match="bounded report size"):
        offline.build_report(*inputs)
