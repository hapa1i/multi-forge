"""Tests for the interactive Codex TUI launcher (codex_frontend Phase 5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive.env import (
    FORGE_DEPTH_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    RunIdentity,
)
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.session.codex_invoke import invoke_codex_interactive

_TID = "019eaa51-6920-7c41-ae34-d4f7f368d55a"
_IDENTITY = RunIdentity(run_id="run_aaaaaaaaaaaa", parent_run_id=None, root_run_id="run_aaaaaaaaaaaa")


def _preflight(
    *, auth_source: str = "credential_file", billing_mode: str = "api", auth_method: str | None = None
) -> CodexPreflight:
    if auth_method is None:
        auth_method = "chatgpt_tokens" if auth_source == "codex_store" else "api_key"
    return CodexPreflight(
        installed=True,
        version="0.139.0",
        version_ok=True,
        auth_method=auth_method,  # type: ignore[arg-type]
        auth_source=auth_source,
        billing_mode=billing_mode,  # type: ignore[arg-type]
        ready=True,
        blocking_reason=None,
        hook_seam="enrollment_gated",
        proxy_responses="native_direct",
        doctor_status="ok",
    )


def _invoke(mock_run: MagicMock, **overrides: Any) -> int:
    mock_run.return_value = MagicMock(returncode=overrides.pop("returncode", 0))
    kwargs: dict[str, Any] = {
        "preflight": _preflight(auth_source="codex_store"),
        "session_name": "impl",
        "forge_root": "/proj",
        "cwd": "/proj/worktree",
        "run_identity": _IDENTITY,
    }
    kwargs.update(overrides)
    return invoke_codex_interactive(**kwargs)


@patch("forge.session.codex_invoke.subprocess.run")
class TestArgv:
    def test_bare_start_argv(self, mock_run: MagicMock) -> None:
        _invoke(mock_run)
        argv = mock_run.call_args.args[0]
        assert argv == ["codex", "--sandbox", "workspace-write"]

    def test_sandbox_override(self, mock_run: MagicMock) -> None:
        _invoke(mock_run, sandbox="read-only")
        assert mock_run.call_args.args[0] == ["codex", "--sandbox", "read-only"]

    def test_initial_prompt_is_last_positional(self, mock_run: MagicMock) -> None:
        _invoke(mock_run, initial_prompt="# Handoff context\n\nBODY\n")
        argv = mock_run.call_args.args[0]
        assert argv == ["codex", "--sandbox", "workspace-write", "# Handoff context\n\nBODY\n"]

    def test_reattach_uses_resume_subcommand_with_its_own_sandbox(self, mock_run: MagicMock) -> None:
        """`codex resume` declares its own -s/--sandbox (codex 0.139.0); a root-level
        flag is not guaranteed to propagate into the subcommand's flow."""
        _invoke(mock_run, resume_thread_id=_TID)
        argv = mock_run.call_args.args[0]
        assert argv == ["codex", "resume", "--sandbox", "workspace-write", _TID]

    def test_resume_and_prompt_are_mutually_exclusive(self, mock_run: MagicMock) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            _invoke(mock_run, resume_thread_id=_TID, initial_prompt="x")
        mock_run.assert_not_called()


@patch("forge.session.codex_invoke.subprocess.run")
class TestEnvAndProcess:
    def test_foreground_terminal_inherited_and_cwd(self, mock_run: MagicMock) -> None:
        _invoke(mock_run)
        kwargs = mock_run.call_args.kwargs
        assert kwargs["stdin"] is None
        assert kwargs["stdout"] is None
        assert kwargs["stderr"] is None
        assert kwargs["cwd"] == "/proj/worktree"

    def test_exit_code_passthrough(self, mock_run: MagicMock) -> None:
        assert _invoke(mock_run, returncode=3) == 3

    def test_session_and_root_identity_in_env(self, mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        # An inherited parent-run var must not survive: an interactive launch is a root.
        monkeypatch.setenv(FORGE_PARENT_RUN_ID_VAR, "run_bbbbbbbbbbbb")
        _invoke(mock_run)
        env = mock_run.call_args.kwargs["env"]
        assert env["FORGE_SESSION"] == "impl"
        assert env["FORGE_FORGE_ROOT"] == "/proj"
        assert env[FORGE_RUN_ID_VAR] == _IDENTITY.run_id
        assert env[FORGE_ROOT_RUN_ID_VAR] == _IDENTITY.root_run_id
        assert FORGE_PARENT_RUN_ID_VAR not in env

    def test_caller_identity_used_verbatim_never_minted(self, mock_run: MagicMock) -> None:
        """One-run-tree contract: the TUI env carries exactly the caller's root, so the
        transfer-curation event (emitted under the same identity) joins it."""
        other = RunIdentity(run_id="run_cccccccccccc", parent_run_id=None, root_run_id="run_cccccccccccc")
        _invoke(mock_run, run_identity=other)
        env = mock_run.call_args.kwargs["env"]
        assert env[FORGE_RUN_ID_VAR] == "run_cccccccccccc"
        assert env[FORGE_ROOT_RUN_ID_VAR] == "run_cccccccccccc"

    def test_env_sanitized_and_depth_incremented(self, mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "stale")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy")
        monkeypatch.setenv("CODEX_API_KEY", "stale-key")
        monkeypatch.setenv(FORGE_DEPTH_VAR, "0")
        _invoke(mock_run)  # codex_store posture: nothing re-injected
        env = mock_run.call_args.kwargs["env"]
        assert "ANTHROPIC_API_KEY" not in env
        assert "ANTHROPIC_BASE_URL" not in env
        assert "CODEX_API_KEY" not in env
        assert env[FORGE_DEPTH_VAR] == "1"

    @patch("forge.core.invoker.codex.codex_api_key_for_subprocess", return_value="resolved-key")
    def test_credential_file_auth_reinjected(self, _key: MagicMock, mock_run: MagicMock) -> None:
        _invoke(mock_run, preflight=_preflight(auth_source="credential_file"))
        env = mock_run.call_args.kwargs["env"]
        assert env["CODEX_API_KEY"] == "resolved-key"
