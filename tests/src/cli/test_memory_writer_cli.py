"""Tests for the hidden memory-writer CLI (forge memory-writer run)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from forge.cli.memory_writer import memory_writer
from forge.session.consumer_lanes import set_intent_lane
from forge.session.memory_writer import MEMORY_WRITER_CONSUMER
from forge.session.models import (
    LaneRecord,
    MemoryIntent,
    MemoryWriterConfig,
    create_session_state,
)
from forge.session.passport import synthesize_passport, write_passport
from forge.session.store import SessionStore

_CLAUDE_MAX = LaneRecord("claude_code", "claude-max", "opus")


def _write_handoff_session(worktree: Path, *, subprocess_proxy: str | None = None) -> None:
    manifest = create_session_state("session")
    manifest.intent.subprocess_proxy = subprocess_proxy
    manifest.intent.memory = MemoryIntent(auto_update=MemoryWriterConfig(enabled=True))
    SessionStore(str(worktree), "session").write(manifest)


def test_handoff_run_uses_manifest_subprocess_proxy(tmp_path: Path) -> None:
    """Detached handoff reads persisted subprocess proxy intent from the manifest."""
    _write_handoff_session(tmp_path, subprocess_proxy="openrouter-subprocess")

    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy") as mock_resolve,
        patch("forge.session.memory_writer.run_memory_writer", return_value=True),
    ):
        result = CliRunner().invoke(
            memory_writer,
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
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy") as mock_resolve,
        patch("forge.session.memory_writer.run_memory_writer", return_value=True),
    ):
        result = CliRunner().invoke(
            memory_writer,
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


def _run(root: Path):
    return CliRunner().invoke(
        memory_writer,
        ["run", "--session-name", "session", "--worktree-path", str(root), "--transcript-rel", "transcript.jsonl"],
    )


def test_run_cmd_manifest_activation(tmp_path: Path) -> None:
    """Handoff runs when manifest has memory.auto_update.enabled=True."""
    root = tmp_path.resolve()
    _write_handoff_session(root)
    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy"),
        patch("forge.session.memory_writer.run_memory_writer", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    assert mock_run.called


def test_run_cmd_disabled_returns_early(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    _write_plain_session(root)  # no project config, no session memory -> activation None
    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy"),
        patch("forge.session.memory_writer.run_memory_writer", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    assert not mock_run.called


def test_run_cmd_scans_passported_docs(tmp_path: Path) -> None:
    """Handoff discovers docs via scan_passported_docs (not session doc lists)."""
    root = tmp_path.resolve()
    _write_handoff_session(root)
    _write_passport_doc(root, "docs/changelog.md", strategy="changelog")
    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy"),
        patch("forge.session.memory_writer.run_memory_writer", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    docs = mock_run.call_args.kwargs["designated_docs"]
    assert [d.path for d in docs] == ["docs/changelog.md"]


def test_run_cmd_passport_strategy_used(tmp_path: Path) -> None:
    """Scanned passport strategy is the only doc source (no session doc lists)."""
    root = tmp_path.resolve()
    _write_handoff_session(root)
    _write_passport_doc(root, "docs/changelog.md", strategy="changelog")
    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy"),
        patch("forge.session.memory_writer.run_memory_writer", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    docs = mock_run.call_args.kwargs["designated_docs"]
    assert len(docs) == 1
    assert docs[0].strategy == "changelog"  # passport strategy only


def _dispatching(**kwargs: object) -> bool:
    """Stand-in for run_memory_writer that ACTUALLY dispatches: invokes the on_dispatch hook."""
    on_dispatch = kwargs.get("on_dispatch")
    if callable(on_dispatch):
        on_dispatch()
    return True


def _declared_handoff_store(root: Path) -> SessionStore:
    manifest = create_session_state("session")
    manifest.intent.memory = MemoryIntent(auto_update=MemoryWriterConfig(enabled=True))
    set_intent_lane(manifest, MEMORY_WRITER_CONSUMER, _CLAUDE_MAX)
    store = SessionStore(str(root), "session")
    store.write(manifest)
    return store


def test_run_cmd_freezes_on_real_dispatch(tmp_path: Path) -> None:
    """When the writer actually dispatches (on_dispatch fires), the declared lane freezes and
    the same backend_id flows to the runner (the billing input)."""
    root = tmp_path.resolve()
    store = _declared_handoff_store(root)
    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy"),
        patch("forge.session.memory_writer.run_memory_writer", side_effect=_dispatching) as mock_run,
    ):
        result = _run(root)

    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["backend_id"] == "claude-max"
    confirmed = store.read().confirmed.consumer_lanes
    assert confirmed is not None and confirmed.memory_writer is not None
    assert confirmed.memory_writer.lane == _CLAUDE_MAX


def test_run_cmd_no_freeze_when_writer_skips(tmp_path: Path) -> None:
    """Declared lane, but the writer skips without dispatching (no on_dispatch, e.g.
    below-min-turns/no-docs): the lane must NOT freeze (Finding 1)."""
    root = tmp_path.resolve()
    store = _declared_handoff_store(root)
    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy"),
        # return_value=True without invoking on_dispatch == a skip path inside run_memory_writer.
        patch("forge.session.memory_writer.run_memory_writer", return_value=True),
    ):
        result = _run(root)

    assert result.exit_code == 0, result.output
    assert store.read().confirmed.consumer_lanes is None


def test_run_cmd_undeclared_lane_does_not_freeze(tmp_path: Path) -> None:
    """No declaration -> dispatched lane is None -> even a real dispatch never freezes; backend_id None."""
    root = tmp_path.resolve()
    _write_handoff_session(root)
    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy"),
        patch("forge.session.memory_writer.run_memory_writer", side_effect=_dispatching) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs["backend_id"] is None
    assert SessionStore(str(root), "session").read().confirmed.consumer_lanes is None


def test_run_cmd_shadow_doc_scanned(tmp_path: Path) -> None:
    """Shadow doc discovered via passport scan is passed through to the agent."""
    root = tmp_path.resolve()
    shadow = ".forge/memory/shadow_official.md"
    _write_handoff_session(root)
    _write_passport_doc(root, "docs/official.md", strategy="generic", update_mode="shadow-only", shadow_path=shadow)
    # Create the shadow file so scan_passported_docs can discover it
    (root / shadow).parent.mkdir(parents=True, exist_ok=True)
    (root / shadow).write_text("# Shadow\n", encoding="utf-8")
    with (
        patch("forge.session.memory_writer.resolve_writer_base_url", return_value="http://proxy"),
        patch("forge.session.memory_writer.run_memory_writer", return_value=True) as mock_run,
    ):
        result = _run(root)
    assert result.exit_code == 0, result.output
    docs = mock_run.call_args.kwargs["designated_docs"]
    assert len(docs) == 1
    assert docs[0].shadows == "docs/official.md"
