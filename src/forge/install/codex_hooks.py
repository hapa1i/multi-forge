"""Codex hook registration (managed block in Codex config.toml).

Forge registers its Codex hooks through the user-scope dispatcher by appending
a marker-delimited TOML block to the Codex config:

- ``user``            -> ``$CODEX_HOME/config.toml`` (default ``~/.codex/config.toml``)
- ``project``/``local`` -> no managed hook block (runtime hooks are user-scope only)

codex-cli owns config.toml (model settings, project trust, comments), so Forge
never rewrites or normalizes it: merge appends or replaces only the managed
block, and the merged content is re-validated with tomllib before the atomic
write. Registration alone is inert -- Codex hooks fire only after the user's
one-time interactive trust ceremony, which the installer can neither perform
nor verify (the ``trusted_hash`` is not computable; see design.md §3.9).

Trust durability: Codex's ``trusted_hash`` covers the registration definition,
so the rendered entry bytes (command strings, shape) must stay stable across
Forge versions -- changing them silently invalidates existing enrollment.
"""

from __future__ import annotations

import shutil
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from forge.core.runtime.codex_rollouts import codex_home
from forge.core.state import atomic_write_text

from .exceptions import ForgeInstallError
from .hook_dispatcher import render_dispatcher_command
from .hooks import forge_hook_handler
from .models import InstallScope

# The 10 Codex lifecycle events (probe-pinned, codex-cli 0.138.0+). Codex
# loads bogus event names silently, so the installer validates them itself.
CODEX_HOOK_EVENTS = frozenset(
    {
        "SessionStart",
        "SubagentStart",
        "PreToolUse",
        "PostToolUse",
        "PermissionRequest",
        "PreCompact",
        "PostCompact",
        "UserPromptSubmit",
        "SubagentStop",
        "Stop",
    }
)

# Marker lines must stay byte-stable forever: block detection (merge, remove,
# status) keys on them across Forge versions.
CODEX_BLOCK_BEGIN = "# >>> forge hooks >>>"
CODEX_BLOCK_END = "# <<< forge hooks <<<"

CODEX_CONFIG_FILENAME = "config.toml"

CodexRegistrationKey = tuple[str, str, str]


@dataclass(frozen=True)
class CodexHookEntry:
    """One hook registration in the managed block.

    The rendered bytes of an entry are part of Codex's trust hash -- keep
    ``command`` strings and the rendered shape stable across versions.
    """

    event: str
    command: str
    timeout: int = 60
    matcher: str | None = None


def get_builtin_codex_entries() -> tuple[CodexHookEntry, ...]:
    """Return the Forge-managed Codex hook registrations.

    PreToolUse registers with NO matcher: the hook adapter itself filters
    apply_patch vs Bash (probe: tool names are "Bash"/"apply_patch";
    matcher="shell" never fired).
    """
    return (
        CodexHookEntry(
            event="SessionStart",
            command=render_dispatcher_command("codex-session-start"),
        ),
        CodexHookEntry(event="PreToolUse", command=render_dispatcher_command("codex-policy-check")),
    )


def validate_codex_events(entries: tuple[CodexHookEntry, ...]) -> None:
    """Reject unknown event names at plan time.

    Codex's registration validation is shallow -- bogus event names load
    silently and the hook just never fires, so this is the only typo guard.

    Raises:
        ForgeInstallError: If any entry uses an unknown event name.
    """
    unknown = sorted({e.event for e in entries} - CODEX_HOOK_EVENTS)
    if unknown:
        raise ForgeInstallError(
            f"unknown Codex hook event name(s): {', '.join(unknown)}. "
            f"Known events: {', '.join(sorted(CODEX_HOOK_EVENTS))}"
        )


def get_codex_config_path(scope: InstallScope, project_root: Path | None = None) -> Path:
    """Map a Forge install scope to its Codex config target.

    Codex has no settings.local analog, so PROJECT and LOCAL both target the
    one per-project config file.

    Raises:
        ValueError: If project_root is required but not provided.
    """
    if scope == InstallScope.USER:
        return codex_home() / CODEX_CONFIG_FILENAME
    if project_root is None:
        raise ValueError(f"project_root required for {scope.value} scope")
    return project_root / ".codex" / CODEX_CONFIG_FILENAME


def _toml_str(value: str) -> str:
    """Render a TOML basic string."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_codex_block(entries: tuple[CodexHookEntry, ...]) -> str:
    """Render the managed block (probe-pinned nested array-of-tables shape).

    Entry rendering is deterministic from the entries alone, so an unchanged
    entry renders to unchanged bytes across versions (trust preserved).
    """
    lines: list[str] = [
        CODEX_BLOCK_BEGIN,
        "# Managed by 'forge extension enable'. Do not edit: Codex trust enrollment",
        "# hashes these definitions; any change silently disables the hooks.",
    ]
    for i, entry in enumerate(entries):
        if i:
            lines.append("")
        lines.append(f"[[hooks.{entry.event}]]")
        if entry.matcher is not None:
            lines.append(f"matcher = {_toml_str(entry.matcher)}")
        lines.append(f"[[hooks.{entry.event}.hooks]]")
        lines.append('type = "command"')
        lines.append(f"command = {_toml_str(entry.command)}")
        lines.append(f"timeout = {entry.timeout}")
    lines.append(CODEX_BLOCK_END)
    return "\n".join(lines) + "\n"


def _split_block(text: str) -> tuple[str, str, str] | None:
    """Split config text into (before, block, after) around the managed block.

    Returns None when no BEGIN marker exists.

    Raises:
        ForgeInstallError: If a BEGIN marker exists without an END marker
            (a half-deleted block; merging blind would duplicate entries).
    """
    lines = text.splitlines(keepends=True)
    begin_idx: int | None = None
    end_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if begin_idx is None and stripped == CODEX_BLOCK_BEGIN:
            begin_idx = i
        elif begin_idx is not None and stripped == CODEX_BLOCK_END:
            end_idx = i
            break
    if begin_idx is None:
        return None
    if end_idx is None:
        raise ForgeInstallError(
            f"Codex config has a '{CODEX_BLOCK_BEGIN}' marker without a closing "
            f"'{CODEX_BLOCK_END}' marker. Repair or remove the partial block first."
        )
    before = "".join(lines[:begin_idx])
    block = "".join(lines[begin_idx : end_idx + 1])
    after = "".join(lines[end_idx + 1 :])
    return before, block, after


def _collect_registrations(parsed: dict[str, Any]) -> set[tuple[str, str]]:
    """Collect (event, command) registration pairs from a parsed config.

    Dedupe identity must match Codex's own registration identity (event ->
    command entry), not bare command strings: a Forge command under the wrong
    (or bogus -- Codex loads those silently) event is not a working
    registration and must not satisfy dedupe. Only ``type = "command"``
    entries count. Matchers are deliberately ignored: a matcher'd entry still
    fires on overlapping events, so installing ours alongside it would
    double-fire -- the thing dedupe exists to prevent.
    """
    hooks = parsed.get("hooks")
    if not isinstance(hooks, dict):
        return set()
    found: set[tuple[str, str]] = set()
    for event, event_entries in hooks.items():
        if not isinstance(event_entries, list):
            continue
        for entry in event_entries:
            if not isinstance(entry, dict):
                continue
            inner = entry.get("hooks")
            if not isinstance(inner, list):
                continue
            for hook in inner:
                if isinstance(hook, dict) and hook.get("type") == "command" and isinstance(hook.get("command"), str):
                    found.add((str(event), hook["command"]))
    return found


def _command_identity(command: str) -> tuple[str, str]:
    handler = forge_hook_handler(command)
    if handler is not None:
        return "forge-hook", handler
    return "command", command


def codex_registration_key(event: str, command: str) -> CodexRegistrationKey:
    """Return the logical Codex hook registration identity for an event/command."""

    kind, value = _command_identity(command)
    return event, kind, value


def codex_expected_registration_keys(
    entries: tuple[CodexHookEntry, ...],
) -> set[CodexRegistrationKey]:
    """Return logical registration keys for Forge-managed Codex hook entries."""

    return {codex_registration_key(e.event, e.command) for e in entries}


def _collect_registration_keys(parsed: dict[str, Any]) -> set[CodexRegistrationKey]:
    return {codex_registration_key(event, command) for event, command in _collect_registrations(parsed)}


def _collect_commands_by_key(
    parsed: dict[str, Any],
) -> dict[CodexRegistrationKey, set[str]]:
    commands: dict[CodexRegistrationKey, set[str]] = {}
    for event, command in _collect_registrations(parsed):
        commands.setdefault(codex_registration_key(event, command), set()).add(command)
    return commands


def _collect_forge_commands(parsed: dict[str, Any]) -> tuple[str, ...]:
    """Return all logical Forge hook commands, regardless of event/handler."""

    return tuple(
        sorted(command for _event, command in _collect_registrations(parsed) if forge_hook_handler(command) is not None)
    )


def _format_registration_keys(
    keys: set[CodexRegistrationKey],
    entries: tuple[CodexHookEntry, ...],
    commands_by_key: dict[CodexRegistrationKey, set[str]] | None = None,
) -> list[str]:
    expected = {codex_registration_key(e.event, e.command): e.command for e in entries}
    formatted: list[str] = []
    for key in sorted(keys):
        event, kind, value = key
        commands = sorted((commands_by_key or {}).get(key, {expected.get(key, f"{kind}:{value}")}))
        formatted.append(f"{event}: {', '.join(commands)}")
    return formatted


def _structure_conflict(parsed: dict[str, Any], events: set[str]) -> str | None:
    """Return a reason when appending array-of-tables entries cannot parse.

    A user config that defines ``hooks`` (or ``hooks.<event>``) as a non-array
    value makes any ``[[hooks.<event>]]`` append a TOML error.
    """
    hooks = parsed.get("hooks")
    if hooks is None:
        return None
    if not isinstance(hooks, dict):
        return "'hooks' is not a table"
    for event in sorted(events):
        existing = hooks.get(event)
        if existing is not None and not isinstance(existing, list):
            return f"'hooks.{event}' is not an array of tables"
    return None


@dataclass(frozen=True)
class CodexMergePlan:
    """Planned outcome for merging the managed block into one config file.

    action: "install" | "update" | "skip" | "conflict".
    """

    action: str
    config_path: str
    reason: str | None = None


def plan_codex_merge(config_path: Path, entries: tuple[CodexHookEntry, ...]) -> CodexMergePlan:
    """Decide what merging the managed block into config_path would do.

    Never modifies the file. Conflicts are returned (not raised) so the
    installer can surface them through the normal plan/conflict flow.
    """
    validate_codex_events(entries)
    path_str = str(config_path)

    if not config_path.is_file():
        return CodexMergePlan(action="install", config_path=path_str)

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as e:
        return CodexMergePlan(action="conflict", config_path=path_str, reason=f"cannot read: {e}")

    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        return CodexMergePlan(
            action="conflict",
            config_path=path_str,
            reason=f"existing config is not valid TOML: {e}",
        )

    try:
        split = _split_block(text)
    except ForgeInstallError as e:
        return CodexMergePlan(action="conflict", config_path=path_str, reason=str(e))

    block = render_codex_block(entries)
    if split is not None:
        return (
            CodexMergePlan(action="skip", config_path=path_str, reason="already installed")
            if split[1] == block
            else CodexMergePlan(action="update", config_path=path_str)
        )

    if reason := _structure_conflict(parsed, {e.event for e in entries}):
        return CodexMergePlan(action="conflict", config_path=path_str, reason=reason)

    # No managed block: dedupe against manually registered Forge hooks, by
    # (event, command) registration identity -- a command under the wrong
    # event is not a working registration and must not satisfy dedupe.
    ours = codex_expected_registration_keys(entries)
    present = _collect_registration_keys(parsed) & ours
    if present == ours:
        return CodexMergePlan(
            action="skip",
            config_path=path_str,
            reason="already registered outside Forge markers (manual registration kept)",
        )
    if present:
        commands_by_key = _collect_commands_by_key(parsed)
        present_strs = _format_registration_keys(present, entries, commands_by_key)
        missing = _format_registration_keys(ours - present, entries)
        return CodexMergePlan(
            action="conflict",
            config_path=path_str,
            reason=(
                f"partially registered outside Forge markers ({', '.join(present_strs)}); "
                f"installing would duplicate it. Remove the manual entries or register "
                f"{', '.join(missing)} manually."
            ),
        )

    return CodexMergePlan(action="install", config_path=path_str)


def _get_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def get_codex_backup_path(config_path: Path, timestamp: str | None = None) -> Path:
    """Backup path mirroring the settings pattern: .config.toml.forge.backup.{ts}."""
    ts = timestamp or _get_timestamp()
    return config_path.parent / f".{config_path.name}.forge.backup.{ts}"


def backup_codex_config(config_path: Path) -> Path | None:
    """Copy config.toml aside before the first modification (None if absent)."""
    if not config_path.is_file():
        return None
    backup_path = get_codex_backup_path(config_path)
    shutil.copy2(config_path, backup_path)
    return backup_path


def apply_codex_merge(config_path: Path, entries: tuple[CodexHookEntry, ...]) -> Path | None:
    """Install or update the managed block. Returns the backup path (if any).

    Caller is expected to have planned first; this re-checks cheaply and
    no-ops on "skip". The merged content is parse-validated before writing,
    so a failure leaves the original file untouched.

    Raises:
        ForgeInstallError: On a conflict plan or post-merge validation failure.
    """
    plan = plan_codex_merge(config_path, entries)
    if plan.action == "skip":
        return None
    if plan.action == "conflict":
        raise ForgeInstallError(f"Codex config conflict at {config_path}: {plan.reason}")

    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    block = render_codex_block(entries)

    split = _split_block(text)
    if split is not None:
        before, _, after = split
        new_text = before + block + after
    else:
        before = text
        if before and not before.endswith("\n"):
            before += "\n"
        if before.strip():
            before += "\n"  # one blank line between user content and the block
        new_text = before + block

    try:
        merged = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as e:
        raise ForgeInstallError(
            f"merging Forge hooks into {config_path} would produce invalid TOML " f"({e}); file left unmodified"
        ) from e
    missing_regs = codex_expected_registration_keys(entries) - _collect_registration_keys(merged)
    if missing_regs:
        missing_strs = _format_registration_keys(missing_regs, entries)
        raise ForgeInstallError(
            f"post-merge validation failed for {config_path}: "
            f"{', '.join(missing_strs)} not present; file left unmodified"
        )

    backup_path = backup_codex_config(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config_path, new_text, preserve_existing_mode=True)
    return backup_path


@dataclass(frozen=True)
class CodexRemoveResult:
    """Outcome of removing the managed block.

    leftover_commands: Forge commands found OUTSIDE the markers -- user-owned
    (moved or manually registered); warned about, never touched.
    """

    removed: bool
    deleted_file: bool = False
    leftover_commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodexRemovePlan:
    """Strict migration plan for removing one managed Codex block."""

    action: str
    config_path: str
    reason: str | None = None
    leftover_commands: tuple[str, ...] = ()


def plan_codex_remove(config_path: Path, entries: tuple[CodexHookEntry, ...]) -> CodexRemovePlan:
    """Plan strict migration removal without mutating ``config_path``.

    Unlike uninstall's best-effort path, migration refuses malformed TOML,
    partial markers, or matching manual registrations outside Forge's block.
    """

    validate_codex_events(entries)
    path_str = str(config_path)
    if not config_path.is_file():
        return CodexRemovePlan(action="skip", config_path=path_str, reason="config absent")

    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as e:
        return CodexRemovePlan(action="conflict", config_path=path_str, reason=f"cannot read: {e}")

    try:
        split = _split_block(text)
    except ForgeInstallError as e:
        return CodexRemovePlan(action="conflict", config_path=path_str, reason=str(e))

    remainder = text if split is None else split[0] + split[2]
    try:
        parsed = tomllib.loads(remainder)
    except tomllib.TOMLDecodeError as e:
        return CodexRemovePlan(
            action="conflict",
            config_path=path_str,
            reason=f"config outside the Forge block is not valid TOML: {e}",
        )

    leftover = _collect_forge_commands(parsed)
    if leftover:
        return CodexRemovePlan(
            action="conflict",
            config_path=path_str,
            reason="Forge hook commands remain outside the managed block",
            leftover_commands=leftover,
        )
    if split is None:
        return CodexRemovePlan(action="skip", config_path=path_str, reason="managed block absent")
    return CodexRemovePlan(action="remove", config_path=path_str)


def remove_codex_block(config_path: Path, entries: tuple[CodexHookEntry, ...]) -> CodexRemoveResult:
    """Remove the managed block from config_path (uninstall path).

    Only the marker block is removed; everything else is preserved. A file
    left whitespace-only is deleted (Forge created it). An unparseable file
    is still de-blocked textually -- uninstall must not strand the block.
    """
    if not config_path.is_file():
        return CodexRemoveResult(removed=False)

    text = config_path.read_text(encoding="utf-8")
    try:
        split = _split_block(text)
    except ForgeInstallError:
        split = None  # malformed block: leave for the user, but still report leftovers

    remainder = text if split is None else split[0] + split[2]
    try:
        parsed = tomllib.loads(remainder)
    except tomllib.TOMLDecodeError:
        parsed = {}
    leftover = _collect_forge_commands(parsed)

    if split is None:
        return CodexRemoveResult(removed=False, leftover_commands=leftover)

    before, _, after = split
    # Consume the single blank separator line install added before the block.
    if before.endswith("\n\n"):
        before = before[:-1]
    new_text = before + after

    if not new_text.strip():
        config_path.unlink()
        return CodexRemoveResult(removed=True, deleted_file=True, leftover_commands=leftover)

    atomic_write_text(config_path, new_text, preserve_existing_mode=True)
    return CodexRemoveResult(removed=True, leftover_commands=leftover)


@dataclass(frozen=True)
class CodexRegistrationStatus:
    """Read-only registration state for status surfaces."""

    config_path: str
    block_present: bool
    commands_registered: tuple[str, ...]


def read_codex_registration(config_path: Path, entries: tuple[CodexHookEntry, ...]) -> CodexRegistrationStatus:
    """Report whether the managed block / Forge commands are registered."""
    path_str = str(config_path)
    if not config_path.is_file():
        return CodexRegistrationStatus(config_path=path_str, block_present=False, commands_registered=())

    text = config_path.read_text(encoding="utf-8")
    try:
        split = _split_block(text)
    except ForgeInstallError:
        split = None
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        parsed = {}
    ours = codex_expected_registration_keys(entries)
    commands_by_key = _collect_commands_by_key(parsed)
    registered = tuple(sorted(command for key in ours for command in commands_by_key.get(key, set())))
    return CodexRegistrationStatus(
        config_path=path_str,
        block_present=split is not None,
        commands_registered=registered,
    )


def codex_registration_pairs(config_path: Path) -> set[tuple[str, str]]:
    """Return the ``(event, command)`` registration pairs in a Codex config (event-aware).

    Use ``codex_registration_keys`` for Forge-owned logical identity checks
    across legacy and dispatcher command bytes. Best-effort: a missing,
    unreadable, or invalid-TOML config yields an empty set (never raises).
    """
    if not config_path.is_file():
        return set()
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()
    return _collect_registrations(parsed)


def codex_registration_keys(config_path: Path) -> set[CodexRegistrationKey]:
    """Return logical Codex registration keys in a config (event + command identity)."""

    if not config_path.is_file():
        return set()
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()
    return _collect_registration_keys(parsed)
