"""`forge session repair`: discover and re-index manifest-only session orphans.

Split from session.py like session_manage.py; session.py imports this module so
the command registers on the `session` group.
"""

from __future__ import annotations

import json
import sys
from typing import cast

import click

from forge.cli.output import err_console, print_error, print_error_with_tip, print_tip
from forge.cli.session import console, handle_session_error
from forge.cli.session import session as _session_untyped
from forge.core.ops.context import _cwd_forge_root
from forge.core.ops.session_context import BindingLookupError
from forge.core.ops.session_repair import (
    Classification,
    OrphanRecord,
    RepairApplyResult,
    RepairScanReport,
    repair_orphans,
    scan_repairable_orphans,
)
from forge.install.project_compat import (
    ProjectCompatibilityError,
    check_project_compatibility,
)
from forge.session import ForgeSessionError

session = cast(click.Group, _session_untyped)  # type: ignore[has-type]  # circular re-export

_CLASS_ORDER: tuple[Classification, ...] = (
    "repairable",
    "collision",
    "missing-worktree",
    "corrupt",
    "unreadable",
    "unrepairable",
)


@session.command("repair")
@click.option("--yes", is_flag=True, help="Apply the repairs (preview by default).")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def repair(yes: bool, as_json: bool) -> None:
    """Discover session manifests missing from the index and re-index them.

    \b
    Examples:
        forge session repair          # Report orphaned manifests in this project
        forge session repair --yes    # Re-index the repairable ones

    A session manifest with no index row is invisible to 'forge session list'
    but still owns its name and conversation. Previews by default; pass --yes
    to re-publish repairable manifests through the ordinary session-creation
    transaction. Scope is the current Forge project root.
    """
    forge_root = _cwd_forge_root()
    if forge_root is None:
        print_error_with_tip(
            "no Forge project found in the current directory.",
            "Run 'forge session repair' from a Forge project root (where .forge/ lives).",
            console=err_console,
        )
        sys.exit(1)

    try:
        report = scan_repairable_orphans(forge_root)
    except ForgeSessionError as e:
        handle_session_error(e)
        return
    except BindingLookupError as e:
        print_error(str(e), console=err_console)
        sys.exit(1)

    # A malformed/unreadable pin file raises here; the scan itself is read-only,
    # so preview degrades to reporting the pin problem instead of dying on it.
    compat_reason: str | None = None
    try:
        compat = check_project_compatibility(forge_root)
        if not compat.compatible:
            compat_reason = compat.reason
    except ProjectCompatibilityError as e:
        compat_reason = str(e)

    apply_result: RepairApplyResult | None = None
    apply_error: str | None = None
    if yes:
        try:
            apply_result = repair_orphans(forge_root, report.records)
        except ProjectCompatibilityError as e:
            apply_error = str(e)
        except ForgeSessionError as e:
            handle_session_error(e)
            return

    if as_json:
        _emit_json(report, compat_reason, apply_result, apply_error)
    else:
        _render(report, compat_reason, yes, apply_result, apply_error)

    if apply_error is not None:
        if not as_json:
            print_error(f"repair refused: {apply_error}", console=err_console)
        sys.exit(1)
    if apply_result is not None and not apply_result.clean:
        sys.exit(1)


def _emit_json(
    report: RepairScanReport,
    compat_reason: str | None,
    apply_result: RepairApplyResult | None,
    apply_error: str | None,
) -> None:
    payload = {
        "forge_root": report.forge_root,
        "compatibility": {"compatible": compat_reason is None, "reason": compat_reason},
        "records": [_record_payload(r) for r in report.records],
        "apply": (
            None
            if apply_result is None
            else {
                "repaired": list(apply_result.repaired),
                "refused": [{"name": i.name, "reason": i.reason} for i in apply_result.refused],
                "failed": [{"name": i.name, "reason": i.reason} for i in apply_result.failed],
            }
        ),
        "apply_error": apply_error,
    }
    click.echo(json.dumps(payload, indent=2))


def _record_payload(record: OrphanRecord) -> dict[str, object]:
    identity = record.identity
    return {
        "name": record.name,
        "classification": record.classification,
        "detail": record.detail,
        "manifest_dir": record.manifest_dir,
        "claude_session_id": record.claude_session_id,
        "codex_thread_id": record.codex_thread_id,
        "collision_holder": record.collision_holder,
        "identity": (
            None
            if identity is None
            else {
                "worktree_path": identity.worktree_path,
                "checkout_root": identity.checkout_root,
                "project_root": identity.project_root,
                "relative_path": identity.relative_path,
                "corrected_worktree_path": identity.corrected_worktree_path,
            }
        ),
    }


def _render(
    report: RepairScanReport,
    compat_reason: str | None,
    applied: bool,
    apply_result: RepairApplyResult | None,
    apply_error: str | None,
) -> None:
    if not report.records:
        console.print("[dim]No orphaned session manifests found.[/dim]")
        return

    counts = ", ".join(
        f"{len(group)} {classification}"
        for classification in _CLASS_ORDER
        if (group := report.by_classification(classification))
    )
    plural = "s" if len(report.records) != 1 else ""
    console.print(f"Found {len(report.records)} orphaned session manifest{plural} ({counts}):")
    for classification in _CLASS_ORDER:
        for record in report.by_classification(classification):
            console.print(f"  [bold]{record.name}[/bold]  [{_style(classification)}]{classification}[/]")
            console.print(f"    [dim]{record.detail}[/dim]")
            if record.classification == "missing-worktree":
                console.print(
                    f"    [dim]Recreate the worktree, or run 'forge session delete {record.name}' from"
                    f" {report.forge_root}[/dim]"
                )
            if record.classification == "unrepairable":
                console.print(f"    [dim]Run 'forge session delete {record.name}' from {report.forge_root}[/dim]")

    if compat_reason is not None and apply_error is None:
        console.print(f"[yellow]Apply would be refused by the project compatibility pin: {compat_reason}[/yellow]")

    if apply_result is not None:
        if apply_result.repaired:
            names = ", ".join(apply_result.repaired)
            console.print(f"Repaired {len(apply_result.repaired)}: {names}")
        for item in apply_result.refused:
            console.print(f"[yellow]Refused {item.name}: {item.reason}[/yellow]")
        for item in apply_result.failed:
            print_error(f"failed to repair {item.name}: {item.reason}", console=err_console)
    elif not applied:
        if report.by_classification("repairable"):
            print_tip("Use --yes to repair.", console=console)
        if report.by_classification("corrupt"):
            print_tip("Run 'forge clean' to remove corrupt manifests.", console=console)


def _style(classification: str) -> str:
    if classification == "repairable":
        return "green"
    if classification in ("collision", "corrupt"):
        return "red"
    return "yellow"
