"""Launch facts and feature-specific admission for Codex policy feedback.

These facts describe a managed executor, not reviewer readiness or an auth boundary.
Hooks consume the launch record without probing a CLI or reading account metadata.
The running executor keeps its identity even if its on-disk binary is later replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

CODEX_EXECUTOR_IDENTITY_VAR = "FORGE_CODEX_EXECUTOR_IDENTITY"
# Feature evidence is separate from the general QA ceiling and release pin.
POLICY_FEEDBACK_VERSIONS = frozenset({"0.161.0", "0.162.1"})
_VERSION = re.compile(r"codex-cli (\d+\.\d+\.\d+)")


def prepare_executor_launch(argv: list[str], env: dict[str, str]) -> list[str]:
    """Resolve the actual launcher and refresh secret-free facts just before spawn.

    A failed or racing version check suppresses feedback, not an otherwise valid
    launch. Using the absolute resolved path prevents a later PATH lookup selecting
    a different executable. The before/after stat rejects replacement during probing.
    """
    env.pop(CODEX_EXECUTOR_IDENTITY_VAR, None)
    selected = shutil.which(argv[0], path=env.get("PATH", os.defpath))
    if selected is None:
        return argv
    executable = Path(selected).resolve()
    launch_argv = [str(executable), *argv[1:]]
    try:
        before = executable.stat()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        result = subprocess.run(
            [str(executable), "--version"], env=env, capture_output=True, text=True, timeout=3, check=False
        )
        after = executable.stat()
        match = _VERSION.fullmatch(result.stdout.strip())

        def fingerprint(s: os.stat_result) -> tuple[int, int, int, int, int]:
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

        if result.returncode or match is None or fingerprint(before) != fingerprint(after):
            return launch_argv
        env[CODEX_EXECUTOR_IDENTITY_VAR] = json.dumps(
            {
                "schema": 1,
                "executable": str(executable),
                "sha256": digest,
                "version": match[1],
                "device": after.st_dev,
                "inode": after.st_ino,
                "size": after.st_size,
                "mtime_ns": after.st_mtime_ns,
            },
            separators=(",", ":"),
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return launch_argv


def policy_feedback_supported(env: Mapping[str, str]) -> bool:
    """Admit only measured versions with a complete managed launch record."""
    raw = env.get(CODEX_EXECUTOR_IDENTITY_VAR, "")
    if not raw or len(raw) > 4096:
        return False
    try:
        data = json.loads(raw)
        return (
            isinstance(data, dict)
            and type(data.get("schema")) is int
            and data["schema"] == 1
            and data.get("version") in POLICY_FEEDBACK_VERSIONS
            and isinstance(data.get("executable"), str)
            and Path(data["executable"]).is_absolute()
            and isinstance(data.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", data["sha256"]) is not None
            and all(type(data.get(key)) is int and data[key] >= 0 for key in ("device", "inode", "size", "mtime_ns"))
        )
    except (ValueError, TypeError):
        return False
