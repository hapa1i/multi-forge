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

# Native-hook support. "gated" exists for Codex: hooks are real but require a minimum
# CLI version (the machine-readable gate lives in ``hook_min_version``), so a preflight
# must verify the gate rather than assume parity from a bare "yes". A config feature
# flag (``hook_feature_flag``) is recorded only when one is *also* required; Codex's
# hooks are default-on (``codex_hooks`` is a deprecated alias of ``hooks`` -- still
# works, but do not author it), so that field is None.
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
    # Machine-readable gate for ``native_hooks == "gated"`` (None when ungated): a
    # Phase 5 preflight checks these instead of parsing the human ``note``.
    # ``hook_min_version`` is the floor where hooks work without extra config;
    # ``hook_feature_flag`` is recorded only when a config flag is *also* required.
    hook_min_version: str | None = None  # e.g. "0.131.0" (Codex hooks default-on)
    hook_feature_flag: str | None = None  # set only when a config flag is also required
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
        interactive="beta",  # Codex's own interactive mode is GA; Forge frontend integration is the Phase 6 target
        headless=True,
        native_hooks="gated",  # real hooks, default-on; version-gated only (see hook_* fields)
        hook_min_version="0.131.0",  # hooks default-on since 0.131.0; 0.134.0 dropped the plugin-hooks gate, not the alias
        hook_feature_flag=None,  # hooks default-on (no gate); codex_hooks is a deprecated alias -- do not author it
        pretool_policy="partial",  # PreToolUse adapter; NOT a full enforcement boundary (no WebSearch/complex shell)
        usage_source="jsonl_events",
        native_resume=True,  # codex exec resume (cwd-aware since 0.135.0)
        install_scopes=(),  # Forge does not manage Codex install scopes yet
        curated_transfer_in=True,  # SessionStart additionalContext (preferred) or initial user message
        curated_transfer_out=True,  # via headless invoker
        note=(
            "Hooks are default-on (`[features] hooks`, Codex CLI >= 0.131.0); `codex_hooks` is a deprecated "
            "alias (still works -- do not author new config with it). Ten lifecycle events incl. SessionStart/"
            "PreToolUse/PermissionRequest. PreToolUse is a partial guard (does not intercept every tool path) "
            "but can mutate tool input via updatedInput; PermissionRequest is the approval seam. SessionStart "
            "additionalContext can inject a transfer doc, but only when hooks are enabled AND the hook is "
            "trusted (untrusted/first-run projects skip project-local `.codex/` hooks) -- keep an "
            "initial-message fallback. Enterprise `allow_managed_hooks_only` (requirements.toml) can suppress "
            "user/project hooks. Codex emits the Responses API (custom-provider `wire_api=chat` removed ~Feb "
            "2026); a proxy fronting Codex must serve Responses on its Codex-facing endpoint (backend may be "
            "translated). Verified vs Codex CLI 0.137.0 (2026-06-08)."
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
