#!/usr/bin/env python3
"""Observe B4 native event boundaries and candidate Stop responses in owned fixtures only."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

from forge.core.reactive.reviewer_runtime import READ_ONLY_FLAGS
from forge.core.reactive.supervisor_auth import (
    preflight_subscription,
    subscription_environment,
)
from forge.core.reactive.watchdog import run_guarded
from forge.core.runtime.codex_feedback import policy_feedback_supported

RUNTIME = runpy.run_path(str(Path(__file__).resolve().parents[1] / "probe-runtime.py"))


def snapshot(cwd: Path, root: Path) -> dict:
    """Hash small ordinary fixture files without executing Git filters or following symlinks."""
    if not cwd.resolve().is_relative_to(root):
        return {"unavailable": "outside owned round"}
    files = {}
    for directory, dirs, names in os.walk(cwd, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {".git", ".forge", ".codex"}]
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or path.stat().st_size > 100_000:
                continue
            files[str(path.relative_to(cwd))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"files": files}


def main() -> int:
    RUNTIME["register_process"]()
    control = json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())
    capture = Path(control["capture"])
    capture.mkdir(parents=True, exist_ok=True)
    raw = sys.stdin.read()
    payload = json.loads(raw)
    event = sys.argv[1]
    start = time.time()
    stem = capture / f"{event}-{time.time_ns()}-{os.getpid()}"
    stem.with_suffix(".stdin.json").write_text(raw)
    observation = {
        "event": event,
        "started_at": start,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "snapshot": snapshot(Path(payload["cwd"]), Path(os.environ["PROBE_ROUND_ROOT"])),
        "launcher": sys.argv[0],
        "python": sys.executable,
        "dev_override": os.environ.get("FORGE_DEV"),
        "executor_identity": os.environ.get("FORGE_CODEX_EXECUTOR_IDENTITY"),
        "launch_parent_verified": policy_feedback_supported(os.environ),
    }
    stem.with_suffix(".begin.json").write_text(json.dumps(observation, indent=2))
    stdout, stderr, code = "", "", 0

    def interrupted(sig: int, frame: object) -> None:
        RUNTIME["append_json"](
            capture / "signals.jsonl",
            {"pid": os.getpid(), "signal": sig, "at": time.time()},
        )
        raise SystemExit(128 + sig)

    signal.signal(signal.SIGTERM, interrupted)
    try:
        if event == "Stop":
            mode = control.get("mode", "observe")
            if mode == "sleep":
                child = subprocess.Popen(
                    [str(Path(os.environ["PROBE_ROUND_ROOT"]) / "stub-bin/claude")],
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
                RUNTIME["append_json"](capture / "children.jsonl", {"pid": child.pid, "at": time.time()})
                time.sleep(90)
            elif mode in {"guarded-deadline", "guarded-native-expiry"}:
                env = subscription_environment()
                binary = preflight_subscription(
                    env=env, cwd=payload["cwd"], deadline=time.monotonic() + 10, control_args=READ_ONLY_FLAGS
                )
                try:
                    run_guarded(
                        [binary, *READ_ONLY_FLAGS],
                        input="Synthetic B4 lifetime control; no inference.",
                        env=env,
                        cwd=payload["cwd"],
                        timeout=3 if mode == "guarded-deadline" else 90,
                    )
                except subprocess.TimeoutExpired:
                    stdout = json.dumps({"systemMessage": "B4 review unavailable: controlled deadline."})
            elif mode == "block" and not payload.get("stop_hook_active"):
                guard = capture / ("blocked-" + str(payload.get("turn_id")))
                try:
                    guard.touch(exist_ok=False)
                except FileExistsError:
                    pass
                else:
                    stdout = json.dumps({"decision": "block", "reason": control["reason"]})
            elif mode == "notice":
                stdout = json.dumps({"systemMessage": control["notice"]})
        if stdout:
            print(stdout, flush=True)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
    except Exception:
        code = 1
        stderr = traceback.format_exc()
        sys.stderr.write(stderr)
    finally:
        stem.with_suffix(".stdout.txt").write_text(stdout + ("\n" if stdout else ""))
        stem.with_suffix(".stderr.txt").write_text(stderr)
        stem.with_suffix(".result.json").write_text(
            json.dumps(
                {
                    "exit_code": code,
                    "finished_at": time.time(),
                    "elapsed_seconds": time.time() - start,
                }
            )
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
