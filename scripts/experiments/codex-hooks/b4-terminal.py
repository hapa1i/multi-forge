#!/usr/bin/env python3
"""Record B4 multi-prompt TUI boundaries, forwarding keys and retaining each submitted turn."""

import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--close-after-turn", action="store_true")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--prompts-json", type=Path)
    parser.add_argument("--initial-turns", type=int, default=0)
    parser.add_argument("--after-initial-command-json", type=Path)
    parser.add_argument("--before-prompts-commands-json", type=Path)
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
    prompts = json.loads(args.prompts_json.read_text()) if args.prompts_json else []
    if args.prompt_file:
        prompts.append(args.prompt_file.read_text())
    before_prompts = (
        json.loads(args.before_prompts_commands_json.read_text()) if args.before_prompts_commands_json else []
    )
    if before_prompts and len(before_prompts) != len(prompts):
        raise ValueError("Supply one optional operator command for each explicit prompt")
    prompt_count = 0
    completed_count = 0
    initial_configured = args.after_initial_command_json is None
    next_prompt_at = None
    terminal_ready = None
    recent_output = b""
    with (capture / "terminal.log").open("wb", buffering=0) as log:
        while time.monotonic() - started < 240:
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
                    recent_output += data
                    if terminal_ready is None and b"\x1b[?2004h" in recent_output:
                        terminal_ready = time.monotonic()
                    recent_output = recent_output[-32:]
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
            # Submit the next explicit user prompt only after the previous turn completed.
            if terminal_ready is not None and next_prompt_at is None:
                next_prompt_at = terminal_ready + 8
            completions = 0
            for path in Path(os.environ["CODEX_HOME"]).rglob("rollout-*.jsonl"):
                for line in path.read_bytes()[before.get(path, 0) :].decode(errors="replace").splitlines():
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("type") == "event_msg" and row.get("payload", {}).get("type") == "task_complete":
                        completions += 1
            if completions > completed_count:
                completed_count = completions
                next_prompt_at = time.monotonic() + 3
                actions.append({"at": time.time(), "completed_count": completed_count})
                if args.close_after_turn and completed_count >= len(prompts) + args.initial_turns:
                    completed = time.monotonic()
            if not initial_configured and terminal_ready is not None and completed_count >= args.initial_turns:
                result = subprocess.run(
                    json.loads(args.after_initial_command_json.read_text()),
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                (capture / "idle-configuration.json").write_text(json.dumps(vars(result), default=str, indent=2))
                result.check_returncode()
                initial_configured = True
                next_prompt_at = time.monotonic() + 3
            if (
                prompt_count < len(prompts)
                and prompt_count + args.initial_turns <= completed_count
                and initial_configured
                and next_prompt_at is not None
                and time.monotonic() > next_prompt_at
            ):
                if before_prompts and before_prompts[prompt_count]:
                    result = subprocess.run(
                        before_prompts[prompt_count],
                        capture_output=True,
                        text=True,
                        timeout=45,
                    )
                    (capture / f"before-prompt-{prompt_count + 1}.json").write_text(
                        json.dumps(vars(result), default=str, indent=2)
                    )
                    result.check_returncode()
                os.write(
                    terminal,
                    b"\x1b[200~" + prompts[prompt_count].encode() + b"\x1b[201~",
                )
                time.sleep(0.3)
                os.write(terminal, b"\r")
                prompt_count += 1
                actions.append({"at": time.time(), "submitted_prompt": prompt_count})
            if completed is not None and time.monotonic() - completed > 2 and not notice_opened:
                os.write(terminal, b"\x1bOQ")
                notice_opened = True
                actions.append({"at": time.time(), "action": "F2 inspect notices"})
            # Escape must be processed before EOF; sending both in one write can
            # be interpreted as an Alt-modified key and leave the TUI running.
            if completed is not None and close_step < 3 and time.monotonic() - completed > 5 + close_step:
                os.write(terminal, b"\x1b" if close_step == 0 else b"\x04")
                actions.append(
                    {
                        "at": time.time(),
                        "action": "dismiss notice" if close_step == 0 else "EOF",
                    }
                )
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
