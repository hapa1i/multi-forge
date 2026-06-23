"""Structural invariants for the Forge CLI command tree.

Mechanical guards for the `cli_style_guidelines.md` rules that are checkable by
walking the Click tree (group depth, leaf naming, `--json` scripting contract).

Each ``*_ALLOWLIST`` is a debt ledger of pre-existing violations tracked by
``docs/board/proposed/forge_cli_cleanup/card.md``. Every check asserts both that
no *new* violation appears and that no allowlisted entry has been *fixed without
being removed* -- so the ledger can only shrink, never silently grow or rot.
"""

from __future__ import annotations

import click

from forge.cli.main import main


def _walk(cmd: click.Command, path: list[str]):
    """Yield ``(path, command)`` for the command and, recursively, its subtree."""
    yield path, cmd
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            yield from _walk(sub, path + [name])


def _tree() -> list[tuple[str, click.Command]]:
    return [(" ".join(path), cmd) for path, cmd in _walk(main, ["forge"])]


def _visible_subcommands(group: click.Group) -> list[str]:
    return [name for name, sub in group.commands.items() if not getattr(sub, "hidden", False)]


def _json_dests(cmd: click.Command) -> list[str]:
    return [p.name for p in cmd.params if isinstance(p, click.Option) and "--json" in p.opts and p.name is not None]


def _assert_ledger(violations: set[str], allowlist: set[str], rule: str) -> None:
    """Fail on new violations or on allowlisted entries that no longer violate."""
    new = violations - allowlist
    fixed = allowlist - violations
    assert not new, f"{rule}: new violation(s) not allowed: {sorted(new)}"
    assert not fixed, f"{rule}: these were fixed -- remove them from the allowlist: {sorted(fixed)}"


# --- Rule: read surfaces bind `--json` to dest `as_json` ----------------------
# Pre-existing `json_output` dests; normalize to `as_json` under the cleanup card.
JSON_DEST_ALLOWLIST = {
    "forge proxy create",
    "forge proxy metrics",
    "forge policy check",
    "forge policy supervisor",
    "forge workflow list-models",
    "forge workflow panel",
    "forge workflow analyze",
    "forge workflow debate",
    "forge workflow consensus",
}


def test_json_option_dest_is_as_json() -> None:
    violations = {
        path
        for path, cmd in _tree()
        if not isinstance(cmd, click.Group)
        for dest in _json_dests(cmd)
        if dest != "as_json"
    }
    _assert_ledger(violations, JSON_DEST_ALLOWLIST, "--json must bind dest `as_json`")


# --- Rule: a group earns a path segment only with >=2 visible leaves ----------
# Hidden groups (internal workers) are exempt. Pre-existing single-leaf groups:
SINGLE_LEAF_GROUP_ALLOWLIST = {
    "forge provider",  # -> trace (single child); flatten to provider list|show|explain
    "forge policy shadow",  # -> show (run is hidden)
    "forge memory report",  # -> show; flatten to a leaf
    # Phased, not flatten: the second leaf `start --proxy` is parked until the Responses
    # transport ships (card forge_codex_command_group, Phase 4). Remove this when it lands.
    "forge codex",
}


def test_no_single_leaf_groups() -> None:
    violations = set()
    for path, cmd in _tree():
        if not isinstance(cmd, click.Group) or getattr(cmd, "hidden", False):
            continue
        if path == "forge":
            continue
        if len(_visible_subcommands(cmd)) == 1:
            violations.add(path)
    _assert_ledger(violations, SINGLE_LEAF_GROUP_ALLOWLIST, "group needs >=2 visible leaves")


# --- Rule: no confusable sibling leaves (prefix collision / long shared prefix)
SHARED_PREFIX_MIN = 6


def _confusable(a: str, b: str) -> bool:
    if a.startswith(b) or b.startswith(a):
        return True
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return common >= SHARED_PREFIX_MIN


# Pre-existing confusable pair; resolved by renaming the supervisor one-shot leaf.
LEAF_NAMING_ALLOWLIST = {
    "forge policy: supervise|supervisor",
}


def test_no_confusable_sibling_leaves() -> None:
    # Hidden groups host internal handler names (e.g. `forge hook codex-*`) that
    # users never tab-complete, so confusability there is not a UX hazard.
    violations = set()
    for path, cmd in _tree():
        if not isinstance(cmd, click.Group) or getattr(cmd, "hidden", False):
            continue
        leaves = sorted(_visible_subcommands(cmd))
        for i, a in enumerate(leaves):
            for b in leaves[i + 1 :]:
                if _confusable(a, b):
                    violations.add(f"{path}: {a}|{b}")
    _assert_ledger(violations, LEAF_NAMING_ALLOWLIST, "sibling leaves must not be confusable")


# --- Rule: read leaves (list/show/status) expose `--json` for scripting -------
_READ_LEAVES = {"list", "show", "status"}
# Pre-existing read surfaces with no `--json`; each needs an explicit raw-vs-json
# decision per cleanup-card finding #4.
JSON_MISSING_ALLOWLIST = {
    "forge authentication status",
    "forge backend show",
    "forge proxy template list",
    "forge proxy template show",
    "forge claude preset show",
    "forge config show",
    "forge memory shadows show",
    "forge memory report show",
    "forge search status",
}


def test_read_leaves_expose_json() -> None:
    violations = set()
    for path, cmd in _tree():
        if isinstance(cmd, click.Group) or getattr(cmd, "hidden", False):
            continue
        if path.split()[-1] in _READ_LEAVES and not _json_dests(cmd):
            violations.add(path)
    _assert_ledger(violations, JSON_MISSING_ALLOWLIST, "read leaf should expose --json")
