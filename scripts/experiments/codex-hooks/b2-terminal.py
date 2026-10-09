#!/usr/bin/env python3
"""Drive only the synthetic B2 TUI prompts; never answer enrollment or approval dialogs."""

from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time
from pathlib import Path


def main() -> int:
    case, *command = sys.argv[1:]
    capture = Path(os.environ["PROBE_CAPTURE_DIR"])
    prompts = {
        "start": [
            "Remember TUI-PERSIMMON. Use apply_patch once to add tui_system.txt containing OK. "
            "Do not use other tools. Reply with any B2- nonce from hook feedback or NONE if absent."
        ],
        "resume": [
            "What word did I ask you to remember? Use apply_patch once to add tui_stderr.txt "
            "containing OK. Do not use other tools. Reply with the remembered word and any "
            "B2- nonce from hook feedback or NONE if absent."
        ],
        "background": [
            "Run printf B2-IDLE once with exec_command, then immediately reply DONE. "
            "Do not wait or use other tools.",
            "Without using tools, reply with any B2- nonce from hook feedback or NONE if absent.",
        ],
        "context": [
            "Without reading files or using tools, reply with the oracle token from transferred "
            "planning context or NONE if absent."
        ],
    }[case]
    initial_argument = case in {"start", "context"}
    if initial_argument:
        command.append(prompts[0])
    pid, terminal = pty.fork()
    if pid == 0:
        os.execv(command[0], command)
    fcntl.ioctl(terminal, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 140, 0, 0))
    started = time.monotonic()
    sent = int(initial_argument)
    submit_at = None
    stopped_at = None
    exiting = False
    close_sent = False
    checked_active = False
    transcript = bytearray()
    actions = [{"at": time.time(), "prompt": prompts[0], "delivery": "initial TUI argument"}] if sent else []
    finished, status = 0, 0
    with (capture / "terminal.log").open("wb", buffering=0) as log:
        while time.monotonic() - started < 160:
            ready, _, _ = select.select([terminal], [], [], 0.1)
            if ready:
                try:
                    data = os.read(terminal, 65536)
                except OSError:
                    break
                if not data:
                    break
                transcript.extend(data)
                log.write(data)
                if b"\x1b[6n" in data:
                    os.write(terminal, b"\x1b[1;1R")
            if not sent and time.monotonic() - started > 8 and b"low" in transcript[-6000:]:
                os.write(terminal, b"\x1b[200~" + prompts[0].encode() + b"\x1b[201~")
                submit_at = time.monotonic() + 0.5
                actions.append({"at": time.time(), "prompt": prompts[0], "delivery": "terminal paste"})
                sent = 1
            if submit_at is not None and time.monotonic() >= submit_at:
                os.write(terminal, b"\r")
                submit_at = None
            if case == "start" and time.monotonic() - started > 12 and not checked_active:
                checked_active = True
                result = subprocess.run(
                    [command[0], "session", "resume", os.environ["PROBE_TUI_SESSION"]],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                (capture / "active-refusal.json").write_text(
                    json.dumps(
                        {
                            "returncode": result.returncode,
                            "stdout": result.stdout,
                            "stderr": result.stderr,
                        },
                        indent=2,
                    )
                )
            stops = list(capture.glob("Stop-*.stdin.json"))
            if len(stops) >= sent and sent and stopped_at is None:
                stopped_at = time.monotonic()
                actions.append({"at": time.time(), "stop_count": len(stops)})
            if stopped_at is not None and not exiting:
                if case == "background" and sent == 1 and time.monotonic() - stopped_at > 8:
                    actions.append({"at": time.time(), "idle_stop_count": len(stops), "prompt": prompts[1]})
                    os.write(terminal, b"\x1b[200~" + prompts[1].encode() + b"\x1b[201~")
                    submit_at = time.monotonic() + 0.5
                    sent = 2
                    stopped_at = None
                elif (case != "background" or sent == 2) and time.monotonic() - stopped_at > 2:
                    os.write(terminal, b"\x1bOQ")  # F2: inspect operator warnings, without accepting anything.
                    actions.append({"at": time.time(), "action": "inspect_warnings"})
                    exiting = True
            if exiting and not close_sent and stopped_at is not None and time.monotonic() - stopped_at > 4:
                close_sent = True
                try:
                    os.write(terminal, b"\x1b")
                    time.sleep(0.3)
                    os.write(terminal, b"\x04")
                    time.sleep(0.2)
                    os.write(terminal, b"\x04")
                except OSError:
                    pass  # The first EOF may already have closed the terminal.
            finished, status = os.waitpid(pid, os.WNOHANG)
            if finished:
                break
    (capture / "terminal-actions.json").write_text(json.dumps(actions, indent=2) + "\n")
    # If the terminal did not exit, the independent owner retains and sweeps it.
    if not finished:
        finished, status = os.waitpid(pid, os.WNOHANG)
    (capture / "terminal-result.json").write_text(json.dumps({"pid": pid, "exited": bool(finished), "status": status}))
    return os.waitstatus_to_exitcode(status) if finished else 125


if __name__ == "__main__":
    raise SystemExit(main())
