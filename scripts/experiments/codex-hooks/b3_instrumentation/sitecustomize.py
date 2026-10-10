"""Opt-in B3 observation only: preserve hook bytes and collect exit/provenance facts."""

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
captured_out, captured_err, captured_in = io.StringIO(), io.StringIO(), io.StringIO()
exit_code = 0


class Tee:
    def __init__(self, stream, capture):
        self.stream, self.capture = stream, capture

    def write(self, value):
        self.capture.write(value)
        return self.stream.write(value)

    def read(self, *args):
        value = self.stream.read(*args)
        self.capture.write(value)
        return value

    def __getattr__(self, name):
        return getattr(self.stream, name)


def capture_dir() -> Path:
    return Path(json.loads(Path(os.environ["PROBE_CONTROL"]).read_text())["capture"])


if sys.argv[1:2] == ["hook"] and os.environ.get("PROBE_CONTROL"):
    sys.stdout = Tee(sys.stdout, captured_out)
    sys.stderr = Tee(sys.stderr, captured_err)
    sys.stdin = Tee(sys.stdin, captured_in)
    ordinary_exit, ordinary_exception = sys.exit, sys.excepthook

    def observed_exit(code=0):
        global exit_code
        exit_code = code if isinstance(code, int) else 0 if code is None else 1
        ordinary_exit(code)

    def observed_exception(*args):
        global exit_code
        exit_code = 1
        ordinary_exception(*args)

    sys.exit = observed_exit
    sys.excepthook = observed_exception

    def record_hook():
        spec = importlib.util.find_spec("forge")
        runtime["append_json"](
            capture_dir() / "hooks.jsonl",
            {
                "at": time.time(),
                "pid": os.getpid(),
                "launcher": sys.argv[0],
                "python": sys.executable,
                "forge_module": spec.origin if spec else None,
                "hook": sys.argv[2:],
                "elapsed_seconds": time.monotonic() - started,
                "exit_code": exit_code,
                "stdout": captured_out.getvalue(),
                "stderr": captured_err.getvalue(),
                "stdin": captured_in.getvalue(),
                "executor_identity": os.environ.get("FORGE_CODEX_EXECUTOR_IDENTITY"),
                "dev_override": os.environ.get("FORGE_DEV"),
            },
        )

    atexit.register(record_hook)


if os.environ.get("PROBE_CONTROL") and sys.argv[1:3] in (["session", "start"], ["session", "resume"]):
    from forge.core.invoker.codex import CodexHeadlessInvoker

    original_build = CodexHeadlessInvoker._build_result

    def observed_build(self, request, **kwargs):
        result = original_build(self, request, **kwargs)
        directory = capture_dir()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{result.run_id}-native-stream.jsonl").write_text(kwargs["stdout"])
        return result

    CodexHeadlessInvoker._build_result = observed_build  # type: ignore[method-assign]
