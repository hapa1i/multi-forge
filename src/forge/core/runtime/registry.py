"""Runtime registry: a declarative capability matrix for agent runtimes (Phase 4e).

Forge orchestrates work across more than one agent runtime -- Claude Code today;
Codex and Gemini as headless workers, Codex as a future frontend. Code that has to
branch on "can this runtime do X?" should ask this registry instead of hard-coding
Claude Code assumptions.

Each runtime is a frozen :class:`RuntimeSpec` (mirrors the ``Credential`` /
``CREDENTIALS`` pattern in ``core/auth/capabilities.py``): a module-level
:data:`RUNTIMES` table plus lookup helpers. The data is the capability matrix from
the runtime-abstraction card; the registry answers the seven questions that card
poses -- installed? interactive? headless? hooks? usage? native resume? which
install scopes?

Honest capability encoding: where a runtime's support is *partial* (Codex
``PreToolUse`` is a real hook but not a full enforcement boundary) or merely
*planned* (Codex interactive is a target beta, not shipped), the field is a
tri-state ``Literal`` rather than a ``bool`` -- the type itself carries the
limitation instead of overstating parity.

Layering note: the Claude version probe lives in ``forge.install.version`` and is
imported *lazily* inside :func:`_detect_claude` (matching the ``core -> install``
lazy-import precedent in ``core/ops/gc.py``), so importing this module never drags
the installer.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

# Interactive-frontend support: the shipping default, a planned/target beta, or not
# planned. ("beta" is NOT "usable now" -- callers needing a frontend today check
# ``== "default"``.)
InteractiveSupport = Literal["default", "beta", "none"]

# Pre-tool policy enforcement strength. "partial" exists for Codex: its PreToolUse
# hook does not intercept every tool path, so it is a beta-grade guard, not
# Claude-equivalent enforcement.
PolicyEnforcement = Literal["full", "partial", "none"]

# Native-hook support. "gated" exists for Codex: hooks are real but require a
# minimum CLI version AND a config feature flag (the machine-readable gate lives in
# ``hook_min_version`` / ``hook_feature_flag``), so a preflight must verify the gate
# rather than assume parity from a bare "yes".
HookSupport = Literal["full", "gated", "none"]

# Where a runtime's usage/token figures come from.
UsageSource = Literal["transcript_proxy", "jsonl_events", "json_stats"]


def _probe_version(argv: tuple[str, ...]) -> str | None:
    """Best-effort ``<bin> --version`` -> a version-like token, or None.

    None means "could not determine a version" (binary absent, non-zero exit,
    timeout, or unparseable output) -- NOT necessarily "not installed". Use
    :meth:`RuntimeSpec.is_installed` (PATH presence) for the installed? question.
    """
    if shutil.which(argv[0]) is None:
        return None
    try:
        result = subprocess.run(list(argv), capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # Search both streams: a CLI may print a banner to stdout and the version to
    # stderr (or vice versa). stdout first preserves its precedence when both carry
    # a version-like token.
    combined = "\n".join(stream for stream in (result.stdout, result.stderr) if stream)
    match = re.search(r"\d+\.\d+(?:\.\d+)?", combined)
    return match.group(0) if match else None


def _detect_claude() -> str | None:
    """Reuse the installer's Claude Code version probe (lazy import: see module note)."""
    from forge.install.version import get_claude_runtime_version

    return get_claude_runtime_version()


def _detect_codex() -> str | None:
    return _probe_version(("codex", "--version"))


def _detect_gemini() -> str | None:
    return _probe_version(("gemini", "--version"))


@dataclass(frozen=True)
class RuntimeSpec:
    """Capabilities of one agent runtime. Read via :data:`RUNTIMES` / :func:`get_runtime`."""

    id: str  # "claude_code" | "codex" | "gemini"
    display_name: str
    headless_cmd: tuple[str, ...]  # ("claude","-p") | ("codex","exec") | ("gemini","-p")
    detect: Callable[[], str | None]  # best-effort version probe; None if undetermined
    interactive: InteractiveSupport
    headless: bool
    native_hooks: HookSupport
    pretool_policy: PolicyEnforcement
    usage_source: UsageSource
    native_resume: bool
    install_scopes: tuple[str, ...]  # config scopes Forge manages (empty = not Forge-managed)
    curated_transfer_in: bool  # can accept a context doc at session start
    curated_transfer_out: bool  # can generate a curation of its own transcript
    # Machine-readable gate for ``native_hooks == "gated"`` (both None otherwise): a
    # Phase 5 preflight checks these instead of parsing the human ``note``.
    hook_min_version: str | None = None  # e.g. "0.124.0"
    hook_feature_flag: str | None = None  # e.g. "codex_hooks"
    note: str | None = None  # human-facing caveats (exact activation syntax, partial support)

    def is_installed(self) -> bool:
        """True if the runtime's binary is on PATH.

        The reliable "installed?" signal, independent of version parsing -- an
        installed-but-unparseable runtime still reports True here even when
        :meth:`detect` returns None.
        """
        return shutil.which(self.headless_cmd[0]) is not None


# The capability matrix (runtime-abstraction card, "Runtime Capability Matrix").
# Claude Code is fully populated; Codex/Gemini declare their *limits* as capability
# values (not omissions), so a consumer never mistakes a gap for parity.
RUNTIMES: dict[str, RuntimeSpec] = {
    "claude_code": RuntimeSpec(
        id="claude_code",
        display_name="Claude Code",
        headless_cmd=("claude", "-p"),
        detect=_detect_claude,
        interactive="default",
        headless=True,
        native_hooks="full",
        pretool_policy="full",
        usage_source="transcript_proxy",
        native_resume=True,
        # Mirrors install.models.InstallScope (USER/PROJECT/LOCAL).
        install_scopes=("user", "project", "local"),
        curated_transfer_in=True,  # --append-system-prompt-file
        curated_transfer_out=True,  # transfer curator
        note="Forge's first-class frontend; the installer enforces a minimum Claude Code version.",
    ),
    "codex": RuntimeSpec(
        id="codex",
        display_name="Codex CLI",
        headless_cmd=("codex", "exec"),
        detect=_detect_codex,
        interactive="beta",  # target beta, not a shipped Forge frontend
        headless=True,
        native_hooks="gated",  # real hooks, but version + feature-flag gated (see hook_* fields)
        hook_min_version="0.124.0",
        hook_feature_flag="codex_hooks",
        pretool_policy="partial",  # PreToolUse adapter; NOT a full enforcement boundary
        usage_source="jsonl_events",
        native_resume=True,  # codex exec resume
        install_scopes=(),  # Forge does not manage Codex install scopes yet
        curated_transfer_in=True,  # initial user message
        curated_transfer_out=True,  # via headless invoker
        note=(
            "Hooks require `[features] codex_hooks = true` (Codex CLI 0.124.0+). "
            "PreToolUse does not intercept every tool path -- partial enforcement, not parity."
        ),
    ),
    "gemini": RuntimeSpec(
        id="gemini",
        display_name="Gemini CLI",
        headless_cmd=("gemini", "-p"),
        detect=_detect_gemini,
        interactive="none",  # not planned initially
        headless=True,
        native_hooks="none",  # no comparable hook target yet
        pretool_policy="none",  # not initially
        usage_source="json_stats",
        native_resume=False,  # "capability-check first" -- unverified, so claim nothing
        install_scopes=(),  # Forge does not manage Gemini install scopes yet
        curated_transfer_in=True,  # initial message
        curated_transfer_out=True,  # via headless invoker
        note="Native resume unverified (capability-check first); API/Vertex route only; no native hooks.",
    ),
}


def get_runtime(runtime_id: str) -> RuntimeSpec:
    """Return the spec for ``runtime_id``; raise ValueError if unknown.

    Internal boundary: an unresolved runtime id is a programming error, not a
    degrade-to-default case (coding-standards 5).
    """
    try:
        return RUNTIMES[runtime_id]
    except KeyError:
        known = ", ".join(RUNTIMES)
        raise ValueError(f"Unknown runtime '{runtime_id}'. Known runtimes: {known}") from None


def list_runtimes() -> list[RuntimeSpec]:
    """All known runtimes, in registry (declaration) order."""
    return list(RUNTIMES.values())


def installed_runtimes() -> list[RuntimeSpec]:
    """Known runtimes whose binary is currently on PATH."""
    return [spec for spec in RUNTIMES.values() if spec.is_installed()]
