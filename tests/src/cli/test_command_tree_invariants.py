"""Structural invariants for the Forge CLI command tree.

Mechanical guards for the `cli_style_guidelines.md` rules that are checkable by
walking the Click tree (group depth, leaf naming, `--json` scripting contract).

Each ``*_ALLOWLIST`` is a debt ledger of pre-existing violations tracked by
``docs/board/doing/forge_cli_cleanup/card.md``. Every check asserts both that
no *new* violation appears and that no allowlisted entry has been *fixed without
being removed* -- so the ledger can only shrink, never silently grow or rot.
"""

from __future__ import annotations

import click
from click.testing import CliRunner

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
# Drained in Slice 07 (forge_cli_cleanup): every read-surface `--json` now binds dest `as_json`.
JSON_DEST_ALLOWLIST: set[str] = set()


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
# Hidden groups (internal workers) are exempt. Drained empty by forge_cli_cleanup
# Slice 12: `forge policy shadow` gained a `status` leaf (now show + status visible).
SINGLE_LEAF_GROUP_ALLOWLIST: set[str] = set()


def test_no_single_leaf_groups() -> None:
    violations = set()
    for path, cmd in _tree():
        if not isinstance(cmd, click.Group) or getattr(cmd, "hidden", False):
            continue
        if path == "forge":
            continue
        if len(_visible_subcommands(cmd)) <= 1:
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


# Drained in Slice 10 (forge_cli_cleanup): `forge policy supervise` was removed and the
# one-shot `supervisor` leaf became the `supervisor` group, dissolving the collision.
LEAF_NAMING_ALLOWLIST: set[str] = set()


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


# --- Rule: read leaves (catalog/list/report/show/status/profiles/diff) expose `--json`
# `report` is here because `forge session memory report` was flattened from a
# `show` leaf in Slice 02; without it the read-surface debt would escape the guard.
# `profiles`/`diff` were added in Slice 07 once `auth profiles` and
# `session transfer diff` grew `--json` (the only previously-bare leaves with those names).
_READ_LEAVES = {"catalog", "list", "report", "show", "status", "profiles", "diff"}
# Drained in Slice 07 (forge_cli_cleanup): every read leaf now exposes `--json`.
JSON_MISSING_ALLOWLIST: set[str] = set()


def test_read_leaves_expose_json() -> None:
    violations = set()
    for path, cmd in _tree():
        if isinstance(cmd, click.Group) or getattr(cmd, "hidden", False):
            continue
        if path.split()[-1] in _READ_LEAVES and not _json_dests(cmd):
            violations.add(path)
    _assert_ledger(violations, JSON_MISSING_ALLOWLIST, "read leaf should expose --json")


# --- Rule: editable config objects expose the core {show, edit, reset} vocabulary
# Tiered decision (forge_cli_cleanup Slice 08 / D7): editable-config objects share a
# core verb set; lifecycle resources follow the sibling-verbs rule instead. This guard
# covers ONLY the mandatory core on the three editable-config objects, plus a boundary
# lock that `proxy`/`model backend` carry no `reset`. Optional verbs (`set`/`validate`)
# and the exception rationale are review-only (see cli_style_guidelines.md).
_EDITABLE_CONFIG_OBJECTS = ("forge config", "forge proxy template", "forge claude preset")
_CORE_CONFIG_VERBS = {"show", "edit", "reset"}


def test_editable_config_objects_share_core_verbs() -> None:
    tree = dict(_tree())
    for path in _EDITABLE_CONFIG_OBJECTS:
        group = tree.get(path)
        assert isinstance(group, click.Group), f"editable config object not a reachable group: {path!r}"
        missing = _CORE_CONFIG_VERBS - set(_visible_subcommands(group))
        assert not missing, f"{path}: editable config object missing core verb(s): {sorted(missing)}"

    # Boundary lock: `proxy` and `model backend` are deliberately NOT editable config
    # objects. The documented exception is "no `reset`"; if either grows one, force a
    # conscious doc update rather than silent drift.
    for path in ("forge proxy", "forge model backend"):
        group = tree.get(path)
        assert isinstance(group, click.Group), f"expected reachable group: {path!r}"
        assert "reset" not in _visible_subcommands(group), (
            f"{path} grew a `reset` verb -- if it is now an editable config object, add it to "
            f"_EDITABLE_CONFIG_OBJECTS and update cli_style_guidelines.md"
        )


# --- Rule: `clean` verbs preview by default and mutate only with --yes ---------
# Destructive decision (forge_cli_cleanup Slice 09 / F3): a `clean` leaf previews by
# default and mutates only with `--yes`. Preview-by-default makes `--dry-run` redundant,
# so a clean leaf must carry `--yes` and must NOT carry `--dry-run`. (`forge proxy clean`
# was removed as redundant in the same slice.)
def _option_dests(cmd: click.Command) -> set[str]:
    return {p.name for p in cmd.params if isinstance(p, click.Option) and p.name is not None}


def test_clean_verbs_preview_by_default() -> None:
    for path, cmd in _tree():
        if isinstance(cmd, click.Group) or getattr(cmd, "hidden", False):
            continue
        if path.split()[-1] != "clean":
            continue
        dests = _option_dests(cmd)
        assert "yes" in dests, f"{path}: clean leaf must expose --yes (preview is the default)"
        assert "dry_run" not in dests, f"{path}: clean leaf must not carry --dry-run (preview is already the default)"


# --- Rule: delete/reset leaves expose the --yes confirmation-bypass ------------
# One confirmation-bypass flag name across the CLI (Slice 09 / F3). `forge session reset`
# resets the session override layer (a persisted but non-deleting config rewind -- it
# removes no sessions, worktrees, or artifacts); it acts immediately by design and is the
# one permanent exemption.
_DESTRUCTIVE_PROMPT_VERBS = {"delete", "reset"}
_OVERRIDE_RESET_LEAVES = {"forge session reset"}


def test_destructive_prompt_verbs_use_yes() -> None:
    for path, cmd in _tree():
        if isinstance(cmd, click.Group) or getattr(cmd, "hidden", False):
            continue
        if path.split()[-1] not in _DESTRUCTIVE_PROMPT_VERBS or path in _OVERRIDE_RESET_LEAVES:
            continue
        assert "yes" in _option_dests(cmd), f"{path}: delete/reset leaf must expose the --yes confirmation-bypass"


# --- Rule: removed aliases are clean breaks, not tombstones --------------------
# forge_cli_cleanup Slice 05 (D6): `auth` is the canonical command name (the
# `authentication` alias is gone) and the `extensions` -> `extension` rename shim
# is removed. Both old paths -- bare group and a real old leaf -- must fail through
# Click's native "No such command", and the canonical names must still resolve.
_REMOVED_ALIAS_ARGVS = (
    ["authentication"],
    ["authentication", "status"],
    ["extensions"],
    ["extensions", "status"],
    ["hook", "enable"],
    ["hook", "disable"],
)
_CANONICAL_ALIAS_ARGVS = (
    ["auth", "--help"],
    ["extension", "--help"],
)


def test_removed_aliases_are_clean_breaks() -> None:
    runner = CliRunner()
    for argv in _REMOVED_ALIAS_ARGVS:
        result = runner.invoke(main, argv)
        joined = " ".join(argv)
        assert result.exit_code == 2, f"{joined!r} should be a clean break (exit 2), got {result.exit_code}"
        assert "No such command" in result.output, f"{joined!r} should fail with Click 'No such command'"


def test_canonical_command_names_resolve() -> None:
    runner = CliRunner()
    for argv in _CANONICAL_ALIAS_ARGVS:
        result = runner.invoke(main, argv)
        joined = " ".join(argv)
        assert result.exit_code == 0, f"{joined!r} should resolve (exit 0), got {result.exit_code}: {result.output}"
