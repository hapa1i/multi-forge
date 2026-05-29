"""Memory writer CLI commands.

Commands:
- forge memory-writer run: Execute the memory writer for a session (background process)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import click

logger = logging.getLogger(__name__)


@click.group("memory-writer", hidden=True)
def memory_writer() -> None:
    """Manage memory writer operations."""


@memory_writer.command("run")
@click.option("--session-name", required=True, help="Forge session name")
@click.option(
    "--worktree-path",
    required=True,
    type=click.Path(exists=True),
    help="Absolute path to the worktree",
)
@click.option(
    "--transcript-rel",
    required=True,
    help="Repo-relative path to transcript artifact",
)
@click.option("--timeout", default=None, type=int, help="Max seconds for agent to run")
@click.option("--subprocess-proxy", default=None, hidden=True, help="Stop-time subprocess proxy snapshot")
@click.option("--root", "forge_root", default=None, type=click.Path(), hidden=True, help="Explicit Forge project root")
def run_cmd(
    session_name: str,
    worktree_path: str,
    transcript_rel: str,
    timeout: int | None,
    subprocess_proxy: str | None,
    forge_root: str | None,
) -> None:
    """Run the memory writer for a completed session.

    This is typically invoked by the work queue handler as a background process,
    not directly by users. It reads the session manifest, checks if memory is
    enabled, and spawns claude -p to update project memory documents.
    """
    worktree = Path(worktree_path).resolve()
    effective_root = Path(forge_root).resolve() if forge_root else worktree

    # We use SessionStore directly (not resolve_session_store) because this
    # runs as a detached background process without FORGE_SESSION env var set.
    # The marker payload carries session_name explicitly.
    try:
        from forge.session.effective import compute_effective_intent
        from forge.session.store import SessionStore

        store = SessionStore(str(effective_root), session_name)
        if not store.exists():
            logger.info("No session manifest for %s in %s", session_name, worktree)
            return

        manifest = store.read()
        effective = compute_effective_intent(manifest)
    except Exception as e:
        logger.warning("Failed to read session manifest for %s: %s", session_name, e)
        raise SystemExit(1)

    import dataclasses

    from forge.session.memory_writer import resolve_writer_base_url, run_memory_writer
    from forge.session.project_memory import (
        DEFAULT_SCAN_ROOTS,
        is_memory_enabled,
        scan_passported_docs,
    )

    if not is_memory_enabled(manifest, effective):
        logger.info("Memory writer not activated for session %s", session_name)
        return

    assert effective.memory is not None and effective.memory.auto_update is not None
    config = dataclasses.replace(effective.memory.auto_update, enabled=True)

    confirmed_proxy_url = None
    if manifest.confirmed.started_with_proxy:
        confirmed_proxy_url = manifest.confirmed.started_with_proxy.base_url

    base_url = resolve_writer_base_url(
        proxy_id=config.proxy,
        confirmed_proxy_base_url=confirmed_proxy_url,
        env_base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        direct=config.direct,
        subprocess_proxy=subprocess_proxy or effective.subprocess_proxy,
    )

    designated_docs = scan_passported_docs(effective_root, DEFAULT_SCAN_ROOTS, session_name)

    success = run_memory_writer(
        session_name=session_name,
        forge_root=effective_root,
        transcript_snapshot_rel=transcript_rel,
        config=config,
        base_url=base_url,
        timeout_seconds=timeout,
        designated_docs=designated_docs,
    )

    if not success:
        raise SystemExit(1)
