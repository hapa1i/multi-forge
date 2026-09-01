#!/usr/bin/env python3
"""Resolve release-QA evidence selection and deterministic execution budgets."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

EVIDENCE_LANES = {
    "automated-suite",
    "clean-wheel-smoke",
    "human-acceptance",
    "extended-exploratory",
}
BLOCKING_LANES = {"clean-wheel-smoke", "human-acceptance"}
HUMAN_EXECUTION_CLASSES = {"human:guided", "human:confirm"}
PAID_RE = re.compile(r"^paid-operations:\s*(\d+)$")
EVIDENCE_RE = re.compile(r"^evidence:\s*(\S+)$")

CATEGORIES = {
    "enable": "0",
    "preflight": "1",
    "extensions": "2",
    "auth": "3",
    "proxy": "4",
    "session": "5",
    "hooks": "6",
    "costs": "7",
    "status-line": "8",
    "commands": "9",
    "resume": "10",
    "config": "11",
    "search": "12",
    "policy": "13",
    "workflow": "14",
    "skills": "15",
    "memory-writer": "16",
    "info": "17",
    "disable": "18",
    "uninstall": "19",
    "cleanup": "20",
}


class SelectionError(ValueError):
    """Raised when a QA selection cannot be resolved deterministically."""


def _load_state_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("forge_qa_selection_state", path)
    if spec is None or spec.loader is None:
        raise SelectionError(f"cannot load checklist parser: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence_lane(step: dict[str, Any]) -> str:
    explicit = []
    for annotation in step["annotations"]:
        match = EVIDENCE_RE.fullmatch(annotation)
        if match:
            explicit.append(match.group(1))
    if len(explicit) > 1:
        raise SelectionError(f"step {step['id']} declares multiple evidence lanes: {explicit}")
    if explicit:
        lane = explicit[0]
        if lane not in EVIDENCE_LANES:
            raise SelectionError(f"step {step['id']} declares unknown evidence lane {lane!r}")
        return lane
    if step["annotation"] in HUMAN_EXECUTION_CLASSES:
        return "human-acceptance"
    return "clean-wheel-smoke"


def _paid_operations(step: dict[str, Any]) -> int:
    declared = []
    for annotation in step["annotations"]:
        match = PAID_RE.fullmatch(annotation)
        if match:
            declared.append(int(match.group(1)))
    if len(declared) > 1:
        raise SelectionError(f"step {step['id']} declares paid operations more than once")
    return declared[0] if declared else 0


def _boundary_index(steps: list[dict[str, Any]], value: str | None, *, default: int) -> int:
    if value is None:
        return default
    if "." in value:
        for index, step in enumerate(steps):
            if step["id"] == value:
                return index
        raise SelectionError(f"unknown checklist step {value!r}")
    if not value.isdigit():
        raise SelectionError(f"range boundary must be a section or step id, got {value!r}")
    for index, step in enumerate(steps):
        if step["section_id"] == value:
            return index
    raise SelectionError(f"unknown checklist section {value!r}")


def _summary(steps: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "steps": len(steps),
        "assertions": sum(step["assertion_count"] for step in steps),
        "human_checkpoints": sum(step["annotation"] in HUMAN_EXECUTION_CLASSES for step in steps),
        "paid_operations": sum(step["paid_operations"] for step in steps),
    }


def resolve_selection(
    *,
    checklist: Path,
    parser_script: Path,
    budget_path: Path,
    categories: list[str] | None = None,
    from_id: str | None = None,
    to_id: str | None = None,
    extended: bool = False,
) -> dict[str, Any]:
    """Return selected step ids, lanes, and deterministic budget counts."""
    state = _load_state_script(parser_script)
    parsed = state.parse_checklist(str(checklist))
    try:
        budget = json.loads(budget_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectionError(f"cannot read execution budget {budget_path}: {exc}") from exc
    if budget.get("schema_version") != 1:
        raise SelectionError(f"unsupported execution-budget schema: {budget.get('schema_version')!r}")

    unknown = sorted(set(categories or ()) - CATEGORIES.keys())
    if unknown:
        raise SelectionError(f"unknown categories: {', '.join(unknown)}")
    selected_sections = {CATEGORIES[name] for name in categories or ()}

    all_steps: list[dict[str, Any]] = []
    for raw in parsed["_all_subs"]:
        step = dict(raw)
        step["evidence_lane"] = _evidence_lane(step)
        step["paid_operations"] = _paid_operations(step)
        all_steps.append(step)

    start = _boundary_index(all_steps, from_id, default=0)
    stop = _boundary_index(all_steps, to_id, default=len(all_steps))
    if start > stop:
        raise SelectionError(f"--from {from_id} is after --to {to_id}")

    allowed_lanes = set(BLOCKING_LANES)
    if extended:
        allowed_lanes.add("extended-exploratory")
    chosen = [
        step
        for index, step in enumerate(all_steps)
        if start <= index < stop
        and (not selected_sections or step["section_id"] in selected_sections)
        and step["evidence_lane"] in allowed_lanes
    ]
    blocking = [step for step in all_steps if step["evidence_lane"] in BLOCKING_LANES]
    limits = budget["blocking"]
    blocking_counts = _summary(blocking)
    budget_ok = (
        blocking_counts["human_checkpoints"] <= limits["max_human_checkpoints"]
        and blocking_counts["paid_operations"] <= limits["max_paid_operations"]
    )

    return {
        "schema_version": 1,
        "mode": "extended" if extended else "blocking",
        "evidence_lanes": sorted(allowed_lanes),
        "categories": categories or [],
        "from": from_id,
        "to": to_id,
        "steps": [
            {
                "id": step["id"],
                "section_id": step["section_id"],
                "execution_class": step["annotation"],
                "evidence_lane": step["evidence_lane"],
                "assertion_count": step["assertion_count"],
                "paid_operations": step["paid_operations"],
                "step_hash": state.step_hash(step),
            }
            for step in chosen
        ],
        "selected_counts": _summary(chosen),
        "blocking_counts": blocking_counts,
        "blocking_limits": limits,
        "blocking_budget_ok": budget_ok,
        "driver_orchestration": "excluded",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checklist", type=Path, required=True)
    parser.add_argument("--parser", type=Path, required=True)
    parser.add_argument("--budget", type=Path, required=True)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--from", dest="from_id")
    parser.add_argument("--to", dest="to_id")
    parser.add_argument("--extended", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = resolve_selection(
            checklist=args.checklist,
            parser_script=args.parser,
            budget_path=args.budget,
            categories=args.category,
            from_id=args.from_id,
            to_id=args.to_id,
            extended=args.extended,
        )
    except SelectionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
