"""Regression: memory shadow display must not read paths outside the Forge root.

Bug: legacy ``memory.designated_docs`` overrides could contain an absolute or
traversal shadow path. ``forge memory shadows show`` used to read that path
directly, allowing outside-root content to be printed.

Affected file: src/forge/cli/memory.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


def _seed_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from forge.session import IndexStore, SessionStore, create_session_state

    forge_root = tmp_path / "project"
    forge_root.mkdir()
    docs_dir = forge_root / "docs"
    docs_dir.mkdir()
    (docs_dir / "impl_notes.md").write_text("# Impl notes\n", encoding="utf-8")

    state = create_session_state(
        "s1",
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8085",
        worktree_path=str(forge_root),
    )
    state.forge_root = str(forge_root)
    SessionStore(str(forge_root), "s1").write(state)

    IndexStore().add_session(
        name="s1",
        worktree_path=str(forge_root),
        project_root=str(tmp_path),
        forge_root=str(forge_root),
        checkout_root=str(forge_root),
        relative_path=".",
        is_incognito=False,
        is_fork=False,
        parent_session=None,
    )

    monkeypatch.setenv("FORGE_SESSION", "s1")
    monkeypatch.chdir(forge_root)
    return forge_root


def test_memory_shadows_show_skips_absolute_legacy_shadow_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.session import set_session_override

    _seed_session(tmp_path, monkeypatch)
    outside = tmp_path / "outside-secret.md"
    outside.write_text("DO_NOT_PRINT\n", encoding="utf-8")

    ctx = ExecutionContext.from_cwd()
    payload = [{"path": str(outside), "strategy": "suggested", "shadows": "docs/impl_notes.md"}]
    set_session_override(ctx=ctx, session_name=None, key="memory.designated_docs", value_str=json.dumps(payload))

    result = CliRunner().invoke(main, ["memory", "shadows", "show", "--for", "docs/impl_notes.md"])

    assert result.exit_code == 0, result.output
    assert "DO_NOT_PRINT" not in result.output
    assert "Skipping unsafe shadow path" in result.output
    assert "No readable shadow proposals" in result.output
