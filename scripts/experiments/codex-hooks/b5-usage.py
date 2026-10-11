#!/usr/bin/env python3
"""Create a persistent compacted-source control for new-turn usage attribution."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from forge.core.runtime.codex_rollouts import find_rollouts_by_thread_id


def main() -> int:
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    copy_home = root / "copy-home"
    if Path(os.environ["CODEX_HOME"]) != copy_home or list((root / "originals-held").iterdir()):
        raise ValueError("Use the independent copy home without concurrent quarantine.")
    source_id = "01a12b65-e16b-7753-8b13-1764cd34a007"
    originals = find_rollouts_by_thread_id(source_id, home=root / "codex-home")
    if len(originals) != 1:
        raise ValueError("Exactly one owned compacted source must resolve.")
    original = originals[0]
    data = original.read_bytes()
    records = [json.loads(line) for line in data.splitlines()]
    if records[-1].get("payload", {}).get("type") != "task_complete":
        raise ValueError("Use the quiescent complete source for this control.")
    # Reload seeds from token_count; compaction can make source thread counters differ.
    baseline = next(
        row["payload"]["info"]["total_token_usage"]
        for row in reversed(records)
        if row["type"] == "event_msg" and row["payload"].get("type") == "token_count"
    )
    copied = copy_home / original.relative_to(root / "codex-home")
    before = copied.read_bytes()
    expected = json.loads((root / "captures/G8-incomplete-tool/fork-result.json").read_text())["source_sha256_after"]
    if hashlib.sha256(before).hexdigest() != expected:
        raise ValueError("Only replace the owned incomplete-boundary control copy.")
    (root / "prior-incomplete-prefix.jsonl").write_bytes(before)
    copied.write_bytes(data)
    held = root / "originals-held" / original.name
    original.rename(held)
    label = "G0-compacted-copy-usage"
    capture = root / "captures" / label
    scripts = Path(__file__).resolve().parent
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(scripts / "b5-capture.py"),
                "run",
                "--seconds",
                "60",
                label,
                "--",
                "codex",
                "exec",
                "--json",
                "--sandbox",
                "read-only",
                "-C",
                str(root / "action"),
                "fork",
                "--ignore-user-config",
                "--ignore-rules",
                "--disable",
                "hooks",
                "-c",
                "agents.enabled=false",
                "-c",
                "features.apps=false",
                "-c",
                "features.plugins=false",
                "-c",
                "mcp_servers={}",
                "-m",
                "gpt-6.1-sol",
                "-c",
                'model_reasoning_effort="low"',
                "--output-schema",
                str(root / "review-schema.json"),
                "-o",
                str(capture / "last.txt"),
                source_id,
                "-",
            ],
            input=(root / "prompts/fork-long.txt").read_text(),
            text=True,
            check=False,
        )
        events = [json.loads(line) for line in (capture / "run/stdout").read_text().splitlines()]
        child = next(row["thread_id"] for row in events if row.get("type") == "thread.started")
        child_paths = find_rollouts_by_thread_id(child, home=copy_home)
        if len(child_paths) != 1:
            raise ValueError("The usage control requires a persistent native fork.")
        child_records = [json.loads(line) for line in child_paths[0].read_text().splitlines()]
        requests = [row["payload"] for row in child_records if row["type"] == "token_usage_record"]
        reported = next(row["usage"] for row in events if row.get("type") == "turn.completed")
        delta = {key: value - baseline[key] for key, value in reported.items()}
        report = {
            "source_id": source_id,
            "child_id": child,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "source_bytes": len(data),
            "old_copy_sha256": hashlib.sha256(before).hexdigest(),
            "source_original_unavailable": not original.exists(),
            "original_unchanged": held.read_bytes() == data,
            "copied_source_unchanged": copied.read_bytes() == data,
            "native_history_base": child_records[0]["payload"].get("history_base"),
            "source_terminal_baseline": baseline,
            "reported_terminal_usage": reported,
            "new_request_usage": [row["usage"] for row in requests],
            "new_turn_usage": requests[-1]["turn_token_usage"],
            "terminal_delta": delta,
            "delta_matches_new_turn": all(delta[key] == requests[-1]["turn_token_usage"][key] for key in delta),
            "verdict": json.loads((capture / "last.txt").read_text()),
        }
        (capture / "usage-result.json").write_text(json.dumps(report, indent=2) + "\n")
        return result.returncode
    finally:
        if original.exists():
            raise ValueError("Original path reappeared; preserve both files for inspection.")
        held.rename(original)


if __name__ == "__main__":
    raise SystemExit(main())
