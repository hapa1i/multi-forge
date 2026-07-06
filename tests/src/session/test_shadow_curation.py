"""Tests for ``forge.session.shadow_curation``."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from forge.core.lanes import Lane, valid_lanes
from forge.core.reactive.session_runner import SessionResult
from forge.core.usage.ledger import read_usage_events
from forge.session.models import LaneRecord
from forge.session.shadow_curation import (
    SHADOW_CURATION_CONSUMER,
    ShadowEntry,
    _doc_slug,
    build_curation_prompt,
    curation_report_dir,
    persist_curation_report,
    report_glob_pattern,
    run_shadow_curation,
)
from tests.fixtures.codex_result import codex_result

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
                shadow_path=".forge/memory/shadow_notes.md",
                strategy="generic",
                session="s1",
                forge_root="/project",
                content="- [ ] Add caching docs",
            ),
            ShadowEntry(
                official="docs/notes.md",
                shadow_path=".forge/memory/shadow_notes.md",
                strategy="generic",
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

    def test_embedded_fences_cannot_close_content_blocks(self) -> None:
        entries = [
            ShadowEntry(
                official="docs/notes.md",
                shadow_path=".forge/memory/shadow_notes.md",
                strategy="generic",
                session="s1",
                forge_root="/project",
                content="````\nshadow proposal\n````",
            ),
        ]

        prompt = build_curation_prompt(
            official_path="docs/notes.md",
            official_content="```python\nprint('official')\n```",
            shadow_entries=entries,
        )

        assert "````\n```python\nprint('official')\n```\n````" in prompt
        assert "`````\n````\nshadow proposal\n````\n`````" in prompt


# ---------------------------------------------------------------------------
# _doc_slug
# ---------------------------------------------------------------------------


class TestDocSlug:
    def test_basic_path(self) -> None:
        slug = _doc_slug("docs/board/impl_notes.md")
        assert slug.startswith("docs_board_impl_notes-")
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
            scope="workspace",
            shadow_count=3,
            content="Body content.",
        )
        text = path.read_text()
        assert "docs/notes.md" in text
        assert "s1" in text
        assert "Shadow sources**: 3" in text
        assert "workspace" in text
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
        result.run_id = "run_cur"
        result.parent_run_id = "run_parent"
        result.root_run_id = "run_root"
        return result

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.reactive.cost_tracking.track_verb_cost")
    def test_success_persists_report(self, mock_cost: MagicMock, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = self._mock_result()

        entries = [
            ShadowEntry("docs/n.md", ".forge/memory/s.md", "generic", "s1", str(tmp_path), "content"),
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
    def test_claude_max_binding_emits_subscription_quota(
        self, mock_run: MagicMock, tmp_path: Path, monkeypatch
    ) -> None:
        """A keyless, direct, claude-max-bound curation run threads backend_id ->
        emit, so the usage event is labeled subscription_quota."""
        monkeypatch.setattr(
            "forge.core.auth.template_secrets.resolve_env_or_credential",
            lambda _key: None,  # keyless: no resolvable ANTHROPIC_API_KEY
        )
        mock_run.return_value = SessionResult(stdout="## Promote\n- Item", stderr="", returncode=0, run_id="run_cur")
        entries = [
            ShadowEntry("docs/n.md", ".forge/memory/s.md", "generic", "s1", str(tmp_path), "content"),
        ]
        run_shadow_curation(
            session_name="s1",
            forge_root=tmp_path,
            official_path="docs/n.md",
            official_content="# Notes",
            shadow_entries=entries,
            direct=True,
            backend_id="claude-max",
        )

        events = read_usage_events(command="curation")
        assert len(events) == 1
        assert events[0].billing_mode == "subscription_quota"

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.reactive.cost_tracking.track_verb_cost")
    def test_passes_base_url_and_direct(self, mock_cost: MagicMock, mock_run: MagicMock, tmp_path: Path) -> None:
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
    def test_failure_returns_no_report(self, mock_cost: MagicMock, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_cost.return_value.__enter__.return_value.duration_ms = 0.0
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
        from forge.core.telemetry.upstream import read_upstream_outcomes

        outcomes = read_upstream_outcomes(session="s1", command="curation")
        assert len(outcomes) == 1
        assert outcomes[0].operation == "memory.shadow_curation"
        assert outcomes[0].status == "error"
        assert outcomes[0].reason_code == "subprocess_error"
        assert outcomes[0].latency_ms == 0.0

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.reactive.cost_tracking.track_verb_cost")
    def test_result_run_tree_ids_are_optional(self, mock_cost: MagicMock, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_cost.return_value.__enter__.return_value.duration_ms = 12.3
        mock_run.return_value = type(
            "R",
            (),
            {
                "success": False,
                "returncode": 1,
                "timed_out": False,
                "error": "failed",
                "stdout": "",
                "stderr": "",
            },
        )()

        result = run_shadow_curation(
            session_name="s1",
            forge_root=tmp_path,
            official_path="docs/n.md",
            official_content="# Notes",
            shadow_entries=[],
        )

        assert not result.success
        from forge.core.telemetry.upstream import read_upstream_outcomes

        outcomes = read_upstream_outcomes(session="s1", command="curation")
        assert len(outcomes) == 1
        assert outcomes[0].status == "error"
        assert outcomes[0].run_id is None
        assert outcomes[0].root_run_id is None


# ---------------------------------------------------------------------------
# collect_shadow_entries
# ---------------------------------------------------------------------------


class TestCollectShadowEntries:
    """Direct unit tests for the session-layer shadow discovery function."""

    def test_returns_shadow_entries_and_scanned_roots(self, tmp_path: Path, monkeypatch: MagicMock) -> None:
        """Shadow entries are discovered via passport scan, not session manifests."""
        from forge.core.ops.context import ExecutionContext
        from forge.session import IndexStore, SessionStore, create_session_state
        from forge.session.passport import synthesize_passport, write_passport
        from forge.session.shadow_curation import collect_shadow_entries

        forge_root = tmp_path / "project"
        forge_root.mkdir()
        (forge_root / ".forge").mkdir(parents=True)
        (forge_root / "docs").mkdir()
        official = forge_root / "docs" / "notes.md"
        official.write_text("# Notes\n")
        write_passport(
            official,
            synthesize_passport(
                strategy="generic",
                update_mode="shadow-only",
                shadow_path=".forge/memory/shadow_notes.md",
            ),
        )
        shadow_dir = forge_root / ".forge" / "memory"
        shadow_dir.mkdir(parents=True)
        (shadow_dir / "shadow_notes.md").write_text("- proposal\n")

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

        monkeypatch.chdir(forge_root)
        ctx = ExecutionContext.from_cwd(cwd=forge_root)
        entries, roots = collect_shadow_entries(ctx=ctx, scope="project", session_filter=None)

        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, ShadowEntry)
        assert entry.official == "docs/notes.md"
        assert entry.shadow_path == ".forge/memory/shadow_notes.md"
        assert entry.strategy == "generic"
        assert entry.session == "(project)"
        assert entry.forge_root == str(forge_root)
        assert str(forge_root) in roots

    def test_session_filter_skips_passport_scan(self, tmp_path: Path, monkeypatch: MagicMock) -> None:
        """session_filter suppresses the passport scan -- project shadows belong to no session."""
        from forge.core.ops.context import ExecutionContext
        from forge.session import IndexStore, SessionStore, create_session_state
        from forge.session.passport import synthesize_passport, write_passport
        from forge.session.shadow_curation import collect_shadow_entries

        forge_root = tmp_path / "project"
        forge_root.mkdir()
        (forge_root / ".forge").mkdir(parents=True)
        (forge_root / "docs").mkdir()
        official = forge_root / "docs" / "notes.md"
        official.write_text("# Notes\n")
        write_passport(
            official,
            synthesize_passport(
                strategy="generic",
                update_mode="shadow-only",
                shadow_path=".forge/memory/shadow_notes.md",
            ),
        )

        for name in ("s1", "s2"):
            state = create_session_state(
                name,
                proxy_template="litellm-openai",
                proxy_base_url="http://localhost:8085",
                worktree_path=str(forge_root),
            )
            state.forge_root = str(forge_root)
            SessionStore(str(forge_root), name).write(state)
            IndexStore().add_session(
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

        # Passport scan is skipped when session_filter is set
        assert len(entries) == 0

    def _setup_project_shadow(self, tmp_path: Path) -> Path:
        """Create a forge_root with a sessionless shadow-only passport (no manifest)."""
        from forge.session.passport import synthesize_passport, write_passport

        forge_root = tmp_path / "project"
        forge_root.mkdir()
        (forge_root / ".forge").mkdir(parents=True)
        (forge_root / "docs").mkdir()
        official = forge_root / "docs" / "notes.md"
        official.write_text("# Notes\n")
        write_passport(
            official,
            synthesize_passport(
                strategy="generic", update_mode="shadow-only", shadow_path=".forge/memory/shadow_notes.md"
            ),
        )
        return forge_root

    def _register_session(self, tmp_path: Path, forge_root: Path, name: str = "s1") -> None:
        from forge.session import IndexStore, SessionStore, create_session_state

        state = create_session_state(
            name,
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(forge_root),
        )
        state.forge_root = str(forge_root)
        SessionStore(str(forge_root), name).write(state)
        IndexStore().add_session(
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

    def test_discovers_project_origin_shadow_via_scan(self, tmp_path: Path, monkeypatch: MagicMock) -> None:
        """A sessionless ``track --propose`` passport (no manifest entry) is discovered by scan."""
        from forge.core.ops.context import ExecutionContext
        from forge.session.shadow_curation import collect_shadow_entries

        forge_root = self._setup_project_shadow(tmp_path)
        self._register_session(tmp_path, forge_root)  # session exists but has no designated_docs

        monkeypatch.chdir(forge_root)
        ctx = ExecutionContext.from_cwd(cwd=forge_root)
        entries, _ = collect_shadow_entries(ctx=ctx, scope="project", session_filter=None)

        assert len(entries) == 1
        assert entries[0].official == "docs/notes.md"
        assert entries[0].shadow_path == ".forge/memory/shadow_notes.md"
        assert entries[0].session == "(project)"

    def test_passport_scan_deduplicates_same_shadow_across_roots(self, tmp_path: Path, monkeypatch: MagicMock) -> None:
        """When the same forge_root appears via multiple sessions, each shadow passport is emitted once."""
        from forge.core.ops.context import ExecutionContext
        from forge.session.shadow_curation import collect_shadow_entries

        forge_root = self._setup_project_shadow(tmp_path)
        # Register two sessions pointing at the same forge_root
        self._register_session(tmp_path, forge_root, name="s1")
        self._register_session(tmp_path, forge_root, name="s2")

        monkeypatch.chdir(forge_root)
        ctx = ExecutionContext.from_cwd(cwd=forge_root)
        entries, _ = collect_shadow_entries(ctx=ctx, scope="project", session_filter=None)

        assert len(entries) == 1
        assert entries[0].session == "(project)"

    def test_scope_workspace_unions_current_project_root(self, tmp_path: Path, monkeypatch: MagicMock) -> None:
        """--scope workspace includes the current project's passport-origin shadows."""
        from forge.core.ops.context import ExecutionContext
        from forge.session.shadow_curation import collect_shadow_entries

        forge_root = self._setup_project_shadow(tmp_path)
        self._register_session(tmp_path, forge_root)

        monkeypatch.chdir(forge_root)
        ctx = ExecutionContext.from_cwd(cwd=forge_root)
        entries, roots = collect_shadow_entries(ctx=ctx, scope="workspace", session_filter=None)

        assert any(e.session == "(project)" and e.official == "docs/notes.md" for e in entries)
        assert str(forge_root) in roots


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


# ---------------------------------------------------------------------------
# run_shadow_curation reasoning effort
# ---------------------------------------------------------------------------


class TestRunShadowCurationEffort:
    def _mock_result(self) -> MagicMock:
        result = MagicMock()
        result.success = True
        result.returncode = 0
        result.timed_out = False
        result.error = None
        result.stdout = "## Promote\n- Item"
        result.stderr = ""
        return result

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.reactive.cost_tracking.track_verb_cost")
    def test_reasoning_effort_forwarded(self, mock_cost: MagicMock, mock_run: MagicMock, tmp_path: Path) -> None:
        """reasoning_effort='medium' is forwarded to run_claude_session."""
        mock_run.return_value = self._mock_result()

        run_shadow_curation(
            session_name="s1",
            forge_root=tmp_path,
            official_path="docs/n.md",
            official_content="# Notes",
            shadow_entries=[],
            reasoning_effort="medium",
        )

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("reasoning_effort") == "medium"


# ---------------------------------------------------------------------------
# Codex dispatch arm (epic consumer_lanes T6b)
# ---------------------------------------------------------------------------

_CODEX_LANE = Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")
_CODEX_LANE_RECORD = LaneRecord("codex", "chatgpt", "gpt-5-codex")  # the bound-lane manifest DTO
# prepare_codex_request is mocked in these tests, so billing_mode is never read off the preflight.
_READY_PREFLIGHT = SimpleNamespace(ready=True, blocking_reason=None)


_codex_result = partial(codex_result, label="curation", stdout="## Promote\n- Item")


def test_shadow_curation_consumer_allows_codex_lane() -> None:
    """T6b adds (does not replace) the codex lane: both claude-max and codex are valid."""
    lanes = valid_lanes(SHADOW_CURATION_CONSUMER)
    assert _CODEX_LANE in lanes
    assert Lane("claude_code", "claude-max", "opus") in lanes


class TestCodexShadowCuration:
    def _entries(self, root: Path) -> list[ShadowEntry]:
        return [ShadowEntry("docs/n.md", ".forge/memory/s.md", "generic", "s1", str(root), "content")]

    def _run(self, root: Path, **kwargs: Any):
        kwargs.setdefault("lane_record", _CODEX_LANE_RECORD)
        return run_shadow_curation(
            session_name="s1",
            forge_root=root,
            official_path="docs/n.md",
            official_content="# Notes",
            shadow_entries=self._entries(root),
            **kwargs,
        )

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_dispatches_through_invoker_and_persists_from_stdout(
        self,
        mock_read: MagicMock,
        mock_prepare: MagicMock,
        mock_invoker_cls: MagicMock,
        mock_claude: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Reads the cached preflight (no doctor), builds a read-only request, persists codex stdout."""
        mock_read.return_value = _READY_PREFLIGHT
        mock_invoker_cls.return_value.run.return_value = _codex_result(stdout="## Promote\n- From codex")

        result = self._run(tmp_path)

        # Cached read (no `codex doctor` in the path), invoker ran once, claude never touched.
        mock_read.assert_called_once_with()
        mock_invoker_cls.return_value.run.assert_called_once()
        mock_claude.assert_not_called()
        # Read-only sandbox, no model pin (codex picks its own), self-contained prompt at forge_root.
        assert mock_prepare.call_args.kwargs["sandbox"] == "read-only"
        assert mock_prepare.call_args.kwargs["model"] is None
        assert mock_prepare.call_args.kwargs["cwd"] == str(tmp_path)
        # Report persisted from codex stdout.
        assert result.success
        assert result.report_path is not None and result.report_path.exists()
        assert "From codex" in result.report_path.read_text(encoding="utf-8")
        assert result.error is None

    @patch("forge.core.usage.emit_usage_for_session_result")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_pins_operation_and_skips_claude_emitter(
        self,
        mock_read: MagicMock,
        mock_prepare: MagicMock,
        mock_invoker_cls: MagicMock,
        mock_emit: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Single emitter: the codex path never calls the claude-arm emitter; the Attribution it hands
        the invoker pins operation="memory.shadow_curation" so the auto-recorded upstream row matches
        the claude path (NOT the workflow.worker default, NOT None like the supervisor arm)."""
        mock_read.return_value = _READY_PREFLIGHT
        mock_invoker_cls.return_value.run.return_value = _codex_result()

        self._run(tmp_path)

        mock_emit.assert_not_called()
        attribution = mock_prepare.call_args.kwargs["attribution"]
        assert attribution.command == "curation"
        assert attribution.session == "s1"
        assert attribution.operation == "memory.shadow_curation"

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight", return_value=None)
    def test_cold_preflight_fails_loud_no_fallback_no_freeze(
        self,
        mock_read: MagicMock,
        mock_invoker_cls: MagicMock,
        mock_claude: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A cold cache fails loud with the refresh hint, never falls back to claude, never spawns
        codex, and -- as a skip-return -- never freezes the lane."""
        freeze = MagicMock()
        result = self._run(tmp_path, on_dispatch=freeze)

        assert result.success is False
        assert result.report_path is None
        assert result.error is not None
        assert "forge runtime preflight codex" in result.error
        mock_claude.assert_not_called()
        mock_invoker_cls.return_value.run.assert_not_called()
        freeze.assert_not_called()

    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_unready_preflight_surfaces_blocking_reason(
        self, mock_read: MagicMock, mock_invoker_cls: MagicMock, tmp_path: Path
    ) -> None:
        mock_read.return_value = SimpleNamespace(ready=False, blocking_reason="codex not installed")

        result = self._run(tmp_path)

        assert result.success is False
        assert result.error is not None
        assert "codex not installed" in result.error
        assert "forge runtime preflight codex" in result.error
        mock_invoker_cls.return_value.run.assert_not_called()

    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_failed_turn_fails_loud_but_still_freezes(
        self,
        mock_read: MagicMock,
        mock_prepare: MagicMock,
        mock_invoker_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A non-zero codex turn fails loud, but the freeze still fires -- past the preflight gate the
        consumer genuinely dispatched on the codex lane (claude-arm parity)."""
        mock_read.return_value = _READY_PREFLIGHT
        mock_invoker_cls.return_value.run.return_value = _codex_result(returncode=1, stderr="boom", stdout="partial")
        freeze = MagicMock()

        result = self._run(tmp_path, on_dispatch=freeze)

        assert result.success is False
        assert result.report_path is None
        assert result.error is not None and "boom" in result.error
        freeze.assert_called_once()

    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_exit_zero_but_runtime_error_fails_loud(
        self,
        mock_read: MagicMock,
        mock_prepare: MagicMock,
        mock_invoker_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        """HeadlessResult.success is returncode-only; an exit-0 turn that reports an in-stream error
        (runtime_is_error) must still fail loud instead of persisting an empty report."""
        mock_read.return_value = _READY_PREFLIGHT
        mock_invoker_cls.return_value.run.return_value = _codex_result(
            returncode=0, runtime_is_error=True, stderr="model refused"
        )

        result = self._run(tmp_path)

        assert result.success is False
        assert result.report_path is None
        assert result.error is not None and "model refused" in result.error

    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.invoker.codex.prepare_codex_request")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_successful_dispatch_fires_freeze(
        self,
        mock_read: MagicMock,
        mock_prepare: MagicMock,
        mock_invoker_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_read.return_value = _READY_PREFLIGHT
        mock_invoker_cls.return_value.run.return_value = _codex_result()
        freeze = MagicMock()

        result = self._run(tmp_path, on_dispatch=freeze)

        assert result.success
        freeze.assert_called_once()

    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    @patch("forge.core.reactive.cost_tracking.track_verb_cost")
    @patch("forge.core.reactive.session_runner.run_claude_session")
    def test_claude_runtime_never_touches_codex(
        self,
        mock_claude: MagicMock,
        mock_cost: MagicMock,
        mock_read: MagicMock,
        tmp_path: Path,
    ) -> None:
        """The default claude_code runtime takes the existing claude path and never reads the codex
        preflight -- the codex branch is inert unless explicitly selected."""
        mock_claude.return_value = SessionResult(stdout="## Promote\n- Item", stderr="", returncode=0, run_id="r")

        result = run_shadow_curation(
            session_name="s1",
            forge_root=tmp_path,
            official_path="docs/n.md",
            official_content="# Notes",
            shadow_entries=self._entries(tmp_path),
        )

        assert result.success
        mock_claude.assert_called_once()
        mock_read.assert_not_called()

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.invoker.codex.CodexHeadlessInvoker")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_invalid_explicit_lane_fails_loud_no_dispatch_no_freeze(
        self,
        mock_read: MagicMock,
        mock_invoker_cls: MagicMock,
        mock_claude: MagicMock,
        tmp_path: Path,
    ) -> None:
        """A drifted/corrupt explicit binding (codex runtime paired with a non-codex backend) is not
        a declared candidate, so resolve_lane rejects it and curation fails loud as a no-call --
        never dispatching the wrong arm (mirrors the supervisor's resolve_lane guard). No freeze."""
        freeze = MagicMock()
        result = self._run(tmp_path, lane_record=LaneRecord("codex", "anthropic-direct", "opus"), on_dispatch=freeze)

        assert result.success is False
        assert result.report_path is None
        assert result.error is not None
        assert "invalid lane" in result.error
        assert "forge session lane" in result.error  # names the re-pin / clear recovery path
        mock_claude.assert_not_called()  # NOT a silent claude fallback
        mock_invoker_cls.return_value.run.assert_not_called()  # codex never spawned
        mock_read.assert_not_called()  # never reached arm selection
        freeze.assert_not_called()  # validation precedes on_dispatch -> no freeze on an invalid lane

    @patch("forge.core.reactive.session_runner.run_claude_session")
    @patch("forge.core.runtime.codex_preflight_cache.read_fresh_codex_preflight")
    def test_unknown_runtime_fails_loud_not_silent_claude(
        self, mock_read: MagicMock, mock_claude: MagicMock, tmp_path: Path
    ) -> None:
        """An unknown runtime in a stale binding must fail loud, NOT silently fall through to the
        claude arm -- the pre-fix hazard of selecting the arm from a raw, unvalidated runtime_id."""
        result = self._run(tmp_path, lane_record=LaneRecord("vllm", "chatgpt", "gpt-5-codex"))

        assert result.success is False
        assert result.error is not None
        assert "invalid lane" in result.error
        mock_claude.assert_not_called()
        mock_read.assert_not_called()
