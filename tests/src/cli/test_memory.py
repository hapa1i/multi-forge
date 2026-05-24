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

    def test_track_shadow_only_passport_accepted(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Shadow-only passport without --propose is accepted using the passport's shadow_path."""
        forge_root = seeded_session[0]
        from forge.session.passport import synthesize_passport, write_passport

        pp = synthesize_passport(
            strategy="suggested",
            update_mode="shadow-only",
            shadow_path=".forge/memory/suggested.md",
        )
        write_passport(forge_root / "docs/impl_notes.md", pp)

        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "shadow proposal" in result.output
        # Verify manifest entry uses the passport's shadow_path
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(list_result.output)
        shadow_entries = [d for d in docs if d.get("shadows") == "docs/impl_notes.md"]
        assert len(shadow_entries) == 1
        assert shadow_entries[0]["path"] == ".forge/memory/suggested.md"

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
# track --propose
# ---------------------------------------------------------------------------


class TestMemoryTrackPropose:
    def test_propose_derives_shadow_path(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        assert "shadow proposal" in result.output
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(list_result.output)
        shadow = [d for d in docs if d.get("shadows") == "docs/impl_notes.md"]
        assert len(shadow) == 1
        assert shadow[0]["path"] == ".forge/memory/suggested_docs_impl_notes.md"

    def test_propose_auto_creates_shadow_file(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        derived = ".forge/memory/suggested_docs_impl_notes.md"
        assert not (forge_root / derived).exists()
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        assert (forge_root / derived).is_file()
        assert "Shadow file created" in result.output

    def test_propose_creates_shadow_only_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None
        assert pp.update.mode == "shadow-only"
        assert pp.update.strategy == "suggested"
        assert pp.update.shadow_path == ".forge/memory/suggested_docs_impl_notes.md"

    def test_propose_implies_suggested_strategy(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(list_result.output)
        shadow = [d for d in docs if d.get("shadows")]
        assert shadow[0]["strategy"] == "suggested"

    def test_propose_with_as_suggested_compatible(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose", "--as", "suggested"])
        assert result.exit_code == 0, result.output

    def test_propose_with_as_nonsuggested_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose", "--as", "checklist"])
        assert result.exit_code != 0
        assert "suggested" in result.output

    def test_propose_with_shadow_override(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        custom = ".forge/memory/custom_shadow.md"
        (forge_root / custom).parent.mkdir(parents=True, exist_ok=True)
        (forge_root / custom).write_text("", encoding="utf-8")
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose", "--shadow", custom])
        assert result.exit_code == 0, result.output
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(list_result.output)
        shadow = [d for d in docs if d.get("shadows") == "docs/impl_notes.md"]
        assert shadow[0]["path"] == custom

    def test_shadow_without_propose_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--shadow", ".forge/memory/x.md"])
        assert result.exit_code != 0
        assert "--propose" in result.output

    def test_propose_does_not_autocreate_non_forge_paths(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        result = runner.invoke(
            main, ["memory", "track", "docs/impl_notes.md", "--propose", "--shadow", "docs/nonexistent.md"]
        )
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_propose_converts_direct_to_shadow(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--as", "generic"])
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        assert "Converting direct tracking" in result.output
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(list_result.output)
        assert len(docs) == 1
        assert docs[0]["shadows"] == "docs/impl_notes.md"

    def test_propose_auto_enables_memory(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        assert "auto-update enabled" in result.output

    def test_propose_output_mentions_shadow(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        assert "through shadow proposal" in result.output

    def test_propose_with_intent(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(
            main,
            ["memory", "track", "docs/impl_notes.md", "--propose", "--intent", "Durable memory"],
        )
        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None
        assert pp.intent == "Durable memory"

    def test_propose_upsert_updates_shadow_entry(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        custom = ".forge/memory/new_shadow.md"
        (forge_root / custom).parent.mkdir(parents=True, exist_ok=True)
        (forge_root / custom).write_text("", encoding="utf-8")
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose", "--shadow", custom])
        assert result.exit_code == 0, result.output
        assert "Updated tracking" in result.output
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(list_result.output)
        assert len(docs) == 1
        assert docs[0]["path"] == custom

    def test_auto_create_rejects_traversal(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main,
            ["memory", "track", "docs/impl_notes.md", "--propose", "--shadow", ".forge/memory/../../etc/passwd"],
        )
        assert result.exit_code != 0

    def test_propose_derived_collision_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Two official docs with the same parent+stem collide on derived shadow path."""
        forge_root = seeded_session[0]
        (forge_root / "other/docs").mkdir(parents=True, exist_ok=True)
        (forge_root / "other/docs/impl_notes.md").write_text("# Other\n", encoding="utf-8")
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        result = runner.invoke(main, ["memory", "track", "other/docs/impl_notes.md", "--propose"])
        assert result.exit_code != 0
        assert "--shadow" in result.output

    def test_propose_explicit_shadow_collision_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        used_shadow = json.loads(list_result.output)[0]["path"]
        result = runner.invoke(main, ["memory", "track", "docs/changelog.md", "--propose", "--shadow", used_shadow])
        assert result.exit_code != 0
        assert "--shadow" in result.output

    def test_propose_self_shadow_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main, ["memory", "track", "docs/impl_notes.md", "--propose", "--shadow", "docs/impl_notes.md"]
        )
        assert result.exit_code != 0
        assert "same as the official" in result.output


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
# untrack (shadow)
# ---------------------------------------------------------------------------


class TestMemoryUntrackShadow:
    def test_untrack_by_official_path(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        result = runner.invoke(main, ["memory", "untrack", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "Untracked" in result.output
        listed = runner.invoke(main, ["memory", "list", "--json"])
        assert json.loads(listed.output) == []

    def test_untrack_by_shadow_path(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        shadow_path = json.loads(list_result.output)[0]["path"]
        result = runner.invoke(main, ["memory", "untrack", shadow_path])
        assert result.exit_code == 0, result.output
        assert "Untracked" in result.output
        listed = runner.invoke(main, ["memory", "list", "--json"])
        assert json.loads(listed.output) == []

    def test_untrack_shadow_leaves_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        runner.invoke(main, ["memory", "untrack", "docs/impl_notes.md"])
        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None
        assert pp.update.mode == "shadow-only"


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

    def test_list_shows_shadow_target(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        result = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(result.output)
        assert docs[0]["shadows"] == "docs/impl_notes.md"

    def test_list_json_includes_shadows_field(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        result = runner.invoke(main, ["memory", "list", "--json"])
        docs = json.loads(result.output)
        assert "shadows" in docs[0]
        assert docs[0]["shadows"] is None

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

    def test_status_doc_filter_matches_shadow_target(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        result = runner.invoke(main, ["memory", "status", "--doc", "docs/impl_notes.md", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["shadows"] == "docs/impl_notes.md"

    def test_status_json_includes_shadows_field(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--as", "checklist"])
        result = runner.invoke(main, ["memory", "status", "--json"])
        data = json.loads(result.output)
        assert "shadows" in data["entries"][0]


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
# shadows list/show
# ---------------------------------------------------------------------------


class TestMemoryShadowsList:
    def test_empty_shadows(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "shadows", "list"])
        assert result.exit_code == 0, result.output
        assert "No shadow" in result.output

    def test_shadows_list_shows_entries(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        result = runner.invoke(main, ["memory", "shadows", "list"])
        assert result.exit_code == 0, result.output
        assert "docs/impl_notes.md" in result.output

    def test_shadows_list_json(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        result = runner.invoke(main, ["memory", "shadows", "list", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["official"] == "docs/impl_notes.md"
        assert "sessions" in data[0]
        assert "forge_root" in data[0]

    def test_shadows_list_groups_by_official(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        runner.invoke(main, ["memory", "track", "docs/changelog.md", "--propose"])
        result = runner.invoke(main, ["memory", "shadows", "list", "--json"])
        data = json.loads(result.output)
        assert len(data) == 2
        officials = {d["official"] for d in data}
        assert "docs/impl_notes.md" in officials
        assert "docs/changelog.md" in officials

    def test_shadows_list_scope_project(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        result = runner.invoke(main, ["memory", "shadows", "list", "--scope", "project", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data) == 1


class TestMemoryShadowsShow:
    def test_show_no_match(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "shadows", "show", "--for", "docs/nonexistent.md"])
        assert result.exit_code == 0, result.output
        assert "No shadow" in result.output

    def test_show_prints_content(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        # Write content to the shadow file
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        shadow_path = json.loads(list_result.output)[0]["path"]
        (forge_root / shadow_path).write_text("- [ ] Add error handling notes\n", encoding="utf-8")

        result = runner.invoke(main, ["memory", "shadows", "show", "--for", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "error handling" in result.output

    def test_show_missing_shadow_file(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        shadow_path = json.loads(list_result.output)[0]["path"]
        (forge_root / shadow_path).unlink()

        result = runner.invoke(main, ["memory", "shadows", "show", "--for", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "does not exist" in result.output


# ---------------------------------------------------------------------------
# shadows review
# ---------------------------------------------------------------------------


class TestShadowsReview:
    def test_review_without_curate_shows_raw_with_hint(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        # Write content to shadow
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        shadow_path = json.loads(list_result.output)[0]["path"]
        (forge_root / shadow_path).write_text("- [ ] Add caching notes\n", encoding="utf-8")

        result = runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "caching notes" in result.output
        assert "--curate" in result.output
        assert "--show-latest" in result.output

    def test_review_curate_requires_session(
        self, runner: CliRunner, seeded_session: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        result = runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/notes.md", "--curate"])
        assert result.exit_code != 0
        assert "session" in result.output.lower()

    def test_review_curate_and_show_latest_exclusive(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main, ["memory", "shadows", "review", "--for", "docs/notes.md", "--curate", "--show-latest"]
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_review_scope_all_curate_rejected(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main, ["memory", "shadows", "review", "--for", "docs/notes.md", "--curate", "--scope", "all"]
        )
        assert result.exit_code != 0
        assert "deferred" in result.output.lower()

    def test_review_show_latest_requires_session(
        self, runner: CliRunner, seeded_session: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        result = runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/notes.md", "--show-latest"])
        assert result.exit_code != 0
        assert "session" in result.output.lower()

    def test_review_show_latest_rejects_scope_repo(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main, ["memory", "shadows", "review", "--for", "docs/notes.md", "--show-latest", "--scope", "repo"]
        )
        assert result.exit_code != 0
        assert "not applicable" in result.output.lower()

    def test_review_show_latest_filters_by_doc(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        from forge.session.shadow_curation import persist_curation_report

        # Create reports for two different docs
        persist_curation_report(
            forge_root=forge_root,
            session_name="s1",
            official_path="docs/impl_notes.md",
            scope="project",
            shadow_count=1,
            content="Notes curation result.",
        )
        persist_curation_report(
            forge_root=forge_root,
            session_name="s1",
            official_path="docs/other.md",
            scope="project",
            shadow_count=1,
            content="Other curation result.",
        )

        result = runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--show-latest"])
        assert result.exit_code == 0, result.output
        assert "Notes curation result" in result.output
        assert "Other curation" not in result.output

    def test_review_show_latest_no_reports(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--show-latest"])
        assert result.exit_code == 0, result.output
        assert "No curation reports" in result.output
        assert "--curate" in result.output

    def test_review_curate_no_shadows(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--curate"])
        assert result.exit_code == 0, result.output
        assert "No shadow" in result.output

    def test_review_curate_does_not_mutate_official(
        self, runner: CliRunner, seeded_session: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        # Write shadow content
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        shadow_path = json.loads(list_result.output)[0]["path"]
        (forge_root / shadow_path).write_text("- [ ] Add new note\n", encoding="utf-8")

        official_before = (forge_root / "docs/impl_notes.md").read_text()

        # Mock run_claude_session to avoid real LLM call
        mock_result = type(
            "R",
            (),
            {
                "success": True,
                "returncode": 0,
                "timed_out": False,
                "error": None,
                "stdout": "## Promote\n- Item",
                "stderr": "",
            },
        )()
        monkeypatch.setattr(
            "forge.core.reactive.session_runner.run_claude_session",
            lambda *a, **kw: mock_result,
        )

        runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--curate"])

        official_after = (forge_root / "docs/impl_notes.md").read_text()
        assert official_before == official_after

    def test_review_curate_json_output(
        self, runner: CliRunner, seeded_session: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        list_result = runner.invoke(main, ["memory", "list", "--json"])
        shadow_path = json.loads(list_result.output)[0]["path"]
        (forge_root / shadow_path).write_text("- [ ] Item\n", encoding="utf-8")

        mock_result = type(
            "R",
            (),
            {
                "success": True,
                "returncode": 0,
                "timed_out": False,
                "error": None,
                "stdout": "## Promote\n- Item",
                "stderr": "",
            },
        )()
        monkeypatch.setattr(
            "forge.core.reactive.session_runner.run_claude_session",
            lambda *a, **kw: mock_result,
        )

        result = runner.invoke(
            main, ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--curate", "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["official"] == "docs/impl_notes.md"
        assert "report_path" in data
        assert data["shadow_count"] == 1

    def test_review_scope_repo_reads_official_from_session_root(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two forge roots in the same repo. --scope repo collects shadows from
        both, but the official doc baseline comes from the resolved session's root."""
        import subprocess

        from forge.session import IndexStore, SessionStore, create_session_state
        from forge.session.models import DesignatedDoc, MemoryIntent

        project_root = tmp_path

        # Need a git repo so ExecutionContext.from_cwd derives project_root correctly
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
            capture_output=True,
            check=True,
            env={
                **__import__("os").environ,
                "GIT_AUTHOR_NAME": "test",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "test",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )

        # Root A: the session we'll curate from
        root_a = tmp_path / "root_a"
        root_a.mkdir()
        (root_a / ".forge").mkdir(parents=True)
        (root_a / "docs").mkdir()
        (root_a / "docs" / "notes.md").write_text("# Official from root_a\n", encoding="utf-8")

        state_a = create_session_state(
            "sess-a",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(root_a),
        )
        state_a.forge_root = str(root_a)
        SessionStore(str(root_a), "sess-a").write(state_a)

        # Root B: a sibling with its own shadow and a different official doc
        root_b = tmp_path / "root_b"
        root_b.mkdir()
        (root_b / ".forge" / "memory").mkdir(parents=True)
        (root_b / "docs").mkdir()
        (root_b / "docs" / "notes.md").write_text("# Different official from root_b\n", encoding="utf-8")
        (root_b / ".forge" / "memory" / "suggested_notes.md").write_text("- [ ] Shadow from root_b\n", encoding="utf-8")

        state_b = create_session_state(
            "sess-b",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(root_b),
        )
        state_b.forge_root = str(root_b)
        store_b = SessionStore(str(root_b), "sess-b")
        store_b.write(state_b)
        manifest_b = store_b.read()
        manifest_b.intent.memory = MemoryIntent()
        manifest_b.intent.memory.designated_docs.append(
            DesignatedDoc(
                path=".forge/memory/suggested_notes.md",
                strategy="suggested",
                shadows="docs/notes.md",
            )
        )
        store_b.write(manifest_b)

        # Register both sessions in the global index under the same project_root
        index = IndexStore()
        for name, root in [("sess-a", root_a), ("sess-b", root_b)]:
            index.add_session(
                name=name,
                worktree_path=str(root),
                project_root=str(project_root),
                forge_root=str(root),
                checkout_root=str(root),
                relative_path=".",
                is_incognito=False,
                is_fork=False,
                parent_session=None,
            )

        monkeypatch.setenv("FORGE_SESSION", "sess-a")
        monkeypatch.chdir(root_a)

        # Mock the LLM call, capture the prompt to verify official content source
        captured_prompts: list[str] = []

        def fake_run(prompt: str, **kw):
            captured_prompts.append(prompt)
            return type(
                "R",
                (),
                {
                    "success": True,
                    "returncode": 0,
                    "timed_out": False,
                    "error": None,
                    "stdout": "## Promote\n- Item from root_b",
                    "stderr": "",
                },
            )()

        monkeypatch.setattr("forge.core.reactive.session_runner.run_claude_session", fake_run)

        result = runner.invoke(
            main, ["memory", "shadows", "review", "--for", "docs/notes.md", "--curate", "--scope", "repo"]
        )
        assert result.exit_code == 0, result.output

        # The prompt must contain root_a's official content, not root_b's
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "Official from root_a" in prompt
        assert "Different official from root_b" not in prompt
        # But the shadow from root_b should be included
        assert "Shadow from root_b" in prompt


# ---------------------------------------------------------------------------
# alias
# ---------------------------------------------------------------------------


class TestAlias:
    def test_mem_alias(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["mem", "list"])
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# passport show
# ---------------------------------------------------------------------------


class TestPassportShow:
    def test_show_valid_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root, _ = seeded_session
        from forge.session.passport import synthesize_passport, write_passport

        pp = synthesize_passport(strategy="changelog")
        write_passport(forge_root / "docs/changelog.md", pp)

        result = runner.invoke(main, ["memory", "passport", "show", "docs/changelog.md"])
        assert result.exit_code == 0, result.output
        assert "changelog" in result.output
        assert "version" in result.output
        assert "intent" in result.output

    def test_show_json_output(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root, _ = seeded_session
        from forge.session.passport import synthesize_passport, write_passport

        pp = synthesize_passport(strategy="checklist")
        write_passport(forge_root / "docs/checklist.md", pp)

        result = runner.invoke(main, ["memory", "passport", "show", "docs/checklist.md", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["version"] == 1
        assert data["update"]["strategy"] == "checklist"
        assert "intent" in data
        assert isinstance(data["captures"], list)

    def test_show_no_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "passport", "show", "docs/checklist.md"])
        assert result.exit_code == 0, result.output
        assert "No passport" in result.output
        assert "--as" in result.output

    def test_show_no_passport_json(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "passport", "show", "docs/checklist.md", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {
            "success": False,
            "reason": "no_passport",
            "path": "docs/checklist.md",
            "tip": "forge memory track docs/checklist.md --as <strategy>",
        }

    def test_show_file_not_found(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "passport", "show", "docs/nonexistent.md"])
        assert result.exit_code != 0
        assert "not found" in (result.output or "").lower()

    def test_show_malformed_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root, _ = seeded_session
        (forge_root / "docs/checklist.md").write_text(
            "---\nforge_memory:\n  version: 99\n---\n# Doc\n", encoding="utf-8"
        )
        result = runner.invoke(main, ["memory", "passport", "show", "docs/checklist.md"])
        assert result.exit_code != 0
