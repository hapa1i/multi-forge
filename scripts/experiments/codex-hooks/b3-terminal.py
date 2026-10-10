#!/usr/bin/env python3
"""Record a fixture TUI, forwarding operator keys and optionally closing after a turn."""

import argparse
import fcntl
import json
import os
import pty
import select
import struct
import sys
import termios
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--close-after-turn", action="store_true")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    capture = Path(json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())["capture"])
    capture.mkdir(parents=True, exist_ok=True)
    before = {p: p.stat().st_size for p in Path(os.environ["CODEX_HOME"]).rglob("rollout-*.jsonl")}
    pid, terminal = pty.fork()
    if pid == 0:
        os.execv(command[0], command)
    fcntl.ioctl(terminal, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 150, 0, 0))
    started = time.monotonic()
    completed = None
    notice_opened = False
    close_step = 0
    actions = []
    keys_sent = 0
    prompt_sent = False
    with (capture / "terminal.log").open("wb", buffering=0) as log:
        while time.monotonic() - started < 180:
            inputs = [terminal] + ([sys.stdin.fileno()] if sys.stdin.isatty() else [])
            readable, _, _ = select.select(inputs, [], [], 0.2)
            for descriptor in readable:
                try:
                    data = os.read(descriptor, 65536)
                except OSError:
                    data = b""
                if descriptor != terminal:
                    if data:
                        os.write(terminal, data)
                        actions.append({"at": time.time(), "keys_hex": data.hex()})
                elif data:
                    log.write(data)
                    if sys.stdout.isatty():
                        os.write(sys.stdout.fileno(), data)
                    if b"\x1b[6n" in data:
                        os.write(terminal, b"\x1b[1;1R")
            key_file = capture / "operator-keys.json"
            if key_file.exists():
                keys = json.loads(key_file.read_text())
                for key in keys[keys_sent:]:
                    os.write(terminal, bytes.fromhex(key))
                    actions.append({"at": time.time(), "keys_hex": key})
                keys_sent = len(keys)
            if args.prompt_file and not prompt_sent and time.monotonic() - started > 8:
                os.write(terminal, b"\x1b[200~" + args.prompt_file.read_bytes() + b"\x1b[201~")
                time.sleep(0.3)
                os.write(terminal, b"\r")
                prompt_sent = True
                actions.append({"at": time.time(), "action": "submit fixture prompt"})
            if args.close_after_turn and completed is None:
                for path in Path(os.environ["CODEX_HOME"]).rglob("rollout-*.jsonl"):
                    text = path.read_bytes()[before.get(path, 0) :].decode(errors="replace")
                    if '"type":"task_complete"' in text or '"type": "task_complete"' in text:
                        completed = time.monotonic()
                        actions.append({"at": time.time(), "completed_rollout": str(path)})
            if completed is not None and time.monotonic() - completed > 2 and not notice_opened:
                os.write(terminal, b"\x1bOQ")
                notice_opened = True
                actions.append({"at": time.time(), "action": "F2 inspect notices"})
            # Escape must be processed before EOF; sending both in one write can
            # be interpreted as an Alt-modified key and leave the TUI running.
            if completed is not None and close_step < 3 and time.monotonic() - completed > 5 + close_step:
                os.write(terminal, b"\x1b" if close_step == 0 else b"\x04")
                actions.append({"at": time.time(), "action": "dismiss notice" if close_step == 0 else "EOF"})
                close_step += 1
            finished, status = os.waitpid(pid, os.WNOHANG)
            if finished:
                (capture / "terminal-result.json").write_text(
                    json.dumps({"exited": True, "status": status, "actions": actions}, indent=2)
                )
                return os.waitstatus_to_exitcode(status)
    (capture / "terminal-result.json").write_text(json.dumps({"exited": False, "actions": actions}, indent=2))
    return 125  # Outer probe owner sweeps all remaining fixture processes.


if __name__ == "__main__":
    raise SystemExit(main())
