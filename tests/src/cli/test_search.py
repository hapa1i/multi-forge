"""Tests for the forge search CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.search.bm25_store import BM25IndexData, BM25IndexStore
from forge.search.content_store import ContentStore
from forge.search.engine import BM25
from forge.search.exceptions import SearchDocumentStoreCorruptedError
from forge.search.extractor import SearchDocumentMeta
from forge.search.index_state import IndexedFileEntry, IndexState, IndexStateStore
from forge.search.store import SearchDocumentStore
from forge.search.tokenizer import tokenize


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _populate_three_stores(
    project_root: Path,
    docs: list[tuple[str, str, str, str, str, dict]],
) -> SearchDocumentStore:
    """Populate all three search stores for a project.

    Args:
        project_root: Project root path.
        docs: List of (transcript_path, session_name, session_id, content, extracted_at, metadata).
    """
    doc_store = SearchDocumentStore(forge_root=project_root)
    bm25_store = BM25IndexStore(forge_root=project_root)
    content_store = ContentStore(forge_root=project_root)

    metas = []
    content_map = {}
    all_tokens = []
    keys = []

    for tp, sname, sid, content, eat, meta in docs:
        metas.append(
            SearchDocumentMeta(
                transcript_path=tp,
                session_name=sname,
                session_id=sid,
                extracted_at=eat,
                metadata=meta,
            )
        )
        content_map[tp] = content
        all_tokens.append(tokenize(content))
        keys.append(tp)

    doc_store.write(metas)
    content_store.write(content_map)

    # Build BM25 bulk
    bm25 = BM25(all_tokens)
    pre = bm25.to_precomputed()
    bm25_store.write(
        BM25IndexData(
            doc_keys=keys,
            doc_lens=pre["doc_lens"],
            term_freqs=pre["term_freqs"],
            doc_freqs=pre["doc_freqs"],
            avgdl=pre["avgdl"],
        )
    )

    return doc_store


@pytest.fixture
def populated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SearchDocumentStore:
    """Create per-project search stores (documents, BM25 index, content).

    Sets up a project root with .git dir and writes all three stores,
    then chdir so the CLI resolves project_root correctly.
    """
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    monkeypatch.chdir(project_root)

    project_str = str(project_root)
    docs = [
        (
            f"{project_str}/.forge/artifacts/db-config/transcripts/s1.jsonl",
            "db-config",
            "s1",
            "[user] Please update the database timeout to 30 seconds\n"
            "[assistant] I'll update the timeout setting in the config file",
            "2026-02-08T10:00:00+00:00",
            {
                "message_count": 2,
                "worktree_path": project_str,
                "first_timestamp": "2026-02-08T10:00:00Z",
                "last_timestamp": "2026-02-08T10:01:00Z",
            },
        ),
        (
            f"{project_str}/.forge/artifacts/auth-feature/transcripts/s2.jsonl",
            "auth-feature",
            "s2",
            "[user] Add authentication middleware to the API\n"
            "[assistant] I'll implement JWT authentication for the endpoints",
            "2026-02-08T11:00:00+00:00",
            {
                "message_count": 2,
                "worktree_path": project_str,
                "first_timestamp": "2026-02-08T11:00:00Z",
                "last_timestamp": "2026-02-08T11:01:00Z",
            },
        ),
        (
            f"{project_str}/.forge/artifacts/pool-fix/transcripts/s3.jsonl",
            "pool-fix",
            "s3",
            "[user] Fix the timeout bug in connection pooling\n"
            "[assistant] The timeout was caused by a race condition in the pool",
            "2026-02-08T12:00:00+00:00",
            {
                "message_count": 2,
                "worktree_path": project_str,
                "first_timestamp": "2026-02-08T12:00:00Z",
                "last_timestamp": "2026-02-08T12:01:00Z",
            },
        ),
    ]
    return _populate_three_stores(project_root, docs)


class TestSearchCommand:
    """Tests for forge search query <terms>."""

    def test_bare_search_prints_help(self, runner: CliRunner) -> None:
        """Bare non-leaf prints help to stderr and exits 2 (usage error), like every other group."""
        result = runner.invoke(main, ["search"])
        assert result.exit_code == 2
        assert "Usage:" in result.stderr
        assert "query" in result.stderr
        assert "rebuild-index" in result.stderr

    def test_search_default_renders_table(self, runner: CliRunner, populated_store: SearchDocumentStore) -> None:
        """Default (no --json) renders a human table with a result-count footer, not JSON."""
        result = runner.invoke(main, ["search", "query", "timeout"])
        assert result.exit_code == 0
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)
        assert "Score" in result.output
        assert "db-config" in result.output
        assert "result(s)" in result.output

    def test_search_default_no_results_human_message(
        self, runner: CliRunner, populated_store: SearchDocumentStore
    ) -> None:
        """Default with no matches prints a human 'No results' line, not empty JSON."""
        result = runner.invoke(main, ["search", "query", "xyznonexistent"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_search_outputs_json(self, runner: CliRunner, populated_store: SearchDocumentStore) -> None:
        """`--json` outputs valid JSON with results (project scope)."""
        result = runner.invoke(main, ["search", "query", "timeout", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "results" in data
        assert data["total_results"] >= 1
        session_names = [r["session_name"] for r in data["results"]]
        assert "db-config" in session_names

    def test_search_no_results(self, runner: CliRunner, populated_store: SearchDocumentStore) -> None:
        """`--json` for a nonexistent term returns empty results."""
        result = runner.invoke(main, ["search", "query", "xyznonexistent", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] == 0
        assert data["results"] == []

    def test_search_limit(self, runner: CliRunner, populated_store: SearchDocumentStore) -> None:
        """--limit flag caps results."""
        result = runner.invoke(main, ["search", "query", "timeout", "--limit", "1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["results"]) <= 1

    def test_search_no_index_returns_hint(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Search with no index returns JSON with hint, not a crash."""
        project = tmp_path / "empty-project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        result = runner.invoke(main, ["search", "query", "anything", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] == 0
        assert "hint" in data

    def test_search_scope_all_includes_current_project(
        self, runner: CliRunner, populated_store: SearchDocumentStore
    ) -> None:
        """--scope all still searches the current project even if session index points elsewhere."""
        other_root = Path.cwd().parent / "other-project"
        other_root.mkdir()

        with patch(
            "forge.session.index.IndexStore.list_sessions",
            return_value=[("other-session", SimpleNamespace(project_root=str(other_root)))],
        ):
            result = runner.invoke(main, ["search", "query", "timeout", "--scope", "all", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] >= 1
        session_names = [r["session_name"] for r in data["results"]]
        assert "db-config" in session_names

    def test_search_scope_all_no_match_returns_empty_results_without_hint(
        self, runner: CliRunner, populated_store: SearchDocumentStore
    ) -> None:
        """--scope all should not claim the index is missing when indexed projects simply have no matches."""
        with patch("forge.session.index.IndexStore.list_sessions", return_value=[]):
            result = runner.invoke(main, ["search", "query", "xyznonexistent", "--scope", "all", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] == 0
        assert data["results"] == []
        assert "hint" not in data

    def test_search_scope_all_no_index_returns_hint(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--scope all should still hint to rebuild when no project index exists anywhere."""
        project = tmp_path / "empty-project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        with patch("forge.session.index.IndexStore.list_sessions", return_value=[]):
            result = runner.invoke(main, ["search", "query", "anything", "--scope", "all", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] == 0
        assert "hint" in data

    def test_search_corrupted_store_returns_error_json(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Corrupted BM25 index returns JSON error with rebuild hint, not a traceback."""
        project = tmp_path / "corrupt-project"
        project.mkdir()
        (project / ".git").mkdir()
        monkeypatch.chdir(project)

        # Write corrupted BM25 index file (search reads this first)
        store_dir = project / ".forge" / "search-index"
        store_dir.mkdir(parents=True)
        (store_dir / "bm25_index.json").write_text("not valid json {{{")

        result = runner.invoke(main, ["search", "query", "anything", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] == 0
        assert "error" in data
        assert "corrupted" in data["error"].lower() or "invalid" in data["error"].lower()
        assert "rebuild" in data["hint"].lower()


class TestRebuildIndex:
    """Tests for forge search rebuild-index."""

    def test_rebuild_with_transcripts(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rebuild indexes transcript files found in artifacts."""
        # Create artifact structure
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()

        transcript_dir = project_root / ".forge" / "artifacts" / "my-session" / "transcripts"
        transcript_dir.mkdir(parents=True)
        (transcript_dir / "uuid-1.jsonl").write_text(
            '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
            '"message":{"role":"user","content":[{"type":"text","text":"hello world"}]}}\n'
        )

        monkeypatch.chdir(project_root)

        result = runner.invoke(main, ["search", "rebuild-index"])
        assert result.exit_code == 0
        assert "Indexed 1 transcripts" in result.output

        # All three store files should exist
        index_dir = project_root / ".forge" / "search-index"
        assert (index_dir / "documents.json").is_file()
        assert (index_dir / "bm25_index.json").is_file()
        assert (index_dir / "content.json").is_file()

    def test_rebuild_no_artifacts(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rebuild with no artifacts directory reports no artifacts."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        result = runner.invoke(main, ["search", "rebuild-index"])
        assert result.exit_code == 0
        assert "No artifacts" in result.output

    def test_rebuild_auto_prunes_stale_index_entries(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """rebuild-index prunes index state entries for deleted transcript files."""
        from forge.search.index_state import (
            IndexedFileEntry,
            IndexState,
            IndexStateStore,
        )

        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()

        # Create one real transcript
        transcript_dir = project_root / ".forge" / "artifacts" / "sess" / "transcripts"
        transcript_dir.mkdir(parents=True)
        (transcript_dir / "real.jsonl").write_text(
            '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
            '"message":{"role":"user","content":[{"type":"text","text":"hello"}]}}\n'
        )

        # Seed index state with a stale entry pointing to a deleted file
        index_store = IndexStateStore(forge_root=project_root)
        state = IndexState(
            indexed_files={"/deleted/old-transcript.jsonl": IndexedFileEntry(mtime=0, size=0, indexed_at="")}
        )
        index_store.write(state)

        monkeypatch.chdir(project_root)
        result = runner.invoke(main, ["search", "rebuild-index"])
        assert result.exit_code == 0

        # Stale entry should be gone; only the real transcript remains
        updated_state = index_store.read()
        assert "/deleted/old-transcript.jsonl" not in updated_state.indexed_files
        assert len(updated_state.indexed_files) == 1


class TestEndToEndPipeline:
    """End-to-end integration tests: transcript → rebuild-index → search → results."""

    def test_rebuild_then_search_finds_results(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full pipeline: create transcripts, rebuild index, search returns ranked results."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()

        # Create two sessions with different content
        for name, sid, text in [
            ("db-work", "s1", "Please update the database timeout to 30 seconds"),
            (
                "auth-work",
                "s2",
                "Add JWT authentication middleware to the API endpoints",
            ),
        ]:
            tdir = project_root / ".forge" / "artifacts" / name / "transcripts"
            tdir.mkdir(parents=True)
            (tdir / f"{sid}.jsonl").write_text(
                f'{{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
                f'"message":{{"role":"user","content":[{{"type":"text","text":"{text}"}}]}}}}\n'
                f'{{"requestId":"r1","timestamp":"2026-01-01T00:00:01Z",'
                f'"message":{{"role":"assistant","content":[{{"type":"text","text":"Done."}}]}}}}\n'
            )

        monkeypatch.chdir(project_root)

        # Step 1: Rebuild index
        result = runner.invoke(main, ["search", "rebuild-index"])
        assert result.exit_code == 0
        assert "Indexed 2 transcripts" in result.output

        # Step 2: Search for "database timeout"
        result = runner.invoke(main, ["search", "query", "database timeout", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] >= 1
        # db-work should rank highest (contains both query terms)
        assert data["results"][0]["session_name"] == "db-work"

        # Step 3: Search for "authentication" — should find auth-work, not db-work
        result = runner.invoke(main, ["search", "query", "authentication", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] >= 1
        session_names = [r["session_name"] for r in data["results"]]
        assert "auth-work" in session_names
        assert "db-work" not in session_names

    def test_index_handler_then_search(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Full pipeline via work queue: enqueue marker → CLI processes → search finds it."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()

        transcript_dir = project_root / ".forge" / "artifacts" / "perf-fix" / "transcripts"
        transcript_dir.mkdir(parents=True)
        transcript_file = transcript_dir / "queue-test.jsonl"
        transcript_file.write_text(
            '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
            '"message":{"role":"user","content":[{"type":"text","text":"Fix the memory leak in the connection pool"}]}}\n'
        )

        monkeypatch.chdir(project_root)

        # Enqueue index marker (simulates what stop hook does)
        from forge.core.workqueue import enqueue_index_marker

        marker = enqueue_index_marker(
            session_id="queue-test",
            worktree_path=project_root,
            session_name="perf-fix",
            transcript_snapshot_rel=".forge/artifacts/perf-fix/transcripts/queue-test.jsonl",
        )
        assert marker is not None

        # Any non-exempt CLI command triggers queue processing
        runner.invoke(main, ["search", "status"])

        # Now search should find the indexed transcript
        result = runner.invoke(main, ["search", "query", "memory leak", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_results"] >= 1
        assert data["results"][0]["session_name"] == "perf-fix"

    def test_status_reflects_rebuild(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Status shows correct counts after rebuild-index."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()

        tdir = project_root / ".forge" / "artifacts" / "sess" / "transcripts"
        tdir.mkdir(parents=True)
        (tdir / "u1.jsonl").write_text(
            '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
            '"message":{"role":"user","content":[{"type":"text","text":"test content"}]}}\n'
        )

        monkeypatch.chdir(project_root)
        runner.invoke(main, ["search", "rebuild-index"])

        result = runner.invoke(main, ["search", "status"])
        assert result.exit_code == 0
        assert "1" in result.output  # 1 document


class TestPruneCmd:
    """Tests for forge search clean."""

    def _seed_orphans(self, project_root: Path) -> tuple[SearchDocumentStore, IndexStateStore, str]:
        missing_path = "/nonexistent/ghost.jsonl"
        store = SearchDocumentStore(forge_root=project_root)
        store.write(
            [
                SearchDocumentMeta(
                    transcript_path=missing_path,
                    session_name="ghost",
                    session_id="g1",
                    extracted_at="2026-01-01T00:00:00+00:00",
                    metadata={},
                ),
            ]
        )

        index_store = IndexStateStore(forge_root=project_root)
        index_store.write(IndexState(indexed_files={missing_path: IndexedFileEntry(mtime=0, size=0, indexed_at="")}))
        return store, index_store, missing_path

    def test_prune_removes_orphans_from_both_stores(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Prune removes orphans from both document store and index state."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        # Ghost document in document store (v2: metadata only)
        store = SearchDocumentStore(forge_root=project_root)
        store.write(
            [
                SearchDocumentMeta(
                    transcript_path="/nonexistent/ghost.jsonl",
                    session_name="ghost",
                    session_id="g1",
                    extracted_at="2026-01-01T00:00:00+00:00",
                    metadata={},
                ),
            ]
        )

        # Stale entry in index state
        index_store = IndexStateStore(forge_root=project_root)
        # Write a stale entry directly (can't use mark_indexed — file doesn't exist)
        state = IndexState(indexed_files={"/nonexistent/ghost.jsonl": IndexedFileEntry(mtime=0, size=0, indexed_at="")})
        index_store.write(state)

        result = runner.invoke(main, ["search", "clean", "--yes"])
        assert result.exit_code == 0
        assert "1" in result.output and "orphaned documents" in result.output
        assert "1" in result.output and "stale index entries" in result.output
        # Both stores cleaned
        assert store.read() == []
        assert index_store.read().indexed_files == {}

    def test_clean_previews_by_default_without_pruning(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare `clean` previews orphans and offers --yes, removing nothing."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        store = SearchDocumentStore(forge_root=project_root)
        store.write(
            [
                SearchDocumentMeta(
                    transcript_path="/nonexistent/ghost.jsonl",
                    session_name="ghost",
                    session_id="g1",
                    extracted_at="2026-01-01T00:00:00+00:00",
                    metadata={},
                ),
            ]
        )
        index_store = IndexStateStore(forge_root=project_root)
        index_store.write(
            IndexState(indexed_files={"/nonexistent/ghost.jsonl": IndexedFileEntry(mtime=0, size=0, indexed_at="")})
        )

        result = runner.invoke(main, ["search", "clean"])
        assert result.exit_code == 0
        assert "Would prune" in result.output
        assert "Use --yes to prune." in result.output
        # Nothing removed by the preview
        assert len(store.read()) == 1
        assert index_store.read().indexed_files != {}

    def test_clean_json_previews_by_default_without_pruning(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`search clean --json` previews with a stable JSON shape and no mutation."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        store, index_store, missing_path = self._seed_orphans(project_root)

        result = runner.invoke(main, ["search", "clean", "--json"])

        assert result.exit_code == 0
        assert result.stderr == ""
        data = json.loads(result.stdout)
        assert data["scope"] == "project"
        assert data["dry_run"] is True
        assert data["total"] == 2
        categories = {row["category"]: row for row in data["categories"]}
        assert categories["orphaned_documents"]["count"] == 1
        assert categories["orphaned_documents"]["items"] == [missing_path]
        assert categories["stale_index_entries"]["count"] == 1
        assert categories["stale_index_entries"]["items"] == [missing_path]
        assert len(store.read()) == 1
        assert index_store.read().indexed_files != {}

    def test_clean_json_with_yes_reports_deleted_counts(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`search clean --yes --json` reports pruned counts on stdout."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        store, index_store, _ = self._seed_orphans(project_root)

        result = runner.invoke(main, ["search", "clean", "--yes", "--json"])

        assert result.exit_code == 0
        assert result.stderr == ""
        data = json.loads(result.stdout)
        assert data == {
            "scope": "project",
            "dry_run": False,
            "total": 2,
            "deleted": 2,
            "failed": [],
            "categories_cleaned": {
                "orphaned_documents": 1,
                "stale_index_entries": 1,
            },
        }
        assert store.read() == []
        assert index_store.read().indexed_files == {}

    def test_clean_json_error_uses_stderr(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`search clean --json` reports cleanup errors as JSON on stderr."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        def _raise_corrupt(_store: SearchDocumentStore) -> list[str]:
            raise SearchDocumentStoreCorruptedError("documents.json", "invalid JSON")

        monkeypatch.setattr(SearchDocumentStore, "find_missing", _raise_corrupt)

        result = runner.invoke(main, ["search", "clean", "--json"])

        assert result.exit_code == 1
        assert result.stdout == ""
        data = json.loads(result.stderr)
        assert data["error"] == "'documents.json': invalid JSON"

    def test_prune_nothing_to_do(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Prune with all valid documents reports nothing to do."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        # Create a real transcript file
        transcript = project_root / "real.jsonl"
        transcript.write_text("{}")

        store = SearchDocumentStore(forge_root=project_root)
        store.write(
            [
                SearchDocumentMeta(
                    transcript_path=str(transcript),
                    session_name="valid",
                    session_id="v1",
                    extracted_at="2026-01-01T00:00:00+00:00",
                    metadata={},
                ),
            ]
        )

        result = runner.invoke(main, ["search", "clean"])
        assert result.exit_code == 0
        assert "No orphaned" in result.output
        assert len(store.read()) == 1


class TestSearchStatus:
    """Tests for forge search status."""

    def test_status_no_index(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Status with no index shows not built and the target index location."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        result = runner.invoke(main, ["search", "status"])
        assert result.exit_code == 0
        assert "not built" in result.output
        normalized_output = result.output.replace("\n", "")
        assert str(project_root / ".forge" / "search-index") in normalized_output

    def test_status_with_index(self, runner: CliRunner, populated_store: SearchDocumentStore) -> None:
        """Status with populated index shows location and document count."""
        result = runner.invoke(main, ["search", "status"])
        assert result.exit_code == 0
        normalized_output = result.output.replace("\n", "")
        assert ".forge/search-index" in normalized_output
        assert "3" in result.output  # 3 documents

    def test_status_json_not_built(self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`--json` for an unbuilt index emits the not-built shape with null/zero stats."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        monkeypatch.chdir(project_root)

        result = runner.invoke(main, ["search", "status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {
            "built": False,
            "index_location": str(project_root / ".forge" / "search-index"),
            "documents_indexed": 0,
            "files_tracked": 0,
            "updated_at": None,
            "sessions": 0,
            "bm25": None,
        }

    def test_status_json_built(self, runner: CliRunner, populated_store: SearchDocumentStore) -> None:
        """`--json` for a populated index emits built=True with document/session/bm25 stats."""
        project_root = Path.cwd()
        result = runner.invoke(main, ["search", "status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)

        assert set(data) == {
            "built",
            "index_location",
            "documents_indexed",
            "files_tracked",
            "updated_at",
            "sessions",
            "bm25",
        }
        assert data["built"] is True
        assert data["index_location"] == str(project_root / ".forge" / "search-index")
        assert data["documents_indexed"] == 3
        assert isinstance(data["files_tracked"], int)
        # updated_at is null unless index state was written; assert nullable contract.
        assert data["updated_at"] is None or isinstance(data["updated_at"], str)
        assert data["sessions"] == 3  # db-config, auth-feature, pool-fix

        bm25 = data["bm25"]
        assert isinstance(bm25, dict)
        assert set(bm25) == {"documents", "unique_terms"}
        assert bm25["documents"] == 3
        assert isinstance(bm25["unique_terms"], int)
        assert bm25["unique_terms"] > 0

    def test_status_json_built_tracks_files_and_timestamp(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a real rebuild, files_tracked and updated_at are populated (non-zero/str).

        The populated_store fixture never writes index state, so files_tracked/updated_at
        stay at their zero/null floor there; this exercises them via the real rebuild path.
        """
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        tdir = project_root / ".forge" / "artifacts" / "sess" / "transcripts"
        tdir.mkdir(parents=True)
        (tdir / "s1.jsonl").write_text(
            '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
            '"message":{"role":"user","content":[{"type":"text","text":"index the search timeout config"}]}}\n'
        )
        monkeypatch.chdir(project_root)

        assert runner.invoke(main, ["search", "rebuild-index"]).exit_code == 0

        result = runner.invoke(main, ["search", "status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["built"] is True
        assert data["files_tracked"] >= 1
        assert isinstance(data["updated_at"], str) and data["updated_at"]

    def test_status_json_built_without_bm25(self, runner: CliRunner, populated_store: SearchDocumentStore) -> None:
        """built=True with bm25:null when documents exist but the BM25 store is absent."""
        bm25_file = Path.cwd() / ".forge" / "search-index" / "bm25_index.json"
        bm25_file.unlink()

        result = runner.invoke(main, ["search", "status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["built"] is True
        assert data["documents_indexed"] == 3
        assert data["bm25"] is None
