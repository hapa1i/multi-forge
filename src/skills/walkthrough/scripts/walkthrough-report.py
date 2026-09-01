#!/usr/bin/env python3
"""Build deterministic walkthrough metrics and a concise Markdown report."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_parser(path: Path):
    # The parser lives in the installed skill package. Importing it must not
    # create __pycache__ beside user-owned extension files.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("forge_walkthrough_report_parser", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load parser: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _option(step: dict) -> str | None:
    values = [
        annotation.split(":", 1)[1].strip() for annotation in step["annotations"] if annotation.startswith("option:")
    ]
    if len(values) > 1:
        raise ValueError(f"step {step['id']} has multiple option annotations")
    return values[0] if values else None


def _options(raw: object) -> dict[str, bool]:
    if not isinstance(raw, str):
        raise ValueError("state is missing RUN_OPTIONS")
    parsed: dict[str, bool] = {}
    for item in raw.split(","):
        key, separator, value = item.partition("=")
        if not separator or key not in {"codex", "sidecar"} or value not in {"true", "false"}:
            raise ValueError("state has invalid RUN_OPTIONS")
        parsed[key] = value == "true"
    if set(parsed) != {"codex", "sidecar"}:
        raise ValueError("state has incomplete RUN_OPTIONS")
    return parsed


def _integer_var(state: dict, key: str) -> int:
    try:
        return int(state.get("vars", {})[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"state has invalid {key}") from exc


def _render_report(metrics: dict) -> str:
    lines = [
        "# Forge Walkthrough Report",
        "",
        f"- Verdict: `{metrics['verdict']}`",
        f"- Checklist: `{metrics['checklist_version']}` / {metrics['selection']['selected_steps']} selected steps",
        f"- Options: codex={str(metrics['options']['codex']).lower()}, sidecar={str(metrics['options']['sidecar']).lower()}",
        f"- Default assertions: {metrics['assertions']['pass']} pass, {metrics['assertions']['fail']} fail, "
        f"{metrics['assertions']['skip']} skip, {metrics['assertions']['missing']} missing",
        f"- Human checkpoints: {metrics['budgets']['human_observed']}/{metrics['budgets']['human_declared']}",
        f"- Paid operations: {metrics['budgets']['paid_observed']}/{metrics['budgets']['paid_declared']}",
        f"- Duration: {metrics['duration_seconds']}s (review required: {str(metrics['duration_review_required']).lower()})",
        f"- Package tree matches marker: {str(metrics['package_identity_preserved']).lower()}",
        f"- Answering package: {metrics['package_identity'].get('distribution')} "
        f"{metrics['package_identity'].get('version')}",
        f"- Installed skill: `{metrics['package_identity'].get('skill_root')}`",
        "",
        "## Selection",
        "",
        f"- Optional assertions not selected: {metrics['selection']['not_selected_assertions']}",
        f"- Selected assertions (default + options): {metrics['selection']['selected_assertions']}",
        f"- Optional human-checkpoint ceiling added: {metrics['budgets']['human_optional_selected']}",
        f"- Optional paid-operation ceiling added: {metrics['budgets']['paid_optional_selected']}",
        "",
        "## Optional compatibility evidence",
        "",
        "| Option | Status | Pass | Fail | Skip | Missing |",
        "| ------ | ------ | ---: | ---: | ---: | ------: |",
    ]
    for option, result in metrics["optional_results"].items():
        lines.append(
            f"| {option} | {result['status']} | {result['pass']} | {result['fail']} | "
            f"{result['skip']} | {result['missing']} |"
        )
    lines.extend(
        [
            "",
            "## Sections",
            "",
            "| Section | Pass | Fail | Skip | Missing |",
            "| ------- | ---: | ---: | ---: | ------: |",
        ]
    )
    for section in metrics["sections"]:
        lines.append(
            f"| {section['id']}. {section['title']} | {section['pass']} | {section['fail']} | "
            f"{section['skip']} | {section['missing']} |"
        )
    return "\n".join(lines) + "\n"


def build_metrics(
    *,
    checklist: Path,
    parser_path: Path,
    state_path: Path,
    package_identity_path: Path,
    ended_epoch: int,
) -> dict:
    parser = _load_parser(parser_path)
    data = parser.parse_checklist(str(checklist))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    package_identity = json.loads(package_identity_path.read_text(encoding="utf-8"))
    options = _options(state.get("vars", {}).get("RUN_OPTIONS"))
    recorded_steps = state.get("steps")
    if not isinstance(recorded_steps, dict):
        raise ValueError("state has invalid step records")
    checklist_step_ids = {step["id"] for step in data["_all_subs"]}
    orphaned_steps = sorted(set(recorded_steps) - checklist_step_ids)
    if orphaned_steps:
        raise ValueError(f"state has orphaned step records: {', '.join(orphaned_steps)}")

    totals = {"pass": 0, "fail": 0, "skip": 0, "missing": 0}
    selected_totals = {"pass": 0, "fail": 0, "skip": 0, "missing": 0}
    optional_results = {option: {"pass": 0, "fail": 0, "skip": 0, "missing": 0} for option in ("codex", "sidecar")}
    selected_steps = 0
    not_selected_steps = 0
    not_selected_assertions = 0
    sections: list[dict[str, object]] = []

    for section in data["sections"]:
        section_totals = {"pass": 0, "fail": 0, "skip": 0, "missing": 0}
        for step in section["subsections"]:
            option = _option(step)
            selected = option is None or options[option]
            if not selected:
                not_selected_steps += 1
                not_selected_assertions += step["assertion_count"]
                continue
            selected_steps += 1
            buckets = [selected_totals]
            if option is None:
                buckets.append(totals)
            else:
                buckets.append(optional_results[option])
            recorded = recorded_steps.get(step["id"])
            if recorded is None:
                section_totals["missing"] += step["assertion_count"]
                for bucket in buckets:
                    bucket["missing"] += step["assertion_count"]
                continue
            results = recorded.get("results", [])
            if len(results) != step["assertion_count"]:
                raise ValueError(f"result count mismatch for {step['id']}")
            stored_hash = recorded.get("hash")
            if stored_hash is None or stored_hash != parser.step_hash(step):
                raise ValueError(f"stale or unverified result for {step['id']}")
            for result in results:
                if result not in {"pass", "fail", "skip"}:
                    raise ValueError(f"invalid result for {step['id']}: {result}")
                section_totals[result] += 1
                for bucket in buckets:
                    bucket[result] += 1
        sections.append({"id": section["id"], "title": section["title"], **section_totals})

    if state.get("checklist_version") != data["version"]:
        raise ValueError("state checklist version does not match the packaged checklist")

    optional_statuses: dict[str, dict[str, object]] = {}
    for option, counts in optional_results.items():
        if not options[option]:
            status = "not-selected"
        elif counts["fail"]:
            status = "fail"
        elif counts["missing"]:
            status = "incomplete"
        elif counts["skip"]:
            status = "unavailable"
        else:
            status = "pass"
        optional_statuses[option] = {**counts, "status": status}

    start_epoch = _integer_var(state, "RUN_STARTED_EPOCH")
    duration = max(0, ended_epoch - start_epoch)
    cleanup = next(section for section in sections if section["id"] == "13")
    cleanup_passed = cleanup["fail"] == cleanup["skip"] == cleanup["missing"] == 0
    identity_preserved = (
        package_identity.get("package_tree_matches_marker") is True
        and package_identity.get("package_matches_answering_distribution") is True
    )

    default_steps = [step for step in data["_all_subs"] if _option(step) is None]
    default_human = sum(step["annotation"].startswith("human:") for step in default_steps)
    default_paid = sum(
        int(annotation.split(":", 1)[1].strip())
        for step in default_steps
        for annotation in step["annotations"]
        if annotation.startswith("paid-operations:")
    )
    human_declared = _integer_var(state, "DECLARED_HUMAN_CHECKPOINTS")
    paid_declared = _integer_var(state, "DECLARED_PAID_OPERATIONS")
    if (human_declared, paid_declared) != (default_human, default_paid):
        raise ValueError("state default budgets do not match the packaged checklist")

    optional_human = sum(
        step["annotation"].startswith("human:")
        for step in data["_all_subs"]
        if (option := _option(step)) is not None and options[option]
    )
    optional_paid = sum(
        int(annotation.split(":", 1)[1].strip())
        for step in data["_all_subs"]
        if (option := _option(step)) is not None and options[option]
        for annotation in step["annotations"]
        if annotation.startswith("paid-operations:")
    )
    passed_options = {option for option, result in optional_statuses.items() if result["status"] == "pass"}
    required_optional_human = sum(
        step["annotation"].startswith("human:") for step in data["_all_subs"] if _option(step) in passed_options
    )
    required_optional_paid = sum(
        int(annotation.split(":", 1)[1].strip())
        for step in data["_all_subs"]
        if _option(step) in passed_options
        for annotation in step["annotations"]
        if annotation.startswith("paid-operations:")
    )
    human_observed = _integer_var(state, "HUMAN_CHECKPOINTS_OBSERVED")
    paid_observed = _integer_var(state, "PAID_OPERATIONS_OBSERVED")
    budget_counts_valid = (
        default_human + required_optional_human <= human_observed <= default_human + optional_human
        and default_paid + required_optional_paid <= paid_observed <= default_paid + optional_paid
    )

    if totals["missing"]:
        verdict = "incomplete"
    elif totals["fail"] or totals["skip"] or not cleanup_passed or not identity_preserved or not budget_counts_valid:
        verdict = "fail"
    else:
        verdict = "pass"

    return {
        "schema_version": 1,
        "verdict": verdict,
        "checklist_version": data["version"],
        "started_epoch": start_epoch,
        "ended_epoch": ended_epoch,
        "ended_at": datetime.fromtimestamp(ended_epoch, timezone.utc).isoformat(),
        "duration_seconds": duration,
        "duration_review_threshold_seconds": 1800,
        "duration_review_required": duration > 1800,
        "options": options,
        "codex_auth_mode": state.get("vars", {}).get("CODEX_AUTH_MODE", "none"),
        "selection": {
            "selected_steps": selected_steps,
            "selected_assertions": sum(selected_totals.values()),
            "not_selected_steps": not_selected_steps,
            "not_selected_assertions": not_selected_assertions,
        },
        "assertions": totals,
        "selected_assertions": selected_totals,
        "optional_results": optional_statuses,
        "budgets": {
            "human_declared": human_declared,
            "human_optional_selected": optional_human,
            "human_observed": human_observed,
            "paid_declared": paid_declared,
            "paid_optional_selected": optional_paid,
            "paid_observed": paid_observed,
            "counts_valid": budget_counts_valid,
        },
        "cleanup_passed": cleanup_passed,
        "package_identity_preserved": identity_preserved,
        "package_marker_sha256": package_identity.get("package_marker_sha256"),
        "package_identity": {
            key: package_identity.get(key)
            for key in (
                "distribution",
                "version",
                "distribution_root",
                "forge_launcher",
                "forge_module",
                "skill_root",
                "walkthrough_source_root",
                "walkthrough_payload_sha256",
                "installed_payload_sha256",
                "package_marker_sha256",
                "package_tree_matches_marker",
                "package_matches_answering_distribution",
            )
        },
        "sections": sections,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checklist", required=True, type=Path)
    parser.add_argument("--parser", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--package-identity", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ended-epoch", required=True, type=int)
    args = parser.parse_args()

    try:
        metrics = build_metrics(
            checklist=args.checklist,
            parser_path=args.parser,
            state_path=args.state,
            package_identity_path=args.package_identity,
            ended_epoch=args.ended_epoch,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}), file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "run-metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(_render_report(metrics))
    (args.output_dir / "selected-options.json").write_text(
        json.dumps(
            {
                "options": metrics["options"],
                "codex_auth_mode": metrics["codex_auth_mode"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    shutil.copyfile(args.state, args.output_dir / "state.json")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
