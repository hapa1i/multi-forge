"""Claude Code minimum version detection and enforcement.

Forge requires a minimum Claude Code version to ensure hooks, policy enforcement,
and session features work correctly. This module provides cached version detection
and comparison utilities used by the installer and session launch flow.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)

# Minimum Claude Code version required by Forge.
# v2.1.78: hooks load in worktrees, StopFailure event, PreToolUse deny fix (v2.1.77),
#          transcript_path correct for forked/resumed sessions (v2.1.72).
MIN_CLAUDE_CODE_VERSION = "2.1.78"

# Process-scoped cache to avoid running `claude --version` on every call.
_VERSION_CACHE_TTL_S = 300  # 5 minutes
_cached_version: tuple[float, str | None] | None = None


@dataclass
class VersionCheckResult:
    """Result of checking Claude Code version against the minimum."""

    ok: bool
    version: str | None
    minimum: str
    reason: str


def get_claude_runtime_version() -> str | None:
    """Detect the installed Claude Code version via ``claude --version``.

    Returns the version string (e.g. ``"2.1.78"``) or None if Claude Code
    is not installed, times out, or produces unparseable output.

    Results are cached for ``_VERSION_CACHE_TTL_S`` seconds to avoid
    repeated subprocess calls within a single CLI invocation.
    """
    global _cached_version  # noqa: PLW0603 — module-level cache by design

    now = time.monotonic()
    if _cached_version is not None:
        cached_at, cached_value = _cached_version
        if now - cached_at < _VERSION_CACHE_TTL_S:
            return cached_value

    version = _run_claude_version()
    _cached_version = (now, version)
    return version


def _run_claude_version() -> str | None:
    """Run ``claude --version`` and parse the output."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        raw = result.stdout.strip()
        if not raw:
            return None
        # Output is like "2.1.78 (Claude Code)" — strip the suffix
        if " (Claude Code)" in raw:
            raw = raw.replace(" (Claude Code)", "")
        return raw.split()[0] if raw else None
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        logger.debug("Unexpected error detecting Claude Code version", exc_info=True)
        return None


def check_minimum_version(version_str: str | None = None) -> VersionCheckResult:
    """Check whether the installed Claude Code meets the minimum version.

    Args:
        version_str: Explicit version string (for testing). If None, detects
            the runtime version via ``get_claude_runtime_version()``.
    """
    minimum = MIN_CLAUDE_CODE_VERSION

    if version_str is None:
        version_str = get_claude_runtime_version()

    if version_str is None:
        return VersionCheckResult(
            ok=False,
            version=None,
            minimum=minimum,
            reason="Claude Code not found. Install it first: https://docs.anthropic.com/en/docs/claude-code",
        )

    try:
        detected = Version(version_str)
    except InvalidVersion:
        return VersionCheckResult(
            ok=False,
            version=version_str,
            minimum=minimum,
            reason=f"Could not parse Claude Code version '{version_str}'.",
        )

    required = Version(minimum)
    if detected < required:
        return VersionCheckResult(
            ok=False,
            version=version_str,
            minimum=minimum,
            reason=(
                f"Claude Code {version_str} is below the minimum required "
                f"version {minimum}. Run 'claude update' to upgrade."
            ),
        )

    return VersionCheckResult(
        ok=True,
        version=version_str,
        minimum=minimum,
        reason="OK",
    )


def reset_version_cache() -> None:
    """Clear the cached version (for testing)."""
    global _cached_version  # noqa: PLW0603
    _cached_version = None
