"""CLI-owned derivation enrichment for derived sessions."""

from __future__ import annotations

from pathlib import Path

from forge.cli.session import _persist_fork_transfer_derivation
from forge.session.models import Derivation, create_session_state
from forge.session.store import SessionStore


def test_persist_fork_transfer_derivation_records_strategy_and_context(tmp_path: Path) -> None:
    """Worktree fork handoff metadata is persisted after the CLI creates context."""
    worktree = tmp_path / "child-worktree"
    worktree.mkdir()
    context = worktree / ".forge" / "handoff" / "child.md"
    context.parent.mkdir(parents=True)
    context.write_text("handoff\n")

    manifest = create_session_state(
        "child",
        parent_session="parent",
        is_fork=True,
        worktree_path=str(worktree),
    )
    manifest.forge_root = str(worktree)
    manifest.confirmed.derivation = Derivation(
        parent_session="parent",
        resume_mode="handoff",
        strategy=None,
        context_file=None,
    )
    SessionStore(str(worktree), "child").write(manifest)

    updated = _persist_fork_transfer_derivation(
        manifest=manifest,
        strategy="structured",
        context_path=context,
    )

    assert updated.confirmed.derivation is not None
    assert updated.confirmed.derivation.resume_mode == "handoff"
    assert updated.confirmed.derivation.strategy == "structured"
    assert updated.confirmed.derivation.context_file == ".forge/handoff/child.md"

    persisted = SessionStore(str(worktree), "child").read()
    assert persisted.confirmed.derivation is not None
    assert persisted.confirmed.derivation.strategy == "structured"
    assert persisted.confirmed.derivation.context_file == ".forge/handoff/child.md"
