"""Tests for the UserPromptSubmit dispatcher (`forge hook user-prompt-submit`).

This validates the `%<cmd>` parsing and dispatch behavior.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks import hooks
from forge.session import SessionStore


@pytest.mark.parametrize(
    "prompt,should_block",
    [
        ("%h", True),
        ("%help", True),
        ("%session list", True),
        ("%plan", True),
        ("%cancel-verification", True),
        ("  %help", True),  # Leading whitespace stripped, then recognized
        ("hello world", False),
        ("what is %help?", False),  # % not at start (after strip)
        ("%unknown_xyz", False),  # Unknown commands pass through
    ],
)
def test_command_recognition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    should_block: bool,
) -> None:
    """Test that the hook correctly recognizes % commands."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    payload = json.dumps({"prompt": prompt, "transcript_path": ""})

    result = runner.invoke(hooks, ["user-prompt-submit"], input=payload)

    assert result.exit_code == 0

    if should_block:
        output = json.loads(result.output)
        # Command was recognized; without a session it may skip (fail-open)
        # or block. Either response proves recognition.
        assert "decision" in output or "action" in output
    else:
        # Not blocked = empty output
        assert result.output.strip() == ""


class TestUserPromptSubmitDispatcher:
    def test_cancel_verification_sets_override(self, tmp_path: Path, monkeypatch) -> None:
        """%cancel-verification persists verification.bypass override."""
        monkeypatch.chdir(tmp_path)

        # Create minimal session manifest so SessionStore resolves
        from forge.session import SessionStore, create_session_state
        from forge.session.models import VerificationConfig

        store = SessionStore(str(tmp_path), "test-session")
        manifest = create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )
        # Must configure verification before %cancel-verification can bypass it
        manifest.intent.verification = VerificationConfig(promise="<done>COMPLETE</done>")
        store.write(manifest)

        monkeypatch.setenv("FORGE_SESSION", "test-session")

        runner = CliRunner()
        payload = {"prompt": "%cancel-verification", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"

        updated = store.read()
        assert updated.overrides.get("verification", {}).get("bypass") is True

    def test_ignores_non_percent_prompt(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        payload = {"prompt": "hello", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        assert result.output == ""

    def test_ignores_unknown_percent_command(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        payload = {"prompt": "%unknown", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        assert result.output == ""

    def test_session_list_blocks(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        payload = {"prompt": "%session list", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "sessions" in out["reason"].lower()

    def test_help_blocks_with_help_text(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        payload = {"prompt": "%help", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "%session" in out["reason"]
        assert "%plan" in out["reason"]


class TestSessionShowDirectCommand:
    @staticmethod
    def _init_git_repo(path: Path) -> None:
        import subprocess

        subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True, check=True)
        (path / "README.md").write_text("# Test\n")
        subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), capture_output=True, check=True)

    def test_session_show_current_from_env(self, tmp_path: Path, monkeypatch) -> None:
        """Default %session show uses FORGE_SESSION env var."""
        self._init_git_repo(tmp_path)
        (tmp_path / ".forge").mkdir(exist_ok=True)
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        from forge.session import SessionManager

        manager = SessionManager()
        manager.start_session("show-test", worktree_path=str(tmp_path))

        monkeypatch.setenv("FORGE_SESSION", "show-test")

        payload = {"prompt": "%session show", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "show-test" in out["reason"]

    def test_session_show_named(self, tmp_path: Path, monkeypatch) -> None:
        """Explicit name in %session show <name>."""
        self._init_git_repo(tmp_path)
        (tmp_path / ".forge").mkdir(exist_ok=True)
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        from forge.session import SessionManager

        manager = SessionManager()
        manager.start_session("named-show", worktree_path=str(tmp_path))

        payload = {"prompt": "%session show named-show", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "named-show" in out["reason"]

    def test_session_show_no_env_no_name(self, tmp_path: Path, monkeypatch) -> None:
        """No FORGE_SESSION and no name -> error, not active-session fallback."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        runner = CliRunner()

        payload = {"prompt": "%session show", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "No active session" in out["reason"]


class TestPlanDirectCommands:
    def test_plan_blocks_with_latest_plan_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
        runner = CliRunner()

        from forge.session import create_session_state

        store = SessionStore(str(tmp_path), "test-session")
        manifest = create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )
        manifest.confirmed.latest_plan_path = ".claude/plans/example.md"
        store.write(manifest)
        monkeypatch.setenv("FORGE_SESSION", "test-session")

        payload = {"prompt": "%plan", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "Plan (draft):" in out["reason"]
        assert ".claude/plans/example.md" in out["reason"]

    def test_plan_resolves_nested_project_draft_against_launch_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        checkout_root = tmp_path
        nested_forge_root = tmp_path / "nested"
        nested_forge_root.mkdir()
        monkeypatch.chdir(nested_forge_root)
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(nested_forge_root))
        runner = CliRunner()

        from forge.session import create_session_state

        draft = nested_forge_root / ".claude" / "plans" / "nested.md"
        draft.parent.mkdir(parents=True)
        draft.write_text("# Nested plan")

        store = SessionStore(str(nested_forge_root), "test-session")
        manifest = create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
            worktree_path=str(checkout_root),
        )
        manifest.forge_root = str(nested_forge_root)
        manifest.confirmed.latest_plan_path = ".claude/plans/nested.md"
        store.write(manifest)
        monkeypatch.setenv("FORGE_SESSION", "test-session")

        payload = {"prompt": "%plan", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert f"Plan (draft): {draft.resolve()}" in out["reason"]
        assert "file missing" not in out["reason"]

    def test_plan_blocks_when_no_plan_recorded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
        runner = CliRunner()

        from forge.session import create_session_state

        store = SessionStore(str(tmp_path), "test-session")
        manifest = create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )
        store.write(manifest)
        monkeypatch.setenv("FORGE_SESSION", "test-session")

        payload = {"prompt": "%plan", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["reason"] == "No plan file recorded for this session or its ancestry"

    def test_plan_shows_parent_plan_via_derivation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resume children carry confirmed.derivation pointing at the parent."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
        runner = CliRunner()

        from forge.session import create_session_state
        from forge.session.models import Derivation

        parent = create_session_state("planner")
        parent.confirmed.latest_plan_path = ".claude/plans/approved.md"
        SessionStore(str(tmp_path), "planner").write(parent)

        child = create_session_state("executor")
        child.confirmed.derivation = Derivation(parent_session="planner")
        SessionStore(str(tmp_path), "executor").write(child)

        monkeypatch.setenv("FORGE_SESSION", "executor")

        payload = {"prompt": "%plan", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "Plan (draft, from 'planner')" in out["reason"]
        assert ".claude/plans/approved.md" in out["reason"]

    def test_plan_shows_parent_plan_for_real_fork(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork children only carry top-level parent_session; %plan must still walk to parent."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
        runner = CliRunner()

        from forge.session import IndexStore, create_session_state

        parent = create_session_state("planner", worktree_path=str(tmp_path))
        parent.forge_root = str(tmp_path)
        parent.confirmed.artifacts["plans"] = [
            {
                "kind": "approved",
                "snapshot_path": ".forge/artifacts/planner/plans/real.md",
            }
        ]
        SessionStore(str(tmp_path), "planner").write(parent)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(tmp_path),
            project_root=str(tmp_path),
            forge_root=str(tmp_path),
            checkout_root=str(tmp_path),
            relative_path=".",
        )

        child = create_session_state(
            "executor",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(tmp_path),
        )
        child.forge_root = str(tmp_path)
        SessionStore(str(tmp_path), "executor").write(child)
        IndexStore().add_session(
            name="executor",
            worktree_path=str(tmp_path),
            project_root=str(tmp_path),
            forge_root=str(tmp_path),
            checkout_root=str(tmp_path),
            relative_path=".",
        )

        monkeypatch.setenv("FORGE_SESSION", "executor")

        payload = {"prompt": "%plan", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "Approved plan (snapshot, from 'planner')" in out["reason"]
        assert ".forge/artifacts/planner/plans/real.md" in out["reason"]

    def test_plan_prefers_approved_snapshot_over_draft(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Self-session with both draft and approved snapshot: %plan points to approved."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
        runner = CliRunner()

        from forge.session import create_session_state

        snap_dir = tmp_path / ".forge" / "artifacts" / "planner" / "plans"
        snap_dir.mkdir(parents=True)
        snap = snap_dir / "real.md"
        snap.write_text("# Plan")

        state = create_session_state("planner", worktree_path=str(tmp_path))
        state.forge_root = str(tmp_path)
        state.confirmed.latest_plan_path = ".claude/plans/stale.md"
        state.confirmed.artifacts["plans"] = [
            {"kind": "approved", "snapshot_path": ".forge/artifacts/planner/plans/real.md"}
        ]
        SessionStore(str(tmp_path), "planner").write(state)
        monkeypatch.setenv("FORGE_SESSION", "planner")

        payload = {"prompt": "%plan", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "Approved plan (snapshot):" in out["reason"]
        assert str(snap.resolve()) in out["reason"]
        assert "stale" not in out["reason"]
        assert "file missing" not in out["reason"]

    def test_plan_annotates_missing_snapshot_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the recorded snapshot path doesn't exist on disk, surface it explicitly."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
        runner = CliRunner()

        from forge.session import create_session_state

        state = create_session_state("planner", worktree_path=str(tmp_path))
        state.forge_root = str(tmp_path)
        state.confirmed.artifacts["plans"] = [
            {"kind": "approved", "snapshot_path": ".forge/artifacts/planner/plans/gone.md"}
        ]
        SessionStore(str(tmp_path), "planner").write(state)
        monkeypatch.setenv("FORGE_SESSION", "planner")

        payload = {"prompt": "%plan", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "gone.md" in out["reason"]
        assert "file missing" in out["reason"]

    def test_plan_blocks_when_no_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        runner = CliRunner()

        payload = {"prompt": "%plan", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["reason"] == "No session found"

    def test_plan_with_args_shows_usage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        payload = {"prompt": "%plan extra", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["reason"] == "Usage: %plan"


class TestProxyDirectCommands:
    """Tests for %proxy direct commands.

    Note: conftest.py's isolate_forge_home fixture auto-sets FORGE_HOME to an isolated temp dir.
    """

    def test_proxy_list_blocks_with_no_leases(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test %proxy list blocks and shows message when no proxies."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        payload = {"prompt": "%proxy list", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "no proxies" in out["reason"].lower()

    def test_proxy_list_blocks_with_leases(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test %proxy list blocks and shows proxies when present."""
        monkeypatch.chdir(tmp_path)

        # Create registry with a proxy (uses FORGE_HOME from isolate_forge_home fixture)
        forge_home = Path(os.environ["FORGE_HOME"])
        proxies_dir = forge_home / "proxies"
        proxies_dir.mkdir(parents=True, exist_ok=True)
        (proxies_dir / "index.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "proxies": {
                        "test-proxy": {
                            "proxy_id": "test-proxy",
                            "template": "litellm-openai",
                            "base_url": "http://localhost:8085",
                            "port": 8085,
                            "pid": None,
                            "status": "healthy",
                        }
                    },
                }
            )
        )

        runner = CliRunner()
        payload = {"prompt": "%proxy list", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "test-proxy" in out["reason"]
        assert "litellm-openai" in out["reason"]

    def test_proxy_show_blocks_with_details(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test %proxy show <id> blocks and shows proxy details."""
        monkeypatch.chdir(tmp_path)

        # Create registry with a proxy (uses FORGE_HOME from isolate_forge_home fixture)
        forge_home = Path(os.environ["FORGE_HOME"])
        proxies_dir = forge_home / "proxies"
        proxies_dir.mkdir(parents=True, exist_ok=True)
        (proxies_dir / "index.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "proxies": {
                        "test-proxy": {
                            "proxy_id": "test-proxy",
                            "template": "litellm-openai",
                            "base_url": "http://localhost:8085",
                            "port": 8085,
                            "pid": None,
                            "status": "healthy",
                        }
                    },
                }
            )
        )

        runner = CliRunner()
        payload = {"prompt": "%proxy show test-proxy", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "test-proxy" in out["reason"]
        assert "litellm-openai" in out["reason"]
        assert "8085" in out["reason"]

    def test_proxy_show_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test %proxy show <id> shows error when proxy not found."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        payload = {"prompt": "%proxy show nonexistent", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "error" in out["reason"].lower()

    def test_proxy_show_requires_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test %proxy show without ID shows usage error."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        payload = {"prompt": "%proxy show", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "usage" in out["reason"].lower()

    def test_proxy_no_subcommand_shows_usage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test %proxy without subcommand shows usage."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        payload = {"prompt": "%proxy", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "usage" in out["reason"].lower()

    def test_proxy_unknown_subcommand_shows_usage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test %proxy <unknown> shows usage."""
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()

        payload = {"prompt": "%proxy foobar", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "usage" in out["reason"].lower()

    def test_proxy_audit_show_blocks_with_metadata(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%proxy audit show renders metadata; plaintext is never shown."""
        monkeypatch.chdir(tmp_path)
        from forge.proxy import audit_logger

        audit_logger.write_metadata_record(
            request_id="r",
            proxy_id="p",
            mode="inspect",
            route={"template": "anthropic-passthrough"},
            system_prompt_hash=audit_logger.hash_system_prompt("SECRET-PROMPT"),
            tool_surface_hash=None,
            counts={"num_messages": 1, "num_tools": 0},
        )

        payload = {"prompt": "%proxy audit show", "transcript_path": ""}
        result = CliRunner().invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "inspect" in out["reason"]
        assert "SECRET-PROMPT" not in out["reason"]

    def test_proxy_audit_diff_blocks_with_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%proxy audit diff renders drift + override mutations."""
        monkeypatch.chdir(tmp_path)
        from forge.proxy import audit_logger

        audit_logger.write_drift_record(
            request_id="r",
            proxy_id="p",
            dimension="system_prompt",
            previous_hash="sha256:aaaaaaaa",
            current_hash="sha256:bbbbbbbb",
            route={"template": "t"},
        )
        audit_logger.write_mutation_record(
            request_id="r",
            proxy_id="p",
            route={"template": "t"},
            mutation={
                "blocked": False,
                "mutations": [{"target": "system_prompt", "action": "augment", "augment_len": 5}],
            },
        )

        payload = {"prompt": "%proxy audit diff", "transcript_path": ""}
        result = CliRunner().invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "drift" in out["reason"]
        assert "augment" in out["reason"]

    def test_proxy_audit_unknown_action_shows_usage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%proxy audit <unknown> shows the show|diff usage."""
        monkeypatch.chdir(tmp_path)
        payload = {"prompt": "%proxy audit bogus", "transcript_path": ""}
        result = CliRunner().invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "show|diff" in out["reason"]


class TestGuardCommands:
    """Test %policy enable/disable use overrides (not intent mutation)."""

    def _make_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionStore:
        """Helper: create a session store with a minimal manifest."""
        from forge.session import create_session_state

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_SESSION", "test-session")

        store = SessionStore(str(tmp_path), "test-session")
        manifest = create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )
        store.write(manifest)
        return store

    def test_guard_enable_sets_overrides(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%policy enable tdd sets policy overrides, not intent (M7 regression)."""
        store = self._make_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy enable tdd", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "enabled" in out["reason"].lower()

        updated = store.read()
        policy_overrides = updated.overrides.get("policy", {})
        assert policy_overrides["enabled"] is True
        assert policy_overrides["bundles"] == ["tdd"]
        assert policy_overrides["fail_mode"] == "open"

        # Intent should be unchanged (None or original value)
        assert updated.intent.policy is None or updated.intent.policy.enabled is None

    def test_guard_enable_multiple_bundles(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%policy enable tdd coding_standards sets both bundles (M7 regression)."""
        store = self._make_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {
            "prompt": "%policy enable tdd coding_standards",
            "transcript_path": "",
        }
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0

        updated = store.read()
        policy_overrides = updated.overrides.get("policy", {})
        assert set(policy_overrides["bundles"]) == {"tdd", "coding_standards"}

    def test_guard_enable_with_fail_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%policy enable tdd --fail-mode closed sets fail_mode override (M7 regression)."""
        store = self._make_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {
            "prompt": "%policy enable tdd --fail-mode closed",
            "transcript_path": "",
        }
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0

        updated = store.read()
        policy_overrides = updated.overrides.get("policy", {})
        assert policy_overrides["fail_mode"] == "closed"

    def test_guard_disable_sets_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%policy disable sets policy.enabled=False as override (M7 regression)."""
        store = self._make_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy disable", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "disabled" in out["reason"].lower()

        updated = store.read()
        policy_overrides = updated.overrides.get("policy", {})
        assert policy_overrides["enabled"] is False

        # Intent should be unchanged
        assert updated.intent.policy is None or updated.intent.policy.enabled is None

    def test_guard_disable_preserves_intent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%policy disable after enable preserves the enable override baseline (M7 regression)."""
        from forge.session import SessionStore, create_session_state
        from forge.session.models import PolicyIntent

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_SESSION", "test-session")

        store = SessionStore(str(tmp_path), "test-session")
        manifest = create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )
        # Set a baseline intent with TDD enabled
        manifest.intent.policy = PolicyIntent(enabled=True, bundles=["tdd"], fail_mode="open")
        store.write(manifest)

        runner = CliRunner()
        # Disable policy
        payload = {"prompt": "%policy disable", "transcript_path": ""}
        runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        updated = store.read()
        # Override says disabled
        assert updated.overrides.get("policy", {}).get("enabled") is False
        # But original intent is preserved
        assert updated.intent.policy is not None
        assert updated.intent.policy.enabled is True
        assert updated.intent.policy.bundles == ["tdd"]

    def test_guard_enable_no_bundles_blocks_with_usage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%policy enable with no bundles shows usage."""
        self._make_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy enable", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "usage" in out["reason"].lower()


class TestSplitDiffPerFile:
    """Unit tests for _split_diff_per_file helper."""

    def test_single_file_diff(self) -> None:
        from forge.cli.hooks.direct_commands import _split_diff_per_file

        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1 +1 @@\n"
            "-old = 0\n"
            "+x = 1\n"
        )
        result = _split_diff_per_file(diff)
        assert len(result) == 1
        assert result[0][0] == "src/foo.py"
        assert "+x = 1" in result[0][1]

    def test_multi_file_diff(self) -> None:
        from forge.cli.hooks.direct_commands import _split_diff_per_file

        diff = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1 +1 @@\n"
            "+x = 1\n"
            "diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
            "--- /dev/null\n"
            "+++ b/tests/test_foo.py\n"
            "@@ -0,0 +1 @@\n"
            "+def test_foo(): pass\n"
        )
        result = _split_diff_per_file(diff)
        assert len(result) == 2
        paths = [r[0] for r in result]
        assert "src/foo.py" in paths
        assert "tests/test_foo.py" in paths

    def test_deleted_file_skipped(self) -> None:
        from forge.cli.hooks.direct_commands import _split_diff_per_file

        diff = (
            "diff --git a/old.py b/old.py\n"
            "deleted file mode 100644\n"
            "--- a/old.py\n"
            "+++ /dev/null\n"
            "@@ -1 +0,0 @@\n"
            "-x = 1\n"
        )
        result = _split_diff_per_file(diff)
        assert len(result) == 0

    def test_binary_file_extracts_path(self) -> None:
        from forge.cli.hooks.direct_commands import _split_diff_per_file

        diff = "diff --git a/image.png b/image.png\n" "Binary files a/image.png and b/image.png differ\n"
        result = _split_diff_per_file(diff)
        assert len(result) == 1
        assert result[0][0] == "image.png"

    def test_empty_diff(self) -> None:
        from forge.cli.hooks.direct_commands import _split_diff_per_file

        assert _split_diff_per_file("") == []
        assert _split_diff_per_file("  \n") == []

    def test_no_diff_headers(self) -> None:
        from forge.cli.hooks.direct_commands import _split_diff_per_file

        assert _split_diff_per_file("just some text\n") == []


class TestExtractAddedLines:
    """Tests for extract_added_lines utility."""

    def test_extracts_added_lines_only(self) -> None:
        from forge.policy.types import extract_added_lines

        diff = "@@ -1,3 +1,4 @@\n" " context line\n" "-removed line\n" "+added line\n" "+another added\n"
        result = extract_added_lines(diff)
        assert result == "added line\nanother added"

    def test_skips_plus_plus_plus_header(self) -> None:
        from forge.policy.types import extract_added_lines

        diff = "+++ b/src/foo.py\n+real content\n"
        assert extract_added_lines(diff) == "real content"

    def test_empty_diff(self) -> None:
        from forge.policy.types import extract_added_lines

        assert extract_added_lines("") == ""

    def test_no_additions(self) -> None:
        from forge.policy.types import extract_added_lines

        diff = "@@ -1,2 +1,1 @@\n context\n-removed\n"
        assert extract_added_lines(diff) == ""


class TestGuardCheck:
    """Tests for %policy check direct command."""

    def _make_session(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        policy_enabled: bool = True,
    ) -> SessionStore:
        """Create session with TDD bundle configured."""
        from forge.session import create_session_state
        from forge.session.models import PolicyIntent

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_SESSION", "test-session")

        store = SessionStore(str(tmp_path), "test-session")
        manifest = create_session_state(
            "test-session",
            proxy_template="test-family",
            proxy_base_url="http://localhost:8080",
        )
        manifest.intent.policy = PolicyIntent(enabled=policy_enabled, bundles=["tdd"], fail_mode="closed")
        store.write(manifest)
        return store

    def _make_git_repo(self, tmp_path: Path) -> None:
        """Initialize a git repo with an initial commit."""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        (tmp_path / "README.md").write_text("# Test\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

    def test_check_no_bundles_no_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No session and no --bundle shows error."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_SESSION", raising=False)

        runner = CliRunner()
        payload = {"prompt": "%policy check", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["passed"] is False
        assert "no bundles" in out["reason"].lower()

    def test_check_no_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty diff reports no changes."""
        self._make_git_repo(tmp_path)
        self._make_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy check", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert "no" in out["reason"].lower() and "changes" in out["reason"].lower()

    def test_check_test_file_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A test file change passes TDD checks."""
        self._make_git_repo(tmp_path)
        self._make_session(tmp_path, monkeypatch)

        # Track file then modify to create unstaged change
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("# placeholder\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add test"], cwd=str(tmp_path), capture_output=True, check=True)
        (tests_dir / "test_foo.py").write_text("def test_foo():\n    assert True\n")

        runner = CliRunner()
        payload = {"prompt": "%policy check --bundle tdd", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["passed"] is True
        assert "passed" in out["reason"].lower()

    def test_check_impl_only_denied(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An impl file without tests is denied by TDD."""
        self._make_git_repo(tmp_path)
        self._make_session(tmp_path, monkeypatch)

        # Track file then modify to create unstaged change
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "foo.py").write_text("# placeholder\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add src"], cwd=str(tmp_path), capture_output=True, check=True)
        (src_dir / "foo.py").write_text("def compute():\n    return 42\n")

        runner = CliRunner()
        payload = {"prompt": "%policy check --bundle tdd", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["passed"] is False
        assert "failed" in out["reason"].lower()

    def test_check_impl_and_test_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Impl + test together passes TDD (optimistic tests-first ordering)."""
        self._make_git_repo(tmp_path)
        self._make_session(tmp_path, monkeypatch)

        # Track files then modify to create unstaged changes
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("# placeholder\n")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "foo.py").write_text("# placeholder\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add files"], cwd=str(tmp_path), capture_output=True, check=True)
        (tests_dir / "test_foo.py").write_text("def test_foo():\n    assert True\n")
        (src_dir / "foo.py").write_text("def compute():\n    return 42\n")

        runner = CliRunner()
        payload = {"prompt": "%policy check --bundle tdd", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["passed"] is True
        assert out["files_checked"] >= 2

    def test_check_staged_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--staged evaluates only staged changes."""
        self._make_git_repo(tmp_path)
        self._make_session(tmp_path, monkeypatch)

        # Create and commit both files first
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_bar.py").write_text("# placeholder\n")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "bar.py").write_text("# placeholder\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add files"], cwd=str(tmp_path), capture_output=True, check=True)

        # Modify test file and stage it
        (tests_dir / "test_bar.py").write_text("def test_bar():\n    pass\n")
        subprocess.run(["git", "add", "tests/"], cwd=str(tmp_path), capture_output=True, check=True)

        # Modify impl file but leave unstaged — should NOT be seen with --staged
        (src_dir / "bar.py").write_text("x = 1\n")

        runner = CliRunner()
        payload = {"prompt": "%policy check --staged --bundle tdd", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["passed"] is True
        assert out["files_checked"] == 1

    def test_check_uses_session_bundles(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no --bundle specified, uses session's effective bundles."""
        self._make_git_repo(tmp_path)
        self._make_session(tmp_path, monkeypatch)

        # Track file then modify to create unstaged change
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("# placeholder\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add test"], cwd=str(tmp_path), capture_output=True, check=True)
        (tests_dir / "test_foo.py").write_text("def test_foo():\n    pass\n")

        runner = CliRunner()
        payload = {"prompt": "%policy check", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["passed"] is True
        assert out["bundles"] == ["tdd"]

    def test_check_disabled_session_still_uses_bundles(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even with policy disabled, %policy check still reads session bundles (diagnostic)."""
        self._make_git_repo(tmp_path)
        self._make_session(tmp_path, monkeypatch, policy_enabled=False)

        # Track file then modify to create unstaged change
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("# placeholder\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add test"], cwd=str(tmp_path), capture_output=True, check=True)
        (tests_dir / "test_foo.py").write_text("def test_foo():\n    pass\n")

        runner = CliRunner()
        payload = {"prompt": "%policy check", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["passed"] is True
        assert out["bundles"] == ["tdd"]

    def test_check_explicit_bundle_overrides_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit --bundle overrides session bundles."""
        self._make_git_repo(tmp_path)
        self._make_session(tmp_path, monkeypatch)

        # Track file then modify to create unstaged change
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "foo.py").write_text("# placeholder\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add src"], cwd=str(tmp_path), capture_output=True, check=True)
        (src_dir / "foo.py").write_text("x = 1\n")

        runner = CliRunner()
        # Session has tdd, but we override with coding_standards
        payload = {
            "prompt": "%policy check --bundle coding_standards",
            "transcript_path": "",
        }
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        # coding_standards won't deny "x = 1" (no TYPE_CHECKING, no backward compat)
        assert out["passed"] is True
        assert out["bundles"] == ["coding_standards"]

    def test_check_not_git_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-git directory reports error."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("FORGE_SESSION", "test-session")

        runner = CliRunner()
        payload = {"prompt": "%policy check --bundle tdd", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["decision"] == "block"
        assert out["passed"] is False
        assert "error" in out["reason"].lower()

    def test_check_session_read_error_surfaces(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Session read failure produces a clear error, not silent fallthrough."""
        self._make_git_repo(tmp_path)

        store = self._make_session(tmp_path, monkeypatch)
        # Corrupt the manifest to trigger a read error
        manifest_path = Path(store.manifest_path)
        manifest_path.write_text("not valid json{{{")

        runner = CliRunner()
        payload = {"prompt": "%policy check", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["passed"] is False
        assert "error reading session" in out["reason"].lower()

    def test_check_evaluation_crash_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If engine.evaluate() throws, the file counts as a failure."""
        self._make_git_repo(tmp_path)
        monkeypatch.chdir(tmp_path)

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("# placeholder\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "add test"], cwd=str(tmp_path), capture_output=True, check=True)
        (tests_dir / "test_foo.py").write_text("def test_foo():\n    assert True\n")

        from forge.policy.engine import PolicyEngine

        def boom(self_engine, context):
            raise RuntimeError("policy engine exploded")

        monkeypatch.setattr(PolicyEngine, "evaluate", boom)

        runner = CliRunner()
        payload = {"prompt": "%policy check --bundle tdd", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert out["passed"] is False
        assert "engine-error" in out["reason"]
        assert out["files_checked"] == 1

    def test_check_appears_in_help(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """%help includes policy check."""
        monkeypatch.chdir(tmp_path)

        runner = CliRunner()
        payload = {"prompt": "%help", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "check" in out["reason"]


def _make_supervised_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, suspended: bool = False
) -> SessionStore:
    """Shared harness for the %policy supervise toggle/cascade test classes."""
    from forge.session import create_session_state
    from forge.session.models import PolicyIntent, SupervisorConfig

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "test-session")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))

    store = SessionStore(str(tmp_path), "test-session")
    manifest = create_session_state(
        "test-session",
        proxy_template="test-family",
        proxy_base_url="http://localhost:8080",
    )
    manifest.intent.policy = PolicyIntent(
        enabled=True,
        supervisor=SupervisorConfig(
            resume_id="planner",
            proxy="litellm-openai",
            suspended=suspended,
        ),
    )
    store.write(manifest)
    return store


def _make_bare_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SessionStore:
    from forge.session import create_session_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "test-session")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))

    store = SessionStore(str(tmp_path), "test-session")
    manifest = create_session_state("test-session")
    store.write(manifest)
    return store


class TestGuardSuperviseToggle:
    """Test %policy supervise off/on/remove/reload toggle commands."""

    def test_off_suspends_not_removes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_supervised_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise off", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "suspended" in out["reason"].lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.suspended is True
        assert updated.intent.policy.supervisor.resume_id == "planner"

    def test_on_resumes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_supervised_session(tmp_path, monkeypatch, suspended=True)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise on", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "resumed" in out["reason"].lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.suspended is False

    def test_on_without_supervisor_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_bare_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise on", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "no supervisor configured" in out["reason"].lower()

    def test_remove_destroys_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_supervised_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise remove", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "removed" in out["reason"].lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is None

    def test_off_without_supervisor_reports_not_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_bare_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise off", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "no supervisor configured" in out["reason"].lower()

    def test_reload_explicit_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_supervised_session(tmp_path, monkeypatch)
        plan = tmp_path / "plan.md"
        plan.write_text("# The Plan")

        runner = CliRunner()
        payload = {"prompt": f"%policy supervise reload {plan}", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "plan updated" in out["reason"].lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.plan_override_path == str(plan.resolve())

    def test_reload_extra_args_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_supervised_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise reload a b", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "usage" in out["reason"].lower()

    def test_reload_without_supervisor_reports_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_bare_session(tmp_path, monkeypatch)
        plan = tmp_path / "plan.md"
        plan.write_text("# The Plan")

        runner = CliRunner()
        payload = {"prompt": f"%policy supervise reload {plan}", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "no supervisor configured" in out["reason"].lower()

    def test_show_includes_suspended_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_supervised_session(tmp_path, monkeypatch, suspended=True)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "suspended" in out["reason"].lower()

    def test_show_includes_plan_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_supervised_session(tmp_path, monkeypatch)

        def _set_plan(m):
            m.intent.policy.supervisor.plan_override_path = "/some/plan.md"

        store.update(timeout_s=5.0, mutate=_set_plan)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "/some/plan.md" in out["reason"]

    def test_show_includes_cascade_line(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_supervised_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "Cascade: off" in out["reason"]

    def test_show_includes_unsupported_checker_provider(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_supervised_session(tmp_path, monkeypatch)

        def _set_bad_provider(m):
            m.intent.policy.supervisor.cascade = True
            m.intent.policy.supervisor.checker_provider = "anthropic"

        store.update(timeout_s=5.0, mutate=_set_bad_provider)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "Checker: unresolved via anthropic (unsupported)" in out["reason"]


class TestGuardSuperviseCascade:
    """Test %policy supervise cascade on|off."""

    def test_cascade_on_with_existing_plan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_supervised_session(tmp_path, monkeypatch)
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan")

        def _set_plan(m):
            m.intent.policy.supervisor.plan_override_path = str(plan)

        store.update(timeout_s=5.0, mutate=_set_plan)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise cascade on", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "cascade enabled" in out["reason"].lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.cascade is True

    def test_cascade_on_auto_resolves_plan(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch as mock_patch

        store = _make_supervised_session(tmp_path, monkeypatch)
        plan = tmp_path / "resolved.md"
        plan.write_text("# Plan")
        fake = SimpleNamespace(path=str(plan), source="self", session_name="test-session", captured_at=None)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise cascade on", "transcript_path": ""}
        with mock_patch(
            "forge.policy.semantic.supervisor.resolve_supervisor_reload_plan_path",
            return_value=fake,
        ):
            result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "cascade enabled" in out["reason"].lower()
        assert "current session" in out["reason"]

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.cascade is True
        assert updated.intent.policy.supervisor.plan_override_path == str(plan)

    def test_cascade_on_unresolvable_blocks_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import patch as mock_patch

        store = _make_supervised_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise cascade on", "transcript_path": ""}
        with mock_patch(
            "forge.policy.semantic.supervisor.resolve_supervisor_reload_plan_path",
            return_value=None,
        ):
            result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "no approved plan snapshot" in out["reason"].lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.cascade is False

    def test_cascade_off_disables(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_supervised_session(tmp_path, monkeypatch)

        def _enable(m):
            m.intent.policy.supervisor.cascade = True
            m.intent.policy.supervisor.plan_override_path = "/some/plan.md"

        store.update(timeout_s=5.0, mutate=_enable)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise cascade off", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "cascade disabled" in out["reason"].lower()

        updated = store.read()
        assert updated.intent.policy is not None
        assert updated.intent.policy.supervisor is not None
        assert updated.intent.policy.supervisor.cascade is False

    def test_cascade_bad_subcommand_shows_usage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_supervised_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise cascade maybe", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "usage" in out["reason"].lower()

    def test_cascade_on_without_supervisor_reports_not_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_bare_session(tmp_path, monkeypatch)

        runner = CliRunner()
        payload = {"prompt": "%policy supervise cascade on", "transcript_path": ""}
        result = runner.invoke(hooks, ["user-prompt-submit"], input=json.dumps(payload))

        assert result.exit_code == 0
        out = json.loads(result.output)
        assert "no supervisor configured" in out["reason"].lower()
