#!/usr/bin/env python3
"""Private wheel instrumentation: reserve native starts without changing child argv/env.

Loaded by a .pth file ONLY in the owned B5 candidate virtualenv. It observes the
production watchdog's Popen call as well as executor starts. The actual runtime
binary, stdin, hooks, configuration and invocation path remain production code.
"""

from __future__ import annotations

import atexit
import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path


def install(root: Path) -> None:
    if getattr(subprocess.Popen, "b5_budgeted", False):
        return
    reserve = runpy.run_path(str(Path(__file__).with_name("b5-runtime.py")))["reserve_start"]

    def append(path: Path, record: dict) -> None:
        encoded = (json.dumps(record, sort_keys=True) + "\n").encode()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)

    class BudgetedPopen(subprocess.Popen):
        b5_budgeted = True

        def __init__(self, args, *positional, **kwargs):
            self.b5_record = None
            self.b5_started = time.monotonic()
            self.b5_finished = False
            argv = list(args) if isinstance(args, (list, tuple)) else []
            if (
                argv
                and Path(str(argv[0])).name == "codex"
                and not any(flag in argv for flag in ("--help", "-h", "--version", "-V"))
            ):
                if "exec" not in argv:
                    if any(word in argv for word in ("login", "logout", "features", "doctor", "debug")):
                        super().__init__(args, *positional, **kwargs)
                        return
                    raise ValueError("B5 product harness refuses unallocated interactive inference")
                if (root / "B5_ROUND").read_text() != "independent-b5-round-v1\n" or (root / "CLOSED").exists():
                    raise ValueError("The B5 fixture is not open")
                identity = json.loads((root / "identity.json").read_text())
                env = kwargs.get("env") or os.environ
                executable = shutil.which(str(argv[0]), path=env.get("PATH"))
                if executable is None:
                    raise ValueError("Product runtime is unavailable")
                with Path(executable).open("rb") as binary:
                    if hashlib.file_digest(binary, "sha256").hexdigest() != identity["sha256"]:
                        raise ValueError("B5 product runtime identity changed")
                control = json.loads((root / "product-control.json").read_text())
                if control["case"] not in {"P1", "P2"}:
                    raise ValueError("Only allocated product cases are admitted")
                if env.get("HOME") != str(root / "home"):
                    raise ValueError("Product inference must use the private fixture HOME")
                reviewer = "fork" in argv
                expected_home = root / "forge-home/reviewers/codex" if reviewer else root / "codex-home"
                if env.get("CODEX_HOME") != str(expected_home):
                    raise ValueError("Unexpected product native home")
                if any(value for key, value in env.items() if key.endswith("API_KEY") or key == "CODEX_ACCESS_TOKEN"):
                    raise ValueError("Product probes have no API authorization")
                leaf = (
                    argv.index("fork") if reviewer else argv.index("resume") if "resume" in argv else argv.index("exec")
                )
                if 'forced_login_method="chatgpt"' not in argv[leaf:]:
                    config = tomllib.loads((expected_home / "config.toml").read_text())
                    if reviewer or config.get("forced_login_method") != "chatgpt" or "--ignore-user-config" in argv:
                        raise ValueError("Product start must force subscription auth")
                model = argv[argv.index("-m") + 1] if "-m" in argv else control["model"]
                if model != "gpt-6.1-sol":
                    raise ValueError("Product slots are allocated to the admitted subscription model")
                metadata = {
                    "PROBE_CASE": control["case"],
                    "PROBE_MODEL": model,
                    "PROBE_ROLE": "reviewer" if reviewer else "executor",
                    "PROBE_CAPTURE": str(root / "captures" / control["label"]),
                }
                saved = {key: os.environ.get(key) for key in metadata}
                try:
                    os.environ.update(metadata)
                    self.b5_record = reserve(
                        root, identity, "subscription-only", json.loads((root / "authorization.json").read_text())
                    )
                finally:
                    for key, value in saved.items():
                        if value is None:
                            os.environ.pop(key, None)
                        else:
                            os.environ[key] = value
                append(
                    root / "product-invocations.jsonl",
                    {**self.b5_record, "argv": argv, "cwd": kwargs.get("cwd"), "env_keys": sorted(env)},
                )
            super().__init__(args, *positional, **kwargs)

        def communicate(self, input=None, timeout=None):
            output, errors = super().communicate(input=input, timeout=timeout)
            if self.b5_record and not self.b5_finished:
                self.b5_finished = True
                capture = Path(self.b5_record["capture"])
                capture.mkdir(parents=True, exist_ok=True, mode=0o700)
                prefix = self.b5_record["id"]
                for name, value in (("stdout", output), ("stderr", errors)):
                    if value is not None:
                        (capture / f"{prefix}-{name}.txt").write_bytes(
                            value.encode() if isinstance(value, str) else value
                        )
                append(
                    root / "product-outcomes.jsonl",
                    {
                        "id": prefix,
                        "elapsed_seconds": time.monotonic() - self.b5_started,
                        "returncode": self.returncode,
                        "stdin_bytes": len(input) if input is not None else None,
                        "global_ignore_sentinel_seen": (
                            "B5_GLOBAL_IGNORE_SENTINEL" in (input.decode() if isinstance(input, bytes) else input)
                            if input is not None
                            else None
                        ),
                    },
                )
            return output, errors

    setattr(subprocess, "Popen", BudgetedPopen)
    if sys.argv[1:2] == ["hook"]:
        control = json.loads((root / "product-control.json").read_text())
        capture = root / "captures" / control["label"]
        capture.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = sys.stdin.read()
        sys.stdin = io.StringIO(raw)
        captured: dict[str, list[str]] = {"stdout": [], "stderr": []}
        started = time.monotonic()

        class Tee:
            def __init__(self, stream, key):
                self.stream, self.key = stream, key

            def write(self, value):
                result = self.stream.write(value)
                captured[self.key].append(value.decode() if isinstance(value, bytes) else value)
                return result

            def __getattr__(self, name):
                return getattr(self.stream, name)

        sys.stdout, sys.stderr = Tee(sys.stdout, "stdout"), Tee(sys.stderr, "stderr")

        def finished_hook():
            append(
                capture / "product-hooks.jsonl",
                {
                    "hook": sys.argv[2:],
                    "stdin": raw,
                    "stdout": "".join(captured["stdout"]),
                    "stderr": "".join(captured["stderr"]),
                    "elapsed_seconds": time.monotonic() - started,
                    "forge_module": getattr(sys.modules.get("forge"), "__file__", None),
                    "dev_override": os.environ.get("FORGE_DEV"),
                    "parent_pid": os.getppid(),
                },
            )

        atexit.register(finished_hook)
