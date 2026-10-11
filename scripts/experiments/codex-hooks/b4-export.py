#!/usr/bin/env python3
"""Export B4 gate/product evidence, retaining failures and source drift without credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent


def read(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text()) if path.is_file() else default


def lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def command_result(path: Path) -> dict | None:
    value = read(path)
    if value is not None:
        try:
            value["stdout"] = json.loads(value["stdout"])
        except (ValueError, KeyError):
            pass
    return value


def export(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    current = {
        str(p.relative_to(SCRIPTS)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in SCRIPTS.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    cases, snapshots = {}, {}
    for capture in sorted((root / "captures").iterdir()):
        if not capture.is_dir():
            continue
        command = read(capture / "run/command.json", {})
        hashes = command.pop("harness_files", {})
        snapshots[capture.name] = {
            "files": hashes,
            "different_from_exported_tree": {k: v for k, v in hashes.items() if current.get(k) != v},
            "added_after_capture": sorted(set(current) - set(hashes)),
        }
        events = []
        for path in capture.glob("*.stdin.json"):
            stem = path.name.removesuffix(".stdin.json")
            observation = read(capture / (stem + ".begin.json"), {})
            events.append(
                {
                    "payload": read(path),
                    "observation": observation,
                    "result": read(capture / (stem + ".result.json")),
                    "stdout": (
                        (capture / (stem + ".stdout.txt")).read_text()
                        if (capture / (stem + ".stdout.txt")).exists()
                        else None
                    ),
                    "stderr": (
                        (capture / (stem + ".stderr.txt")).read_text()
                        if (capture / (stem + ".stderr.txt")).exists()
                        else None
                    ),
                }
            )
        events.sort(key=lambda e: e["observation"].get("started_at", 0))
        turn_ids = {event["payload"].get("turn_id") for event in events}
        hook_messages = []
        for rollout in capture.glob("rollout-*.jsonl"):
            for line in rollout.read_text().splitlines():
                row = json.loads(line)
                if (
                    row.get("type") == "response_item"
                    and "<hook_prompt " in line
                    and row.get("metadata", {}).get("turn_id") in turn_ids
                ):
                    hook_messages.append(row)
        terminal = capture / "terminal.log"
        cases[capture.name] = {
            "command": command,
            "control": read(capture / "control.json"),
            "completion": read(capture / "completed.json"),
            "cleanup": read(capture / "run/process-result.json"),
            "events": events,
            "hook_messages_in_retained_rollout": hook_messages,
            "operator_notice_in_terminal": (
                "B4-STOP-OPERATOR-NOTICE" in terminal.read_text(errors="replace") if terminal.exists() else None
            ),
            "terminal": read(capture / "terminal-result.json"),
            "idle_configuration": read(capture / "idle-configuration.json"),
            "fresh_policy": read(capture / "fresh-policy.json"),
            "stdout": ((capture / "run/stdout").read_text() if (capture / "run/stdout").exists() else None),
            "stderr": ((capture / "run/stderr").read_text() if (capture / "run/stderr").exists() else None),
            "receipts": {p.name: read(p) for p in capture.glob("*-receipt.json")},
            "product_hooks": lines(capture / "hooks.jsonl"),
            "review_checkpoints": lines(capture / "review-events.jsonl"),
            "supervisor_status": command_result(capture / "supervisor-status.json"),
            "activity": command_result(capture / "activity.json"),
            "session": command_result(capture / "session.json"),
            "real_review": read(capture / "real-review.json"),
            "fault": read(capture / "fault.json"),
            "stop_enrollment": read(capture / "stop-enrollment.json"),
            "completion_usage": [
                row
                for stream in capture.glob("*-native-stream.jsonl")
                for row in lines(stream)
                if row.get("type") == "turn.completed"
            ],
            "reviewer_events": (
                [json.loads(line) for line in (capture / "reviewer.jsonl").read_text().splitlines()]
                if (capture / "reviewer.jsonl").exists()
                else []
            ),
        }

    def save(name: str, value: object) -> None:
        text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        for source, target in (
            (str(root), "<ROUND>"),
            (str(SCRIPTS.parents[2]), "<CHECKOUT>"),
            (str(Path.home()), "<HOST_HOME>"),
        ):
            text = text.replace(source, target)
        (destination / name).write_text(text)

    save(
        "native-gate.json",
        {
            "decision": read(root / "gate-decision.json"),
            "identity": read(root / "identity.json"),
            "readiness": read(root / "readiness.json"),
            "stub_admission": read(root / "stub-admission.json"),
            "enrollment": read(root / "gate-enrollment.json", read(root / "ENROLLED")),
            "budget": read(root / "budget.json"),
            "turn_reservations": [json.loads(line) for line in (root / "turns.jsonl").read_text().splitlines()],
            "setup_attempts": {p.name: read(p) for p in root.glob("*setup*.json")},
            "cases": {key: value for key, value in cases.items() if key[:2].isdigit() and int(key[:2]) <= 11},
        },
    )
    save(
        "product.json",
        {
            "cases": {key: value for key, value in cases.items() if not key[:2].isdigit() or int(key[:2]) > 11},
            "enrollment": read(root / "ENROLLED"),
            "product_sync": read(root / "product-sync.json"),
            "ui_seal_change": read(root / "ui-seal-change.json"),
            "wheel": {p.name: read(p) for p in root.glob("wheel-*.json")},
            "verification": read(root / "product-verification.json"),
            "teardown": read(root / "teardown.json"),
            "budget": read(root / "budget.json"),
            "turn_reservations": lines(root / "turns.jsonl"),
        },
    )
    save("harness-snapshots.json", snapshots)
    save("helper-sources.json", current)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.root.resolve(), args.destination.resolve())


if __name__ == "__main__":
    main()
