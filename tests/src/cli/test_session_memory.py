"""Tests for ``forge session memory`` activation + report commands."""

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
# enable / disable
# ---------------------------------------------------------------------------


class TestSessionMemoryEnable:
    """Session-scoped enable (``--session`` or ``$FORGE_SESSION``)."""

    def test_enable_sets_auto_update(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        assert result.exit_code == 0, result.output
        assert "enabled" in result.output
        assert "augment" in result.output

    def test_enable_idempotent(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        result = runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        assert result.exit_code == 0, result.output
        assert "already enabled" in result.output

    def test_enable_review_only(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["session", "memory", "enable", "--review-only", "--session", "s1"])
        assert result.exit_code == 0, result.output
        assert "review-only" in result.output

    def test_enable_changes_mode(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        result = runner.invoke(main, ["session", "memory", "enable", "--review-only", "--session", "s1"])
        assert result.exit_code == 0, result.output
        assert "enabled" in result.output
        assert "review-only" in result.output

    def test_enable_outside_session_errors(
        self, runner: CliRunner, seeded_session: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        result = runner.invoke(main, ["session", "memory", "enable"])
        assert result.exit_code != 0
        assert "session-scoped" in result.output.lower()

    def test_enable_writes_effective_memory_state(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        """Enable from intent.memory=None produces correct effective state."""
        forge_root, _ = seeded_session
        result = runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        assert result.exit_code == 0, result.output

        from forge.session.effective import compute_effective_intent
        from forge.session.store import SessionStore

        state = SessionStore(str(forge_root), "s1").read()
        effective = compute_effective_intent(state)
        assert effective.memory is not None
        assert effective.memory.auto_update is not None
        assert effective.memory.auto_update.enabled is True

    def test_effort_only_change_persists_when_already_enabled(
        self, runner: CliRunner, seeded_session: tuple[Path, str]
    ) -> None:
        """Regression: an effort-only change must persist even when memory is
        already enabled in the same mode.

        The old early-return short-circuited on "already enabled AND same mode",
        silently dropping the --effort override. The fix only short-circuits when
        nothing (enabled/mode/effort) is pending.
        """
        forge_root, _ = seeded_session

        # First enable in the default (augment) mode, no effort set.
        first = runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        assert first.exit_code == 0, first.output

        # Same mode (augment), but now request an effort change.
        result = runner.invoke(main, ["session", "memory", "enable", "--session", "s1", "--effort", "high"])
        assert result.exit_code == 0, result.output
        # Must NOT have taken the "already enabled" no-op path.
        assert "already enabled" not in result.output

        from forge.session.effective import compute_effective_intent
        from forge.session.store import SessionStore

        state = SessionStore(str(forge_root), "s1").read()
        effective = compute_effective_intent(state)
        assert effective.memory is not None
        assert effective.memory.auto_update is not None
        assert effective.memory.auto_update.effort == "high"

    def test_disable_session_scoped(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        result = runner.invoke(main, ["session", "memory", "disable", "--session", "s1"])
        assert result.exit_code == 0, result.output
        assert "disabled" in result.output

    def test_disable_outside_session_errors(
        self, runner: CliRunner, seeded_session: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        result = runner.invoke(main, ["session", "memory", "disable"])
        assert result.exit_code != 0
        assert "session-scoped" in result.output.lower()


class TestMemoryActivationCleanBreak:
    """Activation/report verbs moved to ``forge session memory`` (Slice 02 clean break)."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["memory", "enable", "--session", "s1"],
            ["memory", "disable", "--session", "s1"],
            ["memory", "status"],
            ["memory", "report", "show", "s1"],
        ],
    )
    def test_old_path_is_no_such_command(self, runner: CliRunner, argv: list[str]) -> None:
        result = runner.invoke(main, argv)
        assert result.exit_code == 2  # Click "No such command", no tombstone
        assert "No such command" in result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestSessionMemoryStatus:
    """status shows per-session activation (enabled/disabled)."""

    def test_status_shows_session_activation(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        result = runner.invoke(main, ["session", "memory", "status"])
        assert result.exit_code == 0, result.output
        assert "s1" in result.output
        assert "on" in result.output

    def test_status_empty(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        result = runner.invoke(main, ["session", "memory", "status"])
        assert result.exit_code == 0, result.output
        # Session exists but memory is off; still shown
        assert "s1" in result.output or "No sessions" in result.output

    def test_status_json(self, runner: CliRunner, seeded_session: tuple[Path, str]) -> None:
        runner.invoke(main, ["session", "memory", "enable", "--session", "s1"])
        result = runner.invoke(main, ["session", "memory", "status", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "sessions" in data
        assert len(data["sessions"]) >= 1
        session_entry = data["sessions"][0]
        assert "session" in session_entry
        assert "enabled" in session_entry
        assert "mode" in session_entry
        assert session_entry["enabled"] is True
