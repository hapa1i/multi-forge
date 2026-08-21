"""Structural invariants for the Forge CLI command tree.

Mechanical guards for the `cli_style_guidelines.md` rules that are checkable by
walking the Click tree (group depth, leaf naming, `--json` scripting contract).

Each ``*_ALLOWLIST`` is a debt ledger of pre-existing violations or an explicitly
documented temporary exception. Every check asserts both that no *unrecorded*
violation appears and that no allowlisted entry has been fixed without being
removed, so an exception cannot silently rot after its command shape changes.
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


# Hidden internal-worker groups are exempt. ``forge workspace`` has one read leaf because
# ``status`` requires root-scoped telemetry identity; a placeholder must not satisfy this rule.
SINGLE_LEAF_GROUP_ALLOWLIST: set[str] = {"forge workspace"}


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


def test_workspace_group_shape_and_no_alias() -> None:
    tree = dict(_tree())
    group = tree.get("forge workspace")

    assert isinstance(group, click.Group)
    assert _visible_subcommands(group) == ["worktrees"]
    bare = CliRunner().invoke(main, ["workspace"])
    assert bare.exit_code == 2
    assert "worktrees" in bare.output
    assert CliRunner().invoke(main, ["ws"]).exit_code == 2


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


# Treat `report`, `profiles`, and `diff` as read leaves alongside list, show, and status.
_READ_LEAVES = {"catalog", "list", "report", "show", "status", "profiles", "diff"}
JSON_MISSING_ALLOWLIST: set[str] = set()


def test_read_leaves_expose_json() -> None:
    violations = set()
    for path, cmd in _tree():
        if isinstance(cmd, click.Group) or getattr(cmd, "hidden", False):
            continue
        if path.split()[-1] in _READ_LEAVES and not _json_dests(cmd):
            violations.add(path)
    _assert_ledger(violations, JSON_MISSING_ALLOWLIST, "read leaf should expose --json")


def test_memory_passport_upgrade_is_a_reachable_mutation_leaf() -> None:
    tree = dict(_tree())
    command = tree.get("forge memory passport upgrade")

    assert command is not None
    assert not isinstance(command, click.Group)
    assert not _json_dests(command), "mutating upgrade leaf should not expose --json"


# Editable config objects share a core verb set. Lifecycle resources follow the sibling-verbs rule instead.
# This guard covers the mandatory core and ensures that `proxy` and `model backend` do not expose `reset`.
# Optional verbs and exception rationale remain review-only; see cli_style_guidelines.md.
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


# A `clean` leaf previews by default and mutates only with `--yes`; `--dry-run` is redundant.
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


# Use one confirmation-bypass flag name across the CLI. `forge session reset`
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


# Removed aliases must fail through Click's native "No such command" path while canonical names still resolve.
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
