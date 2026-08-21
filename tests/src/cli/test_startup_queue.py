"""Tests for CLI startup queue processing.

These tests verify that non-exempt CLI commands (like `forge status`) trigger
pending-work queue processing, while exempt commands (like `forge hook`) skip it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

import forge.core.workqueue.queue as workqueue_queue
from forge.cli.main import _EXEMPT_SUBCOMMANDS, main
from forge.core.state import StateUnreadableError
from forge.core.workqueue import (
    MARKER_SCHEMA_VERSION,
    enqueue_index_marker,
    enqueue_shadow_marker,
    enqueue_stop_marker,
    pending_work_dir,
)

_REPO_ROOT = Path(__file__).parents[3]
_QUEUE_GUIDES = (
    _REPO_ROOT / "docs" / "end-user" / "memory.md",
    _REPO_ROOT / "docs" / "end-user" / "search.md",
)
_DOCUMENTED_EXEMPTIONS = re.compile(r"\((?P<commands>[^()]*) are exempt\)")


def _documented_exempt_subcommands(path: Path) -> frozenset[str]:
    matches = list(_DOCUMENTED_EXEMPTIONS.finditer(path.read_text(encoding="utf-8")))
    assert len(matches) == 1, f"Expected one startup-queue exemption clause in {path}"
    commands = matches[0].group("commands").replace(", and ", ",")
    return frozenset(command.strip(" `") for command in commands.split(","))


@pytest.mark.parametrize("guide", _QUEUE_GUIDES, ids=lambda path: path.stem)
def test_startup_queue_exemption_guides_match_runtime_constant(guide: Path) -> None:
    assert _documented_exempt_subcommands(guide) == _EXEMPT_SUBCOMMANDS


def _create_test_marker(tmp_path: Path, session_id: str = "test-marker-123") -> Path:
    """Create a valid pending-work marker for testing."""
    marker = enqueue_stop_marker(
        session_id=session_id,
        worktree_path=tmp_path,
        session_name="test-session",
        transcript_snapshot_rel=f".forge/artifacts/test-session/transcripts/{session_id}.jsonl",
    )
    assert marker is not None
    return marker


def _create_newer_marker(marker_id: str = "a-future") -> tuple[Path, bytes]:
    queue_dir = pending_work_dir()
    queue_dir.mkdir(parents=True, exist_ok=True)
    marker = queue_dir / f"{marker_id}.json"
    content = (
        json.dumps(
            {
                "schema_version": MARKER_SCHEMA_VERSION + 1,
                "kind": "future-kind",
                "marker_id": marker_id,
                "payload": {"future": [1, 2, 3]},
                "future_envelope_field": "preserve",
            },
            indent=4,
        )
        + "\n"
    ).encode()
    marker.write_bytes(content)
    return marker, content


class TestStartupQueueProcessing:
    """Tests for CLI startup queue processing behavior."""

    def test_forge_status_processes_queue(self, tmp_path: Path) -> None:
        """forge status (non-exempt) triggers pending-work processing and deletes markers."""
        marker = _create_test_marker(tmp_path)
        assert marker.is_file()

        runner = CliRunner()
        runner.invoke(main, ["extension", "status"])

        # Queue processing runs before command-specific validation, so the exit status is irrelevant here.
        assert not marker.is_file(), "Non-exempt command should process and delete pending-work markers"

    def test_forge_status_handles_empty_queue(self) -> None:
        """forge status handles empty queue gracefully (fast path)."""
        queue_dir = pending_work_dir()
        assert not queue_dir.exists()

        runner = CliRunner()
        result = runner.invoke(main, ["status"])

        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_sidecar_cli_leaves_host_queue_for_host_drain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marker = _create_test_marker(tmp_path)
        monkeypatch.setenv("FORGE_SIDECAR", "1")

        CliRunner().invoke(main, ["extension", "status"])

        assert marker.is_file(), "Sidecar commands must not consume host-path work markers"


class TestExemptSubcommands:
    """Tests that exempt subcommands skip queue processing."""

    def test_forge_hook_skips_queue(self, tmp_path: Path) -> None:
        """forge hook (exempt) does NOT process pending-work queue."""
        marker = _create_test_marker(tmp_path)
        assert marker.is_file()

        runner = CliRunner()
        # Send empty JSON to avoid parse errors
        runner.invoke(main, ["hook", "stop"], input="{}")

        assert marker.is_file(), "Exempt command (hook) should NOT process pending-work queue"

    def test_forge_status_line_skips_queue(self, tmp_path: Path) -> None:
        """forge status-line (exempt) does NOT process pending-work queue."""
        marker = _create_test_marker(tmp_path)
        assert marker.is_file()

        runner = CliRunner()
        runner.invoke(main, ["status-line"])

        assert marker.is_file(), "Exempt command (status-line) should NOT process pending-work queue"


class TestStartupQueueRobustness:
    """Tests for startup queue robustness (error handling)."""

    def test_corrupted_marker_does_not_crash_cli(self, tmp_path: Path) -> None:
        """Corrupted markers don't crash CLI startup and are moved to failed/."""
        queue_dir = pending_work_dir()
        queue_dir.mkdir(parents=True, exist_ok=True)

        corrupt_marker = queue_dir / "corrupted.json"
        corrupt_marker.write_text("not valid json")

        runner = CliRunner()
        result = runner.invoke(main, ["extension", "status"])

        assert result.exception is None or isinstance(result.exception, SystemExit)

        assert not corrupt_marker.is_file()
        assert (queue_dir / "failed" / "corrupted.json").is_file()

    def test_multiple_markers_processed(self, tmp_path: Path) -> None:
        """Multiple markers are processed by startup."""
        markers = []
        for i in range(3):
            marker = _create_test_marker(tmp_path, session_id=f"multi-{i}")
            markers.append(marker)

        assert all(m.is_file() for m in markers)

        runner = CliRunner()
        runner.invoke(main, ["extension", "status"])

        assert all(not m.is_file() for m in markers), "All valid markers should be processed"

    def test_unreadable_marker_warns_on_stderr_and_leaves_json_stdout_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        unreadable = _create_test_marker(tmp_path, session_id="a-unreadable")
        readable = _create_test_marker(tmp_path, session_id="z-readable")
        original_bytes = unreadable.read_bytes()
        real_read_json = workqueue_queue.read_json

        def read_with_transient_failure(path: Path) -> dict:
            if path == unreadable:
                raise StateUnreadableError(str(path), "simulated transient read failure")
            return real_read_json(path)

        monkeypatch.setattr(workqueue_queue, "read_json", read_with_transient_failure)

        result = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert result.exit_code == 0, result.output
        json.loads(result.stdout)
        assert "Warning:" in result.stderr
        assert "a-unreadable.json could not be read" in result.stderr
        assert unreadable.read_bytes() == original_bytes
        assert not readable.exists()

    def test_newer_schema_marker_warns_once_and_leaves_json_stdout_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(workqueue_queue, "_warned_newer_schema", False)
        newer, original = _create_newer_marker()
        current = _create_test_marker(tmp_path, session_id="z-current")

        first = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert first.exit_code == 0, first.output
        json.loads(first.stdout)
        assert first.stderr.count("Warning:") == 1
        assert "written by newer Forge" in first.stderr
        assert "Upgrade Forge" in first.stderr
        assert newer.read_bytes() == original
        assert not current.exists()
        assert not (pending_work_dir() / "failed" / newer.name).exists()

        second = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert second.exit_code == 0, second.output
        json.loads(second.stdout)
        assert "written by newer Forge" not in second.stderr
        assert newer.read_bytes() == original


def _create_index_marker_with_transcript(tmp_path: Path, session_id: str = "test-idx-123") -> Path:
    """Create a valid index marker AND its backing transcript file.

    The real index handler requires the transcript file to exist on disk.
    Creates a minimal .git dir so resolve_project_root finds the project root.
    """
    (tmp_path / ".git").mkdir(exist_ok=True)

    transcript_rel = f".forge/artifacts/test-session/transcripts/{session_id}.jsonl"
    transcript_abs = tmp_path / transcript_rel
    transcript_abs.parent.mkdir(parents=True, exist_ok=True)
    transcript_abs.write_text(
        '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
        '"message":{"role":"user","content":[{"type":"text","text":"hello"}]}}\n'
    )

    marker = enqueue_index_marker(
        session_id=session_id,
        worktree_path=tmp_path,
        session_name="test-session",
        transcript_snapshot_rel=transcript_rel,
    )
    assert marker is not None
    return marker


def _enqueue_existing_index_marker(tmp_path: Path, *, session_id: str) -> Path:
    marker = enqueue_index_marker(
        session_id=session_id,
        worktree_path=tmp_path,
        session_name="test-session",
        transcript_snapshot_rel=f".forge/artifacts/test-session/transcripts/{session_id}.jsonl",
    )
    assert marker is not None
    return marker


class TestIndexMarkerProcessing:
    """Tests for index marker processing during CLI startup."""

    def test_index_marker_deleted_on_startup(self, tmp_path: Path) -> None:
        """Index markers are processed and deleted by non-exempt CLI commands."""
        marker = _create_index_marker_with_transcript(tmp_path)
        assert marker.is_file()

        runner = CliRunner()
        runner.invoke(main, ["extension", "status"])

        assert not marker.is_file(), "Index marker should be deleted by startup processing"

    def test_both_stop_and_index_markers_processed(self, tmp_path: Path) -> None:
        """Both stop and index markers from the same session are processed."""
        stop_marker = _create_test_marker(tmp_path, session_id="dual-test")
        index_marker = _create_index_marker_with_transcript(tmp_path, session_id="dual-test")

        assert stop_marker.is_file()
        assert index_marker.is_file()

        runner = CliRunner()
        runner.invoke(main, ["extension", "status"])

        assert not stop_marker.is_file(), "Stop marker should be processed"
        assert not index_marker.is_file(), "Index marker should be processed"

    def test_exempt_command_skips_index_markers(self, tmp_path: Path) -> None:
        """Exempt commands (hook) do not process index markers."""
        marker = _create_index_marker_with_transcript(tmp_path)
        assert marker.is_file()

        runner = CliRunner()
        runner.invoke(main, ["hook", "stop"], input="{}")

        assert marker.is_file(), "Exempt command should not process index markers"

    def test_index_handler_creates_search_document(self, tmp_path: Path) -> None:
        """Index marker processing extracts and stores a search document."""
        _create_index_marker_with_transcript(tmp_path, session_id="doc-test")

        runner = CliRunner()
        runner.invoke(main, ["extension", "status"])

        from forge.search.store import SearchDocumentStore

        store = SearchDocumentStore(forge_root=tmp_path)
        docs = store.read()
        assert any(d.session_id == "doc-test" for d in docs)

    def test_metadata_unchanged_snapshot_skips_extraction_and_store_writes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session_id = "guard-unchanged"
        _create_index_marker_with_transcript(tmp_path, session_id=session_id)
        first = CliRunner().invoke(main, ["model", "backend", "list", "--json"])
        assert first.exit_code == 0, first.output

        index_dir = tmp_path / ".forge" / "search-index"
        store_paths = tuple(
            index_dir / name
            for name in (
                "documents.json",
                "bm25_index.json",
                "content.json",
                "state.json",
            )
        )
        before = {path: path.read_bytes() for path in store_paths}
        marker = _enqueue_existing_index_marker(tmp_path, session_id=session_id)

        def unexpected_work(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("metadata-unchanged snapshots must not be extracted or rewritten")

        import forge.search.extractor as extractor
        from forge.search.bm25_store import BM25IndexStore
        from forge.search.content_store import ContentStore
        from forge.search.store import SearchDocumentStore

        monkeypatch.setattr(extractor, "extract_document", unexpected_work)
        monkeypatch.setattr(SearchDocumentStore, "add", unexpected_work)
        monkeypatch.setattr(BM25IndexStore, "upsert_document", unexpected_work)
        monkeypatch.setattr(ContentStore, "add", unexpected_work)

        second = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert second.exit_code == 0, second.output
        assert not marker.exists()
        assert {path: path.read_bytes() for path in store_paths} == before

    def test_changed_snapshot_runs_full_upsert_and_refreshes_state(self, tmp_path: Path) -> None:
        session_id = "guard-changed"
        _create_index_marker_with_transcript(tmp_path, session_id=session_id)
        first = CliRunner().invoke(main, ["model", "backend", "list", "--json"])
        assert first.exit_code == 0, first.output

        transcript = tmp_path / f".forge/artifacts/test-session/transcripts/{session_id}.jsonl"
        transcript.write_text(
            '{"requestId":"r2","timestamp":"2026-01-01T00:01:00Z",'
            '"message":{"role":"user","content":[{"type":"text","text":"updated transcript"}]}}\n',
            encoding="utf-8",
        )
        marker = _enqueue_existing_index_marker(tmp_path, session_id=session_id)

        second = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert second.exit_code == 0, second.output
        assert not marker.exists()

        from forge.search.bm25_store import BM25IndexStore
        from forge.search.content_store import ContentStore
        from forge.search.index_state import IndexStateStore
        from forge.search.store import SearchDocumentStore

        key = str(transcript)
        assert "updated transcript" in ContentStore(forge_root=tmp_path).read_all()[key]
        assert SearchDocumentStore(forge_root=tmp_path).read()[0].session_id == session_id
        bm25_index = BM25IndexStore(forge_root=tmp_path).read()
        assert bm25_index is not None
        assert bm25_index.doc_keys == [key]
        state_entry = IndexStateStore(forge_root=tmp_path).read().indexed_files[key]
        assert state_entry.size == transcript.stat().st_size
        assert state_entry.mtime == transcript.stat().st_mtime

    def test_missing_state_entry_reindexes_metadata_unchanged_snapshot(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session_id = "guard-invalidated"
        _create_index_marker_with_transcript(tmp_path, session_id=session_id)
        first = CliRunner().invoke(main, ["model", "backend", "list", "--json"])
        assert first.exit_code == 0, first.output

        transcript = tmp_path / f".forge/artifacts/test-session/transcripts/{session_id}.jsonl"
        from forge.search.index_state import IndexStateStore

        state_store = IndexStateStore(forge_root=tmp_path)
        state = state_store.read()
        del state.indexed_files[str(transcript)]
        state_store.write(state)

        import forge.search.extractor as extractor

        real_extract = extractor.extract_document
        extracted: list[Path] = []

        def track_extract(
            transcript_path: Path,
            session_name: str,
            session_id: str,
            worktree_path: str,
        ) -> extractor.SearchDocument:
            extracted.append(transcript_path)
            return real_extract(
                transcript_path=transcript_path,
                session_name=session_name,
                session_id=session_id,
                worktree_path=worktree_path,
            )

        monkeypatch.setattr(extractor, "extract_document", track_extract)
        marker = _enqueue_existing_index_marker(tmp_path, session_id=session_id)

        second = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert second.exit_code == 0, second.output
        assert not marker.exists()
        assert extracted == [transcript]
        assert str(transcript) in state_store.read().indexed_files

    @pytest.mark.parametrize(
        ("state_contents", "error_fragment"),
        [
            pytest.param("not valid json", "invalid JSON", id="corrupt"),
            pytest.param('{"schema_version": 999, "indexed_files": {}}', "incompatible version", id="newer"),
        ],
    )
    def test_unusable_index_state_does_not_gate_search_store_writes(
        self,
        tmp_path: Path,
        state_contents: str,
        error_fragment: str,
    ) -> None:
        session_id = "guard-unusable-state"
        marker = _create_index_marker_with_transcript(tmp_path, session_id=session_id)
        transcript = tmp_path / f".forge/artifacts/test-session/transcripts/{session_id}.jsonl"
        index_dir = tmp_path / ".forge" / "search-index"
        index_dir.mkdir(parents=True)
        state_path = index_dir / "state.json"
        state_path.write_text(state_contents, encoding="utf-8")

        result = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert result.exit_code == 0, result.output
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        assert marker_data["attempt_count"] == 1
        assert error_fragment in marker_data["last_error"]
        assert state_path.read_text(encoding="utf-8") == state_contents

        from forge.search.content_store import ContentStore

        assert (index_dir / "documents.json").is_file()
        assert (index_dir / "bm25_index.json").is_file()
        assert str(transcript) in ContentStore(forge_root=tmp_path).read_all()

    def test_unreadable_index_state_does_not_gate_search_store_writes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session_id = "guard-unreadable-state"
        marker = _create_index_marker_with_transcript(tmp_path, session_id=session_id)
        transcript = tmp_path / f".forge/artifacts/test-session/transcripts/{session_id}.jsonl"
        index_dir = tmp_path / ".forge" / "search-index"
        state_path = index_dir / "state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text('{"schema_version": 1, "indexed_files": {}}', encoding="utf-8")

        from forge.search.exceptions import IndexStateUnreadableError
        from forge.search.index_state import IndexStateStore

        real_read = IndexStateStore.read

        def unreadable_state(store: IndexStateStore) -> object:
            if store.state_path == state_path:
                raise IndexStateUnreadableError(str(state_path), "permission denied")
            return real_read(store)

        monkeypatch.setattr(IndexStateStore, "read", unreadable_state)

        result = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert result.exit_code == 0, result.output
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        assert marker_data["attempt_count"] == 1
        assert "permission denied" in marker_data["last_error"]

        from forge.search.content_store import ContentStore

        assert (index_dir / "documents.json").is_file()
        assert (index_dir / "bm25_index.json").is_file()
        assert str(transcript) in ContentStore(forge_root=tmp_path).read_all()

    def test_failed_content_write_retries_without_marking_transcript_indexed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session_id = "guard-write-failure"
        marker = _create_index_marker_with_transcript(tmp_path, session_id=session_id)

        from forge.search.content_store import ContentStore

        def fail_content_write(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated content-store failure")

        monkeypatch.setattr(ContentStore, "add", fail_content_write)

        result = CliRunner().invoke(main, ["model", "backend", "list", "--json"])

        assert result.exit_code == 0, result.output
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        assert marker_data["attempt_count"] == 1
        assert marker_data["last_error"] == "handler error: simulated content-store failure"
        assert not (tmp_path / ".forge" / "search-index" / "state.json").exists()

    def test_incompatible_project_retries_without_search_writes(self, tmp_path: Path) -> None:
        marker = _create_index_marker_with_transcript(tmp_path, session_id="compat-refused")
        (tmp_path / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n',
            encoding="utf-8",
        )

        result = CliRunner().invoke(main, ["extension", "status"])

        assert result.exit_code == 0, result.output
        assert marker.is_file()
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        assert marker_data["attempt_count"] == 1
        assert "project compatibility refused (incompatible)" in marker_data["last_error"]
        assert "project.toml" in marker_data["last_error"]
        assert not (tmp_path / ".forge" / "search-index").exists()

        (tmp_path / ".forge" / "project.toml").unlink()
        CliRunner().invoke(main, ["extension", "status"])
        assert not marker.exists()

    def test_incompatible_project_marker_moves_to_failed_at_retry_limit(self, tmp_path: Path) -> None:
        marker = _create_index_marker_with_transcript(tmp_path, session_id="compat-poison")
        (tmp_path / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n',
            encoding="utf-8",
        )

        for _ in range(5):
            CliRunner().invoke(main, ["extension", "status"])

        assert not marker.exists()
        assert (pending_work_dir() / "failed" / marker.name).is_file()


class TestShadowMarkerCompatibility:
    def test_incompatible_project_retries_without_spawning_or_claiming_candidate(
        self,
        tmp_path: Path,
    ) -> None:
        candidate = tmp_path / ".forge" / "artifacts" / "session" / "shadow" / "candidate.json"
        candidate.parent.mkdir(parents=True)
        candidate.write_text("{}", encoding="utf-8")
        (tmp_path / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n',
            encoding="utf-8",
        )
        marker = enqueue_shadow_marker(
            session_id="shadow-compat",
            session_name="session",
            worktree_path=tmp_path,
            forge_root=str(tmp_path),
        )
        assert marker is not None

        from unittest.mock import patch

        with patch("subprocess.Popen") as mock_popen:
            result = CliRunner().invoke(main, ["extension", "status"])

        assert result.exit_code == 0, result.output
        mock_popen.assert_not_called()
        assert candidate.is_file()
        assert not candidate.with_suffix(".processing").exists()
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        assert marker_data["attempt_count"] == 1
        assert "project compatibility refused (incompatible)" in marker_data["last_error"]


class TestMemoryWriterRunIdentity:
    """The detached memory writer is re-rooted under the originating session."""

    def test_env_roots_under_origin(self) -> None:
        from forge.cli.main import _memory_writer_env

        env = _memory_writer_env({"origin_run_id": "run_C", "origin_root_run_id": "run_R"})
        assert env["FORGE_PARENT_RUN_ID"] == "run_C"
        assert env["FORGE_ROOT_RUN_ID"] == "run_R"
        assert env["FORGE_RUN_ID"].startswith("run_")
        assert env["FORGE_RUN_ID"] not in ("run_C", "run_R")

    def test_env_tolerates_partial_origin_marker(self) -> None:
        """Current markers write both origin ids; fallback is defensive only."""
        from forge.cli.main import _memory_writer_env

        env = _memory_writer_env({"origin_run_id": "run_C"})
        assert env["FORGE_PARENT_RUN_ID"] == "run_C"
        assert env["FORGE_ROOT_RUN_ID"] == "run_C"
        assert env["FORGE_RUN_ID"].startswith("run_")
        assert env["FORGE_RUN_ID"] != "run_C"

    def test_env_scrubs_drainer_identity_when_no_origin(self) -> None:
        """With no origin captured, the memory-writer must not inherit the drainer's run id."""
        from unittest.mock import patch

        from forge.cli.main import _memory_writer_env

        with patch.dict(
            "os.environ",
            {"FORGE_RUN_ID": "run_drainer", "FORGE_ROOT_RUN_ID": "run_drainer"},
        ):
            env = _memory_writer_env({})
        assert "FORGE_RUN_ID" not in env
        assert "FORGE_PARENT_RUN_ID" not in env
        assert "FORGE_ROOT_RUN_ID" not in env

    def test_env_scrubs_drainer_session_identity(self) -> None:
        """The writer must not inherit the drainer's SESSION identity either.

        A `forge` command draining the queue inside another active session would otherwise
        run the writer's claude -p child (hooks/status) under that drainer's session. The
        session vars are scrubbed unconditionally — even when the run-tree origin is present
        and re-rooted.
        """
        from unittest.mock import patch

        from forge.cli.main import _memory_writer_env

        with patch.dict(
            "os.environ",
            {
                "FORGE_SESSION": "drainer-session",
                "FORGE_FORK_NAME": "drainer-fork",
                "FORGE_PARENT_SESSION": "drainer-parent",
            },
        ):
            env = _memory_writer_env({"origin_run_id": "run_C", "origin_root_run_id": "run_R"})
        assert "FORGE_SESSION" not in env
        assert "FORGE_FORK_NAME" not in env
        assert "FORGE_PARENT_SESSION" not in env
        # Run-tree re-rooting is independent of (and unaffected by) the session scrub.
        assert env["FORGE_ROOT_RUN_ID"] == "run_R"
        assert env["FORGE_PARENT_RUN_ID"] == "run_C"

    def test_handoff_marker_captures_origin_identity(self, tmp_path: Path) -> None:
        """enqueue_handoff_marker snapshots the session's run identity into the payload."""
        import json
        from unittest.mock import patch

        from forge.core.workqueue.queue import enqueue_handoff_marker

        with patch.dict("os.environ", {"FORGE_RUN_ID": "run_C", "FORGE_ROOT_RUN_ID": "run_R"}):
            marker_path = enqueue_handoff_marker(
                session_id="sess-origin",
                worktree_path=tmp_path,
                session_name="s",
                transcript_snapshot_rel=".forge/artifacts/s/transcripts/sess-origin.jsonl",
            )
        assert marker_path is not None
        payload = json.loads(marker_path.read_text())["payload"]
        assert payload["origin_run_id"] == "run_C"
        assert payload["origin_root_run_id"] == "run_R"


class TestShadowQueueRouting:
    """The Stop->queue->handler chain for supervisor shadow sampling (no real frontier)."""

    def test_enqueue_shadow_marker_captures_origin_identity(self, tmp_path: Path) -> None:
        import json
        from unittest.mock import patch

        from forge.core.workqueue.queue import enqueue_shadow_marker

        with patch.dict("os.environ", {"FORGE_RUN_ID": "run_C", "FORGE_ROOT_RUN_ID": "run_R"}):
            marker_path = enqueue_shadow_marker(
                session_id="sid",
                session_name="exec",
                worktree_path=tmp_path,
                forge_root=str(tmp_path),
            )
        assert marker_path is not None
        payload = json.loads(marker_path.read_text())["payload"]
        assert payload["origin_run_id"] == "run_C"
        assert payload["origin_root_run_id"] == "run_R"
        assert payload["session_name"] == "exec"
        assert payload["forge_root"] == str(tmp_path)

    def test_shadow_marker_spawns_detached_worker_with_rerooted_env(self, tmp_path: Path) -> None:
        """Draining a shadow marker Popens `forge policy shadow run` with the session's
        run-tree re-rooted and the drainer's SESSION scrubbed, then deletes the marker."""
        from unittest.mock import patch

        from forge.cli.main import _process_pending_work_best_effort
        from forge.core.workqueue.queue import enqueue_shadow_marker

        # FORGE_DEPTH=3 simulates a drainer running deep in a subprocess chain; the
        # detached worker is a fresh top-level tree and must reset it to 0, else
        # run_supervisor_check would skip the frontier (depth >= 2) and record false errors.
        with patch.dict(
            "os.environ",
            {
                "FORGE_RUN_ID": "run_C",
                "FORGE_ROOT_RUN_ID": "run_R",
                "FORGE_SESSION": "drainer",
                "FORGE_DEPTH": "3",
            },
        ):
            marker_path = enqueue_shadow_marker(
                session_id="sid",
                session_name="exec",
                worktree_path=tmp_path,
                forge_root=str(tmp_path),
            )
            assert marker_path is not None
            with patch("subprocess.Popen") as popen:
                _process_pending_work_best_effort()

        popen.assert_called_once()
        cmd = popen.call_args.args[0] if popen.call_args.args else popen.call_args.kwargs["args"]
        assert cmd[:4] == ["forge", "policy", "shadow", "run"]
        assert cmd[cmd.index("--session-name") + 1] == "exec"
        assert cmd[cmd.index("--root") + 1] == str(tmp_path)
        env = popen.call_args.kwargs["env"]
        assert env["FORGE_ROOT_RUN_ID"] == "run_R"  # re-rooted under the originating session
        assert env["FORGE_PARENT_RUN_ID"] == "run_C"
        assert "FORGE_SESSION" not in env  # drainer identity scrubbed
        assert env["FORGE_DEPTH"] == "0"  # depth reset so the frontier replay actually spawns
        assert not marker_path.is_file()  # handler Popen'd -> marker consumed
