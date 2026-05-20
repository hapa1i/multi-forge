"""CLI command for forge info (global installation information).

The info command remains at top-level for quick diagnostics.
Other installation lifecycle commands have moved to `forge extensions` group.
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from forge.core.paths import display_path

from .tracking import TrackingStore

console = Console()


# --- Info Command ---


@click.command("info")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--sessions", "-s", "max_sessions", default=5, help="Max recent sessions to show")
def info_cmd(as_json: bool, max_sessions: int) -> None:
    """Show global Forge installation information.

    Displays comprehensive system status including:
    - Forge and Claude Code versions
    - Active session
    - Tracked installations
    - Registered proxies
    - Recent sessions

    \b
    Examples:
        forge info              # Full dashboard
        forge info --json       # JSON output for scripting
        forge info --sessions 10  # Show more recent sessions
    """
    info_data = _gather_info_data(max_sessions)

    if as_json:
        console.print_json(data=info_data)
        return

    _print_info_human(info_data)


def _gather_info_data(max_sessions: int) -> dict:
    """Gather all info data into a dict (for both JSON and human output)."""
    import shutil
    import subprocess

    from .models import parse_installation_key

    data: dict = {}

    # Forge info
    try:
        from importlib.metadata import version

        data["forge_version"] = version("multi-forge")
    except Exception:
        data["forge_version"] = "unknown"

    from forge.core.paths import get_forge_home

    data["forge_home"] = str(get_forge_home())

    # Claude Code info
    claude_path = shutil.which("claude")
    data["claude_code"] = {
        "path": claude_path,
        "version": None,
    }
    if claude_path:
        try:
            result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version_str = result.stdout.strip()
                if " (Claude Code)" in version_str:
                    version_str = version_str.replace(" (Claude Code)", "")
                data["claude_code"]["version"] = version_str
        except Exception:
            pass

    # Python/uv versions
    try:
        import sys

        data["python_version"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    except Exception:
        data["python_version"] = "unknown"

    try:
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            uv_ver = result.stdout.strip().replace("uv ", "")
            # Strip git hash suffix if present (e.g., "0.6.14 (a4cec56dc 2025-04-09)")
            if " (" in uv_ver:
                uv_ver = uv_ver.split(" (")[0]
            data["uv_version"] = uv_ver
    except Exception:
        data["uv_version"] = "unknown"

    # Installations
    tracking = TrackingStore()
    try:
        manifest = tracking.read()
    except Exception as e:
        data["tracking_file"] = str(tracking.path)
        data["tracking_error"] = str(e)
        data["installations"] = []
        data["proxies"] = []
        data["sessions"] = []
        return data
    data["tracking_file"] = str(tracking.path)
    data["installations"] = []
    for key, inst in manifest.installations.items():
        scope, project_path = parse_installation_key(key)
        data["installations"].append(
            {
                "key": key,
                "scope": scope,
                "project_path": project_path,
                "profile": inst.profile,
                "mode": inst.mode,
                "files_count": len(inst.files),
                "settings_count": len(inst.settings_entries),
            }
        )

    # Proxies
    data["proxies"] = []
    try:
        from forge.proxy.proxies import ProxyRegistryStore

        proxy_store = ProxyRegistryStore()
        proxy_registry = proxy_store.read()
        for proxy_id, proxy_entry in proxy_registry.proxies.items():
            data["proxies"].append(
                {
                    "proxy_id": proxy_id,
                    "base_url": proxy_entry.base_url,
                    "template": proxy_entry.template,
                }
            )
    except Exception:
        pass

    # Recent sessions
    data["sessions"] = []
    try:
        from forge.session import SessionManager

        manager = SessionManager()
        sessions = manager.list_sessions(include_incognito=False)
        for name, entry in sessions[:max_sessions]:
            data["sessions"].append(
                {
                    "name": name,
                    "worktree": entry.worktree_path,
                    "last_accessed": entry.last_accessed_at,
                }
            )
    except Exception:
        pass

    return data


def _print_info_human(data: dict) -> None:
    """Print info in human-readable format."""
    # Header
    console.print("\n[bold cyan]Forge Info[/bold cyan]")
    console.print("[cyan]" + "─" * 50 + "[/cyan]")

    # System info
    console.print("\n[bold]System[/bold]")
    console.print(f"  Forge:        {data.get('forge_version', 'unknown')}")
    console.print(f"  Install Path: {display_path(data.get('forge_home', 'unknown'))}")

    cc = data.get("claude_code", {})
    if cc.get("version"):
        cc_info = cc["version"]
    elif cc.get("path"):
        cc_info = f"at {display_path(cc['path'])}"
    else:
        cc_info = "[dim]not found[/dim]"
    console.print(f"  Claude Code:  {cc_info}")

    console.print(f"  Python:       {data.get('python_version', 'unknown')}")
    console.print(f"  uv:           {data.get('uv_version', 'unknown')}")

    # Tracking errors (e.g., stale pre-OSS manifest)
    if "tracking_error" in data:
        console.print("\n[bold red]Tracking Error[/bold red]")
        console.print(f"  {data['tracking_error']}")

    # Installations
    installations = data.get("installations", [])
    console.print(f"\n[bold]Installations[/bold] ({len(installations)})")
    if installations:
        table = Table(
            show_header=True,
            header_style="bold",
            box=None,
            expand=False,
            padding=(0, 1),
        )
        table.add_column("SCOPE", width=8)
        table.add_column("PATH", overflow="fold", no_wrap=False)
        table.add_column("PROFILE", width=10)
        table.add_column("MODE", width=8)

        for inst in installations:
            raw_path = inst.get("project_path")
            path_display = display_path(raw_path) if raw_path else "[dim]~/.claude[/dim]"
            table.add_row(
                inst.get("scope", ""),
                path_display,
                inst.get("profile", ""),
                inst.get("mode", ""),
            )
        console.print(table)
    else:
        console.print("  [dim](none)[/dim]")

    # Proxies
    proxies = data.get("proxies", [])
    console.print(f"\n[bold]Proxies[/bold] ({len(proxies)})")
    if proxies:
        table = Table(
            show_header=True,
            header_style="bold",
            box=None,
            expand=False,
            padding=(0, 1),
        )
        table.add_column("PROXY ID", width=25)
        table.add_column("TEMPLATE", width=20)
        table.add_column("BASE URL", overflow="fold")

        for proxy in proxies:
            table.add_row(
                proxy.get("proxy_id", ""),
                proxy.get("template") or "[dim]-[/dim]",
                proxy.get("base_url", ""),
            )
        console.print(table)
    else:
        console.print("  [dim](none)[/dim]")

    # Recent sessions
    sessions = data.get("sessions", [])
    console.print(f"\n[bold]Recent Sessions[/bold] ({len(sessions)} shown)")
    if sessions:
        table = Table(
            show_header=True,
            header_style="bold",
            box=None,
            expand=False,
            padding=(0, 1),
        )
        table.add_column("NAME", width=25)
        table.add_column("LAST ACCESSED", width=20)

        for sess in sessions:
            # Format timestamp
            last_accessed = sess.get("last_accessed", "")
            if last_accessed:
                # Truncate to date+time
                last_accessed = last_accessed[:19].replace("T", " ")
            table.add_row(sess.get("name", ""), last_accessed)
        console.print(table)
    else:
        console.print("  [dim](none)[/dim]")

    console.print()
