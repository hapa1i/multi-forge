#!/usr/bin/env python3
"""Compute release-QA budget, scope, and verdict metadata from saved evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

BLOCKING_LANES = {"clean-wheel-smoke", "human-acceptance"}
HUMAN_CLASSES = {"human:guided", "human:confirm"}


class MetricsError(ValueError):
    """Raised when saved QA evidence cannot produce trustworthy metrics."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetricsError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MetricsError(f"{label} must contain one JSON object: {path}")
    return value


def _recorded_entry(state: dict[str, Any], step_id: str) -> dict[str, Any] | None:
    entry = state.get("steps", {}).get(step_id)
    if not isinstance(entry, dict):
        return None
    run_scope = state.get("vars", {}).get("RUN_SCOPE")
    if run_scope is not None and entry.get("scope") != run_scope:
        return None
    return entry


def _paid_var_name(step_id: str) -> str:
    return f"PAID_OPERATIONS_{step_id.replace('.', '_')}"


def _planned_counts(steps: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "steps": len(steps),
        "assertions": sum(int(step.get("assertion_count", 0)) for step in steps),
        "human_checkpoints": sum(step.get("execution_class") in HUMAN_CLASSES for step in steps),
        "paid_operations": sum(int(step.get("paid_operations", 0)) for step in steps),
    }


def _summarize_steps(steps: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    result_counts = {"pass": 0, "fail": 0, "skip": 0}
    missing_steps: list[str] = []
    recorded_steps = 0
    completed_human = 0
    sections: dict[str, dict[str, Any]] = {}
    for step in steps:
        step_id = str(step["id"])
        section_id = str(step["section_id"])
        section = sections.setdefault(
            section_id,
            {
                "id": section_id,
                "expected": 0,
                "pass": 0,
                "fail": 0,
                "skip": 0,
                "missing_steps": [],
            },
        )
        section["expected"] += int(step.get("assertion_count", 0))
        entry = _recorded_entry(state, step_id)
        if entry is None:
            missing_steps.append(step_id)
            section["missing_steps"].append(step_id)
            continue
        expected_hash = step.get("step_hash")
        if not expected_hash or entry.get("hash") != expected_hash:
            raise MetricsError(f"step {step_id} has stale or missing structural hash evidence")
        results = entry.get("results")
        if not isinstance(results, list):
            raise MetricsError(f"step {step_id} has no result list")
        expected_assertions = int(step.get("assertion_count", 0))
        if len(results) != expected_assertions:
            raise MetricsError(f"step {step_id} expects {expected_assertions} assertion results, found {len(results)}")
        recorded_steps += 1
        if step.get("execution_class") in HUMAN_CLASSES and results and any(result != "skip" for result in results):
            completed_human += 1
        for result in results:
            if result not in result_counts:
                raise MetricsError(f"step {step_id} has unknown result {result!r}")
            result_counts[result] += 1
            section[result] += 1
    return {
        "recorded_steps": recorded_steps,
        "results": result_counts,
        "missing_steps": missing_steps,
        "human_checkpoints_completed": completed_human,
        "sections": list(sections.values()),
    }


def _final_runtime_identity_preserved(
    *,
    artifact: dict[str, Any],
    runtime_final: dict[str, Any],
) -> bool:
    if runtime_final.get("schema_version") != 1:
        raise MetricsError("unsupported final runtime identity schema")

    initial = artifact.get("runtime", {})
    expected_track = initial.get("track")
    expected_blocking = initial.get("blocking")
    if not isinstance(expected_track, str) or not isinstance(expected_blocking, bool):
        raise MetricsError("artifact runtime track and blocking flag must be typed")
    if runtime_final.get("track") != expected_track or runtime_final.get("blocking") is not expected_blocking:
        raise MetricsError("final runtime track does not match artifact identity")

    available: list[bool] = []
    matches: list[bool] = []
    for runtime_name in ("claude", "codex"):
        initial_runtime = initial.get(runtime_name, {})
        final_runtime = runtime_final.get(runtime_name, {})
        if not isinstance(initial_runtime, dict) or not isinstance(final_runtime, dict):
            raise MetricsError(f"{runtime_name} runtime identity must be an object")
        if final_runtime.get("pin") != initial_runtime.get("pin"):
            raise MetricsError(f"final {runtime_name} pin does not match artifact identity")
        runtime_available = final_runtime.get("available")
        if not isinstance(runtime_available, bool):
            raise MetricsError(f"final {runtime_name} availability must be boolean")
        available.append(runtime_available)
        matches_pin = final_runtime.get("matches_pin")
        if expected_blocking:
            if not isinstance(matches_pin, bool):
                raise MetricsError(f"final {runtime_name} pin match must be boolean on the pinned track")
            matches.append(matches_pin)
        elif matches_pin is not None:
            raise MetricsError(f"final {runtime_name} pin match must be null on a compatibility track")

    preserved = all(available) and (not expected_blocking or all(matches))
    if runtime_final.get("identity_preserved") is not preserved:
        raise MetricsError("final runtime preservation flag is inconsistent with its probes")
    return preserved


def compute_metrics(
    *,
    artifact: dict[str, Any],
    runtime_final: dict[str, Any],
    selection: dict[str, Any],
    state: dict[str, Any],
    started_epoch: int,
    ended_epoch: int,
    duration_disposition: str | None = None,
) -> dict[str, Any]:
    """Return deterministic run metrics and the strongest verdict supported by evidence."""
    if ended_epoch < started_epoch:
        raise MetricsError("ended epoch precedes started epoch")
    if artifact.get("schema_version") != 1 or selection.get("schema_version") != 1:
        raise MetricsError("unsupported artifact or selection schema")
    driver = artifact.get("driver")
    if (
        not isinstance(driver, dict)
        or driver.get("matches_artifact") is not True
        or not isinstance(driver.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", driver["sha256"]) is None
    ):
        raise MetricsError("artifact QA driver identity is missing, malformed, or does not match the selected wheel")
    runtime_identity_preserved = _final_runtime_identity_preserved(
        artifact=artifact,
        runtime_final=runtime_final,
    )

    selected_steps = selection.get("steps", [])
    if not isinstance(selected_steps, list):
        raise MetricsError("selection steps must be a list")
    if _planned_counts(selected_steps) != selection.get("selected_counts"):
        raise MetricsError("selected step plan does not match selected_counts")
    blocking_steps = [step for step in selected_steps if step.get("evidence_lane") in BLOCKING_LANES]
    selected_summary = _summarize_steps(selected_steps, state)
    blocking_summary = _summarize_steps(blocking_steps, state)

    paid_observed = 0
    blocking_paid_observed = 0
    state_vars = state.get("vars", {})
    for step in selected_steps:
        entry = _recorded_entry(state, str(step["id"]))
        if entry is None:
            continue
        variable = _paid_var_name(str(step["id"]))
        step_plan = int(step.get("paid_operations", 0))
        if step_plan and variable not in state_vars:
            raise MetricsError(f"{variable} is required for recorded paid step {step['id']}")
        try:
            step_paid = int(state_vars.get(variable, 0))
        except (TypeError, ValueError) as exc:
            raise MetricsError(f"{variable} is not an integer") from exc
        if step_paid < 0 or step_paid > step_plan:
            raise MetricsError(f"{variable} must be between 0 and the step plan of {step_plan}")
        results = entry.get("results", [])
        if step_plan and results and all(result == "pass" for result in results) and step_paid != step_plan:
            raise MetricsError(f"{variable} must equal the step plan of {step_plan} when every assertion passes")
        paid_observed += step_paid
        if step.get("evidence_lane") in BLOCKING_LANES:
            blocking_paid_observed += step_paid

    limits = selection.get("blocking_limits", {})
    blocking_plan = selection.get("blocking_counts", {})
    if blocking_plan.get("human_checkpoints", 0) > limits.get("max_human_checkpoints", -1):
        raise MetricsError("blocking human-checkpoint plan exceeds its limit")
    if blocking_plan.get("paid_operations", 0) > limits.get("max_paid_operations", -1):
        raise MetricsError("blocking paid-operation plan exceeds its limit")

    duration_seconds = ended_epoch - started_epoch
    try:
        duration_threshold = int(limits["duration_review_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MetricsError("blocking limits need an integer duration_review_seconds") from exc
    budget_review_required = duration_seconds > duration_threshold
    full_scope = not selection.get("categories") and selection.get("from") is None and selection.get("to") is None
    if full_scope and _planned_counts(blocking_steps) != blocking_plan:
        raise MetricsError("full-scope blocking steps do not match blocking_counts")
    artifact_mode = artifact.get("artifact", {}).get("mode")
    if artifact_mode not in {"prebuilt", "development-build"}:
        raise MetricsError(f"unsupported artifact mode {artifact_mode!r}")
    artifact_release_capable = (
        artifact_mode == "prebuilt"
        and artifact.get("runtime", {}).get("track") == "pinned"
        and artifact.get("runtime", {}).get("blocking") is True
        and runtime_identity_preserved
    )

    if not runtime_identity_preserved or blocking_summary["results"]["fail"]:
        verdict = "fail"
    elif blocking_summary["missing_steps"] or blocking_summary["results"]["skip"]:
        verdict = "incomplete"
    elif artifact_mode != "prebuilt":
        verdict = "development-only"
    elif artifact.get("runtime", {}).get("blocking") is not True:
        verdict = "compatibility-only"
    elif not full_scope:
        verdict = "partial"
    elif budget_review_required and not duration_disposition:
        verdict = "pass-review-required"
    else:
        verdict = "pass"

    return {
        "schema_version": 1,
        "scope": {
            "full": full_scope,
            "mode": selection.get("mode"),
            "categories": selection.get("categories", []),
            "from": selection.get("from"),
            "to": selection.get("to"),
            "evidence_lanes": selection.get("evidence_lanes", []),
        },
        "duration": {
            "started_epoch": started_epoch,
            "ended_epoch": ended_epoch,
            "seconds": duration_seconds,
            "review_threshold_seconds": duration_threshold,
            "budget_review_required": budget_review_required,
            "maintainer_disposition": duration_disposition,
        },
        "counts": {
            "selected_plan": selection.get("selected_counts", {}),
            "blocking_plan": blocking_plan,
            "selected_recorded_steps": selected_summary["recorded_steps"],
            "selected_results": selected_summary["results"],
            "blocking_recorded_steps": blocking_summary["recorded_steps"],
            "blocking_results": blocking_summary["results"],
            "human_checkpoints_completed": selected_summary["human_checkpoints_completed"],
            "blocking_human_checkpoints_completed": blocking_summary["human_checkpoints_completed"],
            "paid_operations_observed": paid_observed,
            "blocking_paid_operations_observed": blocking_paid_observed,
            "driver_orchestration": {
                "counted": False,
                "description": "Claude-hosted checklist driver; excluded from subject-under-test counts",
            },
        },
        "sections": selected_summary["sections"],
        "gaps": {
            "missing_selected_steps": selected_summary["missing_steps"],
            "missing_blocking_steps": blocking_summary["missing_steps"],
        },
        "runtime_identity": {
            "preserved": runtime_identity_preserved,
            "final": runtime_final,
        },
        "artifact_release_capable": artifact_release_capable,
        "verdict": verdict,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--runtime-final", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--started-epoch", type=int, required=True)
    parser.add_argument("--ended-epoch", type=int, required=True)
    parser.add_argument("--duration-disposition")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = compute_metrics(
            artifact=_read_json(args.artifact, "artifact identity"),
            runtime_final=_read_json(args.runtime_final, "final runtime identity"),
            selection=_read_json(args.selection, "selection"),
            state=_read_json(args.state, "state"),
            started_epoch=args.started_epoch,
            ended_epoch=args.ended_epoch,
            duration_disposition=args.duration_disposition,
        )
    except MetricsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
