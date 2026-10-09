"""Opt-in fixture startup evidence, activated only by the probe's PYTHONPATH."""

from __future__ import annotations

import atexit
import importlib.util
import io
import json
import os
import runpy
import sys
import time
from pathlib import Path

runtime = runpy.run_path(str(Path(__file__).resolve().parents[1] / "probe-runtime.py"))
runtime["register_process"]()
started = time.monotonic()
captured = io.StringIO()
output = sys.stdout


class HookOutput:
    """Tee only this fixture's product-hook stdout without changing its bytes."""

    def write(self, value: str) -> int:
        captured.write(value)
        return output.write(value)

    def flush(self) -> None:
        output.flush()

    def __getattr__(self, name: str) -> object:
        return getattr(output, name)


if len(sys.argv) > 1 and sys.argv[1] == "hook":
    sys.stdout = HookOutput()
    control_path = os.environ.get("PROBE_CONTROL")
    if control_path:
        control = json.loads(Path(control_path).read_text())
        runtime["append_json"](
            Path(control["capture"]) / "hook-entry.jsonl",
            {
                "at": time.time(),
                "pid": os.getpid(),
                "hook": sys.argv[2:],
                "identity": runtime["process_table"]().get(os.getpid()),
            },
        )
        if control.get("mode") == "natural-review-expiry" and sys.argv[2:] == ["codex-policy-check"]:
            # Runtime-expiry fixture only: bypass the earlier product budget while
            # retaining the admitted reviewer and B1's actual watchdog transport.
            # Ordinary deadline/cancellation arms do not enter this branch.
            import forge.policy.semantic.supervisor as supervisor

            ordinary_run = supervisor.run_claude_session

            def extended_review(*args, **kwargs):
                kwargs["timeout_seconds"] = 90
                kwargs["deadline"] = time.monotonic() + 90
                return ordinary_run(*args, **kwargs)

            supervisor.run_claude_session = extended_review


def record_hook_exit() -> None:
    control_path = os.environ.get("PROBE_CONTROL")
    if not control_path or len(sys.argv) < 2 or sys.argv[1] != "hook":
        return
    control = json.loads(Path(control_path).read_text())
    capture = Path(control["capture"])
    spec = importlib.util.find_spec("forge")
    row = {
        "at": time.time(),
        "pid": os.getpid(),
        "launcher": sys.argv[0],
        "python": sys.executable,
        "forge_module": spec.origin if spec else None,
        "hook": sys.argv[2:],
        "elapsed_seconds": time.monotonic() - started,
        "stdout": captured.getvalue(),
    }
    runtime["append_json"](capture / "hook-launchers.jsonl", row)
    project = os.environ.get("FORGE_FORGE_ROOT")
    session = os.environ.get("FORGE_SESSION")
    if project and session:
        handoff = Path(project) / ".forge/sessions" / session / "codex"
        for name in ("observation-receipt.json", "context-receipt.json"):
            receipt = handoff / name
            if receipt.is_file():
                (capture / f"{os.getpid()}-{name}").write_bytes(receipt.read_bytes())


atexit.register(record_hook_exit)


if os.environ.get("PROBE_CONTROL") and sys.argv[1:3] in (["session", "start"], ["session", "resume"]):
    from dataclasses import asdict

    from forge.core.invoker.codex import CodexHeadlessInvoker
    from forge.core.usage.ledger import read_usage_events

    build_result = CodexHeadlessInvoker._build_result
    emit_result = CodexHeadlessInvoker._emit

    def observed_build(self, request, **kwargs):
        result = build_result(self, request, **kwargs)
        control = json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())
        capture = Path(control["capture"])
        capture.mkdir(parents=True, exist_ok=True)
        (capture / f"{result.run_id}-native-stream.jsonl").write_text(kwargs["stdout"])
        return result

    def observed_emit(self, request, result):
        emit_result(self, request, result)
        control = json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())
        events = [asdict(event) for event in read_usage_events() if event.run_id == result.run_id]
        runtime["append_json"](
            Path(control["capture"]) / "usage-correlation.jsonl",
            {
                "run_id": result.run_id,
                "result": asdict(result),
                "usage_events": events,
            },
        )

    CodexHeadlessInvoker._build_result = observed_build  # type: ignore[method-assign]
    CodexHeadlessInvoker._emit = observed_emit  # type: ignore[method-assign]
