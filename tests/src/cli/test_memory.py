"""Tests for ``forge memory`` top-level commands."""

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
        "docs/coding_standards.md",
        "docs/a.md",
        "docs/b.md",
        ".forge/memory/shadow_impl_notes.md",
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
# track
# ---------------------------------------------------------------------------


class TestMemoryTrack:
    def test_track_help_documents_intent_and_writer_formats(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["memory", "track", "--help"])
        output = " ".join(result.output.split())

        assert result.exit_code == 0
        assert "why this doc is memory" in output
        assert "all-sessions or comma-separated session names" in output

    def test_track_writes_passport_no_manifest(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """track authors a project-lifetime passport and writes no session participation."""
        forge_root = seeded_session[0]
        from forge.session.passport import read_passport
        from forge.session.store import SessionStore

        result = runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "checklist"])
        assert result.exit_code == 0, result.output
        assert "Passport created" in result.output

        pp = read_passport(forge_root / "docs/checklist.md")
        assert pp is not None and pp.update.strategy == "checklist"

        state = SessionStore(str(forge_root), "s1").read()
        assert "memory" not in state.overrides

    def test_track_refuses_incompatible_project_without_editing_doc(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        forge_root = seeded_session[0]
        doc = forge_root / "docs/checklist.md"
        before = doc.read_bytes()
        (forge_root / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "checklist"])

        assert result.exit_code == 1
        assert "requires Forge" in result.output
        assert doc.read_bytes() == before

    def test_track_ignores_ambient_session(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Fixture sets FORGE_SESSION=s1; bare track must not write session state."""
        forge_root = seeded_session[0]
        from forge.session.store import SessionStore

        result = runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "checklist"])
        assert result.exit_code == 0, result.output
        state = SessionStore(str(forge_root), "s1").read()
        assert "memory" not in state.overrides

    def test_track_synthesizes_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "checklist"])

        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/checklist.md")
        assert pp is not None
        assert pp.update.strategy == "checklist"
        assert pp.version == 1

    def test_track_without_passport_and_without_strategy_fails(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/checklist.md"])
        assert result.exit_code != 0
        assert "no passport" in result.output.lower()
        assert "--strategy" in result.output

    def test_track_existing_passport_no_op(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """track on an already-passported doc with no flags is a legible no-op (exit 0)."""
        forge_root = seeded_session[0]
        from forge.session.passport import synthesize_passport, write_passport

        write_passport(forge_root / "docs/changelog.md", synthesize_passport(strategy="changelog"))

        result = runner.invoke(main, ["memory", "track", "docs/changelog.md"])
        assert result.exit_code == 0, result.output
        assert "already present" in result.output.lower()
        assert "changelog" in result.output

    def test_track_strategy_flag_overrides_and_rewrites_passport(
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

        result = runner.invoke(main, ["memory", "track", "docs/changelog.md", "--strategy", "checklist"])
        assert result.exit_code == 0, result.output
        assert "Warning" in result.output
        assert "Passport updated" in result.output
        assert "Future sessions" in result.output

        # Verify passport on disk was rewritten
        reread = read_passport(forge_root / "docs/changelog.md")
        assert reread is not None
        assert reread.update.strategy == "checklist"

    def test_track_rewrite_is_idempotent_at_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Re-running track updates the passport in place; never writes a manifest entry."""
        forge_root = seeded_session[0]
        from forge.session.passport import read_passport
        from forge.session.store import SessionStore

        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "checklist"])
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "changelog"])

        pp = read_passport(forge_root / "docs/checklist.md")
        assert pp is not None and pp.update.strategy == "changelog"

        state = SessionStore(str(forge_root), "s1").read()
        assert "memory" not in state.overrides

    def test_track_warns_out_of_root(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """A passported doc outside the scan roots warns it won't be project-discovered."""
        forge_root = seeded_session[0]
        (forge_root / "notes.md").write_text("# Top-level\n", encoding="utf-8")
        result = runner.invoke(main, ["memory", "track", "notes.md", "--strategy", "generic"])
        assert result.exit_code == 0, result.output
        assert "outside" in result.output
        assert "scan roots" in result.output
        from forge.session.passport import read_passport

        assert read_passport(forge_root / "notes.md") is not None

    def test_track_shadow_only_passport_accepted(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Shadow-only passport without --propose: shadow file ensured, no manifest entry."""
        forge_root = seeded_session[0]
        from forge.session.passport import synthesize_passport, write_passport

        pp = synthesize_passport(
            strategy="generic",
            update_mode="shadow-only",
            shadow_path=".forge/memory/shadow_impl_notes.md",
        )
        write_passport(forge_root / "docs/impl_notes.md", pp)

        # Ensure the shadow file exists
        (forge_root / ".forge/memory/shadow_impl_notes.md").parent.mkdir(parents=True, exist_ok=True)
        (forge_root / ".forge/memory/shadow_impl_notes.md").write_text("", encoding="utf-8")

        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "shadow-only" in result.output
        assert (forge_root / ".forge/memory/shadow_impl_notes.md").is_file()

    def test_track_rejects_absolute_path(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "/etc/passwd", "--strategy", "generic"])
        assert result.exit_code != 0
        assert "Invalid path" in result.output

    def test_track_rejects_missing_file(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/nonexistent.md", "--strategy", "generic"])
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_track_rejects_invalid_strategy(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "invalid"])
        assert result.exit_code != 0

    def test_track_with_intent(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/checklist.md",
                "--strategy",
                "checklist",
                "--intent",
                "Active task tracking",
            ],
        )

        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/checklist.md")
        assert pp is not None
        assert pp.intent == "Active task tracking"


# ---------------------------------------------------------------------------
# track --propose
# ---------------------------------------------------------------------------


class TestMemoryTrackPropose:
    DERIVED = ".forge/memory/shadow_docs_impl_notes.md"

    def test_propose_derives_shadow_path(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        from forge.session.passport import read_passport

        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None and pp.update.shadow_path == self.DERIVED
        # Discoverable via passport scan (no manifest needed).
        shadows = runner.invoke(main, ["memory", "shadows", "list", "--json"])
        data = json.loads(shadows.output)
        assert any(d["official"] == "docs/impl_notes.md" for d in data)

    def test_propose_auto_creates_shadow_file(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        assert not (forge_root / self.DERIVED).exists()
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        assert (forge_root / self.DERIVED).is_file()
        assert "Shadow file created" in result.output

    def test_propose_creates_shadow_only_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None
        assert pp.update.mode == "shadow-only"
        assert pp.update.strategy == "generic"
        assert pp.update.shadow_path == self.DERIVED

    def test_propose_writes_no_manifest(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """propose is passport-only: it never writes session participation."""
        forge_root = seeded_session[0]
        from forge.session.store import SessionStore

        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        state = SessionStore(str(forge_root), "s1").read()
        assert "memory" not in state.overrides

    def test_propose_defaults_to_generic_strategy(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        from forge.session.passport import read_passport

        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None and pp.update.strategy == "generic"

    def test_propose_with_explicit_strategy(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        from forge.session.passport import read_passport

        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/impl_notes.md",
                "--propose",
                "--strategy",
                "changelog",
            ],
        )
        assert result.exit_code == 0, result.output
        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None
        assert pp.update.strategy == "changelog"
        assert pp.update.mode == "shadow-only"

    def test_propose_preserves_existing_passport_strategy(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        forge_root = seeded_session[0]
        from forge.session.passport import (
            read_passport,
            synthesize_passport,
            write_passport,
        )

        write_passport(forge_root / "docs/impl_notes.md", synthesize_passport(strategy="changelog"))

        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None
        assert pp.update.strategy == "changelog"
        assert pp.update.mode == "shadow-only"

    def test_propose_with_shadow_override(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        custom = ".forge/memory/custom_shadow.md"
        (forge_root / custom).parent.mkdir(parents=True, exist_ok=True)
        (forge_root / custom).write_text("", encoding="utf-8")
        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/impl_notes.md",
                "--propose",
                "--shadow-path",
                custom,
            ],
        )
        assert result.exit_code == 0, result.output
        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None and pp.update.shadow_path == custom

    def test_shadow_without_propose_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/impl_notes.md",
                "--shadow-path",
                ".forge/memory/x.md",
            ],
        )
        assert result.exit_code != 0
        assert "--propose" in result.output

    def test_propose_does_not_autocreate_non_forge_paths(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/impl_notes.md",
                "--propose",
                "--shadow-path",
                "docs/nonexistent.md",
            ],
        )
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_propose_converts_direct_to_shadow(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """A direct passport is converted to shadow-only by --propose."""
        forge_root = seeded_session[0]
        from forge.session.passport import read_passport

        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--strategy", "generic"])
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        assert "converted to shadow-only" in result.output
        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None and pp.update.mode == "shadow-only"

    def test_propose_output_mentions_shadow(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        assert result.exit_code == 0, result.output
        assert "shadow" in result.output.lower()
        assert self.DERIVED in result.output

    def test_propose_with_intent(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/impl_notes.md",
                "--propose",
                "--intent",
                "Durable memory",
            ],
        )
        from forge.session.passport import read_passport

        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None
        assert pp.intent == "Durable memory"

    def test_propose_upsert_updates_shadow_path(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        from forge.session.passport import read_passport

        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        custom = ".forge/memory/new_shadow.md"
        (forge_root / custom).parent.mkdir(parents=True, exist_ok=True)
        (forge_root / custom).write_text("", encoding="utf-8")
        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/impl_notes.md",
                "--propose",
                "--shadow-path",
                custom,
            ],
        )
        assert result.exit_code == 0, result.output
        pp = read_passport(forge_root / "docs/impl_notes.md")
        assert pp is not None and pp.update.shadow_path == custom

    def test_auto_create_rejects_traversal(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/impl_notes.md",
                "--propose",
                "--shadow-path",
                ".forge/memory/../../etc/passwd",
            ],
        )
        assert result.exit_code != 0

    def test_propose_derived_collision_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Two official docs with the same parent+stem collide on derived shadow path."""
        forge_root = seeded_session[0]
        # Both under docs/ so the collision scan sees the first one's passport.
        (forge_root / "docs/sub").mkdir(parents=True, exist_ok=True)
        (forge_root / "docs/sub/changelog.md").write_text("# Other\n", encoding="utf-8")
        runner.invoke(main, ["memory", "track", "docs/changelog.md", "--propose"])
        # docs/changelog.md -> shadow_docs_changelog.md; docs/sub/changelog.md -> shadow_sub_changelog.md.
        # Force a real collision with an explicit shadow path.
        used = ".forge/memory/shadow_docs_changelog.md"
        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/sub/changelog.md",
                "--propose",
                "--shadow-path",
                used,
            ],
        )
        assert result.exit_code != 0
        assert "--shadow-path" in result.output

    def test_propose_explicit_shadow_collision_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/changelog.md",
                "--propose",
                "--shadow-path",
                self.DERIVED,
            ],
        )
        assert result.exit_code != 0
        assert "--shadow-path" in result.output

    def test_propose_self_shadow_fails(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main,
            [
                "memory",
                "track",
                "docs/impl_notes.md",
                "--propose",
                "--shadow-path",
                "docs/impl_notes.md",
            ],
        )
        assert result.exit_code != 0
        assert "same as the official" in result.output


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestMemoryList:
    """list is now a sessionless passport scan under scan roots."""

    def test_list_empty(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "No passported" in result.output

    def test_list_shows_passported_docs(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "checklist"])
        result = runner.invoke(main, ["memory", "list"])
        assert result.exit_code == 0, result.output
        assert "docs/checklist.md" in result.output
        assert "checklist" in result.output

    def test_list_json(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["memory", "track", "docs/checklist.md", "--strategy", "checklist"])
        result = runner.invoke(main, ["memory", "list", "--json"])
        assert result.exit_code == 0, result.output
        docs = json.loads(result.output)
        assert len(docs) == 1
        assert docs[0]["path"] == "docs/checklist.md"
        assert docs[0]["strategy"] == "checklist"
        assert docs[0]["mode"] == "direct"
        assert docs[0]["writers"] == "all-sessions"

    def test_list_includes_all_writers(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Docs with restricted writers still appear (no writer filtering)."""
        forge_root = seeded_session[0]
        from forge.session.passport import synthesize_passport, write_passport

        write_passport(
            forge_root / "docs/checklist.md",
            synthesize_passport(strategy="checklist", writers="planner"),
        )
        result = runner.invoke(main, ["memory", "list", "--json"])
        assert result.exit_code == 0, result.output
        docs = json.loads(result.output)
        assert len(docs) == 1
        assert docs[0]["writers"] == "planner"


# ---------------------------------------------------------------------------
# shadows list/show
# ---------------------------------------------------------------------------


class TestMemoryShadowsList:
    def test_shadows_help_documents_scope_and_for_format(self, runner: CliRunner) -> None:
        list_help = runner.invoke(main, ["memory", "shadows", "list", "--help"])
        show_help = runner.invoke(main, ["memory", "shadows", "show", "--help"])
        review_help = runner.invoke(main, ["memory", "shadows", "review", "--help"])

        assert list_help.exit_code == 0
        assert "Scope for shadow discovery" in list_help.output
        assert show_help.exit_code == 0
        assert "docs/impl_notes.md" in show_help.output
        assert "Output as JSON" in show_help.output
        assert review_help.exit_code == 0
        assert "docs/impl_notes.md" in review_help.output
        assert "Scope for shadow discovery" in review_help.output

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
        shadow_path = ".forge/memory/shadow_docs_impl_notes.md"
        (forge_root / shadow_path).write_text("- [ ] Add error handling notes\n", encoding="utf-8")

        result = runner.invoke(main, ["memory", "shadows", "show", "--for", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "error handling" in result.output

    def test_show_missing_shadow_file(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        shadow_path = ".forge/memory/shadow_docs_impl_notes.md"
        (forge_root / shadow_path).unlink()

        result = runner.invoke(main, ["memory", "shadows", "show", "--for", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "does not exist" in result.output

    def test_show_json_no_match(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Unknown doc emits structured empty payload, not human text."""
        result = runner.invoke(
            main,
            ["memory", "shadows", "show", "--for", "docs/nonexistent.md", "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {
            "official": "docs/nonexistent.md",
            "scope": "project",
            "shadows": [],
        }

    def test_show_json_populated_readable(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """A real shadow file's content comes through with readable=true and reason=null."""
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        shadow_path = ".forge/memory/shadow_docs_impl_notes.md"
        (forge_root / shadow_path).write_text("- [ ] Add error handling notes\n", encoding="utf-8")

        result = runner.invoke(main, ["memory", "shadows", "show", "--for", "docs/impl_notes.md", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["official"] == "docs/impl_notes.md"
        assert data["scope"] == "project"
        shadows = data["shadows"]
        assert len(shadows) == 1
        row = shadows[0]
        assert set(row) == {
            "shadow_path",
            "forge_root",
            "sessions",
            "content",
            "readable",
            "reason",
        }
        assert row["shadow_path"] == shadow_path
        assert row["forge_root"] == str(forge_root)
        assert row["sessions"] == sorted(set(row["sessions"]))
        assert row["readable"] is True
        assert row["reason"] is None
        assert "Add error handling notes" in row["content"]

    def test_show_json_isolates_to_requested_official(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        """With two passported officials, --for selects only the matching shadow rows.

        collect_shadow_entries keys discovered shadows by (forge_root, shadow_path)
        with official = the passport's host doc, so each official yields one row;
        --for must filter to the requested doc, not bleed the sibling's shadow.
        """
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        runner.invoke(main, ["memory", "track", "docs/changelog.md", "--propose"])
        (forge_root / ".forge/memory/shadow_docs_impl_notes.md").write_text(
            "- [ ] Impl note source\n", encoding="utf-8"
        )
        (forge_root / ".forge/memory/shadow_docs_changelog.md").write_text("- [ ] Changelog source\n", encoding="utf-8")

        result = runner.invoke(main, ["memory", "shadows", "show", "--for", "docs/impl_notes.md", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["official"] == "docs/impl_notes.md"
        rows = data["shadows"]
        assert isinstance(rows, list)
        assert len(rows) == 1
        row = rows[0]
        assert set(row) == {
            "shadow_path",
            "forge_root",
            "sessions",
            "content",
            "readable",
            "reason",
        }
        assert row["shadow_path"] == ".forge/memory/shadow_docs_impl_notes.md"
        assert row["readable"] is True
        assert "Impl note source" in row["content"]
        # The sibling's shadow must not leak into this official's rows.
        assert "Changelog source" not in row["content"]

    def test_show_json_absent_file(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """A passported-but-absent shadow file reports content=null, readable=false, reason set."""
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        shadow_path = ".forge/memory/shadow_docs_impl_notes.md"
        (forge_root / shadow_path).unlink()

        result = runner.invoke(main, ["memory", "shadows", "show", "--for", "docs/impl_notes.md", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert len(data["shadows"]) == 1
        row = data["shadows"][0]
        assert row["content"] is None
        assert row["readable"] is False
        assert row["reason"] is not None
        assert "does not exist" in row["reason"]


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
        shadow_path = ".forge/memory/shadow_docs_impl_notes.md"
        (forge_root / shadow_path).write_text("- [ ] Add caching notes\n", encoding="utf-8")

        result = runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/impl_notes.md"])
        assert result.exit_code == 0, result.output
        assert "caching notes" in result.output
        assert "--curate" in result.output
        assert "--show-latest" in result.output

    def test_review_curate_requires_session(
        self,
        runner: CliRunner,
        seeded_session: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        result = runner.invoke(main, ["memory", "shadows", "review", "--for", "docs/notes.md", "--curate"])
        assert result.exit_code != 0
        assert "session" in result.output.lower()

    def test_review_curate_and_show_latest_exclusive(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/notes.md",
                "--curate",
                "--show-latest",
            ],
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output.lower()

    def test_review_scope_all_curate_rejected(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/notes.md",
                "--curate",
                "--scope",
                "all",
            ],
        )
        assert result.exit_code != 0
        assert "deferred" in result.output.lower()

    def test_review_show_latest_requires_session(
        self,
        runner: CliRunner,
        seeded_session: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        result = runner.invoke(
            main,
            ["memory", "shadows", "review", "--for", "docs/notes.md", "--show-latest"],
        )
        assert result.exit_code != 0
        assert "session" in result.output.lower()

    def test_review_show_latest_rejects_scope_workspace(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        result = runner.invoke(
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/notes.md",
                "--show-latest",
                "--scope",
                "workspace",
            ],
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

        result = runner.invoke(
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/impl_notes.md",
                "--show-latest",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Notes curation result" in result.output
        assert "Other curation" not in result.output

    def test_review_show_latest_no_reports(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/impl_notes.md",
                "--show-latest",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "No curation reports" in result.output
        assert "--curate" in result.output

    def test_review_show_latest_remains_readable_under_incompatible_pin(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        forge_root = seeded_session[0]
        (forge_root / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/impl_notes.md",
                "--show-latest",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "No curation reports" in result.output

    def test_review_curate_refuses_incompatible_target_before_dispatch(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        forge_root = seeded_session[0]
        (forge_root / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(
            main,
            ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--curate"],
        )

        assert result.exit_code == 1
        assert "requires Forge" in result.output

    def test_review_curate_no_shadows(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(
            main,
            ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--curate"],
        )
        assert result.exit_code == 0, result.output
        assert "No shadow" in result.output

    def test_review_curate_does_not_mutate_official(
        self,
        runner: CliRunner,
        seeded_session: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        # Write shadow content
        shadow_path = ".forge/memory/shadow_docs_impl_notes.md"
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

        runner.invoke(
            main,
            ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--curate"],
        )

        official_after = (forge_root / "docs/impl_notes.md").read_text()
        assert official_before == official_after

    def test_review_curate_json_output(
        self,
        runner: CliRunner,
        seeded_session: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        forge_root = seeded_session[0]
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        shadow_path = ".forge/memory/shadow_docs_impl_notes.md"
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
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/impl_notes.md",
                "--curate",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["official"] == "docs/impl_notes.md"
        assert "report_path" in data
        assert data["shadow_count"] == 1

    def _seed_shadow(self, runner: CliRunner, forge_root: Path) -> None:
        """Track impl_notes and write a shadow so --curate reaches the dispatch (past the no-shadows guard)."""
        runner.invoke(main, ["memory", "track", "docs/impl_notes.md", "--propose"])
        (forge_root / ".forge/memory/shadow_docs_impl_notes.md").write_text("- [ ] Item\n", encoding="utf-8")

    def test_review_curate_failure_surfaces_error_json(
        self,
        runner: CliRunner,
        seeded_session: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T6b/D5: a fail-loud CurationResult.error (e.g. cold codex preflight) is carried in --json,
        with exit 1 -- not dropped like it was before the error field existed."""
        from forge.session.shadow_curation import CurationResult

        self._seed_shadow(runner, seeded_session[0])
        hint = "Codex curation unavailable: no fresh preflight cached. Run 'forge runtime preflight codex' to refresh."
        monkeypatch.setattr(
            "forge.session.shadow_curation.run_shadow_curation",
            lambda *a, **kw: CurationResult(success=False, report_path=None, stdout="", error=hint),
        )

        result = runner.invoke(
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/impl_notes.md",
                "--curate",
                "--json",
            ],
        )
        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert data["success"] is False
        assert data["error"] == hint
        assert "forge runtime preflight codex" in data["error"]

    def test_review_curate_failure_surfaces_error_human(
        self,
        runner: CliRunner,
        seeded_session: tuple[Path, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """T6b/D5: the same hint reaches the human (non-JSON) failure output, so a user who bound codex
        and never refreshed the preflight sees the actionable fix, not just a bare 'Curation failed.'
        """
        from forge.session.shadow_curation import CurationResult

        self._seed_shadow(runner, seeded_session[0])
        hint = "Codex curation unavailable: no fresh preflight cached. Run 'forge runtime preflight codex' to refresh."
        monkeypatch.setattr(
            "forge.session.shadow_curation.run_shadow_curation",
            lambda *a, **kw: CurationResult(success=False, report_path=None, stdout="", error=hint),
        )

        result = runner.invoke(
            main,
            ["memory", "shadows", "review", "--for", "docs/impl_notes.md", "--curate"],
        )
        assert result.exit_code == 1, result.output
        # Rich soft-wraps at the harness's terminal width; normalize before matching the hint.
        assert "forge runtime preflight codex" in " ".join(result.output.split())

    def test_review_scope_workspace_reads_official_from_session_root(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two forge roots in the same repo. --scope workspace collects shadows from
        both, but the official doc baseline comes from the resolved session's root."""
        import subprocess

        from forge.session import IndexStore, SessionStore, create_session_state
        from forge.session.passport import synthesize_passport, write_passport

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

        # Root B: a sibling with its own shadow and a different official doc.
        # Shadow discovery uses passport scanning, so put a shadow-only passport
        # on root_b's official doc.
        root_b = tmp_path / "root_b"
        root_b.mkdir()
        (root_b / ".forge" / "memory").mkdir(parents=True)
        (root_b / "docs").mkdir()
        (root_b / "docs" / "notes.md").write_text("# Different official from root_b\n", encoding="utf-8")
        (root_b / ".forge" / "memory" / "shadow_notes.md").write_text("- [ ] Shadow from root_b\n", encoding="utf-8")

        write_passport(
            root_b / "docs" / "notes.md",
            synthesize_passport(
                strategy="generic",
                update_mode="shadow-only",
                shadow_path=".forge/memory/shadow_notes.md",
            ),
        )

        state_b = create_session_state(
            "sess-b",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(root_b),
        )
        state_b.forge_root = str(root_b)
        SessionStore(str(root_b), "sess-b").write(state_b)

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
            main,
            [
                "memory",
                "shadows",
                "review",
                "--for",
                "docs/notes.md",
                "--curate",
                "--scope",
                "workspace",
            ],
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
        assert "--strategy" in result.output

    def test_show_no_passport_json(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "passport", "show", "docs/checklist.md", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data == {
            "success": False,
            "reason": "no_passport",
            "path": "docs/checklist.md",
            "tip": "forge memory track docs/checklist.md --strategy <strategy>",
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


# ---------------------------------------------------------------------------
# passport remove
# ---------------------------------------------------------------------------


class TestPassportRemove:
    def test_remove_existing_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root, _ = seeded_session
        from forge.session.passport import (
            read_passport,
            synthesize_passport,
            write_passport,
        )

        write_passport(forge_root / "docs/checklist.md", synthesize_passport(strategy="checklist"))

        result = runner.invoke(main, ["memory", "passport", "remove", "docs/checklist.md"])
        assert result.exit_code == 0, result.output
        assert "Passport removed" in result.output
        assert read_passport(forge_root / "docs/checklist.md") is None

    def test_remove_refuses_incompatible_project_without_editing_doc(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        forge_root, _ = seeded_session
        from forge.session.passport import synthesize_passport, write_passport

        doc = forge_root / "docs/checklist.md"
        write_passport(doc, synthesize_passport(strategy="checklist"))
        before = doc.read_bytes()
        (forge_root / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8"
        )

        result = runner.invoke(main, ["memory", "passport", "remove", "docs/checklist.md"])

        assert result.exit_code == 1
        assert "requires Forge" in result.output
        assert doc.read_bytes() == before

    def test_remove_no_passport_is_noop(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "passport", "remove", "docs/checklist.md"])
        assert result.exit_code == 0, result.output
        assert "No passport" in result.output

    def test_remove_preserves_other_frontmatter(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root, _ = seeded_session
        (forge_root / "docs/checklist.md").write_text(
            "---\ntitle: Keep Me\nforge_memory:\n  version: 1\n  intent: Test\n---\n# Doc\n",
            encoding="utf-8",
        )

        result = runner.invoke(main, ["memory", "passport", "remove", "docs/checklist.md"])
        assert result.exit_code == 0, result.output
        text = (forge_root / "docs/checklist.md").read_text(encoding="utf-8")
        assert "title: Keep Me" in text
        assert "forge_memory" not in text
        assert "# Doc\n" in text

    def test_remove_schema_invalid_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root, _ = seeded_session
        (forge_root / "docs/checklist.md").write_text(
            "---\nforge_memory:\n  version: 99\n  intent: Newer\n---\n# Doc\n",
            encoding="utf-8",
        )

        result = runner.invoke(main, ["memory", "passport", "remove", "docs/checklist.md"])
        assert result.exit_code == 0, result.output
        assert (forge_root / "docs/checklist.md").read_text(encoding="utf-8") == "# Doc\n"

    def test_remove_malformed_yaml_errors(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root, _ = seeded_session
        (forge_root / "docs/checklist.md").write_text(
            "---\nforge_memory: [invalid: yaml\n---\n# Doc\n",
            encoding="utf-8",
        )

        result = runner.invoke(main, ["memory", "passport", "remove", "docs/checklist.md"])
        assert result.exit_code != 0
        assert "Malformed frontmatter" in result.output

    def test_remove_json(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        forge_root, _ = seeded_session
        from forge.session.passport import synthesize_passport, write_passport

        write_passport(forge_root / "docs/checklist.md", synthesize_passport(strategy="checklist"))

        result = runner.invoke(main, ["memory", "passport", "remove", "docs/checklist.md", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {
            "success": True,
            "removed": True,
            "path": "docs/checklist.md",
        }

    def test_remove_json_no_passport(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["memory", "passport", "remove", "docs/checklist.md", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {
            "success": False,
            "removed": False,
            "path": "docs/checklist.md",
            "reason": "no_passport",
        }
