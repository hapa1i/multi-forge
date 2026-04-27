"""Regression test for QA-033: fork --no-proxy from sidecar parent.

Bug: fork_session(direct=True) nulled the proxy intent but still inherited
the parent's launch intent (mode=sidecar). Launching the child hit the
direct/sidecar guard in session.py:514 with "Direct sessions are not
supported with --sidecar."

Root cause: manager.py inherited launch intent unconditionally after
clearing proxy intent for direct mode.

Fix: When direct=True, force launch.mode to host after inheriting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session.models import (
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
)

pytestmark = pytest.mark.regression


class TestForkDirectFromSidecarParent:
    """Verify fork --no-proxy overrides sidecar launch mode."""

    def test_direct_fork_forces_host_launch_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A direct fork from a sidecar parent must use host launch mode."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))

        from forge.session.index import IndexStore
        from forge.session.manager import SessionManager

        # Create parent with sidecar launch intent + proxy
        index = IndexStore()
        manager = SessionManager(index_store=index)

        worktree = tmp_path / "repo"
        worktree.mkdir()
        (worktree / ".claude").mkdir()
        (worktree / ".forge").mkdir()
        (worktree / ".git").mkdir()

        manager.start_session(
            name="sidecar-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(worktree),
            launch_mode=LAUNCH_MODE_SIDECAR,
        )
        # Simulate a confirmed Claude session (required for fork)
        from forge.session import SessionStore

        store = SessionStore(str(worktree), "sidecar-parent")
        state = store.read()
        state.confirmed.claude_session_id = "parent-uuid-123"
        store.write(state)

        # Fork with direct=True
        _parent_out, fork = manager.fork_session("sidecar-parent", "direct-child", direct=True)

        # Proxy intent must be None (direct mode)
        assert fork.intent.proxy is None

        # Launch mode must be host, not sidecar; inert sidecar payload cleared
        assert fork.intent.launch is not None
        assert fork.intent.launch.mode == LAUNCH_MODE_HOST
        assert fork.intent.launch.sidecar is None

        # Fork lineage preserved
        assert fork.is_fork is True
        assert fork.parent_session == "sidecar-parent"

    def test_direct_fork_from_host_parent_stays_host(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A direct fork from a host parent keeps host launch mode (no-op)."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))

        from forge.session.index import IndexStore
        from forge.session.manager import SessionManager

        index = IndexStore()
        manager = SessionManager(index_store=index)

        worktree = tmp_path / "repo"
        worktree.mkdir()
        (worktree / ".claude").mkdir()
        (worktree / ".forge").mkdir()
        (worktree / ".git").mkdir()

        manager.start_session(
            name="host-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(worktree),
        )
        from forge.session import SessionStore

        store = SessionStore(str(worktree), "host-parent")
        state = store.read()
        state.confirmed.claude_session_id = "parent-uuid-456"
        store.write(state)

        _parent_out, fork = manager.fork_session("host-parent", "direct-child", direct=True)

        assert fork.intent.proxy is None
        assert fork.intent.launch is not None
        assert fork.intent.launch.mode == LAUNCH_MODE_HOST

    def test_non_direct_fork_preserves_sidecar(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A normal (non-direct) fork from a sidecar parent keeps sidecar mode."""
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge"))
        monkeypatch.setenv("CLAUDE_HOME", str(tmp_path / "claude"))

        from forge.session.index import IndexStore
        from forge.session.manager import SessionManager

        index = IndexStore()
        manager = SessionManager(index_store=index)

        worktree = tmp_path / "repo"
        worktree.mkdir()
        (worktree / ".claude").mkdir()
        (worktree / ".forge").mkdir()
        (worktree / ".git").mkdir()

        manager.start_session(
            name="sidecar-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(worktree),
            launch_mode=LAUNCH_MODE_SIDECAR,
        )
        from forge.session import SessionStore

        store = SessionStore(str(worktree), "sidecar-parent")
        state = store.read()
        state.confirmed.claude_session_id = "parent-uuid-789"
        store.write(state)

        _parent_out, fork = manager.fork_session("sidecar-parent", "normal-child", direct=False)

        # Proxy inherited from parent
        assert fork.intent.proxy is not None
        assert fork.intent.proxy.template == "litellm-openai"

        # Sidecar launch mode preserved
        assert fork.intent.launch is not None
        assert fork.intent.launch.mode == LAUNCH_MODE_SIDECAR
