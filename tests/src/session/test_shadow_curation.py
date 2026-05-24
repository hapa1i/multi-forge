"""Tests for ``forge.session.shadow_curation``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from forge.session.shadow_curation import (
    ShadowEntry,
    _doc_slug,
    build_curation_prompt,
    curation_report_dir,
    persist_curation_report,
    report_glob_pattern,
    run_shadow_curation,
)


# ---------------------------------------------------------------------------
# build_curation_prompt
# ---------------------------------------------------------------------------


class TestBuildCurationPrompt:
    def test_includes_official_content(self) -> None:
        prompt = build_curation_prompt(
            official_path="docs/notes.md",
            official_content="# Notes\nSome official content.",
            shadow_entries=[],
        )
        assert "docs/notes.md" in prompt
        assert "Some official content." in prompt

    def test_includes_shadows_with_forge_root(self) -> None:
        entries = [
            ShadowEntry(
                official="docs/notes.md",
                shadow_path=".forge/memory/suggested_notes.md",
                strategy="suggested",
                session="s1",
                forge_root="/project",
                content="- [ ] Add caching docs",
            ),
            ShadowEntry(
                official="docs/notes.md",
                shadow_path=".forge/memory/suggested_notes.md",
                strategy="suggested",
                session="s2",
                forge_root="/other-root",
                content="- [ ] Add auth docs",
            ),
        ]
        prompt = build_curation_prompt(
            official_path="docs/notes.md",
            official_content="# Notes",
            shadow_entries=entries,
        )
        assert "Add caching docs" in prompt
        assert "Add auth docs" in prompt
        assert "/project" in prompt
        assert "/other-root" in prompt
        assert "s1" in prompt
        assert "s2" in prompt

    def test_empty_shadows(self) -> None:
        prompt = build_curation_prompt(
            official_path="docs/notes.md",
            official_content="# Notes",
            shadow_entries=[],
        )
        assert "no shadow proposals" in prompt.lower()


# ---------------------------------------------------------------------------
# _doc_slug
# ---------------------------------------------------------------------------


class TestDocSlug:
    def test_basic_path(self) -> None:
        slug = _doc_slug("docs/status/impl_notes.md")
        assert slug.startswith("docs_status_impl_notes-")
        assert len(slug.split("-")[-1]) == 6

    def test_collision_resistance(self) -> None:
        slug_a = _doc_slug("a/b.md")
        slug_b = _doc_slug("a_b.md")
        assert slug_a != slug_b

    def test_truncation(self) -> None:
        long_path = "a/" * 40 + "file.md"
        slug = _doc_slug(long_path)
        parts = slug.rsplit("-", 1)
        assert len(parts[0]) <= 60

    def test_strips_leading_dots(self) -> None:
        slug = _doc_slug(".forge/memory/notes.md")
        assert not slug.startswith(".")

    def test_no_extension_in_slug(self) -> None:
        slug = _doc_slug("docs/notes.md")
        assert ".md" not in slug


# ---------------------------------------------------------------------------
# curation_report_dir / persist / glob
# ---------------------------------------------------------------------------


class TestReportPersistence:
    def test_curation_report_dir_path(self, tmp_path: Path) -> None:
        result = curation_report_dir(tmp_path, "my-session")
        assert result == tmp_path / ".forge" / "artifacts" / "my-session" / "memory"

    def test_persist_creates_file_with_curation_prefix(self, tmp_path: Path) -> None:
        path = persist_curation_report(
            forge_root=tmp_path,
            session_name="s1",
            official_path="docs/notes.md",
            scope="project",
            shadow_count=2,
            content="## Promote\n- Item 1\n",
        )
        assert path.exists()
        assert path.name.startswith("curation-")
        assert "docs_notes" in path.name

    def test_persist_header_fields(self, tmp_path: Path) -> None:
        path = persist_curation_report(
            forge_root=tmp_path,
            session_name="s1",
            official_path="docs/notes.md",
            scope="repo",
            shadow_count=3,
            content="Body content.",
        )
        text = path.read_text()
        assert "docs/notes.md" in text
        assert "s1" in text
        assert "Shadow sources**: 3" in text
        assert "repo" in text
        assert "Body content." in text

    def test_report_glob_pattern_matches_persisted(self, tmp_path: Path) -> None:
        path = persist_curation_report(
            forge_root=tmp_path,
            session_name="s1",
            official_path="docs/notes.md",
            scope="project",
            shadow_count=1,
            content="test",
        )
        pattern = report_glob_pattern("docs/notes.md")
        matches = list(path.parent.glob(pattern))
        assert path in matches

    def test_report_glob_does_not_match_other_doc(self, tmp_path: Path) -> None:
        persist_curation_report(
            forge_root=tmp_path,
            session_name="s1",
            official_path="docs/other.md",
            scope="project",
            shadow_count=1,
            content="other",
        )
        pattern = report_glob_pattern("docs/notes.md")
        report_dir = curation_report_dir(tmp_path, "s1")
        matches = list(report_dir.glob(pattern))
        assert len(matches) == 0


# ---------------------------------------------------------------------------
# run_shadow_curation
# ---------------------------------------------------------------------------


class TestRunShadowCuration:
    def _mock_result(self, *, success: bool = True, stdout: str = "## Promote\n- Item") -> MagicMock:
        result = MagicMock()
        result.success = success
        result.returncode = 0 if success else 1
        result.timed_out = False
        result.error = None if success else "failed"
        result.stdout = stdout
        result.stderr = ""
        return result

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.reactive.cost_tracking.track_verb_cost")
    def test_success_persists_report(
        self, mock_cost: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = self._mock_result()

        entries = [
            ShadowEntry("docs/n.md", ".forge/memory/s.md", "suggested", "s1", str(tmp_path), "content"),
        ]
        result = run_shadow_curation(
            session_name="s1",
            forge_root=tmp_path,
            official_path="docs/n.md",
            official_content="# Notes",
            shadow_entries=entries,
            base_url="http://localhost:8085",
        )

        assert result.success
        assert result.report_path is not None
        assert result.report_path.exists()

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.reactive.cost_tracking.track_verb_cost")
    def test_passes_base_url_and_direct(
        self, mock_cost: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = self._mock_result()

        run_shadow_curation(
            session_name="s1",
            forge_root=tmp_path,
            official_path="docs/n.md",
            official_content="# Notes",
            shadow_entries=[],
            base_url="http://proxy:8085",
            direct=True,
        )

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("base_url") == "http://proxy:8085"
        assert call_kwargs.kwargs.get("direct") is True

        # Verify cost tracking label
        mock_cost.assert_called_once_with("curation", ["http://proxy:8085"])

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.reactive.cost_tracking.track_verb_cost")
    def test_failure_returns_no_report(
        self, mock_cost: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = self._mock_result(success=False)

        result = run_shadow_curation(
            session_name="s1",
            forge_root=tmp_path,
            official_path="docs/n.md",
            official_content="# Notes",
            shadow_entries=[],
        )

        assert not result.success
        assert result.report_path is None


# ---------------------------------------------------------------------------
# collect_shadow_entries
# ---------------------------------------------------------------------------


class TestCollectShadowEntries:
    """Direct unit tests for the session-layer shadow discovery function."""

    def test_returns_shadow_entries_and_scanned_roots(
        self, tmp_path: Path, monkeypatch: MagicMock
    ) -> None:
        from forge.core.ops.context import ExecutionContext
        from forge.session import IndexStore, SessionStore, create_session_state
        from forge.session.shadow_curation import collect_shadow_entries

        forge_root = tmp_path / "project"
        forge_root.mkdir()
        (forge_root / ".forge").mkdir(parents=True)
        (forge_root / "docs").mkdir()
        (forge_root / "docs" / "notes.md").write_text("# Notes\n")
        shadow_dir = forge_root / ".forge" / "memory"
        shadow_dir.mkdir(parents=True)
        (shadow_dir / "suggested_notes.md").write_text("- proposal\n")

        state = create_session_state(
            "s1",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(forge_root),
        )
        state.forge_root = str(forge_root)
        SessionStore(str(forge_root), "s1").write(state)

        index = IndexStore()
        index.add_session(
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

        # Add a shadow doc to the session manifest
        from forge.session.models import DesignatedDoc

        store = SessionStore(str(forge_root), "s1")
        manifest = store.read()
        if manifest.intent.memory is None:
            from forge.session.models import MemoryIntent

            manifest.intent.memory = MemoryIntent()
        manifest.intent.memory.designated_docs.append(
            DesignatedDoc(
                path=".forge/memory/suggested_notes.md",
                strategy="suggested",
                shadows="docs/notes.md",
            )
        )
        store.write(manifest)

        monkeypatch.chdir(forge_root)
        ctx = ExecutionContext.from_cwd(cwd=forge_root)
        entries, roots = collect_shadow_entries(ctx=ctx, scope="project", session_filter=None)

        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, ShadowEntry)
        assert entry.official == "docs/notes.md"
        assert entry.shadow_path == ".forge/memory/suggested_notes.md"
        assert entry.strategy == "suggested"
        assert entry.session == "s1"
        assert entry.forge_root == str(forge_root)
        assert str(forge_root) in roots

    def test_filters_by_session(self, tmp_path: Path, monkeypatch: MagicMock) -> None:
        from forge.core.ops.context import ExecutionContext
        from forge.session import IndexStore, SessionStore, create_session_state
        from forge.session.models import DesignatedDoc, MemoryIntent
        from forge.session.shadow_curation import collect_shadow_entries

        forge_root = tmp_path / "project"
        forge_root.mkdir()
        (forge_root / ".forge").mkdir(parents=True)
        (forge_root / "docs").mkdir()
        (forge_root / "docs" / "notes.md").write_text("# Notes\n")

        index = IndexStore()
        for name in ("s1", "s2"):
            state = create_session_state(
                name,
                proxy_template="litellm-openai",
                proxy_base_url="http://localhost:8085",
                worktree_path=str(forge_root),
            )
            state.forge_root = str(forge_root)
            store = SessionStore(str(forge_root), name)
            store.write(state)
            manifest = store.read()
            if manifest.intent.memory is None:
                manifest.intent.memory = MemoryIntent()
            manifest.intent.memory.designated_docs.append(
                DesignatedDoc(path=".forge/memory/s.md", strategy="suggested", shadows="docs/notes.md")
            )
            store.write(manifest)
            index.add_session(
                name=name,
                worktree_path=str(forge_root),
                project_root=str(tmp_path),
                forge_root=str(forge_root),
                checkout_root=str(forge_root),
                relative_path=".",
                is_incognito=False,
                is_fork=False,
                parent_session=None,
            )

        monkeypatch.chdir(forge_root)
        ctx = ExecutionContext.from_cwd(cwd=forge_root)
        entries, _ = collect_shadow_entries(ctx=ctx, scope="project", session_filter="s2")

        assert len(entries) == 1
        assert entries[0].session == "s2"


# ---------------------------------------------------------------------------
# Import layering
# ---------------------------------------------------------------------------


class TestImportLayering:
    def test_no_cli_dependency(self) -> None:
        """Importing shadow_curation must not pull in CLI modules."""
        import importlib
        import sys

        cli_modules_before = {k for k in sys.modules if k.startswith("forge.cli")}

        if "forge.session.shadow_curation" in sys.modules:
            importlib.reload(sys.modules["forge.session.shadow_curation"])
        else:
            importlib.import_module("forge.session.shadow_curation")

        cli_modules_after = {k for k in sys.modules if k.startswith("forge.cli")}
        new_cli_imports = cli_modules_after - cli_modules_before
        assert not new_cli_imports, f"shadow_curation imported CLI modules: {new_cli_imports}"
