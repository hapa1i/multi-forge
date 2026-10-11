#!/usr/bin/env python3
"""Reserve and capture B4's single authorized, subscription-only Claude review."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extra-usage-disabled", action="store_true", required=True)
    parser.add_argument(
        "--capture", required=True, help="Completed native capture containing immutable review evidence"
    )
    args = parser.parse_args()
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    capture = Path(json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())["capture"])
    if (root / "B4_ROUND").read_text().strip() != "independent-b4-round-v1":
        raise ValueError("An owned B4 fixture is required.")
    if Path(os.environ["FORGE_HOME"]) != root / "forge-home" or not args.extra_usage_disabled:
        raise ValueError("Use the private Forge home and confirm the account billing setting.")
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1" or any(
        os.environ.get(key) for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY")
    ):
        raise ValueError("Disable dotenv and remove API credentials.")

    from forge.core.reactive import watchdog
    from forge.core.usage.ledger import read_usage_events
    from forge.policy.semantic import supervisor
    from forge.policy.semantic.attempts import read_attempts
    from forge.policy.semantic.identity import validate_reviewer
    from forge.policy.semantic.plan_source import read_plan
    from forge.policy.types import ActionContext
    from forge.session.models import LaneRecord, SupervisorConfig

    source = root / "captures" / args.capture / "review-events.jsonl"
    checkpoint = json.loads(source.read_text().splitlines()[-1])["payload"]
    evidence = checkpoint["evidence"]
    if not evidence["complete"] or not evidence.get("changes"):
        raise ValueError("The real control requires a complete, nonempty native aggregate")
    plan = root / "approved-product-plan.md"
    config = SupervisorConfig(
        review_trigger="stop",
        auth_mode="subscription-only",
        supervisor_model="sonnet",
        direct=True,
        forge_root=str(root / "project"),
        plan_override_path=str(plan),
        timeout_seconds=45,
    )
    lane = LaneRecord("claude_code", "claude-max", "sonnet")
    validate_reviewer(config, lane)
    context = ActionContext(
        origin="codex",
        event="Stop",
        tool_name="TurnReview",
        tool_args={"scope": "captured already-applied turn"},
        repo_root=str(root / "project"),
        session_name="b4-real-aggregate",
        raw_diff=json.dumps(evidence, sort_keys=True),
        action_fingerprint=checkpoint["evidence_digest"],
    )
    binary = Path(shutil.which("claude") or "").resolve()
    with binary.open("rb") as stream:
        binary_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    identity = {
        "executable": str(binary),
        "sha256": binary_sha256,
        "version": subprocess.check_output([str(binary), "--version"], text=True, timeout=5).strip(),
    }
    if "stub-bin" in str(binary):
        raise ValueError("The aggregate control requires the real Claude executable.")
    snapshot = read_plan(config)
    (capture / "review-input.json").write_text(
        json.dumps({"config": asdict(config), "context": asdict(context), "snapshot": asdict(snapshot)}, indent=2)
    )
    reservation = root / "real-claude-reservation.json"
    if reservation.exists():
        if json.loads(reservation.read_text())["identity"] != identity:
            raise ValueError("The reserved Claude identity changed.")
    else:
        with reservation.open("x") as output:
            json.dump({"attempts": 1, "extra_usage_disabled_confirmed": True, "identity": identity}, output, indent=2)
    if (root / "real-claude-dispatched.json").exists():
        raise ValueError("The single real Claude inference attempt was already dispatched.")

    ordinary_guard = watchdog.run_guarded
    dispatches = 0

    def observed_guard(argv, **kwargs):
        nonlocal dispatches
        if "-p" in argv:
            dispatches += 1
            if dispatches > 1:
                raise ValueError("The one-attempt Claude budget forbids another dispatch.")
            with (root / "real-claude-dispatched.json").open("x") as output:
                json.dump({"at": time.time(), "capture": str(capture)}, output)
            (capture / "review-dispatch.json").write_text(json.dumps({"argv": argv, "at": time.time()}, indent=2))
        return ordinary_guard(argv, **kwargs)

    watchdog.run_guarded = observed_guard
    ordinary_session = supervisor.run_claude_session

    def observed_session(prompt, **kwargs):
        (capture / "review-prompt.txt").write_text(prompt)
        result = ordinary_session(prompt, **kwargs)
        (capture / "review-runtime-result.json").write_text(json.dumps(asdict(result), indent=2))
        return result

    supervisor.run_claude_session = observed_session
    result = supervisor.run_supervisor_check(config, context, snapshot=snapshot, lane_record=lane)
    report = {
        "identity": identity,
        "source_capture": args.capture,
        "qualification": "Real transport review of a retained native aggregate, outside the native hook; does not clear operational turn state.",
        "result": asdict(result),
        "dispatches": dispatches,
        "attempts": read_attempts(context.session_name, config.forge_root),
        "usage": [asdict(row) for row in read_usage_events() if row.session == context.session_name],
    }
    (capture / "real-review.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"run_ok": result.run_ok, "parsed": result.parsed, "dispatches": dispatches}))


if __name__ == "__main__":
    main()
