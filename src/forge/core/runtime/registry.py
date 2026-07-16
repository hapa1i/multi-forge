"""Runtime registry: a declarative capability matrix for agent runtimes (Phase 4e).

Forge orchestrates work across more than one agent runtime -- Claude Code and
Codex today. Code that has to branch on "can this runtime do X?" should ask this
registry instead of hard-coding Claude Code assumptions.

Each runtime is a frozen :class:`RuntimeSpec` (mirrors the ``Credential`` /
``CREDENTIALS`` pattern in ``core/credential_registry.py``): a module-level
:data:`RUNTIMES` table plus lookup helpers. The data is the capability matrix from
the runtime-abstraction card; the registry answers the seven questions that card
poses -- installed? interactive? headless? hooks? usage? native resume? which
install scopes?

Honest capability encoding: where a runtime's support is *limited* (Codex hooks are
``enrollment_gated`` -- they fire only after a one-time interactive trust enrollment)
or merely planned (a target beta), the field is a multi-state ``Literal`` rather
than a ``bool`` -- the type itself carries the limitation instead of overstating
parity.

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

# Pre-tool policy enforcement strength, full -> partial -> none. Codex is "partial"
# (codex_frontend Phase 1 probe, 2026-06-10): post-enrollment PreToolUse deny (JSON +
# exit-2) and `updatedInput` mutation are confirmed headless, but the guard is not
# comprehensive -- it exists only in trust-enrolled homes, malformed hook output FAILS
# OPEN (Codex honors an `allow` and ignores unknown/`continue` fields), and
# PermissionRequest has not been observed firing headless. "full" is reserved for a
# comprehensive, fail-closable guard (Claude Code).
PolicyEnforcement = Literal["full", "partial", "none"]

# Native-hook support. "enrollment_gated" covers Codex: hooks are real and fire both
# headless AND interactively, but only after a one-time interactive trust enrollment in
# the TUI (round-2 probe 2026-06-10: enrolled headless fires 40c2/40d, interactive fires
# 50c; untrusted hooks: 0 firings under `codex exec` across every surface, incl.
# --dangerously-bypass-hook-trust -- headless cannot self-enroll). Distinct from "gated",
# which stays reserved for "real but needs a minimum CLI version" (the gate lives in
# ``hook_min_version``) -- Codex meets the version floor yet untrusted hooks still do not
# fire; the gate is trust enrollment, not the version. ``hook_feature_flag`` is recorded
# only when a config flag is *also* required; Codex hooks are default-on (``codex_hooks``
# is a deprecated alias of ``hooks`` -- still works, do not author it), so that field is
# None.
HookSupport = Literal["full", "gated", "enrollment_gated", "none"]

# Where a runtime's usage/token figures come from.
# ``json_stats`` was removed with the Gemini CLI runtime; no supported runtime
# currently reports through that mechanism.
UsageSource = Literal["transcript_proxy", "jsonl_events"]


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


@dataclass(frozen=True)
class RuntimeSpec:
    """Capabilities of one agent runtime. Read via :data:`RUNTIMES` / :func:`get_runtime`."""

    id: str  # "claude_code" | "codex"
    display_name: str
    headless_cmd: tuple[str, ...]  # ("claude","-p") | ("codex","exec")
    detect: Callable[[], str | None]  # best-effort version probe; None if undetermined
    interactive: InteractiveSupport
    headless: bool
    native_hooks: HookSupport
    pretool_policy: PolicyEnforcement
    usage_source: UsageSource
    native_resume: bool
    # Forge extension/session participation scopes, not per-feature runtime-hook targets.
    install_scopes: tuple[str, ...]  # empty = not Forge-managed
    curated_transfer_in: bool  # can accept a context doc at session start
    curated_transfer_out: bool  # can generate a curation of its own transcript
    # Hook registration/enablement floor (None when ungated): a preflight checks these
    # instead of parsing the human ``note``. ``hook_min_version`` is the version where
    # hooks register and enable without extra config -- it is NOT a firing guarantee
    # (Codex meets the floor yet stays ``enrollment_gated``: untrusted hooks do not
    # fire). ``hook_feature_flag`` is recorded only when a config flag is *also*
    # required.
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
# Claude Code is fully populated; Codex declares its *limits* as capability values
# (not omissions), so a consumer never mistakes a gap for parity.
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
        interactive="default",  # Forge-managed interactive sessions shipped -- codex_frontend Phase 5
        headless=True,
        native_hooks="enrollment_gated",  # fire headless + interactive once trust-enrolled; enrollment is a guided one-time TUI ceremony (Phase 1: trusted_hash not black-box computable, so no programmatic pre-enrollment)
        hook_min_version="0.131.0",  # registration/enablement floor (default-on); NOT a firing guarantee -- see native_hooks
        hook_feature_flag=None,  # hooks default-on (no gate); codex_hooks is a deprecated alias -- do not author it
        pretool_policy="partial",  # Phase 1 probe: deny + updatedInput confirmed post-enrollment; partial -- enrollment-gated, malformed output fails open, PermissionRequest unpinned (see PolicyEnforcement)
        usage_source="jsonl_events",
        native_resume=True,  # codex exec resume, by thread_id; works cross-CWD (Phase 6 probe, 0.138.0)
        # Forge extension/session assets support every install scope. Codex runtime
        # hook registration is narrower: user scope writes $CODEX_HOME/config.toml;
        # project/local installs write no runtime hook block.
        install_scopes=("user", "project", "local"),
        curated_transfer_in=True,  # initial user message is the zero-setup default; SessionStart additionalContext delivery is probe-confirmed in enrolled homes (Phase 1 30e PASS; build is codex_frontend Phase 4)
        curated_transfer_out=True,  # via headless invoker
        note=(
            "Hooks are default-on (`[features] hooks`, Codex CLI >= 0.131.0); `codex_hooks` is a deprecated "
            "alias (still works -- do not author new config with it). Hooks fire once trust-enrolled: the "
            "codex_frontend probes (codex-cli 0.138.0, 2026-06-10: scripts/experiments/codex-hooks/) "
            "confirmed trust-enrolled hooks fire under headless `codex exec` and interactively, across the "
            "event set -- SessionStart (incl. additionalContext delivery), PreToolUse deny + `updatedInput` "
            "mutation, Stop block-once, UserPromptSubmit block. Untrusted hooks do NOT fire under "
            "`codex exec` -- 0 firings across all registration surfaces, with "
            "`--dangerously-bypass-hook-trust`; headless cannot self-enroll. Enrollment is a guided one-time "
            "interactive TUI ceremony (one 'trust all' grant enrolls every entry in that registration): the "
            "`[hooks.state]` trusted_hash covers the registration *command string* (not the script bytes) "
            "and is not black-box computable, so Forge cannot pre-enroll programmatically. Trust is keyed by "
            "the registering config's path. The installer registers Forge's two hooks "
            "(`codex-session-start`, `codex-policy-check`) as a managed block only in the user Codex config "
            "(`$CODEX_HOME/config.toml`, so one ceremony covers all projects). Project/local extension "
            "installs write no Codex runtime block; per-project managed blocks are legacy migration inputs, "
            "not a supported target. Registration alone is inert: enrollment is still "
            "the user's one-time interactive trust ceremony, which the installer names but cannot perform; "
            "`forge runtime preflight codex --verify-enrollment` can verify firing afterward. Caveats: malformed PreToolUse "
            "output FAILS OPEN (never rely on Codex fail-closing "
            "on bad hook output); PermissionRequest has not been observed firing headless; PreToolUse "
            "matchers must use Codex tool names (`Bash`, `apply_patch`). Registration validation is shallow "
            "-- bogus event names load silently (the installer validates event names itself). Enterprise "
            "`allow_managed_hooks_only` (requirements.toml) "
            "can suppress user/project hooks regardless of enrollment. Codex emits the Responses API "
            "(custom-provider `wire_api=chat` removed ~Feb 2026); a proxy fronting Codex must serve "
            "Responses on its Codex-facing endpoint (backend may be translated)."
        ),
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
