"""Tests for Claude binary invocation.

IMPORTANT: These tests MUST mock subprocess.run. Never invoke the real Claude binary.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.core.reactive.env import (
    CLAUDE_CODE_ATTRIBUTION_HEADER_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
)
from forge.session.claude.invoke import (
    _build_command,
    _build_environment,
    _run_claude,
    find_claude_binary,
    invoke_claude,
    is_claude_available,
)


class TestBuildCommand:
    """Tests for _build_command()."""

    def test_base_command_is_claude(self) -> None:
        """Base command should just be ['claude']."""
        cmd = _build_command()
        assert cmd == ["claude"]

    def test_session_id_flag(self) -> None:
        """Should add --session-id flag."""
        cmd = _build_command(session_id="abc-123")
        assert "--session-id" in cmd
        assert "abc-123" in cmd
        assert cmd.index("--session-id") + 1 == cmd.index("abc-123")

    def test_resume_flag(self) -> None:
        """Should add --resume flag."""
        cmd = _build_command(resume_id="xyz-789")
        assert "--resume" in cmd
        assert "xyz-789" in cmd

    def test_fork_session_flag(self) -> None:
        """Should add --fork-session flag when resuming with fork."""
        cmd = _build_command(resume_id="parent-id", fork_session=True)
        assert "--resume" in cmd
        assert "--fork-session" in cmd

    def test_fork_without_resume_ignored(self) -> None:
        """Fork flag without resume should be ignored."""
        cmd = _build_command(fork_session=True)
        assert "--fork-session" not in cmd

    def test_model_flag(self) -> None:
        """Should add --model flag."""
        cmd = _build_command(model="opus")
        assert "--model" in cmd
        assert "opus" in cmd

    def test_system_prompt_file_flag(self) -> None:
        """Should add --append-system-prompt-file flag."""
        cmd = _build_command(system_prompt_file="/path/to/prompt.md")
        assert "--append-system-prompt-file" in cmd
        assert "/path/to/prompt.md" in cmd

    def test_multiple_flags_combined(self) -> None:
        """Should combine multiple flags correctly."""
        cmd = _build_command(
            session_id="session-123",
            model="haiku",
            system_prompt_file="/prompt.md",
        )
        assert "claude" in cmd
        assert "--session-id" in cmd
        assert "session-123" in cmd
        assert "--model" in cmd
        assert "haiku" in cmd
        assert "--append-system-prompt-file" in cmd
        assert "/prompt.md" in cmd


class TestBuildEnvironment:
    """Tests for _build_environment()."""

    def test_inherits_current_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should include current environment variables."""
        monkeypatch.setenv("EXISTING_VAR", "existing_value")

        env = _build_environment()
        assert env.get("EXISTING_VAR") == "existing_value"

    def test_adds_extra_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should add extra variables."""
        env = _build_environment({"NEW_VAR": "new_value"})
        assert env.get("NEW_VAR") == "new_value"

    def test_extra_vars_override_existing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Extra vars should override existing."""
        monkeypatch.setenv("MY_VAR", "original")

        env = _build_environment({"MY_VAR": "overridden"})
        assert env.get("MY_VAR") == "overridden"

    def test_none_extra_vars_works(self) -> None:
        """Should handle None extra_vars."""
        env = _build_environment(None)
        assert isinstance(env, dict)

    def test_unset_vars_remove_existing_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """unset_vars should remove stale routing keys from the child env."""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8085")
        monkeypatch.setenv("ACTIVE_TEMPLATE", "litellm-openai")

        env = _build_environment(None, ["ANTHROPIC_BASE_URL", "ACTIVE_TEMPLATE"])

        assert "ANTHROPIC_BASE_URL" not in env
        assert "ACTIVE_TEMPLATE" not in env

    def test_direct_unset_vars_scrub_inherited_attribution_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Interactive direct launches must not inherit the proxy cache workaround."""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8085")
        monkeypatch.setenv(CLAUDE_CODE_ATTRIBUTION_HEADER_VAR, "0")

        env = _build_environment(None, ["ANTHROPIC_BASE_URL", "ACTIVE_TEMPLATE"])

        assert "ANTHROPIC_BASE_URL" not in env
        assert CLAUDE_CODE_ATTRIBUTION_HEADER_VAR not in env

    def test_proxy_extra_vars_force_attribution_header_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Interactive proxy launches explicitly carry the cache workaround."""
        monkeypatch.setenv(CLAUDE_CODE_ATTRIBUTION_HEADER_VAR, "1")

        env = _build_environment({"ANTHROPIC_BASE_URL": "http://localhost:8085"})

        assert env["ANTHROPIC_BASE_URL"] == "http://localhost:8085"
        assert env[CLAUDE_CODE_ATTRIBUTION_HEADER_VAR] == "0"

    def test_mints_fresh_root_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An interactive launch is a run-tree root: FORGE_RUN_ID == FORGE_ROOT_RUN_ID, no parent."""
        for var in (FORGE_RUN_ID_VAR, FORGE_PARENT_RUN_ID_VAR, FORGE_ROOT_RUN_ID_VAR):
            monkeypatch.delenv(var, raising=False)

        env = _build_environment()

        assert env[FORGE_RUN_ID_VAR].startswith("run_")
        assert env[FORGE_RUN_ID_VAR] == env[FORGE_ROOT_RUN_ID_VAR]
        assert FORGE_PARENT_RUN_ID_VAR not in env

    def test_fresh_root_does_not_inherit_run_identity(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inherited run vars must NOT leak into an interactive root.

        Guards the two fragile lines in ``_build_environment``: the merge order (the fresh
        root must win over an inherited ``FORGE_RUN_ID``) and the ``FORGE_PARENT_RUN_ID``
        scrub (a root has no parent). A misparented root silently breaks usage attribution
        while still looking like a valid tree.
        """
        monkeypatch.setenv(FORGE_RUN_ID_VAR, "run_inherited")
        monkeypatch.setenv(FORGE_PARENT_RUN_ID_VAR, "run_inheritedparent")
        monkeypatch.setenv(FORGE_ROOT_RUN_ID_VAR, "run_inheritedroot")

        env = _build_environment()

        # A fresh root, not a child or a continuation of the inherited tree.
        assert env[FORGE_RUN_ID_VAR].startswith("run_")
        assert env[FORGE_RUN_ID_VAR] not in ("run_inherited", "run_inheritedroot")
        assert env[FORGE_ROOT_RUN_ID_VAR] == env[FORGE_RUN_ID_VAR]
        # A root has no parent — the inherited parent must be scrubbed.
        assert FORGE_PARENT_RUN_ID_VAR not in env


class TestRunClaude:
    """Tests for _run_claude()."""

    def test_runs_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should run subprocess with correct arguments."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _run_claude(["claude", "--help"])

        assert result == 0
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == ["claude", "--help"]

    def test_returns_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return subprocess exit code."""
        mock_run = Mock(return_value=Mock(returncode=42))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = _run_claude(["claude"])
        assert result == 42

    def test_passes_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should pass environment variables."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        env = {"FORGE_TEST": "value"}
        _run_claude(["claude"], env=env)

        _, kwargs = mock_run.call_args
        assert kwargs["env"] == env

    def test_passes_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Should pass working directory."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        _run_claude(["claude"], cwd=str(tmp_path))

        _, kwargs = mock_run.call_args
        assert kwargs["cwd"] == str(tmp_path.resolve())


class TestInvokeClaude:
    """Tests for invoke_claude()."""

    def test_builds_correct_command_for_new_session(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should build correct command for new session."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        invoke_claude(session_id="new-session-123", model="opus")

        args, _ = mock_run.call_args
        cmd = args[0]
        assert "--session-id" in cmd
        assert "new-session-123" in cmd
        assert "--model" in cmd
        assert "opus" in cmd

    def test_builds_correct_command_for_resume(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should build correct command for resume."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        invoke_claude(resume_id="existing-session-456")

        args, _ = mock_run.call_args
        cmd = args[0]
        assert "--resume" in cmd
        assert "existing-session-456" in cmd

    def test_builds_correct_command_for_fork(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should build correct command for fork."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        invoke_claude(resume_id="parent-789", fork_session=True)

        args, _ = mock_run.call_args
        cmd = args[0]
        assert "--resume" in cmd
        assert "--fork-session" in cmd

    def test_passes_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should pass environment variables."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)

        invoke_claude(
            session_id="test",
            env_vars={"FORGE_SESSION": "my-session"},
        )

        _, kwargs = mock_run.call_args
        assert kwargs["env"]["FORGE_SESSION"] == "my-session"

    def test_unset_env_vars_are_removed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """invoke_claude should remove requested env vars before spawning Claude."""
        mock_run = Mock(return_value=Mock(returncode=0))
        monkeypatch.setattr("subprocess.run", mock_run)
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8085")

        invoke_claude(
            session_id="test",
            unset_env_vars=["ANTHROPIC_BASE_URL"],
        )

        _, kwargs = mock_run.call_args
        assert "ANTHROPIC_BASE_URL" not in kwargs["env"]

    def test_returns_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return Claude's exit code."""
        mock_run = Mock(return_value=Mock(returncode=1))
        monkeypatch.setattr("subprocess.run", mock_run)

        result = invoke_claude(session_id="test")
        assert result == 1


class TestFindClaudeBinary:
    """Tests for find_claude_binary()."""

    def test_returns_path_when_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return path when claude is found."""
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/claude")

        result = find_claude_binary()
        assert result == "/usr/local/bin/claude"

    def test_returns_none_when_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return None when claude is not found."""
        monkeypatch.setattr("shutil.which", lambda _: None)

        result = find_claude_binary()
        assert result is None


class TestIsClaudeAvailable:
    """Tests for is_claude_available()."""

    def test_returns_true_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return True when claude is in PATH."""
        monkeypatch.setattr("shutil.which", lambda _: "/usr/local/bin/claude")

        assert is_claude_available() is True

    def test_returns_false_when_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return False when claude is not in PATH."""
        monkeypatch.setattr("shutil.which", lambda _: None)

        assert is_claude_available() is False
