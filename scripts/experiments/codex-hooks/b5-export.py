#!/usr/bin/env python3
"""Export selected B5 observations, excluding credentials and opaque native histories."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def export(root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    checkout = Path(__file__).resolve().parents[3]
    hashes: dict[str, str] = {}

    def clean(value):
        if isinstance(value, str):
            return (
                value.replace(str(root), "<ROUND>")
                .replace(str(checkout), "<CHECKOUT>")
                .replace(str(Path.home()), "<HOME>")
            )
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {clean(key): clean(item) for key, item in value.items()}
        return value

    def raw(path: Path) -> str:
        if "auth.json" in path.name:
            raise ValueError("Credentials are never evidence exports.")
        data = path.read_bytes()
        hashes[str(path.relative_to(root))] = hashlib.sha256(data).hexdigest()
        return data.decode()

    def read(path: Path):
        return json.loads(raw(path))

    def rows(path: Path) -> list[dict]:
        return [json.loads(line) for line in raw(path).splitlines() if line.strip()] if path.exists() else []

    def write(name: str, value) -> None:
        (destination / name).write_text(json.dumps(clean(value), indent=2, ensure_ascii=False) + "\n")

    starts, outcomes, invocations = (
        rows(root / name) for name in ("starts.jsonl", "outcomes.jsonl", "invocations.jsonl")
    )
    by_id = {row["id"]: row for row in outcomes}
    commands = {row["id"]: row for row in invocations if row.get("id")}
    write(
        "ledger.json",
        {
            "count": len(starts),
            "ceiling": 60,
            "api_count": sum(row["auth_mode"] == "api" for row in starts),
            "authorization": read(root / "authorization.json"),
            "budget_revisions": read(root / "budget-revisions.json"),
            "case_counts": dict(Counter(row["case"] for row in starts)),
            "starts": [
                {**row, "invocation": commands.get(row["id"]), "outcome": by_id.get(row["id"])} for row in starts
            ],
        },
    )
    cases, forks, boundaries, lifetime, auth = {}, {}, {}, {}, {}
    snapshots = {}
    for capture in sorted((root / "captures").iterdir()):
        if not capture.is_dir():
            continue
        run = capture / "run" if (capture / "run").is_dir() else capture
        if not (run / "command.json").is_file():
            continue
        command = read(run / "command.json")
        snapshot = command.pop("harness_files", {})
        snapshot_id = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        snapshots[snapshot_id] = snapshot
        command["harness_snapshot"] = snapshot_id
        case = {"command": command}
        for name in ("process-result.json", "terminal-result.json"):
            if (run / name).is_file():
                case[name] = read(run / name)
        if (capture / "provenance.json").is_file():
            case["provenance"] = read(capture / "provenance.json")
        cases[capture.name] = case
        if (capture / "fork-result.json").is_file():
            forks[capture.name] = read(capture / "fork-result.json")
        if (capture / "copy-observation.json").is_file():
            forks[capture.name]["copy"] = read(capture / "copy-observation.json")
        if (capture / "boundary-copy.json").is_file():
            forks[capture.name]["boundary_copy"] = read(capture / "boundary-copy.json")
        if capture.name.startswith("G12-") and not capture.name.endswith("-review"):
            boundaries[capture.name] = {
                name: read(capture / name)
                for name in ("boundary-before.json", "boundary-result.json")
                if (capture / name).is_file()
            }
            boundaries[capture.name]["hooks"] = rows(capture / "hooks.jsonl")
        if capture.name.startswith("G13-") or "native-" in capture.name:
            lifetime[capture.name] = {
                name: read(capture / name)
                for name in (
                    "guard-start.json",
                    "guard-result.json",
                    "stub-admission.json",
                    "invoker-result.json",
                    "lifetime-result.json",
                    "fault-result.json",
                    "injected-signal.json",
                    "owned-processes-before-kill.json",
                )
                if (capture / name).is_file()
            }
            lifetime[capture.name]["native_events"] = rows(capture / "native-events.jsonl")
            lifetime[capture.name]["process_result"] = case.get("process-result.json")
        if capture.name.startswith("R-") and ("api" in capture.name or "subscription" in capture.name):
            auth[capture.name] = {"stdout": raw(run / "stdout"), "stderr": raw(run / "stderr")}
    write("provenance.json", {"binary": read(root / "identity.json"), "captures": cases})
    write("harness-snapshots.json", snapshots)
    write("forks.json", forks)
    write("boundaries.json", boundaries)
    write("lifetime.json", lifetime)
    write("auth-negatives.json", auth)
    write("ancestry.json", read(root / "captures/G11-ancestry.json"))
    write(
        "sandbox.json",
        {
            "filesystem": read(root / "captures/G9-filesystem.json"),
            "project_config": raw(root / "G9-project-config.toml"),
            "project_rules": raw(root / "G9-project.rules"),
            "events": {name: rows(root / "captures" / name / "run/stdout") for name in ("G9-readonly", "G9-writable")},
        },
    )
    contexts = {}
    for label in ("G5-long-first", "G6-compacted-first", "G12-stop-review"):
        facts = forks[label]
        data = Path(facts["source_path"]).read_bytes()[: facts["source_bytes"]]
        if hashlib.sha256(data).hexdigest() != facts["source_sha256_before"]:
            raise ValueError("The retained source no longer matches its recorded prefix.")
        records = [json.loads(line) for line in data.splitlines()]
        context = [row["payload"] for row in records if row["type"] == "turn_context"]
        tokens = [
            row["payload"]
            for row in records
            if row["type"] == "event_msg" and row["payload"].get("type") == "token_count"
        ]
        contexts[label] = {
            "bytes": len(data),
            "sha256": facts["source_sha256_before"],
            "records": len(records),
            "compaction_records": sum(row["type"] == "compacted" for row in records),
            "models": sorted({row.get("model", "unknown") for row in context}),
            "task_starts": sum(
                row["type"] == "event_msg" and row["payload"].get("type") == "task_started" for row in records
            ),
            "task_completions": sum(
                row["type"] == "event_msg" and row["payload"].get("type") == "task_complete" for row in records
            ),
            "last_token_info": tokens[-1].get("info") if tokens else None,
        }
    write("context.json", contexts)
    usage = {}
    for label in ("G0-shared-fork", "G0-sibling-fork"):
        events = rows(root / "captures" / label / "run/stdout")
        thread = next(row["thread_id"] for row in events if row.get("type") == "thread.started")
        paths = list((root / "codex-home/sessions").rglob(f"*{thread}.jsonl"))
        if len(paths) != 1:
            raise ValueError("The persistent usage control must have one rollout.")
        records = [json.loads(line) for line in paths[0].read_text().splitlines()]
        native = [row["payload"] for row in records if row["type"] == "token_usage_record"]
        reported = next(row["usage"] for row in events if row.get("type") == "turn.completed")
        usage[label] = {
            "reported_terminal_usage": reported,
            "new_request_usage": [row["usage"] for row in native],
            "final_turn_usage": native[-1]["turn_token_usage"],
            "final_thread_usage": native[-1]["thread_token_usage"],
            "reported_matches_thread_counter": all(
                reported[k] == native[-1]["thread_token_usage"][k] for k in reported
            ),
            "new_turn_matches_request_sum": all(
                native[-1]["turn_token_usage"][k] == sum(row["usage"][k] for row in native) for k in reported
            ),
        }
    compacted = read(root / "captures/G0-compacted-copy-usage/usage-result.json")
    sources = list((root / "codex-home/sessions").glob(f'*/*/*/*{compacted["source_id"]}.jsonl'))
    if len(sources) != 1:
        raise ValueError("The compacted usage control must have one original rollout.")
    data = sources[0].read_bytes()[: compacted["source_bytes"]]
    if hashlib.sha256(data).hexdigest() != compacted["source_sha256"]:
        raise ValueError("The compacted usage source no longer matches its captured prefix.")
    records = [json.loads(line) for line in data.splitlines()]
    compacted["source_baseline_kind"] = "event_msg.token_count.info.total_token_usage"
    compacted["source_native_thread_counter_for_comparison"] = next(
        row["payload"]["thread_token_usage"] for row in reversed(records) if row["type"] == "token_usage_record"
    )
    baseline = next(
        row["payload"]["info"]["total_token_usage"]
        for row in reversed(records)
        if row["type"] == "event_msg" and row["payload"].get("type") == "token_count"
    )
    if baseline != compacted["source_terminal_baseline"]:
        raise ValueError("The captured usage baseline differs from the source token_count record.")
    usage["G0-compacted-copy-usage"] = compacted
    write("usage-counters.json", usage)
    write("admission.json", read(root / "captures/admission-result.json"))
    before = read(root / "host-config-hashes.json")
    host = []
    for name, digest in before.items():
        path = Path(name)
        host_data = path.read_bytes() if path.is_file() else None
        current = hashlib.sha256(host_data).hexdigest() if host_data is not None else None
        host.append(
            {
                "path": name,
                "before": digest,
                "after": current,
                "unchanged": digest == current,
                "modified_utc": (
                    datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if host_data else None
                ),
                "contains_fixture_path": str(root).encode() in host_data if host_data else False,
            }
        )
    write(
        "preservation.json",
        {
            "ordinary_config": host,
            "held_originals": [p.name for p in (root / "originals-held").iterdir()],
            "ordinary_auth_read_or_copied": False,
            "round_closed": (root / "CLOSED").exists(),
        },
    )
    write("source-hashes.json", hashes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.root.resolve(), args.destination.resolve())
