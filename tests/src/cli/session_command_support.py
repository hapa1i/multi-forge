"""Shared helpers for session CLI command tests."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock, _patch, patch

from forge.session import IndexStore, SessionStore, create_session_state
from tests.fixtures.session_state import publish_session

if TYPE_CHECKING:
    from forge.cli.session import ResolvedRouting


def successful_claude_launch() -> _patch[Mock]:
    """Patch Claude invocation for tests that only need a successful launch."""
    return patch("forge.core.ops.claude_session.invoke_claude", return_value=0)


def _publish_fork_parent(parent: Any, project_root: Path) -> IndexStore:
    """Publish a fork parent through the concrete stores used by preflight."""
    if (
        subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=project_root,
            capture_output=True,
            check=False,
        ).returncode
        != 0
    ):
        subprocess.run(["git", "init"], cwd=project_root, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project_root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=project_root, check=True)
        readme = project_root / "README.md"
        readme.write_text("# test\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project_root, check=True)
        subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "commit", "-m", "test"],
            cwd=project_root,
            capture_output=True,
            check=True,
        )

    index_store = IndexStore()
    worktree_root = Path(parent.worktree.path) if parent.worktree is not None else project_root
    forge_root = Path(parent.forge_root) if parent.forge_root else worktree_root
    forge_root.mkdir(parents=True, exist_ok=True)
    (forge_root / ".forge").mkdir(exist_ok=True)
    parent.forge_root = str(forge_root)
    try:
        relative_path = str(forge_root.relative_to(project_root)) or "."
    except ValueError:
        relative_path = "."
    publish_session(
        index_store,
        parent,
        project_root,
        checkout_root=project_root,
        forge_root=forge_root,
        relative_path=relative_path,
    )
    return index_store


def _configure_mock_fork_manager(mock_manager: Any, parent: Any, project_root: Path) -> None:
    """Back a narrow mutation mock with the concrete stores used by preflight."""
    mock_manager.index_store = _publish_fork_parent(parent, project_root)
    mock_manager.get_session.return_value = parent


def _iso_days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _seed_scoped_duplicate_sessions(project: Path) -> tuple[Path, Path]:
    index = IndexStore()

    forge_root_a = project
    forge_root_b = project / "nested-project"
    forge_root_b.mkdir(parents=True, exist_ok=True)

    worktree_a = project
    worktree_b = project / "nested-project-checkout"
    worktree_b.mkdir(parents=True, exist_ok=True)

    manifest_a = create_session_state(
        "shared",
        proxy_template="template-a",
        proxy_base_url="http://localhost:8101",
        worktree_path=str(worktree_a),
    )
    manifest_a.forge_root = str(forge_root_a)

    manifest_b = create_session_state(
        "shared",
        proxy_template="template-b",
        proxy_base_url="http://localhost:8102",
        worktree_path=str(worktree_b),
    )
    manifest_b.forge_root = str(forge_root_b)

    publish_session(
        index,
        manifest_a,
        project,
        forge_root=str(forge_root_a),
        checkout_root=str(worktree_a),
        relative_path=".",
    )
    publish_session(
        index,
        manifest_b,
        project,
        forge_root=str(forge_root_b),
        checkout_root=str(worktree_b),
        relative_path="nested-project",
    )

    return forge_root_a, forge_root_b


def _set_index_age(name: str, forge_root: Path, days: int) -> None:
    IndexStore().update_session(name, last_accessed_at=_iso_days_ago(days), forge_root=str(forge_root))


def _set_manifest_age(forge_root: Path, name: str, days: int) -> None:
    store = SessionStore(str(forge_root), name)

    def _mutate(state) -> None:
        state.last_accessed_at = _iso_days_ago(days)

    store.update(timeout_s=5.0, mutate=_mutate)


def _age_session(forge_root: Path, name: str, days: int) -> None:
    _set_index_age(name, forge_root, days)
    _set_manifest_age(forge_root, name, days)


def _read_session_manifest(forge_root: Path, name: str):
    return SessionStore(str(forge_root), name).read()


def _write_session_manifest(forge_root: Path, name: str, state) -> None:
    SessionStore(str(forge_root), name).write(state)


def _proxy_cfg(
    *,
    haiku: str = "openai/gpt-5.4-mini",
    sonnet: str = "openai/gpt-5.5",
    opus: str = "openai/gpt-5.5",
    default_tier: str = "sonnet",
):
    from forge.config.schema import ProxyInstanceConfig, TierModels

    return ProxyInstanceConfig(
        proxy_format=1,
        template="litellm-openai",
        template_digest="abc",
        provider="litellm",
        proxy_endpoint="http://localhost:8085",
        port=8085,
        upstream_base_url="https://litellm.example/v1",
        tiers=TierModels(haiku=haiku, sonnet=sonnet, opus=opus),
        default_tier=default_tier,
    )


def _proxy_routing(proxy_id: str = "openai-proxy") -> ResolvedRouting:
    from forge.cli.session import ResolvedRouting

    return ResolvedRouting(
        template="litellm-openai",
        base_url="http://localhost:8085",
        proxy_id=proxy_id,
    )


def _seed_cleanup_session(project: Path, forge_root: Path, name: str = "old-session") -> None:
    state = create_session_state(
        name,
        proxy_template="cleanup-template",
        proxy_base_url="http://localhost:8120",
        worktree_path=str(project),
    )
    state.forge_root = str(forge_root)
    publish_session(
        IndexStore(),
        state,
        project,
        forge_root=str(forge_root),
        checkout_root=str(project),
        relative_path=".",
    )
    _age_session(forge_root, name, 60)


def _seed_duplicate_list_sessions(project: Path) -> tuple[Path, Path]:
    forge_root_a, forge_root_b = _seed_scoped_duplicate_sessions(project)
    _age_session(forge_root_a, "shared", 60)
    _age_session(forge_root_b, "shared", 5)
    return forge_root_a, forge_root_b


class _BrokenActiveSessionStore:
    def list_sessions(self):
        raise RuntimeError("registry unreadable")
