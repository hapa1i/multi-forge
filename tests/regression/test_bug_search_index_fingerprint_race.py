"""Regression: search state must fingerprint the bytes written to the stores."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.workqueue import enqueue_index_marker
from forge.search.content_store import (
    HANDLER_LOCK_TIMEOUT_S,
    STORE_LOCK_TIMEOUT_S,
    ContentStore,
)
from forge.search.index_state import IndexStateStore

pytestmark = pytest.mark.regression


def _transcript(text: str, *, request_id: str) -> str:
    return (
        json.dumps(
            {
                "requestId": request_id,
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            },
            separators=(",", ":"),
        )
        + "\n"
    )


def _project_with_transcript(tmp_path: Path) -> tuple[Path, Path, str]:
    project_root = tmp_path / "project"
    (project_root / ".git").mkdir(parents=True)
    session_id = "fingerprint-race"
    transcript = project_root / ".forge" / "artifacts" / "planner" / "transcripts" / f"{session_id}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(_transcript("snapshot B", request_id="r-b"), encoding="utf-8")
    return project_root, transcript, session_id


def test_incremental_index_retains_marker_when_transcript_changes_during_store_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, transcript, session_id = _project_with_transcript(tmp_path)
    fingerprint_b = transcript.stat()
    marker = enqueue_index_marker(
        session_id=session_id,
        worktree_path=project_root,
        session_name="planner",
        transcript_snapshot_rel=str(transcript.relative_to(project_root)),
    )
    assert marker is not None

    real_add = ContentStore.add
    mutated = False

    def add_then_mutate(
        self: ContentStore,
        doc_key: str,
        content: str,
        *,
        timeout_s: float = HANDLER_LOCK_TIMEOUT_S,
    ) -> None:
        nonlocal mutated
        real_add(self, doc_key, content, timeout_s=timeout_s)
        if not mutated:
            transcript.write_text(_transcript("snapshot C is newer and longer", request_id="r-c"), encoding="utf-8")
            mutated = True

    monkeypatch.setattr(ContentStore, "add", add_then_mutate)

    first = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

    assert first.exit_code == 0, first.output
    assert marker.is_file(), "the in-flight marker must remain available to retry snapshot C"
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    assert marker_data["attempt_count"] == 1
    assert "changed while indexing" in marker_data["last_error"]

    key = str(transcript)
    assert "snapshot B" in ContentStore(forge_root=project_root).read_all()[key]
    indexed_b = IndexStateStore(forge_root=project_root).read().indexed_files[key]
    assert (indexed_b.mtime, indexed_b.size) == (fingerprint_b.st_mtime, fingerprint_b.st_size)
    assert indexed_b.size != transcript.stat().st_size

    monkeypatch.setattr(ContentStore, "add", real_add)
    retry = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

    assert retry.exit_code == 0, retry.output
    assert not marker.exists()
    assert "snapshot C" in ContentStore(forge_root=project_root).read_all()[key]
    indexed_c = IndexStateStore(forge_root=project_root).read().indexed_files[key]
    current = transcript.stat()
    assert (indexed_c.mtime, indexed_c.size) == (current.st_mtime, current.st_size)


def test_rebuild_state_describes_extracted_bytes_when_transcript_changes_during_store_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, transcript, _session_id = _project_with_transcript(tmp_path)
    fingerprint_b = transcript.stat()
    monkeypatch.chdir(project_root)

    real_replace_all = ContentStore.replace_all
    mutated = False

    def replace_then_mutate(
        self: ContentStore,
        content_map: dict[str, str],
        *,
        timeout_s: float = STORE_LOCK_TIMEOUT_S,
    ) -> None:
        nonlocal mutated
        real_replace_all(self, content_map, timeout_s=timeout_s)
        if not mutated:
            transcript.write_text(_transcript("snapshot C is newer and longer", request_id="r-c"), encoding="utf-8")
            mutated = True

    monkeypatch.setattr(ContentStore, "replace_all", replace_then_mutate)

    first = CliRunner().invoke(main, ["search", "rebuild-index"])

    assert first.exit_code == 0, first.output
    assert "changed while rebuilding" in first.output
    key = str(transcript)
    assert "snapshot B" in ContentStore(forge_root=project_root).read_all()[key]
    indexed_b = IndexStateStore(forge_root=project_root).read().indexed_files[key]
    assert (indexed_b.mtime, indexed_b.size) == (fingerprint_b.st_mtime, fingerprint_b.st_size)
    assert indexed_b.size != transcript.stat().st_size

    monkeypatch.setattr(ContentStore, "replace_all", real_replace_all)
    second = CliRunner().invoke(main, ["search", "rebuild-index"])

    assert second.exit_code == 0, second.output
    assert "snapshot C" in ContentStore(forge_root=project_root).read_all()[key]
    indexed_c = IndexStateStore(forge_root=project_root).read().indexed_files[key]
    current = transcript.stat()
    assert (indexed_c.mtime, indexed_c.size) == (current.st_mtime, current.st_size)
