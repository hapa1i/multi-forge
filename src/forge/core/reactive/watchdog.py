"""Bound a reviewer even when its invoking hook is killed (including on macOS).

The hook owns a pipe writer. A detached watcher observes EOF/deadline and owns a
detached process-group anchor. The anchor stays unreaped until group cleanup, so
its PID cannot be reused while the watcher signals the group. Reviewers inherit
neither the control pipe nor the anchor's status pipe. An anchor timer also kills
its own group if the watcher itself disappears.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from typing import Any

TERMINATION_GRACE_SECONDS = 0.5
_WATCHDOG_MODULE = "forge.core.reactive.watchdog"
_TIMEOUT_EXIT = 124


def run_guarded(
    argv: list[str],
    *,
    input: str,
    env: dict[str, str],
    cwd: str | None,
    timeout: float,
    pass_fds: tuple[int, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Run under a parent-death watchdog with subprocess.run-compatible results."""
    if timeout <= 0:
        raise subprocess.TimeoutExpired(argv, timeout)
    deadline = time.monotonic() + timeout
    control_read, control_write = os.pipe()
    watcher: subprocess.Popen[str] | None = None
    try:
        watcher = subprocess.Popen(
            [sys.executable, "-I", "-m", _WATCHDOG_MODULE, "watch", str(control_read)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            cwd="/",
            start_new_session=True,
            pass_fds=(control_read, *pass_fds),
        )
        os.close(control_read)
        control_read = -1
        # Helpers must never import checkout modules or PYTHONPATH entries. The
        # actual reviewer still receives its original working directory and env.
        payload = json.dumps(
            {
                "argv": argv,
                "prompt": input,
                "cwd": os.path.abspath(cwd) if cwd else os.getcwd(),
                "deadline": deadline,
                "pass_fds": pass_fds,
            }
        )
        stdout, stderr = watcher.communicate(payload, timeout=timeout + 2 * TERMINATION_GRACE_SECONDS + 2)
        if watcher.returncode == _TIMEOUT_EXIT:
            raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(argv, watcher.returncode, stdout, stderr)
    finally:
        # Closing this writer also handles KeyboardInterrupt and other synchronous
        # cancellation. SIGKILL closes it in the kernel without needing this code.
        os.close(control_write)
        if control_read >= 0:
            os.close(control_read)
        if watcher is not None and watcher.poll() is None:
            try:
                watcher.wait(timeout=2 * TERMINATION_GRACE_SECONDS + 2)
            except subprocess.TimeoutExpired:
                # The independently armed anchor still bounds its reviewer group.
                watcher.kill()
                watcher.wait()


def _signal_group(pid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def _watch(control: int, payload: dict[str, Any]) -> int:
    status_read, status_write = os.pipe()
    anchor: subprocess.Popen[str] | None = None
    completed = False
    try:
        deadline = float(payload["deadline"])
        # Check parent liveness before spawning, including death during payload delivery.
        if time.monotonic() >= deadline or select.select([control], [], [], 0)[0]:
            return _TIMEOUT_EXIT
        anchor = subprocess.Popen(
            [sys.executable, "-I", "-m", _WATCHDOG_MODULE, "anchor", str(status_write)],
            stdin=subprocess.PIPE,
            text=True,
            cwd="/",
            start_new_session=True,
            pass_fds=(status_write, *payload.get("pass_fds", ())),
        )
        os.close(status_write)
        status_write = -1
        assert anchor.stdin is not None
        anchor.stdin.write(json.dumps(payload))
        anchor.stdin.close()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return _TIMEOUT_EXIT
            readable, _, _ = select.select([control, status_read], [], [], remaining)
            if control in readable or not readable:
                return _TIMEOUT_EXIT
            if status_read in readable:
                status = os.read(status_read, 64)
                completed = bool(status)
                return int(status) if status else 125
    finally:
        if anchor is not None:
            # Do not poll/reap the anchor before the last signal. Even a crashed
            # anchor remains a zombie owned by us, retaining this group's identity.
            if not completed:
                _signal_group(anchor.pid, signal.SIGTERM)
                time.sleep(TERMINATION_GRACE_SECONDS)
            _signal_group(anchor.pid, signal.SIGKILL)
            anchor.wait()
        os.close(status_read)
        if status_write >= 0:
            os.close(status_write)
        os.close(control)


def _anchor(status: int, payload: dict[str, Any]) -> None:
    # Stay alive through TERM so the watcher's final group kill retains a live
    # anchor; the reviewer gets the normal default signal disposition on exec.
    signal.signal(signal.SIGTERM, lambda *_: None)
    deadline = float(payload["deadline"])

    def expire() -> None:
        _signal_group(os.getpid(), signal.SIGKILL)

    timer = threading.Timer(max(0.0, deadline - time.monotonic()) + 2 * TERMINATION_GRACE_SECONDS, expire)
    timer.daemon = True
    timer.start()
    try:
        result = subprocess.run(
            payload["argv"],
            input=payload["prompt"],
            text=True,
            cwd=payload["cwd"],
            pass_fds=tuple(payload.get("pass_fds", ())),
            check=False,
        )
        os.write(status, str(result.returncode if result.returncode >= 0 else 128 - result.returncode).encode())
    except OSError as exc:
        print(f"Reviewer launch failed: {exc}", file=sys.stderr)
        os.write(status, b"127")
    finally:
        os.close(status)
    # The watcher owns reaping; the timer remains armed even after successful exit.
    while True:
        signal.pause()


def main() -> None:
    """Private subprocess entry point; input stays on pipes, never in argv/files."""
    mode, descriptor = sys.argv[1:]
    payload = json.load(sys.stdin)
    if mode == "watch":
        sys.exit(_watch(int(descriptor), payload))
    if mode == "anchor":
        _anchor(int(descriptor), payload)
    else:
        raise ValueError("Unknown watchdog role")


if __name__ == "__main__":
    main()
