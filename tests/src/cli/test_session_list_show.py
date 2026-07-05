"""Tests for session list and show CLI commands."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.active import ActiveSessionStore
from forge.session.models import (
    Derivation,
)
from tests.src.cli.session_command_support import (
    _BrokenActiveSessionStore,
    _proxy_cfg,
    _seed_cleanup_session,
    _seed_duplicate_list_sessions,
    _seed_scoped_duplicate_sessions,
    successful_claude_launch,
)


def test_resume_token_estimate_multiplier_skips_proxy_config_lookup(
    temp_env: Path,
) -> None:
    """Proxy-routed resume checks use the default tokenizer heuristic in v1."""
    from forge.cli import session_lifecycle

    parent = create_session_state("parent", worktree_path=str(temp_env))

    with patch(
        "forge.config.loader.load_proxy_instance_config",
        side_effect=AssertionError("unexpected proxy I/O"),
    ):
        multiplier = session_lifecycle._resume_token_estimate_multiplier(
            parent_state=parent,
            effective_proxy_ref="litellm-anthropic",
        )

    assert multiplier == 1.0


def test_resume_token_estimate_multiplier_uses_direct_pin(temp_env: Path) -> None:
    """Direct 4.8 resume checks keep the model-specific tokenizer margin."""
    from forge.cli import session_lifecycle

    parent = create_session_state("parent", worktree_path=str(temp_env), direct_model="claude-opus-4-8")

    multiplier = session_lifecycle._resume_token_estimate_multiplier(
        parent_state=parent,
        effective_proxy_ref=None,
    )

    assert multiplier == 1.35


def test_addendum_resolution_mixed_family_uses_claude_default() -> None:
    """Mixed proxy tiers should use the configured default tier, including None for Claude."""
    from forge.session.addendum import resolve_addendum_content_for_proxy

    config = _proxy_cfg(
        haiku="openai/gpt-5.4-mini",
        sonnet="anthropic/claude-sonnet-4-6",
        opus="openai/gpt-5.5",
        default_tier="sonnet",
    )

    with patch("forge.config.loader.load_proxy_instance_config", return_value=config):
        assert resolve_addendum_content_for_proxy("mixed-proxy") is None


def test_addendum_resolution_mixed_family_uses_openai_default() -> None:
    """Mixed proxy tiers should inject the default tier's addendum when that tier needs one."""
    from forge.session.addendum import resolve_addendum_content_for_proxy

    config = _proxy_cfg(
        haiku="anthropic/claude-haiku-4-5-20251001",
        sonnet="anthropic/claude-sonnet-4-6",
        opus="openai/gpt-5.5",
        default_tier="opus",
    )

    with patch("forge.config.loader.load_proxy_instance_config", return_value=config):
        content = resolve_addendum_content_for_proxy("mixed-proxy")

    assert content is not None
    assert "Tool Parameter Guidance" in content


class TestSessionList:
    """Tests for 'forge session list' command."""

    def test_list_empty_shows_message(self, runner: CliRunner, temp_env: Path) -> None:
        """Should show message when no sessions exist."""
        result = runner.invoke(main, ["session", "list"])

        assert result.exit_code == 0
        assert "No sessions found" in result.output

    def test_list_shows_sessions(self, runner: CliRunner, temp_env: Path) -> None:
        """Should list existing sessions."""
        # Create a session first (mock invoke_claude)
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "test-session"])

        result = runner.invoke(main, ["session", "list"])

        assert result.exit_code == 0
        assert "test-session" in result.output

    def test_list_json_reports_active_liveness(self, runner: CliRunner, temp_env: Path) -> None:
        """`session list --json` emits is_active=True for a session the active registry lists as live."""
        import json

        wt = temp_env  # cwd == project
        (wt / ".forge" / "sessions" / "live-one").mkdir(parents=True)
        (wt / ".forge" / "sessions" / "live-one" / "forge.session.json").write_text("{}")
        IndexStore().add_session(
            name="live-one",
            worktree_path=str(wt),
            project_root=str(wt),
            forge_root=str(wt),
            checkout_root=str(wt),
            relative_path=".",
        )
        # Tag with this process's PID so the liveness probe passes.
        ActiveSessionStore().upsert_session(
            "live-one",
            worktree_path=str(wt),
            launch_mode="host",
            launcher_pid=os.getpid(),
            forge_root=str(wt),
        )

        result = runner.invoke(main, ["session", "list", "--json", "--scope", "all"])

        assert result.exit_code == 0, result.output
        entry = next(row for row in json.loads(result.output) if row["name"] == "live-one")
        assert entry["is_active"] is True

    def test_list_older_than_filters_by_scoped_identity(self, runner: CliRunner, temp_env: Path) -> None:
        """--older-than should not pull in same-name sessions from a different forge_root."""
        forge_root_a, forge_root_b = _seed_duplicate_list_sessions(temp_env)

        result = runner.invoke(main, ["session", "list", "--older-than", "30", "--scope", "workspace"])

        assert result.exit_code == 0
        assert result.output.count("shared") == 1
        assert "nested-project" not in result.output
        assert str(forge_root_b.name) not in result.output

    def test_list_disambiguates_duplicate_names_in_human_output(self, runner: CliRunner, temp_env: Path) -> None:
        """Duplicate display names should show a location column for humans."""
        _seed_scoped_duplicate_sessions(temp_env)

        result = runner.invoke(main, ["session", "list", "--scope", "workspace"])

        assert result.exit_code == 0
        assert "LOCATION" in result.output
        assert result.output.count("shared") == 2
        assert "nested-project" in result.output

    def test_clean_reports_active_registry_failure(self, runner: CliRunner, temp_env: Path) -> None:
        """Cleanup should surface active-registry failures instead of claiming nothing matched."""
        _seed_cleanup_session(temp_env, temp_env)

        with patch(
            "forge.session.cleanup.ActiveSessionStore",
            return_value=_BrokenActiveSessionStore(),
        ):
            result = runner.invoke(main, ["session", "clean", "--older-than", "30", "--yes"])

        assert result.exit_code == 1
        assert "Session cleanup aborted before evaluation completed" in result.output
        assert "registry unreadable" in result.output
        assert "No sessions older than 30 days found." not in result.output
        assert "Encountered 1 cleanup failure" in result.output
        assert "active session registry" in result.output
        assert SessionStore(str(temp_env), "old-session").exists()

    def test_clean_preview_warns_when_active_registry_unreadable(self, runner: CliRunner, temp_env: Path) -> None:
        """The default preview should warn that real cleanup would abort when registry reads fail."""
        _seed_cleanup_session(temp_env, temp_env)

        with patch(
            "forge.session.active.ActiveSessionStore",
            return_value=_BrokenActiveSessionStore(),
        ):
            result = runner.invoke(main, ["session", "clean", "--older-than", "30"])

        assert result.exit_code == 0
        assert "Could not read active session registry" in result.output
        assert "Actual cleanup would abort" in result.output
        assert "old-session" in result.output
        assert "unreadable" not in result.output  # keep preview wording user-facing
        assert SessionStore(str(temp_env), "old-session").exists()

    def test_clean_older_than_reports_nothing_when_registry_healthy_and_no_matches(
        self, runner: CliRunner, temp_env: Path
    ) -> None:
        """Healthy cleanup with no old sessions should keep the existing no-op message."""
        result = runner.invoke(main, ["session", "clean", "--older-than", "30"])

        assert result.exit_code == 0
        assert "No sessions older than 30 days found." in result.output

    def test_clean_previews_by_default_without_deleting(self, runner: CliRunner, temp_env: Path) -> None:
        """Bare `clean` previews the deletable sessions and offers --yes, deleting nothing."""
        _seed_cleanup_session(temp_env, temp_env)

        result = runner.invoke(main, ["session", "clean", "--older-than", "30"])

        assert result.exit_code == 0
        assert "old-session" in result.output
        assert "Would delete 1 session" in result.output
        assert "Use --yes to delete." in result.output
        assert SessionStore(str(temp_env), "old-session").exists()  # nothing removed

    def test_clean_yes_deletes(self, runner: CliRunner, temp_env: Path) -> None:
        """`clean --yes` actually deletes the old session."""
        _seed_cleanup_session(temp_env, temp_env)

        result = runner.invoke(main, ["session", "clean", "--older-than", "30", "--yes"])

        assert result.exit_code == 0
        assert "Cleaned 1 session" in result.output
        assert not SessionStore(str(temp_env), "old-session").exists()


class TestSessionShow:
    """Tests for 'forge session show' command."""

    def test_show_no_session(self, runner: CliRunner, temp_env: Path) -> None:
        """Should show message when no session specified and no FORGE_SESSION."""
        result = runner.invoke(main, ["session", "show"])

        assert result.exit_code == 0
        assert "No session specified" in result.output

    def test_show_named_session(self, runner: CliRunner, temp_env: Path) -> None:
        """Should show detailed session info by name."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "inspect-test"])

        result = runner.invoke(main, ["session", "show", "inspect-test"])

        assert result.exit_code == 0
        assert "inspect-test" in result.output
        assert "UUID" in result.output or "Basic Info" in result.output

    def test_show_nonexistent_fails(self, runner: CliRunner, temp_env: Path) -> None:
        """Should fail for nonexistent session."""
        result = runner.invoke(main, ["session", "show", "nonexistent"])

        assert result.exit_code == 1
        assert "No session found" in result.output

    def test_show_json_output(self, runner: CliRunner, temp_env: Path) -> None:
        """--json should output merged manifest + context as JSON."""
        import json

        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "json-test"])

        result = runner.invoke(main, ["session", "show", "json-test", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["session_name"] == "json-test"
        assert "intent" in data
        assert "context" in data
        assert "model_family" in data["context"]
        assert "main_model" in data["context"]
        assert "main_model" in data
        assert "model_profile" not in data

    def test_show_field_extraction(self, runner: CliRunner, temp_env: Path) -> None:
        """--field should extract a single value."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "field-test"])

        result = runner.invoke(main, ["session", "show", "field-test", "--field", "session_name"])

        assert result.exit_code == 0
        assert "field-test" in result.output

    def test_show_field_nested(self, runner: CliRunner, temp_env: Path) -> None:
        """--field with dot notation should extract nested values."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "nested-test"])

        result = runner.invoke(main, ["session", "show", "nested-test", "--field", "context.model_family"])

        assert result.exit_code == 0
        assert result.output.strip()  # Should output some value

    def test_show_env_fallback(self, runner: CliRunner, temp_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should resolve from $FORGE_SESSION when no argument given."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "env-test"])

        monkeypatch.setenv("FORGE_SESSION", "env-test")
        result = runner.invoke(main, ["session", "show"])

        assert result.exit_code == 0
        assert "env-test" in result.output

    def test_show_computed_context_section(self, runner: CliRunner, temp_env: Path) -> None:
        """Human-readable output should include Computed Context section."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "context-test"])

        result = runner.invoke(main, ["session", "show", "context-test"])

        assert result.exit_code == 0
        assert "Computed Context" in result.output
        assert "Model Family" in result.output


def _seed_bare_session(project: Path, name: str) -> Path:
    """Write a minimal same-project session and register it in the index."""
    state = create_session_state(name, worktree_path=str(project))
    state.forge_root = str(project)
    SessionStore(str(project), name).write(state)
    IndexStore().add_session(
        name=name,
        worktree_path=str(project),
        project_root=str(project),
        forge_root=str(project),
        checkout_root=str(project),
        relative_path=".",
    )
    return project


def _mutate_manifest(project: Path, name: str, mutate) -> None:
    store = SessionStore(str(project), name)
    state = store.read()
    mutate(state)
    store.write(state)


def _write_plan_file(project: Path, relative_path: str, content: str = "# Plan") -> Path:
    """Create an on-disk plan file so displayed-path existence checks pass.

    Returns the canonicalized path (``dest.resolve()``) so assertions match
    what `Path.resolve()` produces in the CLI display (macOS normalizes
    ``/var`` -> ``/private/var``).
    """
    dest = project / relative_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    return dest.resolve()


class TestSessionShowPlanInfo:
    """Tests for plan info surfacing in `forge session show` and `--field`."""

    def test_show_displays_plan_draft_when_populated(self, runner: CliRunner, temp_env: Path) -> None:
        _seed_bare_session(temp_env, "planner")
        draft = _write_plan_file(temp_env, ".claude/plans/my-plan.md")

        def _set_plan(state):
            state.confirmed.latest_plan_path = ".claude/plans/my-plan.md"

        _mutate_manifest(temp_env, "planner", _set_plan)

        result = runner.invoke(main, ["session", "show", "planner"])

        assert result.exit_code == 0
        assert f"Plan (draft): {draft}" in result.output
        assert "file missing" not in result.output

    def test_show_resolves_nested_project_draft_against_launch_root(
        self,
        runner: CliRunner,
        temp_env: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        checkout_root = temp_env
        nested_forge_root = temp_env / "nested"
        nested_forge_root.mkdir()
        draft = _write_plan_file(nested_forge_root, ".claude/plans/nested-plan.md")

        state = create_session_state("planner", worktree_path=str(checkout_root))
        state.forge_root = str(nested_forge_root)
        state.confirmed.latest_plan_path = ".claude/plans/nested-plan.md"
        SessionStore(str(nested_forge_root), "planner").write(state)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(checkout_root),
            project_root=str(checkout_root),
            forge_root=str(nested_forge_root),
            checkout_root=str(checkout_root),
            relative_path="nested",
        )

        monkeypatch.chdir(nested_forge_root)
        result = runner.invoke(main, ["session", "show", "planner"])

        assert result.exit_code == 0
        assert f"Plan (draft): {draft}" in result.output
        assert "file missing" not in result.output

    def test_show_displays_approved_snapshots(self, runner: CliRunner, temp_env: Path) -> None:
        _seed_bare_session(temp_env, "planner")
        snap = _write_plan_file(temp_env, ".forge/artifacts/planner/plans/x.md")

        def _set_snaps(state):
            state.confirmed.artifacts["plans"] = [
                {
                    "kind": "approved",
                    "captured_at": "2026-04-16T12:00:00Z",
                    "source_path": ".claude/plans/p.md",
                    "snapshot_path": ".forge/artifacts/planner/plans/x.md",
                }
            ]

        _mutate_manifest(temp_env, "planner", _set_snaps)

        result = runner.invoke(main, ["session", "show", "planner"])

        assert result.exit_code == 0
        assert "Plans approved: 1" in result.output
        assert str(snap) in result.output
        assert "file missing" not in result.output

    def test_show_displays_missing_file_annotation(self, runner: CliRunner, temp_env: Path) -> None:
        """When the snapshot is recorded but the file is gone, surface it explicitly."""
        _seed_bare_session(temp_env, "planner")

        def _set_snaps(state):
            state.confirmed.artifacts["plans"] = [
                {
                    "kind": "approved",
                    "captured_at": "2026-04-16T12:00:00Z",
                    "source_path": ".claude/plans/p.md",
                    "snapshot_path": ".forge/artifacts/planner/plans/gone.md",
                }
            ]

        _mutate_manifest(temp_env, "planner", _set_snaps)

        result = runner.invoke(main, ["session", "show", "planner"])

        assert result.exit_code == 0
        assert "Plans approved: 1" in result.output
        assert "gone.md" in result.output
        assert "file missing" in result.output

    def test_show_omits_plan_section_when_empty(self, runner: CliRunner, temp_env: Path) -> None:
        _seed_bare_session(temp_env, "solo")

        result = runner.invoke(main, ["session", "show", "solo"])

        assert result.exit_code == 0
        assert "Plan (" not in result.output
        assert "Plans approved" not in result.output

    def test_show_displays_inherited_plan_from_parent_via_derivation(self, runner: CliRunner, temp_env: Path) -> None:
        """Resume sessions populate confirmed.derivation; child should see parent's plan."""
        _seed_bare_session(temp_env, "planner")
        _seed_bare_session(temp_env, "executor")
        draft = _write_plan_file(temp_env, ".claude/plans/parent-plan.md")

        def _set_parent_plan(state):
            state.confirmed.latest_plan_path = ".claude/plans/parent-plan.md"

        def _set_child_derivation(state):
            state.confirmed.derivation = Derivation(parent_session="planner")

        _mutate_manifest(temp_env, "planner", _set_parent_plan)
        _mutate_manifest(temp_env, "executor", _set_child_derivation)

        result = runner.invoke(main, ["session", "show", "executor"])

        assert result.exit_code == 0
        assert f"Plan (inherited from planner, draft): {draft}" in result.output
        assert "file missing" not in result.output

    def test_show_displays_inherited_plan_for_real_fork(self, runner: CliRunner, temp_env: Path) -> None:
        """Fork sessions use top-level parent_session (no derivation). Must still surface parent plan."""
        # Seed parent with an approved snapshot
        _seed_bare_session(temp_env, "planner")
        snap = _write_plan_file(temp_env, ".forge/artifacts/planner/plans/x.md")

        def _set_parent_plan(state):
            state.confirmed.artifacts["plans"] = [
                {
                    "kind": "approved",
                    "captured_at": "2026-04-16T12:00:00Z",
                    "source_path": ".claude/plans/p.md",
                    "snapshot_path": ".forge/artifacts/planner/plans/x.md",
                }
            ]

        _mutate_manifest(temp_env, "planner", _set_parent_plan)

        # Create a fork child the real way: top-level parent_session + is_fork=True.
        fork_state = create_session_state(
            "executor",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(temp_env),
        )
        fork_state.forge_root = str(temp_env)
        SessionStore(str(temp_env), "executor").write(fork_state)
        IndexStore().add_session(
            name="executor",
            worktree_path=str(temp_env),
            project_root=str(temp_env),
            forge_root=str(temp_env),
            checkout_root=str(temp_env),
            relative_path=".",
        )

        result = runner.invoke(main, ["session", "show", "executor"])

        assert result.exit_code == 0
        assert "Plan (inherited from planner, approved snapshot)" in result.output
        assert str(snap) in result.output
        assert "file missing" not in result.output

    def test_show_prefers_approved_snapshot_over_draft_for_self(self, runner: CliRunner, temp_env: Path) -> None:
        """When a session has both a draft and an approved snapshot, show both lines."""
        _seed_bare_session(temp_env, "planner")
        _write_plan_file(temp_env, ".claude/plans/stale-draft.md")
        _write_plan_file(temp_env, ".forge/artifacts/planner/plans/x.md")

        def _set(state):
            state.confirmed.latest_plan_path = ".claude/plans/stale-draft.md"
            state.confirmed.artifacts["plans"] = [
                {
                    "kind": "approved",
                    "captured_at": "2026-04-16T12:00:00Z",
                    "source_path": ".claude/plans/p.md",
                    "snapshot_path": ".forge/artifacts/planner/plans/x.md",
                }
            ]

        _mutate_manifest(temp_env, "planner", _set)

        result = runner.invoke(main, ["session", "show", "planner"])

        assert result.exit_code == 0
        # Approved snapshot line appears BEFORE draft line so the approved path is the first thing the user sees.
        approved_idx = result.output.index("Plans approved:")
        draft_idx = result.output.index("Plan (draft):")
        assert approved_idx < draft_idx
        assert "file missing" not in result.output

    def test_show_prefers_approved_snapshot_when_inherited(self, runner: CliRunner, temp_env: Path) -> None:
        """Parent with both draft and approved: inherited line points at approved."""
        _seed_bare_session(temp_env, "planner")
        _write_plan_file(temp_env, ".claude/plans/stale-draft.md")
        approved = _write_plan_file(temp_env, ".forge/artifacts/planner/plans/real.md")

        def _set_parent(state):
            state.confirmed.latest_plan_path = ".claude/plans/stale-draft.md"
            state.confirmed.artifacts["plans"] = [
                {
                    "kind": "approved",
                    "captured_at": "2026-04-16T12:00:00Z",
                    "source_path": ".claude/plans/p.md",
                    "snapshot_path": ".forge/artifacts/planner/plans/real.md",
                }
            ]

        _mutate_manifest(temp_env, "planner", _set_parent)

        fork_state = create_session_state(
            "executor",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(temp_env),
        )
        fork_state.forge_root = str(temp_env)
        SessionStore(str(temp_env), "executor").write(fork_state)
        IndexStore().add_session(
            name="executor",
            worktree_path=str(temp_env),
            project_root=str(temp_env),
            forge_root=str(temp_env),
            checkout_root=str(temp_env),
            relative_path=".",
        )

        result = runner.invoke(main, ["session", "show", "executor"])

        assert result.exit_code == 0
        assert "Plan (inherited from planner, approved snapshot)" in result.output
        assert str(approved) in result.output
        assert "stale-draft" not in result.output
        assert "file missing" not in result.output

    def test_show_json_exposes_confirmed_plan_fields(self, runner: CliRunner, temp_env: Path) -> None:
        import json

        _seed_bare_session(temp_env, "planner")

        def _set(state):
            state.confirmed.latest_plan_path = ".claude/plans/foo.md"
            state.confirmed.artifacts["plans"] = [{"kind": "approved", "snapshot_path": "snap.md"}]

        _mutate_manifest(temp_env, "planner", _set)

        result = runner.invoke(main, ["session", "show", "planner", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["confirmed"]["latest_plan_path"] == ".claude/plans/foo.md"
        assert data["confirmed"]["artifacts"]["plans"][0]["snapshot_path"] == "snap.md"
        assert data["plan"]["preferred_path"] == "snap.md"
        assert data["plan"]["kind"] == "approved"

    def test_show_json_confirmed_derivation_present(self, runner: CliRunner, temp_env: Path) -> None:
        import json

        _seed_bare_session(temp_env, "planner")
        _seed_bare_session(temp_env, "executor")

        def _set(state):
            state.confirmed.derivation = Derivation(
                parent_session="planner",
                parent_forge_root=str(temp_env),
            )

        _mutate_manifest(temp_env, "executor", _set)

        result = runner.invoke(main, ["session", "show", "executor", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["confirmed"]["derivation"]["parent_session"] == "planner"
        assert data["confirmed"]["derivation"]["parent_forge_root"] == str(temp_env)

    def test_show_json_surfaces_inherited_plan(self, runner: CliRunner, temp_env: Path) -> None:
        import json

        _seed_bare_session(temp_env, "planner")
        _seed_bare_session(temp_env, "executor")

        def _set_parent(state):
            state.confirmed.artifacts["plans"] = [
                {
                    "kind": "approved",
                    "snapshot_path": ".forge/artifacts/planner/plans/real.md",
                }
            ]

        def _set_child(state):
            state.confirmed.derivation = Derivation(parent_session="planner")

        _mutate_manifest(temp_env, "planner", _set_parent)
        _mutate_manifest(temp_env, "executor", _set_child)

        result = runner.invoke(main, ["session", "show", "executor", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["plan"]["source"] == "parent"
        assert data["plan"]["parent_session"] == "planner"
        assert data["plan"]["preferred_path"] == ".forge/artifacts/planner/plans/real.md"
        assert data["plan"]["kind"] == "approved"

    def test_show_field_extraction_plan_path(self, runner: CliRunner, temp_env: Path) -> None:
        _seed_bare_session(temp_env, "planner")

        def _set(state):
            state.confirmed.latest_plan_path = ".claude/plans/foo.md"

        _mutate_manifest(temp_env, "planner", _set)

        result = runner.invoke(
            main,
            ["session", "show", "planner", "--field", "confirmed.latest_plan_path"],
        )

        assert result.exit_code == 0
        assert result.output.strip() == ".claude/plans/foo.md"

    def test_show_field_extraction_inherited_plan_path(self, runner: CliRunner, temp_env: Path) -> None:
        _seed_bare_session(temp_env, "planner")
        _seed_bare_session(temp_env, "executor")

        def _set_parent(state):
            state.confirmed.latest_plan_path = ".claude/plans/parent-plan.md"

        def _set_child(state):
            state.confirmed.derivation = Derivation(parent_session="planner")

        _mutate_manifest(temp_env, "planner", _set_parent)
        _mutate_manifest(temp_env, "executor", _set_child)

        result = runner.invoke(main, ["session", "show", "executor", "--field", "plan.preferred_path"])

        assert result.exit_code == 0
        assert result.output.strip() == ".claude/plans/parent-plan.md"

    def test_show_field_extraction_none_returns_empty(self, runner: CliRunner, temp_env: Path) -> None:
        _seed_bare_session(temp_env, "planner")

        result = runner.invoke(
            main,
            ["session", "show", "planner", "--field", "confirmed.latest_plan_path"],
        )

        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_show_field_extraction_missing_path_errors(self, runner: CliRunner, temp_env: Path) -> None:
        _seed_bare_session(temp_env, "planner")

        result = runner.invoke(
            main,
            ["session", "show", "planner", "--field", "confirmed.nonexistent_field"],
        )

        assert result.exit_code == 1
        assert "not found" in result.output


class TestSessionShowPolicy:
    """Tests for confirmed.policy exposure in session show."""

    def test_show_json_includes_confirmed_policy(self, runner: CliRunner, temp_env: Path) -> None:
        import json

        from forge.session.models import PolicyConfirmed

        _seed_bare_session(temp_env, "executor")

        def _set(state):
            state.confirmed.policy = PolicyConfirmed(
                forge_version="0.1.0",
                bundles=[],
                rules_active=["semantic.supervisor"],
                decisions=[
                    {"final_decision": "allow", "context_summary": "Edit:src/foo.py"},
                ],
            )

        _mutate_manifest(temp_env, "executor", _set)

        result = runner.invoke(main, ["session", "show", "executor", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["confirmed"]["policy"] is not None
        assert data["confirmed"]["policy"]["rules_active"] == ["semantic.supervisor"]
        assert len(data["confirmed"]["policy"]["decisions"]) == 1
        assert data["confirmed"]["policy"]["decisions"][0]["final_decision"] == "allow"

    def test_show_json_confirmed_policy_null_when_empty(self, runner: CliRunner, temp_env: Path) -> None:
        import json

        _seed_bare_session(temp_env, "bare")

        result = runner.invoke(main, ["session", "show", "bare", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["confirmed"]["policy"] is None

    def test_show_field_confirmed_policy_decisions(self, runner: CliRunner, temp_env: Path) -> None:
        from forge.session.models import PolicyConfirmed

        _seed_bare_session(temp_env, "executor")

        def _set(state):
            state.confirmed.policy = PolicyConfirmed(
                decisions=[
                    {"final_decision": "deny", "context_summary": "Write:src/bar.py"},
                    {"final_decision": "allow", "context_summary": "Edit:src/bar.py"},
                ],
            )

        _mutate_manifest(temp_env, "executor", _set)

        result = runner.invoke(
            main,
            ["session", "show", "executor", "--field", "confirmed.policy.decisions"],
        )

        assert result.exit_code == 0
        assert "deny" in result.output
        assert "allow" in result.output

    def test_show_human_includes_policy_evals(self, runner: CliRunner, temp_env: Path) -> None:
        from forge.session.models import PolicyConfirmed

        _seed_bare_session(temp_env, "executor")

        def _set(state):
            state.confirmed.policy = PolicyConfirmed(
                decisions=[
                    {"final_decision": "allow", "context_summary": "Edit:src/foo.py"},
                    {"final_decision": "deny", "context_summary": "Write:src/bar.py"},
                    {"final_decision": "allow", "context_summary": "Edit:src/baz.py"},
                ],
            )

        _mutate_manifest(temp_env, "executor", _set)

        result = runner.invoke(main, ["session", "show", "executor"])

        assert result.exit_code == 0
        assert "Policy Evals:" in result.output
        assert "3 evaluations" in result.output
