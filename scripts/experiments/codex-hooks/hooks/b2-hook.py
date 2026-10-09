#!/usr/bin/env python3
"""Controlled response arms at stable enrolled paths; captures stay outside the repo."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path


def main() -> None:
    control = json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())
    capture = Path(control["capture"])
    capture.mkdir(parents=True, exist_ok=True)
    event = sys.argv[1]
    payload = json.load(sys.stdin)
    name = f"{event}-{time.time_ns()}-{os.getpid()}"
    (capture / f"{name}.stdin.json").write_text(json.dumps(payload, indent=2) + "\n")
    mode = control.get("mode", "observe")
    nonce = control.get("nonce", "")
    response: dict = {}
    specific = {"hookEventName": payload["hook_event_name"]}
    context = f"For the final answer, include this hook-only nonce exactly: {nonce}"
    tool = payload.get("tool_name")
    if event == "PreToolUse" and tool == "apply_patch":
        if mode == "feedback-explicit":
            from forge.cli.hooks.codex_policy import CodexHookResponder

            # The real helper, as distinct from today's empty product allow output.
            print(json.dumps(CodexHookResponder().allow_feedback(context)))
            return
        if mode == "feedback-context":
            response = {"hookSpecificOutput": {**specific, "additionalContext": context}}
        elif mode == "system-message":
            response = {"systemMessage": context}
        elif mode == "stderr":
            print(context, file=sys.stderr)
        elif mode == "malformed":
            print("{invalid-json")
            return
        elif mode == "updated-input":
            updated = dict(payload["tool_input"])
            updated["command"] = updated["command"].replace("ORIGINAL", "REWRITTEN")
            response = {"hookSpecificOutput": {**specific, "permissionDecision": "allow", "updatedInput": updated}}
        elif mode == "deny":
            response = {
                "hookSpecificOutput": {
                    **specific,
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "B2 deny control",
                }
            }
        elif mode == "sleep":
            time.sleep(70)
    elif event == "Stop" and mode == "stop-once":
        guard = capture / f"stop-{payload['session_id']}.guard"
        try:
            guard.touch(exist_ok=False)
        except FileExistsError:
            pass
        else:
            response = {"decision": "block", "reason": f"Reply exactly {nonce}, then finish. Do not call tools."}
    elif event == "Background" and mode == "background":

        def interrupted(sig: int, _frame: object) -> None:
            (capture / f"{name}.cancelled.json").write_text(json.dumps({"at": time.time(), "signal": sig}))
            raise SystemExit(128 + sig)

        signal.signal(signal.SIGTERM, interrupted)
        time.sleep(control.get("delay", 3))
        (capture / f"{name}.completed.json").write_text(json.dumps({"at": time.time()}))
        response = {"hookSpecificOutput": {**specific, "additionalContext": context}, "systemMessage": context}
    if response:
        print(json.dumps(response))


if __name__ == "__main__":
    main()
