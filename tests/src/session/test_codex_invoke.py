"""Tests for the interactive Codex TUI launcher (codex_frontend Phase 5)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive.env import (
    FORGE_DEPTH_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_PROXY_WIRE_SHAPE_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    RunIdentity,
)
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.session.codex_invoke import (
    _build_codex_proxy_argv,
    _build_codex_proxy_env,
    invoke_codex_bare_proxy,
    invoke_codex_interactive,
)

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

    def test_forge_dev_is_inherited(self, mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_DEV", "/checkout")

        _invoke(mock_run)

        assert mock_run.call_args.kwargs["env"]["FORGE_DEV"] == "/checkout"

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


# --- proxy-backed bare launch (forge codex start --proxy) ------------------

_PROXY_BASE = "http://127.0.0.1:8084"
_PROXY_BASE_ARGV = [
    "codex",
    "--sandbox",
    "workspace-write",
    "-c",
    "model_provider=forge_proxy",
    "-c",
    'model_providers.forge_proxy.name="Forge Proxy"',
    "-c",
    'model_providers.forge_proxy.base_url="http://127.0.0.1:8084/v1"',
    "-c",
    'model_providers.forge_proxy.wire_api="responses"',
    "-c",
    'model_providers.forge_proxy.env_key="FORGE_CODEX_PROXY_TOKEN"',
]


class TestBareProxyArgv:
    def test_base_argv_exact_tokens(self) -> None:
        argv = _build_codex_proxy_argv(base_url=_PROXY_BASE, sandbox="workspace-write", model=None, passthrough=())
        assert argv == _PROXY_BASE_ARGV

    def test_trailing_slash_no_double_v1(self) -> None:
        argv = _build_codex_proxy_argv(
            base_url=_PROXY_BASE + "/", sandbox="workspace-write", model=None, passthrough=()
        )
        assert 'model_providers.forge_proxy.base_url="http://127.0.0.1:8084/v1"' in argv
        assert "//v1" not in "".join(argv)

    def test_sandbox_flows_into_argv(self) -> None:
        argv = _build_codex_proxy_argv(base_url=_PROXY_BASE, sandbox="read-only", model=None, passthrough=())
        assert argv[:3] == ["codex", "--sandbox", "read-only"]

    def test_model_appended_when_no_user_model(self) -> None:
        argv = _build_codex_proxy_argv(base_url=_PROXY_BASE, sandbox="workspace-write", model="gpt-5.5", passthrough=())
        assert argv[-2:] == ["-m", "gpt-5.5"]

    def test_user_short_model_flag_suppresses_auto_default(self) -> None:
        argv = _build_codex_proxy_argv(
            base_url=_PROXY_BASE, sandbox="workspace-write", model="gpt-5.5", passthrough=["-m", "o3"]
        )
        assert argv.count("-m") == 1
        assert "gpt-5.5" not in argv
        assert argv[-2:] == ["-m", "o3"]

    def test_user_long_model_flag_suppresses(self) -> None:
        argv = _build_codex_proxy_argv(
            base_url=_PROXY_BASE, sandbox="workspace-write", model="gpt-5.5", passthrough=["--model", "o3"]
        )
        assert "gpt-5.5" not in argv

    def test_user_long_model_equals_suppresses(self) -> None:
        argv = _build_codex_proxy_argv(
            base_url=_PROXY_BASE, sandbox="workspace-write", model="gpt-5.5", passthrough=["--model=o3"]
        )
        assert "gpt-5.5" not in argv

    def test_model_none_no_dash_m(self) -> None:
        argv = _build_codex_proxy_argv(base_url=_PROXY_BASE, sandbox="workspace-write", model=None, passthrough=())
        assert "-m" not in argv

    def test_passthrough_appended_verbatim(self) -> None:
        argv = _build_codex_proxy_argv(
            base_url=_PROXY_BASE, sandbox="workspace-write", model=None, passthrough=["--search", "--foo"]
        )
        assert argv[-2:] == ["--search", "--foo"]

    def test_never_strict_config(self) -> None:
        argv = _build_codex_proxy_argv(
            base_url=_PROXY_BASE, sandbox="workspace-write", model="gpt-5.5", passthrough=["--search"]
        )
        assert "--strict-config" not in argv


# Every var the bare proxy env must scrub: OpenAI account/routing, session/fork identity,
# run-tree vars, and the shared codex/anthropic auth (from _CODEX_CHILD_STRIP_VARS).
_BARE_STRIP_VARS = [
    "OPENAI_API_KEY",
    "OPENAI_ORGANIZATION",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT",
    "OPENAI_BASE_URL",
    "FORGE_SESSION",
    "FORGE_FORGE_ROOT",
    "FORGE_FORK_NAME",
    "FORGE_PARENT_SESSION",
    FORGE_RUN_ID_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_PROXY_WIRE_SHAPE_VAR,
    "CODEX_API_KEY",
    "CODEX_ACCESS_TOKEN",
    "ANTHROPIC_API_KEY",
]


class TestBareProxyEnv:
    def test_all_strip_vars_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in _BARE_STRIP_VARS:
            monkeypatch.setenv(var, "leak")
        env = _build_codex_proxy_env()
        for var in _BARE_STRIP_VARS:
            assert var not in env, f"{var} leaked into the bare proxy env"

    def test_loopback_token_set(self) -> None:
        assert _build_codex_proxy_env()["FORGE_CODEX_PROXY_TOKEN"] == "forge-loopback"

    def test_depth_incremented_from_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(FORGE_DEPTH_VAR, "2")
        assert _build_codex_proxy_env()[FORGE_DEPTH_VAR] == "3"

    def test_depth_from_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(FORGE_DEPTH_VAR, "0")
        assert _build_codex_proxy_env()[FORGE_DEPTH_VAR] == "1"

    def test_depth_unset_defaults_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(FORGE_DEPTH_VAR, raising=False)
        assert _build_codex_proxy_env()[FORGE_DEPTH_VAR] == "1"

    def test_no_native_auth_reestablished(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Contrast sanitize_codex_child_env: the bare proxy env carries NO codex/openai auth.
        monkeypatch.setenv("CODEX_API_KEY", "stale")
        monkeypatch.setenv("OPENAI_API_KEY", "stale")
        env = _build_codex_proxy_env()
        assert "CODEX_API_KEY" not in env
        assert "OPENAI_API_KEY" not in env

    def test_unrelated_vars_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/me")
        env = _build_codex_proxy_env()
        assert env["PATH"] == "/usr/bin"
        assert env["HOME"] == "/home/me"

    def test_forge_dev_is_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FORGE_DEV", "/checkout")

        assert _build_codex_proxy_env()["FORGE_DEV"] == "/checkout"


@patch("forge.session.codex_invoke.subprocess.run")
class TestBareProxyInvoke:
    def test_wires_argv_env_cwd_and_returncode(self, mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CODEX_API_KEY", "stale")
        mock_run.return_value = MagicMock(returncode=7)
        rc = invoke_codex_bare_proxy(
            base_url=_PROXY_BASE, sandbox="workspace-write", model="gpt-5.5", passthrough=["--search"], cwd="/work"
        )
        assert rc == 7
        argv = mock_run.call_args.args[0]
        assert argv[:3] == ["codex", "--sandbox", "workspace-write"]
        assert argv[-3:] == ["-m", "gpt-5.5", "--search"]
        kwargs = mock_run.call_args.kwargs
        assert kwargs["env"]["FORGE_CODEX_PROXY_TOKEN"] == "forge-loopback"
        assert "CODEX_API_KEY" not in kwargs["env"]
        assert kwargs["cwd"] == "/work"
        assert kwargs["stdin"] is None
        assert kwargs["stdout"] is None
        assert kwargs["stderr"] is None

    def test_cwd_defaults_to_getcwd(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        invoke_codex_bare_proxy(base_url=_PROXY_BASE, model=None)
        assert mock_run.call_args.kwargs["cwd"]  # non-empty: os.getcwd()
