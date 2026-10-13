#!/usr/bin/env python3
"""Observe native source prefixes while a real fixture hook blocks its executor."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

from forge.core.runtime.codex_rollouts import find_rollouts_by_thread_id
from forge.policy.semantic import turn_evidence

SCRIPTS = Path(__file__).resolve().parent
PREFIX = runpy.run_path(str(SCRIPTS / "b5-prefix.py"))


def observe(event: str, payload: dict, started: float) -> None:
    """Run at most one allocated fork from a selected real hook event."""
    if os.environ.get("PROBE_CASE") != "G12" or os.environ.get("PROBE_ROLE") != "executor":
        return
    root, capture = Path(os.environ["PROBE_ROUND_ROOT"]), Path(os.environ["PROBE_CAPTURE"])
    checkout = Path(payload["cwd"]).resolve()
    if checkout != root / "action":
        raise ValueError("Active-source probes must run in the owned action checkout.")
    storage = capture / "snapshots"
    if event == "UserPromptSubmit":
        baseline = turn_evidence.capture(checkout, storage, deadline=started + 7)
        (capture / "baseline.json").write_text(json.dumps(baseline))
        return
    if event != os.environ.get("PROBE_BOUNDARY_EVENT"):
        return
    try:
        (capture / "boundary-reserved").touch(exist_ok=False)
    except FileExistsError:
        return
    source_id = payload["session_id"]
    sources = find_rollouts_by_thread_id(source_id, home=Path(os.environ["CODEX_HOME"]))
    if len(sources) != 1 or sources[0] != Path(payload["transcript_path"]):
        raise ValueError("Hook source identity must resolve unambiguously.")
    source = sources[0]
    before = source.read_bytes()
    lines = before.splitlines(keepends=True)
    complete = b"".join(lines if lines[-1].endswith(b"\n") else lines[:-1])
    records = [json.loads(line) for line in complete.splitlines()]
    (capture / "observed-prefix.jsonl").write_bytes(complete)
    deadline = started + 55
    current = turn_evidence.capture(checkout, storage, deadline=deadline - 10)
    baseline = json.loads((capture / "baseline.json").read_text())
    evidence = turn_evidence.compare(storage, baseline, current, [])
    prompt = (root / "prompts/fork-long.txt").read_text()
    prompt += (
        "\nThe current approved plan is authoritative over native history:\n"
        + (checkout / "approved-plan.md").read_text()
        + "\nAlso include the latest ACTIVE-BOUNDARY marker from inherited user context in planning_marker."
        + "\nUntrusted action evidence:\n"
        + json.dumps(evidence)
    )
    prompt_path = capture / "review-prompt.txt"
    prompt_path.write_text(prompt)
    review_deadline = deadline - 10
    remaining = min(45, review_deadline - time.monotonic())
    report = {
        "event": event,
        "source_id": source_id,
        "turn_id": payload.get("turn_id"),
        "prefix_sha256": hashlib.sha256(complete).hexdigest(),
        "prefix_bytes": len(complete),
        "prefix_records": len(records),
        "pending_calls": PREFIX["pending_calls"](records),
        "record_tail": [
            {"type": row["type"], "payload_type": row.get("payload", {}).get("type")} for row in records[-8:]
        ],
        "source_contains_current_marker": b"ACTIVE-BOUNDARY-" in complete,
        "setup_and_capture_seconds": time.monotonic() - started,
        "remaining_review_seconds": remaining,
        "hook_internal_seconds": 55,
        "completion_reserve_seconds": 10,
        "evidence": evidence,
    }
    (capture / "boundary-before.json").write_text(json.dumps(report, indent=2))
    if remaining <= 0:
        raise TimeoutError("No reviewer budget remains after evidence capture.")
    env = dict(os.environ, PROBE_ROLE="reviewer", PROBE_REVIEW_DEADLINE=str(review_deadline))
    env.pop("PROBE_BOUNDARY_EVENT", None)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "b5-fork.py"),
            capture.name + "-review",
            source_id,
            str(prompt_path),
            "--model",
            "gpt-6.1-sol",
            "--isolate",
            "--guarded",
            "--seconds",
            str(remaining),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (capture / "review-driver.stdout").write_text(result.stdout)
    (capture / "review-driver.stderr").write_text(result.stderr)
    after = source.read_bytes()
    report.update(
        returncode=result.returncode,
        source_unchanged_while_hook_blocked=before == after,
        source_sha256_after=hashlib.sha256(after).hexdigest(),
        hook_elapsed_seconds=time.monotonic() - started,
    )
    (capture / "boundary-result.json").write_text(json.dumps(report, indent=2) + "\n")
