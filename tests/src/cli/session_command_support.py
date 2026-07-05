"""Shared helpers for session CLI command tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, _patch, patch

from forge.session import IndexStore, SessionStore, create_session_state

if TYPE_CHECKING:
    from forge.cli.session import ResolvedRouting


def successful_claude_launch() -> _patch[Mock]:
    """Patch Claude invocation for tests that only need a successful launch."""
    return patch("forge.core.ops.claude_session.invoke_claude", return_value=0)


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
    SessionStore(str(forge_root_a), "shared").write(manifest_a)

    manifest_b = create_session_state(
        "shared",
        proxy_template="template-b",
        proxy_base_url="http://localhost:8102",
        worktree_path=str(worktree_b),
    )
    manifest_b.forge_root = str(forge_root_b)
    SessionStore(str(forge_root_b), "shared").write(manifest_b)

    index.add_session(
        name="shared",
        worktree_path=str(worktree_a),
        project_root=str(project),
        forge_root=str(forge_root_a),
        checkout_root=str(worktree_a),
        relative_path=".",
    )
    index.add_session(
        name="shared",
        worktree_path=str(worktree_b),
        project_root=str(project),
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
    SessionStore(str(forge_root), name).write(state)
    IndexStore().add_session(
        name=name,
        worktree_path=str(project),
        project_root=str(project),
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
