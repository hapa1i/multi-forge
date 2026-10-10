#!/usr/bin/env python3
"""Controlled response arms at stable enrolled paths; captures stay outside the repo."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import TextIO


class CapturedOutput:
    """Keep the exact response bytes while forwarding them to Codex."""

    def __init__(self, output: TextIO, capture: TextIO) -> None:
        self.output = output
        self.capture = capture

    def write(self, value: str) -> int:
        self.capture.write(value)
        self.capture.flush()
        return self.output.write(value)

    def flush(self) -> None:
        self.output.flush()
        self.capture.flush()


def respond(event: str, payload: dict, control: dict, capture: Path, name: str) -> None:
    """Emit the B2 response shapes independently of later product helper changes."""
    mode = control.get("mode", "observe")
    nonce = control.get("nonce", "")
    response: dict = {}
    specific = {"hookEventName": payload["hook_event_name"]}
    context = f"For the final answer, include this hook-only nonce exactly: {nonce}"
    tool = payload.get("tool_name")
    if event == "PreToolUse" and tool == "apply_patch":
        if mode == "feedback-explicit":
            response = {"hookSpecificOutput": {**specific, "permissionDecision": "allow", "additionalContext": context}}
        elif mode == "feedback-context":
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


def main() -> int:
    control = json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())
    capture = Path(control["capture"])
    capture.mkdir(parents=True, exist_ok=True)
    event = sys.argv[1]
    payload = json.load(sys.stdin)
    name = f"{event}-{time.time_ns()}-{os.getpid()}"
    (capture / f"{name}.stdin.json").write_text(json.dumps(payload, indent=2) + "\n")
    returncode = None
    with (capture / f"{name}.stdout").open("w") as stdout, (capture / f"{name}.stderr").open("w") as stderr:
        with redirect_stdout(CapturedOutput(sys.stdout, stdout)), redirect_stderr(CapturedOutput(sys.stderr, stderr)):
            try:
                respond(event, payload, control, capture, name)
                returncode = 0
            except SystemExit as exc:
                returncode = exc.code if isinstance(exc.code, int) else int(exc.code is not None)
                if isinstance(exc.code, str):
                    print(exc.code, file=sys.stderr)
            except Exception:
                traceback.print_exc()
                returncode = 1
            finally:
                (capture / f"{name}.result.json").write_text(
                    json.dumps({"returncode": returncode, "completed_at": time.time()}) + "\n"
                )
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
