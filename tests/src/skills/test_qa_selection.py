from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
QA_ROOT = REPO_ROOT / "src" / "skills" / "qa"
CHECKLIST = QA_ROOT / "resources" / "checklist.md"
STATE_SCRIPT = QA_ROOT / "scripts" / "walkthrough-state.py"
BUDGET = QA_ROOT / "resources" / "execution-budget.json"
SELECTION_SCRIPT = QA_ROOT / "scripts" / "qa-selection.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("forge_qa_selection_test", SELECTION_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECTION = _load()


def _resolve(**kwargs):
    return SELECTION.resolve_selection(
        checklist=CHECKLIST,
        parser_script=STATE_SCRIPT,
        budget_path=BUDGET,
        **kwargs,
    )


def test_blocking_selection_excludes_automated_and_exploratory_steps() -> None:
    result = _resolve()
    lanes = {step["evidence_lane"] for step in result["steps"]}
    ids = {step["id"] for step in result["steps"]}

    assert lanes == {"clean-wheel-smoke", "human-acceptance"}
    assert {"4.6", "10.5", "13.7", "14.2"}.isdisjoint(ids)
    assert {"5.7", "5.24", "5.25", "5.26", "5.27", "6.12", "9.11", "10.8"} <= ids
    assert result["blocking_budget_ok"] is True
    assert result["driver_orchestration"] == "excluded"
    assert all(len(step["step_hash"]) == 64 for step in result["steps"])


def test_extended_adds_exploratory_but_never_automated_suite() -> None:
    blocking = _resolve()
    extended = _resolve(extended=True)
    blocking_ids = {step["id"] for step in blocking["steps"]}
    extended_ids = {step["id"] for step in extended["steps"]}

    assert blocking_ids < extended_ids
    assert {"4.26", "10.5", "13.7"} <= extended_ids
    assert {"4.6", "6.3", "14.2", "15.3", "16.2"}.isdisjoint(extended_ids)


def test_category_and_range_filters_intersect_in_checklist_order() -> None:
    result = _resolve(categories=["session", "hooks"], from_id="5.24", to_id="7")
    ids = [step["id"] for step in result["steps"]]

    assert ids[0] == "5.24"
    assert ids[-1] == "6.12"
    assert all(step["section_id"] in {"5", "6"} for step in result["steps"])
    assert "5.15" not in ids


def test_unknown_category_and_reversed_range_fail() -> None:
    with pytest.raises(SELECTION.SelectionError, match="unknown categories"):
        _resolve(categories=["unknown"])
    with pytest.raises(SELECTION.SelectionError, match="is after"):
        _resolve(from_id="10", to_id="5")


def test_paid_annotations_are_counted_per_selected_step() -> None:
    result = _resolve(categories=["session"])
    paid = {step["id"]: step["paid_operations"] for step in result["steps"] if step["paid_operations"]}

    assert paid == {"5.6": 2, "5.24": 1, "5.27": 1}
