#!/usr/bin/env python3
"""Bound admitted no-inference stubs and inject one native review-owner death."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from forge.core.invoker.codex import CodexHeadlessInvoker
from forge.core.invoker.types import HeadlessRequest
from forge.core.reactive.reviewer_runtime import READ_ONLY_FLAGS
from forge.core.reactive.supervisor_auth import (
    preflight_subscription,
    subscription_environment,
)

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = runpy.run_path(str(SCRIPTS / "probe-runtime.py"))


def stub() -> None:
    """Expose synthetic admission responses and exercise only local processes."""
    if "--version" in sys.argv:
        print("2.1.294 (B5 synthetic reviewer; no inference)")
        return
    if "--help" in sys.argv:
        print(" ".join(READ_ONLY_FLAGS))
        return
    if "auth" in sys.argv and "status" in sys.argv:
        print(
            json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "apiKeySource": "none",
                    "subscriptionType": "max",
                    "fixture": True,
                }
            )
        )
        return
    RUNTIME["register_process"]()
    sys.stdin.read()
    mode = os.environ["PROBE_STUB_KIND"]
    if mode == "absent":
        return
    if mode == "malformed":
        print(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "{broken"},
                }
            )
        )
        return
    if mode == "quota":
        print(
            json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": "synthetic quota exceeded"},
                }
            )
        )
        return
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(90)"])
    table = RUNTIME["process_table"]()
    Path(os.environ["PROBE_CAPTURE"], "stub-ready.json").write_text(json.dumps([table[os.getpid()], table[child.pid]]))
    time.sleep(90)


def owner(mode: str) -> int:
    RUNTIME["register_process"]()
    capture = Path(os.environ["PROBE_CAPTURE"])
    env = dict(os.environ, PROBE_STUB_KIND=mode)
    seconds = 2 if mode == "timeout" else 45
    if os.environ.get("PROBE_CANCEL_FIRST") == "1":
        from forge.core.reactive import watchdog

        watchdog.run_guarded = runpy.run_path(str(SCRIPTS / "b5-watchdog.py"))["run_guarded"]
    try:
        result = CodexHeadlessInvoker().run(
            HeadlessRequest(
                argv=[os.environ["PROBE_STUB_BINARY"], *READ_ONLY_FLAGS],
                prompt="Synthetic lifetime/JSON-stream control; no provider inference.",
                env=env,
                cwd=str(Path(os.environ["PROBE_ROUND_ROOT"]) / "action"),
                timeout_seconds=seconds,
                watchdog_deadline=time.monotonic() + seconds,
            )
        )
        (capture / "invoker-result.json").write_text(json.dumps(asdict(result), indent=2))
        return 0
    except KeyboardInterrupt:
        (capture / "cancelled.json").write_text('{"cancelled": true}\n')
        return 130


def run_stub(mode: str) -> int:
    root, capture = Path(os.environ["PROBE_ROUND_ROOT"]), Path(os.environ["PROBE_CAPTURE"])
    stub_bin = root / "stub-bin"
    stub_bin.mkdir(exist_ok=True)
    binary = stub_bin / "claude"
    binary.write_text(
        "#!/bin/bash\nexec " + shlex.join([sys.executable, str(Path(__file__).resolve()), "stub"]) + ' "$@"\n'
    )
    binary.chmod(0o700)
    # This classification is explicitly synthetic and belongs to the empty B5 HOME.
    fixture_login = root / "home/.claude.json"
    if not fixture_login.exists():
        fixture_login.write_text('{"oauthAccount":{"organizationType":"claude_max"},"fixture":true}\n')
    env = subscription_environment({"PATH": str(stub_bin) + os.pathsep + os.environ["PATH"]})
    admitted = preflight_subscription(env=env, cwd=str(root / "action"), deadline=time.monotonic() + 15)
    if Path(admitted) != binary:
        raise ValueError("The admitted reviewer must be the owned synthetic binary.")
    (capture / "stub-admission.json").write_text(
        json.dumps(
            {
                "binary": admitted,
                "admitted": True,
                "synthetic": True,
                "provider_inference": False,
            }
        )
    )
    env.update(PROBE_STUB_BINARY=admitted, PROBE_CAPTURE=str(capture))
    with (
        (capture / "owner.stdout").open("w") as out,
        (capture / "owner.stderr").open("w") as err,
    ):
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "owner", mode],
            env=env,
            stdout=out,
            stderr=err,
        )
        identity = RUNTIME["process_table"]()[child.pid]
        ready = capture / "stub-ready.json"
        until = time.monotonic() + 10
        while mode in {"timeout", "cancel", "owner-death"} and not ready.exists() and child.poll() is None:
            if time.monotonic() > until:
                raise TimeoutError("Stub did not reach its real descendant.")
            time.sleep(0.02)
        table = RUNTIME["process_table"]()
        descendants = {child.pid}
        while True:
            expanded = descendants | {pid for pid, row in table.items() if row["ppid"] in descendants}
            if expanded == descendants:
                break
            descendants = expanded
        known = {pid: table[pid] for pid in descendants if pid in table}
        if mode in {"cancel", "owner-death"}:
            sig = signal.SIGINT if mode == "cancel" else signal.SIGKILL
            RUNTIME["signal_owned"]([identity], sig)
            (capture / "injected-signal.json").write_text(json.dumps({"target": identity, "signal": sig}))
        child.wait(timeout=10)
    if ready.exists():
        known.update({row["pid"]: row for row in json.loads(ready.read_text())})
    until = time.monotonic() + 4
    while RUNTIME["living"](known) and time.monotonic() < until:
        time.sleep(0.05)
    survivors = RUNTIME["living"](known)
    (capture / "lifetime-result.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "owner_returncode": child.returncode,
                "survivors_before_outer_cleanup": survivors,
            },
            indent=2,
        )
    )
    return 1 if survivors else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "stub":
        stub()
        return 0
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "owner"))
    parser.add_argument(
        "mode",
        choices=("timeout", "cancel", "owner-death", "absent", "malformed", "quota"),
    )
    args = parser.parse_args()
    return owner(args.mode) if args.action == "owner" else run_stub(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
