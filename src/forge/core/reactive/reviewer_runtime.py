"""Non-inference admission for the Claude reviewer's required isolation flags."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from time import monotonic

from packaging.version import Version

from forge.core.paths import get_forge_home
from forge.core.reactive.watchdog import run_guarded
from forge.core.state import atomic_write_json
from forge.session.models import LaneRecord, SessionState, SupervisorConfig

READ_ONLY_FLAGS = (
    "--restricted",
    "--safe-mode",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--tools",
    "Read,Glob,Grep",
    "--allowedTools",
    "Read,Glob,Grep",
    "--setting-sources",
    "",
)
MIN_REVIEWER_VERSION = "2.1.248"
_CONTRACT_VERSION = 1


def require_reviewer_runtime(*, env: dict[str, str], deadline: float) -> str:
    """Probe a changed executable once; persist both supported and refused results.

    Auto-updates invalidate the cache through the resolved executable's identity.
    Authentication is deliberately not cached here: each subscription dispatch
    still checks the exact child environment with ``auth status``.
    """
    executable = shutil.which("claude", path=env.get("PATH"))
    if executable is None:
        raise ValueError("Claude reviewer is unavailable. Install Claude Code and run 'claude update'.")
    binary = Path(executable).resolve()
    stat = binary.stat()
    identity = [str(binary), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, _CONTRACT_VERSION]
    cache_key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    cache = get_forge_home() / "cache" / "reviewer_runtime" / f"{cache_key}.json"
    try:
        cached = json.loads(cache.read_text())
        if cached.get("identity") == identity and isinstance(cached.get("reason"), str):
            if cached["reason"]:
                raise ValueError(cached["reason"])
            return str(binary)
    except (OSError, json.JSONDecodeError, AttributeError):
        pass

    def probe(args: list[str]):
        return run_guarded([str(binary), *args], input="", env=env, cwd="/", timeout=min(10, deadline - monotonic()))

    version = probe(["--version"])
    reason = ""
    try:
        detected = Version(version.stdout.split()[0])
        if detected.major > 2:
            reason = (
                "This Forge version cannot verify Claude's new major version. Upgrade Forge or use Claude Code 2.x."
            )
        elif version.returncode or detected.major != 2 or detected < Version(MIN_REVIEWER_VERSION):
            reason = f"Claude review requires version {MIN_REVIEWER_VERSION} or later in major version 2. Run 'claude update'."
    except (ValueError, IndexError):
        reason = "Cannot verify the Claude reviewer version. Run 'claude --version' and repair the installation."
    if not reason:
        help_result = probe([*READ_ONLY_FLAGS, "--help"])
        required = {flag for flag in READ_ONLY_FLAGS if flag.startswith("--")}
        if help_result.returncode or any(flag not in help_result.stdout for flag in required):
            reason = (
                "Claude lacks the required read-only review flags. Run 'claude update' before enabling supervision."
            )
    # No auth material is stored. Failure to persist this optimization does not
    # change the admission result or trigger an unverified fallback.
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(cache, {"identity": identity, "reason": reason})
    except OSError:
        pass
    if reason:
        raise ValueError(reason)
    return str(binary)


def preflight_supervisor_runtime(config: SupervisorConfig, lane: LaneRecord, *, cwd: str | None) -> None:
    """Refuse unusable host Claude supervision before saving or launching it."""
    if lane.runtime_id != "claude_code" or not config.active:
        return
    from forge.core.reactive.env import build_claude_env
    from forge.core.reactive.supervisor_auth import (
        preflight_subscription,
        subscription_environment,
    )

    expires = monotonic() + 15
    try:
        if config.auth_mode == "subscription-only":
            preflight_subscription(env=subscription_environment(), cwd=cwd, deadline=expires)
        else:
            from forge.core.reactive.reviewer_settings import inherited_auth_settings

            env = build_claude_env(direct=config.direct)
            inherited_auth_settings(env, cwd=cwd, direct=config.direct)
            require_reviewer_runtime(env=env, deadline=expires)
    except Exception as exc:
        raise ValueError(f"Supervisor runtime is unavailable: {exc}") from exc


def preflight_host_supervisor(state: SessionState) -> None:
    """Apply the same reviewer admission to Claude and Codex executor launches."""
    from forge.policy.semantic.deadline import validate_timeout
    from forge.policy.semantic.identity import (
        SUPERVISOR_CONSUMER,
        select_supervisor_lane,
        snapshot_supervisor_options,
        validate_reviewer,
    )
    from forge.session.consumer_lanes import read_bound_lane

    config = snapshot_supervisor_options(state)
    if config is None or not config.active:
        return
    lane = read_bound_lane(state, SUPERVISOR_CONSUMER) or select_supervisor_lane()
    validate_timeout(config.timeout_seconds)
    validate_reviewer(config, lane)
    preflight_supervisor_runtime(config, lane, cwd=state.worktree.path if state.worktree else None)
