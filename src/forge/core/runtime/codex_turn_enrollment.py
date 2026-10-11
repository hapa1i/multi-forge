"""Event-specific empirical receipts for the measured Codex Stop hook set.

Receipts prove observed delivery for one configuration and executor fingerprint;
they do not manufacture trust or grant it. Probe artifacts contain no prompt text.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tomllib
from pathlib import Path
from typing import Any
from uuid import UUID

from forge.core.paths import get_forge_home
from forge.core.runtime.codex_feedback import (
    CODEX_EXECUTOR_IDENTITY_VAR,
    STOP_REVIEW_VERSIONS,
    stop_review_supported,
)
from forge.core.state import atomic_write_text, utc_timestamp_z

EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
PROBE_ENV = "FORGE_CODEX_ENROLLMENT_NONCE"


def config_identity() -> dict[str, str]:
    from forge.install.codex_hooks import (
        get_builtin_codex_entries,
        get_codex_config_path,
        inspect_codex_hook_registration,
    )
    from forge.install.models import InstallScope

    path = get_codex_config_path(InstallScope.USER).resolve()
    if not all(inspect_codex_hook_registration(path, entry).exactly_one for entry in get_builtin_codex_entries()):
        raise ValueError("Stop enrollment requires the exact command, matcher, and 60-second timeout for every event")
    with path.open("rb") as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Codex hook configuration exceeds the enrollment read limit")
    config = tomllib.loads(raw.decode())

    # Bind definitions and trust, not unrelated model, display, or MCP settings.
    # Include profile-level hook switches/definitions because they can override
    # the user defaults. Never infer enrollment from a trust hash alone.
    def hook_settings(values: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(values, dict) or not isinstance(values.get("features", {}), dict):
            raise ValueError("Malformed Codex hook configuration")
        features = values.get("features", {})
        return {
            "hooks": values.get("hooks"),
            "features": {k: v for k, v in features.items() if "hook" in k},
            "allow_managed_hooks_only": values.get("allow_managed_hooks_only"),
        }

    relevant = hook_settings(config)
    if not isinstance(config.get("profiles", {}), dict):
        raise ValueError("Malformed Codex profile configuration")
    profiles = {name: hook_settings(values) for name, values in config.get("profiles", {}).items()}
    relevant["profiles"] = {name: values for name, values in profiles.items() if values != hook_settings({})}
    if relevant["profiles"]:
        relevant["profile"] = config.get("profile")
    stable = json.dumps(relevant, sort_keys=True, separators=(",", ":")).encode()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(stable).hexdigest(),
        "scope": "hook_configuration_v1",
    }


def receipt_path() -> Path:
    return get_forge_home() / "runtime" / "codex-stop-enrollment.json"


def observe(data: dict[str, Any]) -> bool:
    """Record probe events only from the verified directly launched executor."""
    nonce = os.environ.get(PROBE_ENV)
    if not nonce or os.environ.get("FORGE_SESSION") != "forge-enroll-probe":
        return False
    if len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce) or not stop_review_supported(os.environ):
        return False
    event = data.get("hook_event_name")
    if event not in EVENTS:
        return False
    root = Path(os.environ["FORGE_FORGE_ROOT"]).resolve(strict=True)
    if Path(data["cwd"]).resolve(strict=True) != root:
        return False
    for key in ("session_id", "turn_id"):
        if UUID(data[key]).version != 7:
            return False
    identity = json.loads(os.environ[CODEX_EXECUTOR_IDENTITY_VAR])
    record = {
        "schema": 1,
        "nonce": nonce,
        "event": event,
        "thread_id": data["session_id"],
        "turn_id": data["turn_id"],
        "config": config_identity(),
        "executable": identity["executable"],
        "sha256": identity["sha256"],
        "version": identity["version"],
    }
    directory = root / ".forge" / "stop-enrollment"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_text(directory / (event + ".json"), json.dumps(record))
    return True


def publish(root: Path, nonce: str) -> bool:
    """Publish only a complete same-turn observation, including a tool outcome."""
    rows = []
    try:
        for event in EVENTS:
            row = _read(root / ".forge" / "stop-enrollment" / (event + ".json"))
            if row.pop("event") != event or row["nonce"] != nonce or row["config"] != config_identity():
                return False
            rows.append(row)
        if not rows or any(row != rows[0] for row in rows):
            return False
        result = dict(rows[0], events=list(EVENTS), verified_at=utc_timestamp_z())
        path = receipt_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write_text(path, json.dumps(result), mode=0o600)
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def verified(identity: dict[str, Any] | None = None) -> bool:
    """A config change invalidates proof; hooks additionally match launch facts."""
    try:
        row = _read(receipt_path())
        if row.get("schema") != 1 or row.get("events") != list(EVENTS) or row["config"] != config_identity():
            return False
        if row["version"] not in STOP_REVIEW_VERSIONS:
            return False
        if identity is not None:
            return all(row[key] == identity.get(key) for key in ("executable", "sha256", "version"))
        # CLI configuration admission has no invoking executor. Recheck the
        # observed executable on disk; launch hooks check the actual launch record.
        with Path(row["executable"]).open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest() == row["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return False


def require_for_launch(*, cwd: str | None = None) -> None:
    """Refuse Stop configuration/launch before inference when the current CLI lacks proof."""
    from forge.core.runtime.codex_feedback import prepare_executor_launch

    env = dict(os.environ)
    prepare_executor_launch(["codex"], env, cwd=cwd)
    raw = env.get(CODEX_EXECUTOR_IDENTITY_VAR, "")
    try:
        identity = json.loads(raw)
    except ValueError:
        identity = {}
    if not isinstance(identity, dict) or identity.get("version") not in STOP_REVIEW_VERSIONS or not verified(identity):
        raise ValueError(
            "Stop review requires measured Codex 0.162.1 and verified hooks for this executable/configuration. "
            "Run forge extension sync, trust hooks in Codex, then forge runtime preflight codex --verify-enrollment."
        )


def _read(path: Path) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16_000:
            raise ValueError("Unsafe enrollment receipt")
        raw = stream.read(16_001)
    if len(raw) > 16_000:
        raise ValueError("Unbounded enrollment receipt")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Malformed enrollment receipt")
    return result
