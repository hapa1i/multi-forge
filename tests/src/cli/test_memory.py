"""Tests for ``forge memory`` top-level commands (Phase 2 of memory enhancement)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def seeded_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    """Create a Forge project with a session and test docs."""
    from forge.session import IndexStore, SessionStore, create_session_state

    forge_root = tmp_path / "project"
    forge_root.mkdir()
    for rel in (
        "docs/checklist.md",
        "docs/changelog.md",
        "docs/impl_notes.md",
        "docs/coding-standards.md",
        "docs/a.md",
        "docs/b.md",
        ".forge/memory/suggested.md",
    ):
        target = forge_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Test doc\n", encoding="utf-8")

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

    monkeypatch.setenv("FORGE_SESSION", "s1")
    monkeypatch.chdir(forge_root)
    return forge_root, "s1"


# ---------------------------------------------------------------------------
# enable
# ---------------------------------------------------------------------------


class TestMemoryEnable:
    def test_enable_sets_auto_update(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "enable"])
        assert result.exit_code == 0, result.output
        assert "enabled" in result.output
        assert "augment" in result.output

    def test_enable_idempotent(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "enable"])
        result = runner.invoke(main, ["memory", "enable"])
        assert result.exit_code == 0, result.output
        assert "already enabled" in result.output

    def test_enable_review_only(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "enable", "--review-only"])
        assert result.exit_code == 0, result.output
        assert "review-only" in result.output

    def test_enable_changes_mode_message(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "enable"])
        result = runner.invoke(main, ["memory", "enable", "--review-only"])
        assert result.exit_code == 0, result.output
        assert "mode changed" in result.output
        assert "augment -> review-only" in result.output

    def test_enable_shows_no_docs_hint(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "enable"])
        assert result.exit_code == 0, result.output
        assert "No docs tracked" in result.output

    def test_enable_shows_tracked_docs_count(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        # Re-enable to see the count
        result = runner.invoke(main, ["memory", "enable", "--review-only"])
        assert result.exit_code == 0, result.output
        assert "1 doc(s)" in result.output


# ---------------------------------------------------------------------------
# track
# ---------------------------------------------------------------------------


class TestMemoryTrack:
    def test_track_creates_entry(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        assert result.exit_code == 0, result.output
        assert "Tracking" in result.output
        assert "checklist" in result.output

        listed = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(listed.output)
        paths = [d["path"] for d in docs]
        assert "docs/checklist.md" in paths

    def test_track_synthesizes_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])

        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/checklist.md")
        assert pp is not None
        assert pp.update.strategy == "checklist"
        assert pp.version == 1

    def test_track_without_passport_and_without_as_fails(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/checklist.md"])
        assert result.exit_code != 0
        assert "no passport" in result.output.lower()
        assert "--as" in result.output

    def test_track_with_existing_passport_uses_passport_strategy(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        forge_root = seeded_session[0]
        from forge.session.passport import synthesize_passport, write_passport

        pp = synthesize_passport(strategy="changelog")
        write_passport(forge_root / "docs/changelog.md", pp)

        result = runner.invoke(main, ["memory", "track", "docs/changelog.md"])
        assert result.exit_code == 0, result.output
        assert "changelog" in result.output

        listed = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(listed.output)
        match = [d for d in docs if d["path"] == "docs/changelog.md"]
        assert match[0]["strategy"] == "changelog"

    def test_track_as_flag_overrides_and_rewrites_passport(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        forge_root = seeded_session[0]
        from forge.session.passport import (
            read_passport,
            synthesize_passport,
            write_passport,
        )

        pp = synthesize_passport(strategy="changelog")
        write_passport(forge_root / "docs/changelog.md", pp)

        result = runner.invoke(main, ["memory", "track", "docs/changelog.md", "--as", "debugging"])
        assert result.exit_code == 0, result.output
        assert "Warning" in result.output
        assert "Passport updated" in result.output
        assert "Future sessions" in result.output

        # Verify passport on disk was rewritten
        reread = read_passport(forge_root / "docs/changelog.md")
        assert reread is not None
        assert reread.update.strategy == "debugging"

    def test_track_upsert_no_duplicate(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "debugging"])

        listed = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(listed.output)
        paths = [d["path"] for d in docs]
        assert paths.count("docs/checklist.md") == 1
        match = [d for d in docs if d["path"] == "docs/checklist.md"]
        assert match[0]["strategy"] == "debugging"

    def test_track_auto_enables_memory(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        assert result.exit_code == 0, result.output
        assert "auto-update enabled" in result.output.lower()

    def test_track_auto_enable_preserves_min_turns(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Leaf-key overrides preserve existing auto_update fields like min_turns."""
        from forge.core.ops.context import ExecutionContext
        from forge.core.ops.session import set_session_override

        ctx = ExecutionContext.from_cwd()
        set_session_override(ctx=ctx, session_name=None, key="memory.auto_update.min_turns", value_str="10")

        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])

        from forge.core.ops.session import resolve_session
        from forge.session.effective import compute_effective_intent

        resolved = resolve_session(ctx=ctx, session_name=None)
        effective = compute_effective_intent(resolved.state)
        assert effective.memory is not None
        assert effective.memory.auto_update is not None
        assert effective.memory.auto_update.enabled is True
        assert effective.memory.auto_update.min_turns == 10

    def test_track_rejects_shadow_only_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        from forge.session.passport import synthesize_passport, write_passport

        pp = synthesize_passport(
            strategy="suggested",
            update_mode="shadow-only",
            shadow_path=".forge/memory/suggested.md",
        )
        write_passport(forge_root / "docs/impl_notes.md", pp)

        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md"])
        assert result.exit_code != 0
        assert "shadow-only" in result.output
        assert "--propose" not in result.output

    def test_track_rejects_absolute_path(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "/etc/passwd", "--as", "generic"])
        assert result.exit_code != 0
        assert "Invalid path" in result.output

    def test_track_rejects_missing_file(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/nonexistent.md", "--as", "generic"])
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_track_rejects_invalid_strategy(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "invalid"])
        assert result.exit_code != 0

    def test_track_output_order(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Output: tracking result first, then passport notices, then auto-enable."""
        result = runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        assert result.exit_code == 0, result.output
        lines = result.output.strip().split("\n")
        tracking_idx = next(i for i, line in enumerate(lines) if "Tracking" in line)
        enable_idx = next(i for i, line in enumerate(lines) if "auto-update" in line.lower())
        assert tracking_idx < enable_idx

    def test_track_with_intent(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(
            main,
            ["memory", "track", "docs/checklist.md", "--as", "checklist", "--intent", "Active task tracking"],
        )

        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/checklist.md")
        assert pp is not None
        assert pp.intent == "Active task tracking"


# ---------------------------------------------------------------------------
# untrack
# ---------------------------------------------------------------------------


class TestMemoryUntrack:
    def test_untrack_removes_doc(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        result = runner.invoke(main, ["memory", "untrack", "docs/checklist.md"])
        assert result.exit_code == 0, result.output
        assert "Untracked" in result.output

        listed = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(listed.output)
        assert not any(d["path"] == "docs/checklist.md" for d in docs)

    def test_untrack_absent_path_succeeds(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "untrack", "docs/nonexistent.md"])
        assert result.exit_code == 0, result.output
        assert "Not tracked" in result.output

    def test_untrack_leaves_others(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/a.md", "--as", "generic"])
        runner.invoke(main, ["memory", "track", "docs/b.md", "--as", "generic"])
        runner.invoke(main, ["memory", "untrack", "docs/a.md"])

        listed = runner.invoke(main, ["memory", "list", "--json"])
        paths = [d["path"] for d in json.loads(listed.output)]
        assert paths == ["docs/b.md"]

    def test_untrack_leaves_passport_intact(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        runner.invoke(main, ["memory", "untrack", "docs/checklist.md"])

        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/checklist.md")
        assert pp is not None
        assert pp.update.strategy == "checklist"


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestMemoryList:
    def test_empty_list(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "No tracked" in result.output

    def test_populated_list(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "docs/checklist.md" in result.output
        assert "checklist" in result.output

    def test_json_output(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        result = runner.invoke(main, ["memory", "list", "--json"])
        assert result.exit_code == 0, result.output
        docs = json.loads(result.output)
        assert len(docs) == 1
        assert docs[0]["path"] == "docs/checklist.md"
        assert docs[0]["has_passport"] is True

    def test_legacy_docs_trigger_warning(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Docs added via old override path (no passport) trigger legacy warning."""
        from forge.core.ops.context import ExecutionContext
        from forge.core.ops.session import set_session_override

        ctx = ExecutionContext.from_cwd()
        payload = [{"path": "docs/checklist.md", "strategy": "checklist", "shadows": None}]
        set_session_override(ctx=ctx, session_name=None, key="memory.designated_docs", value_str=json.dumps(payload))

        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "no passport" in result.output.lower()
        assert "manifest-fallback" in result.output.lower()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestMemoryStatus:
    def test_scope_project_shows_docs(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        result = runner.invoke(main, ["memory", "status", "--scope", "project"])
        assert result.exit_code == 0, result.output
        assert "docs/checklist.md" in result.output

    def test_scope_project_empty(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "status", "--scope", "project"])
        assert result.exit_code == 0, result.output
        assert "No tracked" in result.output

    def test_doc_filter(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        runner.invoke(main, ["memory", "track", "docs/changelog.md", "--as", "changelog"])
        result = runner.invoke(main, ["memory", "status", "--doc", "docs/checklist.md"])
        assert result.exit_code == 0, result.output
        assert "docs/checklist.md" in result.output
        assert "docs/changelog.md" not in result.output

    def test_json_output_includes_forge_root(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        result = runner.invoke(main, ["memory", "status", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "entries" in data
        assert "scanned_roots" in data
        assert len(data["entries"]) == 1
        assert "forge_root" in data["entries"][0]
        assert "session" in data["entries"][0]

    def test_inaccessible_manifest_skipped(
        self, runner: CliRunner, seeded_session: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inaccessible manifests are skipped gracefully in status."""
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])

        from forge.session.manager import SessionManager

        original_get = SessionManager.get_session

        from typing import Any

        def failing_get(self: SessionManager, name: str, **kwargs: Any) -> Any:
            if name == "s1":
                from forge.session.exceptions import ForgeSessionError

                raise ForgeSessionError("simulated failure")
            return original_get(self, name, **kwargs)

        monkeypatch.setattr(SessionManager, "get_session", failing_get)

        result = runner.invoke(main, ["memory", "status", "--scope", "project"])
        assert result.exit_code == 0, result.output
        assert "No tracked" in result.output


# ---------------------------------------------------------------------------
# legacy detection
# ---------------------------------------------------------------------------


class TestLegacyDetection:
    def test_missing_passports_count_per_doc(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        from forge.core.ops.context import ExecutionContext
        from forge.core.ops.session import set_session_override

        ctx = ExecutionContext.from_cwd()
        payload = [
            {"path": "docs/a.md", "strategy": "generic", "shadows": None},
            {"path": "docs/b.md", "strategy": "generic", "shadows": None},
            {"path": "docs/checklist.md", "strategy": "checklist", "shadows": None},
        ]
        set_session_override(ctx=ctx, session_name=None, key="memory.designated_docs", value_str=json.dumps(payload))

        # Give one doc a passport
        from forge.session.passport import synthesize_passport, write_passport

        forge_root = seeded_session[0]
        pp = synthesize_passport(strategy="checklist")
        write_passport(forge_root / "docs/checklist.md", pp)

        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "2 of 3" in result.output
        assert "no passport" in result.output.lower()

    def test_malformed_passport_counted_separately(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        from forge.core.ops.context import ExecutionContext
        from forge.core.ops.session import set_session_override

        forge_root = seeded_session[0]
        ctx = ExecutionContext.from_cwd()
        payload = [
            {"path": "docs/a.md", "strategy": "generic", "shadows": None},
            {"path": "docs/b.md", "strategy": "generic", "shadows": None},
        ]
        set_session_override(ctx=ctx, session_name=None, key="memory.designated_docs", value_str=json.dumps(payload))

        # Write malformed passport
        (forge_root / "docs/a.md").write_text("---\nforge_memory:\n  version: 99\n---\n# Doc\n", encoding="utf-8")

        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "malformed" in result.output.lower()
        assert "1 of 2" in result.output

    def test_all_passported_no_warning(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "no passport" not in result.output.lower()
        assert "malformed" not in result.output.lower()

    def test_empty_docs_no_warning(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "Warning" not in result.output

    def test_shadow_doc_checks_official_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Legacy check uses resolve_passport_source() -- shadow entries check the official doc."""
        from forge.core.ops.context import ExecutionContext
        from forge.core.ops.session import set_session_override
        from forge.session.passport import synthesize_passport, write_passport

        forge_root = seeded_session[0]
        ctx = ExecutionContext.from_cwd()

        # Shadow entry: path is the shadow file, shadows is the official doc
        payload = [
            {
                "path": ".forge/memory/suggested.md",
                "strategy": "suggested",
                "shadows": "docs/coding-standards.md",
            }
        ]
        set_session_override(ctx=ctx, session_name=None, key="memory.designated_docs", value_str=json.dumps(payload))

        # Put passport on the official doc (not the shadow file)
        pp = synthesize_passport(
            strategy="suggested",
            update_mode="shadow-only",
            shadow_path=".forge/memory/suggested.md",
        )
        write_passport(forge_root / "docs/coding-standards.md", pp)

        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        # Should NOT warn -- passport exists on the official doc
        assert "no passport" not in result.output.lower()


# ---------------------------------------------------------------------------
# alias
# ---------------------------------------------------------------------------


class TestAlias:
    def test_mem_alias(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["mem", "list"])
        assert result.exit_code == 0, result.output
