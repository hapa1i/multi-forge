"""Structural contracts for the packaged release-QA resources."""

from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from types import ModuleType

from packaging.version import Version

from forge.core.runtime import codex_preflight
from forge.install.version import MIN_CLAUDE_CODE_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
QA_ROOT = REPO_ROOT / "src" / "skills" / "qa"
CHECKLIST = QA_ROOT / "resources" / "checklist.md"
REPORT_TEMPLATE = QA_ROOT / "resources" / "report-template.md"
SKILL = QA_ROOT / "SKILL.md"
RUNTIME_MATRIX = QA_ROOT / "resources" / "runtime-matrix.json"
COVERAGE_MAP = QA_ROOT / "resources" / "coverage-map.md"
EXECUTION_BUDGET = QA_ROOT / "resources" / "execution-budget.json"
SELECTION_SCRIPT = QA_ROOT / "scripts" / "qa-selection.py"
BASELINE_INVENTORY = REPO_ROOT / "docs" / "board" / "doing" / "refresh_release_qa_for_1_0" / "baseline-inventory.json"
STATE_SCRIPT = QA_ROOT / "scripts" / "walkthrough-state.py"

EXECUTION_CLASSES = {"auto", "human:confirm", "human:guided"}
EVIDENCE_LANES = {
    "automated-suite",
    "clean-wheel-smoke",
    "human-acceptance",
    "extended-exploratory",
}
OUTCOMES = {"keep", "merge", "move", "remove"}
REPORT_CATEGORIES = {
    "0": "Release Artifact",
    "1": "Pre-Flight",
    "2": "Extensions",
    "3": "Auth",
    "4": "Proxy",
    "5": "Session",
    "6": "Hooks",
    "7": "Costs",
    "8": "Status Line",
    "9": "Direct Commands",
    "10": "Session Resume",
    "11": "Runtime Config",
    "12": "Search",
    "13": "Policy",
    "14": "Workflow Runners",
    "15": "Skills",
    "16": "Memory Writer",
    "17": "System Info",
    "18": "Incremental Disable",
    "19": "Complete Removal",
    "20": "Cleanup",
}


def _load_state_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("forge_qa_checklist_contract_state", STATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATE = _load_state_script()


def _load_selection_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("forge_qa_checklist_contract_selection", SELECTION_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTION = _load_selection_script()


def _parsed_checklist() -> dict:
    return STATE.parse_checklist(str(CHECKLIST))


def _declared_test_count() -> int:
    match = re.search(r"<!--\s*test-count:\s*(\d+)\s*-->", CHECKLIST.read_text(encoding="utf-8"))
    assert match is not None
    return int(match.group(1))


def _report_categories() -> list[str]:
    summary = REPORT_TEMPLATE.read_text(encoding="utf-8").split("## Summary", 1)[1].split("## Issues Found", 1)[0]
    categories: list[str] = []
    for line in summary.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("*") for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] in {"Category", "TOTAL"} or set(cells[0]) <= {"-", ":"}:
            continue
        categories.append(cells[0])
    return categories


def test_declared_assertion_count_matches_all_fragments() -> None:
    parsed = _parsed_checklist()
    assert _declared_test_count() == parsed["total_assertions"] == 676


def test_section_and_step_ids_are_unique_and_execution_classes_are_explicit() -> None:
    parsed = _parsed_checklist()
    sections = parsed["sections"]
    assert [section["id"] for section in sections] == [str(number) for number in range(21)]
    assert len({section["id"] for section in sections}) == len(sections)

    steps = parsed["_all_subs"]
    assert len(steps) == 197
    assert len({step["id"] for step in steps}) == len(steps)
    for step in steps:
        assert step["id"].startswith(f"{step['section_id']}.")
        execution_annotations = EXECUTION_CLASSES.intersection(step["annotations"])
        assert execution_annotations == {step["annotation"]}, step["id"]


def test_report_categories_cover_the_index_in_order() -> None:
    parsed = _parsed_checklist()
    expected = [REPORT_CATEGORIES[section["id"]] for section in parsed["sections"]]
    assert _report_categories() == expected


def test_baseline_inventory_reconciles_parser_and_owner_paths() -> None:
    parsed = _parsed_checklist()
    inventory = json.loads(BASELINE_INVENTORY.read_text(encoding="utf-8"))
    records = inventory["steps"]

    assert inventory["schema_version"] == 1
    assert inventory["baseline_counts"] == {
        "steps": 188,
        "assertions": 636,
        "execution_classes": {"auto": 150, "human:guided": 32, "human:confirm": 6},
    }
    assert len(records) == inventory["baseline_counts"]["steps"]
    assert sum(record["assertion_count"] for record in records) == inventory["baseline_counts"]["assertions"]
    assert Counter(record["execution_class"] for record in records) == inventory["baseline_counts"]["execution_classes"]
    assert len({record["id"] for record in records}) == len(records)

    baseline_by_section: dict[str, list[str]] = defaultdict(list)
    current_by_section: dict[str, list[str]] = defaultdict(list)
    for record in records:
        baseline_by_section[record["section_id"]].append(record["id"])
    for step in parsed["_all_subs"]:
        current_by_section[step["section_id"]].append(step["id"])
    for section_id, baseline_ids in baseline_by_section.items():
        assert current_by_section[section_id][: len(baseline_ids)] == baseline_ids

    for record in records:
        assert record["proposed_outcome"] in OUTCOMES
        assert record["evidence_lane"] in EVIDENCE_LANES
        assert record["target_section"] in REPORT_CATEGORIES
        if record["target_execution_class"] is not None:
            assert record["target_execution_class"] in EXECUTION_CLASSES
        for owner in record["automated_owners"]:
            assert (REPO_ROOT / owner).is_file(), (record["id"], owner)


def test_index_references_each_existing_section_fragment_once() -> None:
    references = re.findall(r"<!-- section:\s*(\d+)\s+([^\s]+)\s*-->", CHECKLIST.read_text(encoding="utf-8"))

    assert [section_id for section_id, _ in references] == [str(number) for number in range(21)]
    for _, relative_path in references:
        assert (CHECKLIST.parent / relative_path).is_file(), relative_path


def test_non_blocking_steps_have_machine_checked_owners() -> None:
    selection = SELECTION.resolve_selection(
        checklist=CHECKLIST,
        parser_script=STATE_SCRIPT,
        budget_path=EXECUTION_BUDGET,
        extended=True,
    )
    included = {step["id"] for step in selection["steps"]}
    all_ids = {step["id"] for step in _parsed_checklist()["_all_subs"]}
    excluded = all_ids - included | {
        step["id"] for step in selection["steps"] if step["evidence_lane"] == "extended-exploratory"
    }

    ownership: dict[str, str] = {}
    for ids, owner in re.findall(
        r"<!-- evidence-owner:\s*([^|]+?)\s*\|\s*([^>]+?)\s*-->",
        COVERAGE_MAP.read_text(),
    ):
        for step_id in ids.split(","):
            ownership[step_id.strip()] = owner.strip()

    assert set(ownership) == excluded
    for step_id, owner in ownership.items():
        assert (REPO_ROOT / owner).is_file(), (step_id, owner)


def test_blocking_selection_matches_ratified_budget() -> None:
    budget = json.loads(EXECUTION_BUDGET.read_text(encoding="utf-8"))
    result = SELECTION.resolve_selection(
        checklist=CHECKLIST,
        parser_script=STATE_SCRIPT,
        budget_path=EXECUTION_BUDGET,
    )

    assert result["selected_counts"] == budget["expected_blocking"]
    assert result["blocking_counts"] == budget["expected_blocking"]
    assert result["blocking_budget_ok"] is True
    assert result["blocking_counts"]["human_checkpoints"] <= budget["blocking"]["max_human_checkpoints"]
    assert result["blocking_counts"]["paid_operations"] <= budget["blocking"]["max_paid_operations"]


def test_blocking_selection_is_closed_over_declared_prerequisites() -> None:
    parsed = _parsed_checklist()
    result = SELECTION.resolve_selection(
        checklist=CHECKLIST,
        parser_script=STATE_SCRIPT,
        budget_path=EXECUTION_BUDGET,
    )
    selected = {step["id"] for step in result["steps"]}
    final_step_by_section = {section["id"]: section["subsections"][-1]["id"] for section in parsed["sections"]}

    for step in parsed["_all_subs"]:
        if step["id"] not in selected:
            continue
        for prerequisite in step["prereqs"]:
            owner = prerequisite if "." in prerequisite else final_step_by_section[prerequisite]
            assert owner in selected, (step["id"], prerequisite, owner)


def test_report_template_requires_release_identity_and_budget_evidence() -> None:
    report = REPORT_TEMPLATE.read_text(encoding="utf-8")
    required_fields = {
        "Artifact Path",
        "Wheel Filename",
        "Wheel SHA-256",
        "Artifact Mode",
        "Forge Version",
        "Runtime Track",
        "Claude Pin / Observed",
        "Codex Pin / Observed",
        "Codex Auth Mode",
        "Provider Profile",
        "Evidence Selection",
        "Duration Seconds",
        "Budget Review Required",
        "Duration Disposition",
        "Human Checkpoints",
        "Paid Operations",
        "Driver Orchestration",
        "Release Verdict",
    }

    for field in required_fields:
        assert f"**{field}**" in report


def test_report_finalization_uses_one_atomic_duration_boundary() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    markers = {
        "__QA_DURATION_SECONDS__",
        "__QA_BUDGET_REVIEW_REQUIRED__",
        "__QA_DURATION_DISPOSITION__",
        "__QA_RELEASE_VERDICT__",
    }

    for marker in markers:
        assert skill.count(marker) >= 2
    assert "$RUN_DIR/report.pending.md" in skill
    assert "os.replace(temporary, report_path)" in skill
    assert "This write is the duration boundary" in skill


def test_runtime_matrix_is_pinned_to_fresh_supported_versions() -> None:
    matrix = json.loads(RUNTIME_MATRIX.read_text(encoding="utf-8"))
    pinned = matrix["tracks"][matrix["blocking_track"]]
    claude = pinned["claude"]
    codex = pinned["codex"]

    assert matrix["schema_version"] == 1
    assert re.fullmatch(r"[0-9a-f]{40}", matrix["validated_forge_revision"])
    assert date.fromisoformat(matrix["validated_on"]) >= date(2026, 8, 25)
    assert pinned["blocking"] is True
    assert matrix["tracks"]["latest"]["blocking"] is False
    assert claude["version"] != "latest"
    assert codex["version"] != "latest"
    assert Version(claude["version"]) >= Version(MIN_CLAUDE_CODE_VERSION)
    assert Version(codex["version"]) >= Version(codex_preflight.CODEX_PROXY_CONTRACT_VALIDATED)
    assert Version(codex["version"]) <= Version(codex_preflight.CODEX_VERSION_VALIDATED)
    assert codex["general_probe_ceiling"] == codex_preflight.CODEX_VERSION_VALIDATED
    assert codex["proxy_contract_floor"] == codex_preflight.CODEX_PROXY_CONTRACT_VALIDATED
    assert "forge runtime preflight codex --json" in codex["probe"]["command"]
    assert codex["probe"]["observed"]["preflight_ready"] is True
    assert codex["probe"]["observed"]["within_validated_ceiling"] is True

    for runtime in (claude, codex):
        assert runtime["probe"]["completed_model_turns"] > 0
        assert all(runtime["probe"]["observed"].values())
