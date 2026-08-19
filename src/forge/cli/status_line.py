"""Thin Claude Code status-line command.

Reads one JSON document from stdin, acquires only the sources declared by the
resolved segment plan, and delegates presentation to ``forge.cli.statusline``.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys

import click

from forge.cli.statusline import formatting, rendering
from forge.cli.statusline import sources as status_sources

logger = logging.getLogger(__name__)


def _get_terminal_width() -> int:
    """Get terminal width when Claude Code pipes command stdout.

    Query the controlling terminal first, then fall back to ``COLUMNS`` and the
    conservative formatting default.
    """
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
        try:
            return os.get_terminal_size(fd).columns
        finally:
            os.close(fd)
    except (OSError, ValueError):
        pass
    return shutil.get_terminal_size(fallback=(formatting.DEFAULT_TERM_WIDTH, 24)).columns


@click.command(name="status-line", hidden=True)
def status_line() -> None:
    """Generate the Claude Code status line from one stdin JSON document."""
    # This high-frequency command configures logging itself instead of using the
    # main CLI bootstrap, matching the hook command boundary.
    from forge.core.logging import configure_debug_logging

    configure_debug_logging(component="status-line", subdirectory="cli")

    try:
        json_data = sys.stdin.read()
        if not json_data.strip():
            click.echo(f"{formatting.RED}[Error: No input]{formatting.RESET}", color=True)
            return
        data = json.loads(json_data)
    except json.JSONDecodeError:
        click.echo(f"{formatting.RED}[Error: Invalid JSON]{formatting.RESET}", color=True)
        return

    if not isinstance(data, dict):
        click.echo(f"{formatting.RED}[Error: Invalid input]{formatting.RESET}", color=True)
        return
    if not isinstance(data.get("workspace"), dict):
        data["workspace"] = {}

    logger.debug("env: FORGE_HOME=%s", os.environ.get("FORGE_HOME", "<unset>"))
    logger.debug("env: ANTHROPIC_BASE_URL=%s", os.environ.get("ANTHROPIC_BASE_URL", "<unset>"))
    logger.debug("env: FORGE_SESSION=%s", os.environ.get("FORGE_SESSION", "<unset>"))
    logger.debug("input keys: %s", list(data.keys()))
    logger.debug("workspace.current_dir: %s", data.get("workspace", {}).get("current_dir", "<missing>"))

    # Imports stay lazy so importing the command does not initialize the session
    # graph or config loader before Claude actually invokes this leaf.
    from forge.cli.statusline.context import RenderContext
    from forge.cli.statusline.registry import StatusSource, render_plan, resolve_plan
    from forge.runtime_config import get_runtime_config

    config = get_runtime_config()
    plan = resolve_plan(config.statusline.segments)
    logger.debug("status-line: required sources=%s", sorted(source.value for source in plan.sources))

    if StatusSource.PROXY in plan.sources:
        is_proxy, runtime, is_proxy_authoritative = status_sources.detect_proxy()
    else:
        is_proxy, runtime, is_proxy_authoritative = False, None, False

    logger.debug("proxy: is_proxy=%s, authoritative=%s", is_proxy, is_proxy_authoritative)
    if runtime:
        logger.debug("proxy: template=%s, tier_mappings=%s", runtime.template, runtime.tier_mappings)
    else:
        logger.debug("proxy: runtime=None")

    if StatusSource.SESSION in plan.sources:
        session_manifest, is_session_authoritative = status_sources.discover_session()
    else:
        session_manifest, is_session_authoritative = None, False
    session_name = session_manifest.get("name") if session_manifest else None
    logger.debug("session: name=%s, authoritative=%s", session_name, is_session_authoritative)
    logger.debug(
        "context_window raw: %s (type=%s)",
        data.get("context_window"),
        type(data.get("context_window")).__name__,
    )

    ctx = RenderContext(
        data=data,
        is_proxy=is_proxy,
        runtime=runtime,
        is_proxy_authoritative=is_proxy_authoritative,
        manifest=session_manifest,
        is_session_authoritative=is_session_authoritative,
        config=config,
        forge_root=os.environ.get("FORGE_FORGE_ROOT"),
    )
    where, stream = render_plan(ctx, plan)
    term_width = _get_terminal_width()
    output = rendering.render_output(
        where,
        stream,
        palette=ctx.palette,
        term_width=term_width,
        truncate=os.environ.get("FORGE_STATUS_TRUNCATE") != "0",
    )

    logger.debug(
        "output line_count=%d, visible_width=%d, term_width=%d",
        output.count("\n") + 1,
        formatting.visible_width(output.split("\n")[0]),
        term_width,
    )
    click.echo(output, color=True)
