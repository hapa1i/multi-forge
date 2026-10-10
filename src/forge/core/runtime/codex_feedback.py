"""Launch facts and feature-specific admission for Codex policy feedback.

These facts describe a managed executor, not reviewer readiness or an auth boundary.
Hooks check the invoking process against the launch parent without probing Codex
or reading account metadata. An unverifiable launcher chain suppresses new channels.
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


def prepare_executor_launch(argv: list[str], env: dict[str, str], *, cwd: str | None = None) -> list[str]:
    """Select the child-cwd launcher and refresh secret-free facts before spawn.

    A failed or racing version check suppresses feedback, not an otherwise valid
    launch. Preserve the selected symlink's basename: package-manager shims can
    dispatch on argv[0]. Resolve only for fingerprinting, and reject probe races.
    """
    env.pop(CODEX_EXECUTOR_IDENTITY_VAR, None)
    directory = Path.cwd() / (cwd or ".")
    search_path = os.pathsep.join(str(directory / entry) for entry in env.get("PATH", os.defpath).split(os.pathsep))
    command = str(directory / argv[0]) if os.path.dirname(argv[0]) else argv[0]
    selected = shutil.which(command, path=search_path)
    if selected is None:
        return argv
    launch_argv = [selected, *argv[1:]]
    try:
        executable = Path(selected).resolve()
        before = executable.stat()
        with executable.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        result = subprocess.run(
            [selected, "--version"], env=env, cwd=cwd, capture_output=True, text=True, timeout=3, check=False
        )
        after = executable.stat()
        match = _VERSION.fullmatch(result.stdout.strip())

        def fingerprint(s: os.stat_result) -> tuple[int, int, int, int, int]:
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

        if (
            result.returncode
            or match is None
            or fingerprint(before) != fingerprint(after)
            or Path(selected).resolve() != executable
        ):
            return launch_argv
        env[CODEX_EXECUTOR_IDENTITY_VAR] = json.dumps(
            {
                "schema": 2,
                "launch_parent_pid": os.getpid(),
                "launcher": selected,
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
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        pass
    return launch_argv


def policy_feedback_supported(env: Mapping[str, str]) -> bool:
    """Admit measured versions only on hooks from the directly launched process.

    The dispatcher execs Forge, so its parent is the invoking Codex process. A
    nested runtime inherits the record but has a different launch parent. Wrappers
    that fork instead of exec are conservatively unsupported for new channels.
    """
    raw = env.get(CODEX_EXECUTOR_IDENTITY_VAR, "")
    if not raw or len(raw) > 4096:
        return False
    try:
        data = json.loads(raw)
        return (
            isinstance(data, dict)
            and type(data.get("schema")) is int
            and data["schema"] == 2
            and data.get("version") in POLICY_FEEDBACK_VERSIONS
            and isinstance(data.get("executable"), str)
            and Path(data["executable"]).is_absolute()
            and isinstance(data.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", data["sha256"]) is not None
            and all(type(data.get(key)) is int and data[key] >= 0 for key in ("device", "inode", "size", "mtime_ns"))
            and type(data.get("launch_parent_pid")) is int
            and data["launch_parent_pid"] > 1
            and _hook_from_launch_child(data["launch_parent_pid"])
        )
    except (ValueError, TypeError):
        return False


def _hook_from_launch_child(launch_parent_pid: int) -> bool:
    """Read one bounded OS parent lookup; no executable/version/auth probe runs here."""
    try:
        result = subprocess.run(
            ["/bin/ps", "-o", "ppid=", "-p", str(os.getppid())],
            capture_output=True,
            text=True,
            timeout=0.25,
            check=False,
        )
        return result.returncode == 0 and int(result.stdout.strip()) == launch_parent_pid
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
