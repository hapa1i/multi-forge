"""Tests for the hidden handoff CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from forge.cli.handoff import handoff
from forge.session.models import (
    DesignatedDoc,
    HandoffConfig,
    MemoryIntent,
    create_session_state,
)
from forge.session.passport import synthesize_passport, write_passport
from forge.session.project_memory import (
    ProjectAutoUpdateConfig,
    ProjectMemoryConfig,
    write_project_memory_config,
)
from forge.session.store import SessionStore


def _write_handoff_session(worktree: Path, *, subprocess_proxy: str | None = None) -> None:
    manifest = create_session_state("session")
    manifest.intent.subprocess_proxy = subprocess_proxy
    manifest.intent.memory = MemoryIntent(auto_update=HandoffConfig(enabled=True))
    SessionStore(str(worktree), "session").write(manifest)


def test_handoff_run_uses_manifest_subprocess_proxy(tmp_path: Path) -> None:
    """Detached handoff reads persisted subprocess proxy intent from the manifest."""
    _write_handoff_session(tmp_path, subprocess_proxy="openrouter-subprocess")

    with (
        patch("forge.session.handoff_agent.resolve_handoff_base_url", return_value="http://proxy") as mock_resolve,
        patch("forge.session.handoff_agent.run_handoff_agent", return_value=True),
    ):
        result = CliRunner().invoke(
            handoff,
            [
                "run",
                "--session-name",
                "session",
                "--worktree-path",
                str(tmp_path),
                "--transcript-rel",
                "transcript.jsonl",
            ],
        )

    assert result.exit_code == 0, result.output
    assert mock_resolve.call_args.kwargs["subprocess_proxy"] == "openrouter-subprocess"


def test_handoff_run_prefers_marker_subprocess_proxy_snapshot(tmp_path: Path) -> None:
    """Stop-time marker proxy snapshot wins over later manifest edits."""
    _write_handoff_session(tmp_path, subprocess_proxy="manifest-proxy")

    with (
        patch("forge.session.handoff_agent.resolve_handoff_base_url", return_value="http://proxy") as mock_resolve,
        patch("forge.session.handoff_agent.run_handoff_agent", return_value=True),
    ):
        result = CliRunner().invoke(
            handoff,
            [
                "run",
                "--session-name",
                "session",
                "--worktree-path",
                str(tmp_path),
                "--transcript-rel",
                "transcript.jsonl",
                "--subprocess-proxy",
                "marker-proxy",
            ],
        )

    assert result.exit_code == 0, result.output
    assert mock_resolve.call_args.kwargs["subprocess_proxy"] == "marker-proxy"


# ---------------------------------------------------------------------------
# Project-scoped activation + scan
# ---------------------------------------------------------------------------


def _write_plain_session(root: Path, name: str = "session") -> None:
    SessionStore(str(root), name).write(create_session_state(name))


def _write_session_with_docs(root: Path, docs: list[DesignatedDoc], name: str = "session") -> None:
    manifest = create_session_state(name)
    manifest.intent.memory = MemoryIntent(designated_docs=docs)
    SessionStore(str(root), name).write(manifest)


def _write_passport_doc(
    root, rel, *, strategy="generic", update_mode="direct", shadow_path=None, writers="all-sessions"
):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Body\n", encoding="utf-8")
    write_passport(
        path,
        synthesize_passport(strategy=strategy, update_mode=update_mode, shadow_path=shadow_path, writers=writers),
    )


def _enable_project(root: Path) -> None:
    write_project_memory_config(root, ProjectMemoryConfig(version=1, auto_update=ProjectAutoUpdateConfig(enabled=True)))


def _run(root: Path):
    return CliRunner().invoke(
        handoff,
        ["run", "--session-name", "session", "--worktree-path", str(root), "--transcript-rel", "transcript.jsonl"],
    )


def test_run_cmd_project_activation(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _write_plain_session(root)
    _enable_project(root)
    with (
        patch("forge.session.handoff_agent.resolve_handoff_base_url", return_value="http://proxy"),
        patch("forge.session.handoff_agent.run_handoff_agent", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    assert mock_run.called


def test_run_cmd_disabled_returns_early(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _write_plain_session(root)  # no project config, no session memory -> activation None
    with (
        patch("forge.session.handoff_agent.resolve_handoff_base_url", return_value="http://proxy"),
        patch("forge.session.handoff_agent.run_handoff_agent", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    assert not mock_run.called


def test_run_cmd_project_scans_docs(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _write_plain_session(root)
    _enable_project(root)
    _write_passport_doc(root, "docs/changelog.md", strategy="changelog")
    with (
        patch("forge.session.handoff_agent.resolve_handoff_base_url", return_value="http://proxy"),
        patch("forge.session.handoff_agent.run_handoff_agent", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    docs = mock_run.call_args.kwargs["designated_docs"]
    assert [d.path for d in docs] == ["docs/changelog.md"]


def test_run_cmd_session_docs_win_collision(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _write_session_with_docs(root, [DesignatedDoc(path="docs/changelog.md", strategy="checklist")])
    _enable_project(root)
    _write_passport_doc(root, "docs/changelog.md", strategy="changelog")
    with (
        patch("forge.session.handoff_agent.resolve_handoff_base_url", return_value="http://proxy"),
        patch("forge.session.handoff_agent.run_handoff_agent", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    docs = mock_run.call_args.kwargs["designated_docs"]
    assert len(docs) == 1
    assert docs[0].strategy == "checklist"  # session wins over scanned "changelog"


def test_run_cmd_shadow_collision_dedup(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    shadow = ".forge/memory/suggested_official.md"
    _write_session_with_docs(root, [DesignatedDoc(path=shadow, strategy="suggested", shadows="docs/official.md")])
    _enable_project(root)
    _write_passport_doc(root, "docs/official.md", strategy="suggested", update_mode="shadow-only", shadow_path=shadow)
    with (
        patch("forge.session.handoff_agent.resolve_handoff_base_url", return_value="http://proxy"),
        patch("forge.session.handoff_agent.run_handoff_agent", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    docs = mock_run.call_args.kwargs["designated_docs"]
    # Same (passport_source, write_path) -> deduped to one entry.
    assert len(docs) == 1
    assert docs[0].shadows == "docs/official.md"
