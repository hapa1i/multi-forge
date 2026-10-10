#!/usr/bin/env python3
"""Publish selected synthetic B3 evidence, including failures and helper hashes.

Never export authentication files, environments, or account-bearing session_meta.
The private round retains originals; published paths use $ROUND and $CHECKOUT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []


def export(root: Path, destination: Path) -> None:
    scripts = Path(__file__).resolve().parent
    checkout = scripts.parents[2]
    if (root / "B3_ROUND").read_text().strip() != "independent-b3-round-v1":
        raise ValueError("Only an owned synthetic B3 round can be published.")
    cases = []
    for directory in sorted((root / "captures").iterdir()):
        if not directory.is_dir():
            continue
        case: dict = {"case": directory.name}
        for name in ("control.json", "action-result.json", "terminal-result.json", "preflight.json"):
            if (directory / name).is_file():
                case[name.removesuffix(".json")] = json.loads((directory / name).read_text())
        for name in ("hooks.jsonl", "reviewer.jsonl"):
            case[name.removesuffix(".jsonl")] = rows(directory / name)
        for name in ("command.json", "process-result.json"):
            if (directory / "run" / name).is_file():
                case[name.removesuffix(".json")] = json.loads((directory / "run" / name).read_text())
        for name in ("stdout", "stderr"):
            if (directory / "run" / name).is_file():
                case[name] = (directory / "run" / name).read_text(errors="replace")
        state_file = directory / "session.json"
        if state_file.is_file():
            state = json.loads(state_file.read_text())
            case["session"] = {
                "name": state["name"],
                "policy": state["confirmed"].get("policy"),
                "codex": state["confirmed"].get("codex"),
            }
        native = rows(directory / "private-rollout.jsonl")
        latest = max(
            (
                i
                for i, row in enumerate(native)
                if row.get("type") == "event_msg" and row.get("payload", {}).get("type") == "task_started"
            ),
            default=0,
        )
        case["native_turn"] = [
            row
            for row in native[latest:]
            if row.get("type") == "response_item"
            or (row.get("type") == "event_msg" and row.get("payload", {}).get("type") == "task_complete")
        ]
        case["native_streams"] = {p.name: rows(p) for p in sorted(directory.glob("*-native-stream.jsonl"))}
        if (directory / "usage.json").is_file():
            case["usage"] = json.loads((directory / "usage.json").read_text())
        # Hash every retained capture, including failed attempts and non-published terminal bytes.
        case["raw_sha256"] = {
            str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*"))
            if p.is_file()
        }
        cases.append(case)
    report = {
        "identity": json.loads((root / "identity.json").read_text()),
        "reserved_turns": sum(row["reserved_turns"] for row in rows(root / "turns.jsonl")),
        "turn_ledger": rows(root / "turns.jsonl"),
        "cases": cases,
    }
    helpers = {
        str(p.relative_to(scripts)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(scripts.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }
    destination.mkdir(parents=True, exist_ok=True)
    for name, value in (("captures.json", report), ("helper-sources.json", helpers)):
        output = (
            json.dumps(value, indent=2, ensure_ascii=False)
            .replace(str(root), "$ROUND")
            .replace(str(checkout), "$CHECKOUT")
        )
        (destination / name).write_text(output + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.root.resolve(), args.destination.resolve())


if __name__ == "__main__":
    main()
