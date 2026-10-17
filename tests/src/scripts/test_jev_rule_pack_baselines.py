"""Offline baselines compare structural signals without turning them into human or model judgments."""

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge.core.judgments.types import JudgmentError
from forge.policy.deterministic import coding_standards

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json"


@pytest.fixture
def baseline(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-baselines.py"
    spec = importlib.util.spec_from_file_location("jev_rule_pack_baselines", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def raw():
    data = json.loads(CORPUS.read_text())
    for case in data["cases"]:
        case["adjudication"] = None
    return data


def edit(before, after, path="src/example.py"):
    return SimpleNamespace(
        tool_name="Edit",
        tool_input={"file_path": path, "old_string": before, "new_string": after, "replace_all": False},
    )


def rows_by_id(baseline, raw):
    return {row["id"]: row for row in baseline.compare(baseline.evaluator.Corpus.model_validate(raw))["cases"]}


def test_both_baselines_share_request_admission_and_identities(baseline, raw):
    corpus = baseline.evaluator.Corpus.model_validate(raw)
    expected = baseline.evaluator.prepare(corpus)
    report = baseline.compare(corpus)
    assert report["max_physical_requests"] == 0
    assert report["quality_accepted"] is False
    assert report["corpus_sha256"] == baseline.evaluator.corpus_digest(corpus)
    assert report["prompt_sha256"] == expected["prompt_sha256"]
    assert "rule-pack-baselines.py" in report["sources"]
    assert "forge.policy.rule_pack.definitions" in report["sources"]
    assert "forge.policy.deterministic.coding_standards" in report["sources"]
    assert "forge.cli.hooks.codex_patch" in report["sources"]
    for row, prepared in zip(report["cases"], expected["cases"], strict=True):
        assert row["case_sha256"] == prepared["case_sha256"]
        assert row["payload_sha256"] == prepared.get("payload_sha256")
        assert row["admission"] == prepared["preparation"]
        assert "expected_outcome" not in row


def test_marker_patterns_are_reused_and_raw_matches_do_not_bypass_host_gates(baseline, raw, monkeypatch):
    monkeypatch.setattr(coding_standards, "BACKWARD_COMPAT_PATTERNS", [r"export_model"])
    row = rows_by_id(baseline, raw)["stable-alias"]
    assert row["marker_regex"]["raw_matches"][0]["patterns"] == [r"export_model"]
    assert row["marker_regex"]["flagged"] is None
    assert row["marker_regex"]["status"] == "host_decision"
    assert row["structural_ast"]["status"] == "host_decision"
    assert row["host_outcome"] == "not_applicable"


def test_source_comments_are_data_and_current_marker_patterns_remain_case_sensitive(baseline):
    action = edit("def old():\n    return 1\n", "# backward compat\n# Backward compat\ndef old():\n    return 1\n")
    result = baseline.marker_signal(action)
    assert result["flagged"] is True
    assert all(pattern in coding_standards.BACKWARD_COMPAT_PATTERNS for pattern in result["raw_matches"][0]["patterns"])
    action.tool_input["new_string"] = "# Backward compat\ndef old():\n    return 1\n"
    assert baseline.marker_signal(action)["flagged"] is False


@pytest.mark.parametrize(
    "case_id", ["module-forwarding", "module-injection", "method-argument-adapter", "preview-alias"]
)
def test_forwarding_method_and_alias_shapes_are_candidates(baseline, raw, case_id):
    row = rows_by_id(baseline, raw)[case_id]
    assert row["structural_ast"]["status"] == "assessed"
    assert row["structural_ast"]["flagged"] is True
    assert row["structural_ast"]["candidates"]
    assert row["marker_regex"]["flagged"] is False


@pytest.mark.parametrize("case_id", ["callback-protocol", "validation-boundary", "validation-gratuitous"])
def test_legitimate_and_gratuitous_boundaries_are_both_structural_candidates(baseline, raw, case_id):
    row = rows_by_id(baseline, raw)[case_id]
    assert row["structural_ast"]["flagged"] is True
    assert "outcome" not in row["structural_ast"]
    assert "independent_boundary" not in row["structural_ast"]


def test_complete_clean_break_has_no_retained_pattern(baseline, raw):
    row = rows_by_id(baseline, raw)["module-direct-update"]
    assert row["structural_ast"] == {"status": "assessed", "reason": None, "flagged": False, "candidates": []}
    assert "no_warning" not in row.values()


def test_return_shape_adapter_uses_only_the_assigned_call_result(baseline):
    before = "def count(items):\n    return len(items)\n"
    after = (
        "def describe(items):\n    return {'count': len(items)}\n"
        "def count(items):\n    result = describe(items)\n    return result['count']\n"
    )
    signal = baseline.structural_signal(edit(before, after))
    assert signal["candidates"] == [{"interface": "count", "target": "describe", "shape": "forward_or_adapter"}]
    # An unrelated call followed by an independent result is outside this bounded shape.
    assert baseline.structural_signal(edit(before, after.replace("result['count']", "3")))["flagged"] is False


@pytest.mark.parametrize(
    ("before", "after", "reason"),
    [
        ("return old(value)", "return new(value)", "missing_complete_interface_definitions"),
        ("def old(value):", "def new(value):", "unparseable_python_evidence"),
        (
            "def old(value):\n    return value\n",
            "def old(value):\n    return imported(value)\n",
            "replacement_definition_missing",
        ),
        (
            "def old(value):\n    return value\n",
            "def old(value):\n    return value\ndef old(value):\n    return value + 1\n",
            "ambiguous_repeated_binding",
        ),
    ],
)
def test_incomplete_and_ambiguous_evidence_stays_unknown(baseline, before, after, reason):
    signal = baseline.structural_signal(edit(before, after))
    assert signal["status"] == "unavailable"
    assert signal["flagged"] is None
    assert signal["reason"] == reason


def test_multifile_patch_has_raw_added_markers_but_no_ast_verdict(baseline, raw):
    case = next(case for case in raw["cases"] if case["id"] == "multi-file-wrapper")
    case["action"]["tool_input"]["command"] = case["action"]["tool_input"]["command"].replace(
        "+from .core", "+# backward compat\n+from .core"
    )
    row = rows_by_id(baseline, raw)["multi-file-wrapper"]
    assert row["marker_regex"]["flagged"] is True
    assert len(row["marker_regex"]["raw_matches"]) == 2
    assert row["structural_ast"]["status"] == "unavailable"
    assert row["structural_ast"]["reason"] == "unsupported_tool_shape"


def test_host_write_and_unknown_scope_do_not_become_negative_results(baseline, raw):
    rows = rows_by_id(baseline, raw)
    for case_id, reason in (
        ("write-without-history", "write_without_prior_interface_evidence"),
        ("unknown-public-status", "unknown_surface"),
        ("preview-approved-exception", "approved_preview_exception"),
    ):
        for detector in ("marker_regex", "structural_ast"):
            assert rows[case_id][detector]["status"] == "host_decision"
            assert rows[case_id][detector]["reason"] == reason
            assert rows[case_id][detector]["flagged"] is None


def test_non_python_action_is_not_a_negative(baseline):
    action = edit("const old = 1;", "const old = 2;", "src/example.js")
    assert baseline.marker_signal(action)["flagged"] is None
    assert baseline.structural_signal(action)["flagged"] is None


def test_oversized_and_invalid_actions_fail_shared_admission(baseline, raw):
    raw["cases"] = raw["cases"][:1]
    original = copy.deepcopy(raw)
    raw["cases"][0]["action"]["tool_input"]["new_string"] += "#" * 30_000
    with pytest.raises(JudgmentError, match="byte input cap"):
        baseline.compare(baseline.evaluator.Corpus.model_validate(raw))
    original["cases"][0]["action"]["tool_input"]["extra"] = "not allowed"
    with pytest.raises(ValueError, match="Incomplete or unexpected"):
        baseline.compare(baseline.evaluator.Corpus.model_validate(original))


def test_labels_proposals_and_scope_notes_never_reach_detectors(baseline, raw, monkeypatch):
    raw["cases"][0]["proposal"]["reason"] = "PRIVATE_PROPOSAL"
    raw["cases"][0]["scope_facts"]["basis"] = "PRIVATE_BASIS"
    raw["cases"][0]["reconstruction"] = "PRIVATE_RECONSTRUCTION"
    seen = []
    original = baseline.structural_signal

    def inspect_action(action):
        seen.append(action.model_dump())
        return original(action)

    monkeypatch.setattr(baseline, "structural_signal", inspect_action)
    corpus = baseline.evaluator.Corpus.model_validate(raw)
    without_labels = baseline.compare(corpus)
    first = corpus.cases[0]
    first.adjudication = baseline.evaluator.Adjudication(
        outcome="no_warning",
        reviewer="PRIVATE_REVIEWER",
        review_reference="PRIVATE_REFERENCE",
        case_sha256=baseline.evaluator.case_digest(first),
    )
    assert baseline.compare(corpus) == without_labels
    serialized = json.dumps([without_labels, seen])
    for text in (
        "PRIVATE_PROPOSAL",
        "PRIVATE_BASIS",
        "PRIVATE_RECONSTRUCTION",
        "PRIVATE_REVIEWER",
        "PRIVATE_REFERENCE",
    ):
        assert text not in serialized


def test_detectors_never_read_the_supplied_target_path(baseline, monkeypatch):
    def forbid_read(*args, **kwargs):
        raise AssertionError("Detector tried to supplement action evidence with a file read")

    monkeypatch.setattr(Path, "read_text", forbid_read)
    monkeypatch.setattr(Path, "read_bytes", forbid_read)
    action = edit("def old(value):\n    return value\n", "def new(value):\n    return value\nold = new\n")
    assert baseline.structural_signal(action)["flagged"] is True
    assert baseline.marker_signal(action)["flagged"] is False


def test_cli_emits_offline_json_and_rejects_malformed_input(baseline, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["rule-pack-baselines.py", str(CORPUS)])
    assert baseline.main() == 0
    assert json.loads(capsys.readouterr().out)["max_physical_requests"] == 0
    bad = tmp_path / "bad.json"
    bad.write_text('{"cases": []}')
    monkeypatch.setattr(sys, "argv", ["rule-pack-baselines.py", str(bad)])
    with pytest.raises(SystemExit) as exc:
        baseline.main()
    assert exc.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "retained",
    [
        "def old(new):\n    return new('input')\n",
        "def old(*, new):\n    return new('input')\n",
        "def old(*new):\n    return new('input')\n",
        "def old(**new):\n    return new('input')\n",
        "def old(value):\n    from callbacks import new\n    return new(value)\n",
        "def old(value):\n    import callbacks as new\n    return new(value)\n",
        "def old(value):\n    new: object = callback\n    return new(value)\n",
        "def old(value):\n    new = new(value)\n    return new\n",
        "def old(value):\n    nonlocal new\n    return new(value)\n",
    ],
)
def test_shadowed_replacement_is_unavailable_instead_of_resolved_by_spelling(baseline, retained):
    before = "def old(value):\n    return value.strip()\n"
    after = "def new(value):\n    return value.strip()\n" + retained
    signal = baseline.structural_signal(edit(before, after))
    assert signal == {
        "status": "unavailable",
        "flagged": None,
        "candidates": [],
        "reason": "ambiguous_target_binding",
    }


@pytest.mark.parametrize(
    "binding",
    [
        "from callbacks import new\n",
        "import callbacks as new\n",
        "new: object = external\n",
        "new, other = callbacks\n",
        "if enabled:\n    new = external\n",
    ],
)
def test_rebound_supplied_replacement_is_unavailable(baseline, binding):
    before = "def old(value):\n    return value.strip()\n"
    after = "def new(value):\n    return value.strip()\n" + binding + "def old(value):\n    return new(value)\n"
    signal = baseline.structural_signal(edit(before, after))
    assert signal["status"] == "unavailable"
    assert signal["flagged"] is None
    assert signal["reason"] == "ambiguous_repeated_binding"


def test_wildcard_import_cannot_establish_target_identity(baseline):
    before = "def old(value):\n    return value.strip()\n"
    after = (
        "def new(value):\n    return value.strip()\nfrom callbacks import *\ndef old(value):\n    return new(value)\n"
    )
    signal = baseline.structural_signal(edit(before, after))
    assert signal["reason"] == "ambiguous_target_binding"
    assert signal["flagged"] is None


def test_unrelated_nested_scope_does_not_shadow_module_replacement(baseline):
    before = "def old(value):\n    return value.strip()\n"
    after = (
        "def new(value):\n    return value.strip()\n"
        "def unrelated():\n    from callbacks import new\n    return new\n"
        "def old(value):\n    return new(value)\n"
    )
    signal = baseline.structural_signal(edit(before, after))
    assert signal["status"] == "assessed"
    assert signal["candidates"] == [{"interface": "old", "target": "new", "shape": "forward_or_adapter"}]
