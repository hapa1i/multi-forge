"""O029 regression: launch confirmation only tolerates missing-manifest updates."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.session import create_session_state
from forge.session.launch_confirmation import _infer_launch_confirmation

pytestmark = pytest.mark.regression


def _manifest_with_transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from forge.session.claude.paths import get_transcript_path

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    manifest = create_session_state("launched-session", worktree_path=str(project))
    manifest.forge_root = str(project)
    manifest.confirmed.claude_project_root = str(project)
    transcript = get_transcript_path(str(project), "launched-uuid")
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("{}\n", encoding="utf-8")
    return manifest


def test_o029_manifest_update_failure_does_not_escape_completed_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manifest = _manifest_with_transcript(tmp_path, monkeypatch)
    store = MagicMock()
    store.exists.return_value = True
    store.update.side_effect = OSError("manifest disk unavailable")

    with caplog.at_level(logging.DEBUG, logger="forge.session.launch_confirmation"):
        _infer_launch_confirmation(store=store, manifest=manifest, session_id="launched-uuid")

    assert "launch confirmation" in caplog.text.lower()
    assert "manifest disk unavailable" in caplog.text


def test_o029_transcript_path_failure_does_not_escape_completed_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manifest = _manifest_with_transcript(tmp_path, monkeypatch)
    manifest.confirmed.claude_project_root = None
    store = MagicMock()

    with (
        patch(
            "forge.session.claude.paths.resolve_claude_project_root",
            side_effect=OSError("transcript store unavailable"),
        ),
        caplog.at_level(logging.DEBUG, logger="forge.session.launch_confirmation"),
    ):
        _infer_launch_confirmation(store=store, manifest=manifest, session_id="launched-uuid")

    store.update.assert_not_called()
    assert "launch confirmation" in caplog.text.lower()
    assert "transcript store unavailable" in caplog.text


def test_o029_missing_transcript_remains_a_quiet_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    project = tmp_path / "project"
    project.mkdir()
    manifest = create_session_state("missing-transcript", worktree_path=str(project))
    manifest.confirmed.claude_project_root = str(project)
    store = MagicMock()

    _infer_launch_confirmation(store=store, manifest=manifest, session_id="missing-uuid")

    store.exists.assert_not_called()
    store.update.assert_not_called()
