"""Tests for session resume and routing CLI behavior."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

import forge.cli.session as session_cli
from forge.cli.main import main
from forge.session import SessionManager, SessionStore, create_session_state
from forge.session.config import LAUNCH_MODE_HOST
from forge.session.models import (
    LaneRecord,
    StartedWithProxy,
    SystemPromptIntent,
)
from tests.src.cli.session_command_support import (
    _proxy_cfg,
    _proxy_routing,
    successful_claude_launch,
)


class TestSessionResumeExtended:
    """Additional session resume tests."""

    def test_resume_combines_custom_prompt_under_forge_launch_context(self, runner: CliRunner, temp_env: Path) -> None:
        """Resume should store combined prompt files under .forge/launch-context."""
        custom_prompt = temp_env / "custom-system.md"
        custom_prompt.write_text("Custom system prompt", encoding="utf-8")

        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "resume-parent", "--no-launch"])

        manager = SessionManager()
        parent_store = manager.get_session_store("resume-parent")

        # Simulate SessionStart hook setting the UUID (launch-owned)
        parent_session_id = "simulated-resume-parent-uuid"

        def _set_parent_prompt_and_uuid(manifest) -> None:
            manifest.intent.system_prompt = SystemPromptIntent(file=str(custom_prompt))
            manifest.confirmed.claude_session_id = parent_session_id

        parent_store.update(timeout_s=5.0, mutate=_set_parent_prompt_and_uuid)

        from forge.session.claude.paths import get_transcript_path

        transcript_path = get_transcript_path(str(temp_env.resolve()), parent_session_id)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(
            '{"requestId":"r1","timestamp":"2025-01-15T10:00:00Z","message":{"role":"user","content":[{"type":"text","text":"resume context"}]}}\n',
            encoding="utf-8",
        )

        def _set_parent_transcript(manifest) -> None:
            manifest.confirmed.transcript_path = str(transcript_path)

        parent_store.update(timeout_s=5.0, mutate=_set_parent_transcript)

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(main, ["session", "resume", "resume-parent", "--fresh"])

        assert result.exit_code == 0
        assert mock_invoke.call_args is not None
        prompt_file = mock_invoke.call_args.kwargs["system_prompt_file"]
        assert prompt_file is not None
        prompt_path = Path(prompt_file)
        assert prompt_path.parent == temp_env / ".forge" / "launch-context"
        prompt_content = prompt_path.read_text(encoding="utf-8")
        assert "Custom system prompt" in prompt_content
        assert "# Session Context: resume-parent" in prompt_content

    def test_reconnect_proxy_session_injects_model_addendum(self, runner: CliRunner, temp_env: Path) -> None:
        """Reconnecting a proxy-routed session should retain addendum injection."""
        with patch(
            "forge.cli.session_lifecycle._resolve_routing_from_cli",
            return_value=_proxy_routing(),
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "reconnect-addendum",
                    "--proxy",
                    "openai-proxy",
                    "--no-launch",
                ],
            )
        assert result.exit_code == 0, result.output

        store = SessionStore(str(temp_env), "reconnect-addendum")

        def _confirm_proxy_session(manifest) -> None:
            manifest.confirmed.claude_session_id = "reconnect-uuid"
            manifest.confirmed.confirmed_by = "hook:SessionStart:startup"
            manifest.confirmed.started_with_proxy = StartedWithProxy(
                base_url="http://localhost:8085",
                proxy_id="openai-proxy",
                template="litellm-openai",
            )

        store.update(timeout_s=5.0, mutate=_confirm_proxy_session)

        with (
            patch(
                "forge.config.loader.load_proxy_instance_config",
                return_value=_proxy_cfg(),
            ),
            successful_claude_launch() as mock_invoke,
        ):
            result = runner.invoke(main, ["session", "resume", "reconnect-addendum"])

        assert result.exit_code == 0, result.output
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["resume_id"] == "reconnect-uuid"
        prompt_file = kwargs["system_prompt_file"]
        assert prompt_file is not None
        prompt_content = Path(prompt_file).read_text(encoding="utf-8")
        assert "Tool Parameter Guidance" in prompt_content


class TestSessionResume:
    """Tests for 'forge session resume' command."""

    def test_resume_fresh_creates_derived_session(self, runner: CliRunner, temp_env: Path) -> None:
        """--fresh should create a derived session from an existing one."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "resume-test"])

        with successful_claude_launch():
            result = runner.invoke(main, ["session", "resume", "resume-test", "--fresh"])

        assert result.exit_code == 0
        assert "Created derived session" in result.output

    def test_resume_fresh_direct_parent_keeps_child_direct(self, runner: CliRunner, temp_env: Path) -> None:
        """--fresh on a direct parent should launch the child without proxy env."""
        runner.invoke(main, ["session", "start", "resume-direct", "--no-proxy", "--no-launch"])

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(main, ["session", "resume", "resume-direct", "--fresh"])

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        assert "ANTHROPIC_BASE_URL" not in kwargs["env_vars"]
        assert "ACTIVE_TEMPLATE" not in kwargs["env_vars"]
        assert "FORGE_PROXY_WIRE_SHAPE" not in kwargs["env_vars"]
        assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in kwargs["env_vars"]
        assert sorted(kwargs["unset_env_vars"]) == [
            "ACTIVE_TEMPLATE",
            "ANTHROPIC_BASE_URL",
            "FORGE_PROXY_WIRE_SHAPE",
        ]
        assert kwargs["model"] is None

    def test_resume_fresh_direct_uses_configured_model_override(self, runner: CliRunner, temp_env: Path) -> None:
        """--fresh direct resume should honor the configured direct-model override."""
        runner.invoke(main, ["session", "start", "resume-direct", "--no-proxy", "--no-launch"])

        with (
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.runtime_config.get_default_direct_model",
                return_value="claude-sonnet-4-6",
            ),
        ):
            result = runner.invoke(main, ["session", "resume", "resume-direct", "--fresh"])

        assert result.exit_code == 0
        assert mock_invoke.call_args is not None
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs["model"] is None
        assert kwargs["env_vars"]["ANTHROPIC_MODEL"] == "sonnet"
        assert kwargs["env_vars"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "claude-sonnet-4-6"

    def test_resume_nonexistent_fails(self, runner: CliRunner, temp_env: Path) -> None:
        """Should fail for nonexistent session."""
        result = runner.invoke(main, ["session", "resume", "nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output


class TestResumeNativeMode:
    """Tests for --resume-mode native|transfer on forge session resume."""

    def test_resume_fresh_default_is_transfer(self, runner: CliRunner, temp_env: Path) -> None:
        """--fresh without --resume-mode should use transfer (assembled context)."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "native-test"])

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(main, ["session", "resume", "native-test", "--fresh"])

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        # Transfer mode uses session_id (new session), not resume_id
        assert kwargs.get("session_id") is not None
        assert kwargs.get("resume_id") is None
        assert kwargs.get("fork_session") is False

    def test_resume_fresh_native_uses_resume_fork_session(self, runner: CliRunner, temp_env: Path) -> None:
        """--fresh --resume-mode native should use --resume --fork-session."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "native-test"])

        # Set confirmed session evidence (UUID + confirmed_by, required for native mode)
        store = SessionStore(str(temp_env), "native-test")

        def _confirm_native_test(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid-123"  # type: ignore[attr-defined]
            m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_native_test)

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "native-test",
                    "--fresh",
                    "--resume-mode",
                    "native",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        # Native mode uses resume_id + fork_session, not session_id
        assert kwargs.get("resume_id") == "parent-uuid-123"
        assert kwargs.get("fork_session") is True
        assert kwargs.get("session_id") is None
        # Must NOT pass system_prompt_file
        assert kwargs.get("system_prompt_file") is None

    def test_resume_fresh_native_no_handoff_generation(self, runner: CliRunner, temp_env: Path) -> None:
        """Native mode must not call handoff generation at all."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "native-nogen"])

        store = SessionStore(str(temp_env), "native-nogen")

        def _confirm_nogen(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid-456"  # type: ignore[attr-defined]
            m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_nogen)

        with (
            successful_claude_launch(),
            patch("forge.session.manager.assemble_transfer_context") as mock_handoff,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "native-nogen",
                    "--fresh",
                    "--resume-mode",
                    "native",
                ],
            )

        assert result.exit_code == 0
        mock_handoff.assert_not_called()

    def test_resume_fresh_native_requires_claude_session_id(self, runner: CliRunner, temp_env: Path) -> None:
        """Native mode requires parent to have a confirmed claude_session_id."""
        # Create a session with no claude_session_id (simulate never-launched)
        state = create_session_state(
            "no-uuid",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8085",
            worktree_path=str(temp_env),
            worktree_branch="main",
        )
        assert state.confirmed.claude_session_id is None
        from forge.session.index import IndexStore

        store = SessionStore(str(temp_env), "no-uuid")
        store.write(state)
        idx = IndexStore()
        idx.add_from_state(state, str(temp_env))

        result = runner.invoke(main, ["session", "resume", "no-uuid", "--fresh", "--resume-mode", "native"])

        assert result.exit_code == 1
        assert "resume-mode native requires a parent" in result.output

    def test_resume_fresh_native_accepts_inferred_transcript_file(self, runner: CliRunner, temp_env: Path) -> None:
        """Native mode should accept transcript-backed parents even without confirmed_by."""
        runner.invoke(main, ["session", "start", "native-inferred", "--no-launch"])

        store = SessionStore(str(temp_env), "native-inferred")

        def _set_transcript_backed(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid-inferred"  # type: ignore[attr-defined]
            m.confirmed.confirmed_by = None  # type: ignore[attr-defined]
            m.confirmed.transcript_path = None  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_set_transcript_backed)

        from forge.session.claude.paths import get_transcript_path

        transcript_path = get_transcript_path(str(temp_env), "parent-uuid-inferred")
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text('{"message":{"role":"user","content":[{"type":"text","text":"hello"}]}}\n')

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "native-inferred",
                    "--fresh",
                    "--resume-mode",
                    "native",
                ],
            )

        assert result.exit_code == 0, result.output
        assert mock_invoke.call_args is not None
        assert mock_invoke.call_args.kwargs["resume_id"] == "parent-uuid-inferred"
        assert mock_invoke.call_args.kwargs["fork_session"] is True

    def test_resume_fresh_native_rejects_missing_transcript_file_without_confirmation(
        self, runner: CliRunner, temp_env: Path
    ) -> None:
        """A stale transcript_path string should not count as resumable evidence."""
        runner.invoke(main, ["session", "start", "native-stale", "--no-launch"])

        store = SessionStore(str(temp_env), "native-stale")

        def _set_stale_transcript(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid-stale"  # type: ignore[attr-defined]
            m.confirmed.confirmed_by = None  # type: ignore[attr-defined]
            m.confirmed.transcript_path = str(temp_env / "missing-transcript.jsonl")  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_set_stale_transcript)

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "native-stale",
                    "--fresh",
                    "--resume-mode",
                    "native",
                ],
            )

        assert result.exit_code == 1
        assert mock_invoke.called is False
        assert "resume-mode native requires a parent" in result.output

    def test_resume_mode_without_fresh_is_error(self, runner: CliRunner, temp_env: Path) -> None:
        """--resume-mode without --fresh should error."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "mode-test"])

        result = runner.invoke(main, ["session", "resume", "mode-test", "--resume-mode", "native"])

        assert result.exit_code == 1
        assert "--resume-mode requires --fresh" in result.output

    def test_resume_fresh_native_warns_about_strategy(self, runner: CliRunner, temp_env: Path) -> None:
        """--resume-mode native with explicit --strategy should print a warning tip."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "warn-test"])

        store = SessionStore(str(temp_env), "warn-test")

        def _confirm_warn(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid-789"  # type: ignore[attr-defined]
            m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_warn)

        with successful_claude_launch():
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "warn-test",
                    "--fresh",
                    "--resume-mode",
                    "native",
                    "--strategy",
                    "full",
                ],
            )

        assert result.exit_code == 0
        assert "Tip:" in result.output
        assert "--strategy is ignored" in result.output

    def test_resume_fresh_native_with_proxy_override(self, runner: CliRunner, temp_env: Path) -> None:
        """--fresh --resume-mode native --proxy should apply routing override."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "proxy-native"])

        store = SessionStore(str(temp_env), "proxy-native")

        def _confirm_proxy(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid-abc"  # type: ignore[attr-defined]
            m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_proxy)

        with (
            successful_claude_launch() as mock_invoke,
            patch(
                "forge.cli.session_lifecycle._resolve_routing_from_cli",
                return_value=type(
                    "R",
                    (),
                    {
                        "proxy_id": "test-proxy",
                        "template": "litellm-test",
                        "base_url": "http://localhost:9999",
                        "context_limit": None,
                    },
                )(),
            ),
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "proxy-native",
                    "--fresh",
                    "--resume-mode",
                    "native",
                    "--proxy",
                    "test-proxy",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("resume_id") == "parent-uuid-abc"
        assert kwargs.get("fork_session") is True
        # Proxy env should be set
        assert "ANTHROPIC_BASE_URL" in kwargs.get("env_vars", {})

    def test_resume_fresh_native_with_direct_flag(self, runner: CliRunner, temp_env: Path) -> None:
        """--fresh --resume-mode native --no-proxy should strip proxy env."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "direct-native"])

        store = SessionStore(str(temp_env), "direct-native")

        def _confirm_direct(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid-def"  # type: ignore[attr-defined]
            m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_direct)

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "direct-native",
                    "--fresh",
                    "--resume-mode",
                    "native",
                    "--no-proxy",
                ],
            )

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("resume_id") == "parent-uuid-def"
        assert kwargs.get("fork_session") is True
        # Direct mode should unset proxy env vars
        assert "ANTHROPIC_BASE_URL" not in kwargs.get("env_vars", {})

    def test_resume_fresh_native_persists_derivation(self, runner: CliRunner, temp_env: Path) -> None:
        """Native resume should persist correct derivation fields in child manifest."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "persist-parent"])

        store = SessionStore(str(temp_env), "persist-parent")

        def _confirm_persist(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid-persist"  # type: ignore[attr-defined]
            m.confirmed.confirmed_by = "hook:SessionStart:startup"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_persist)

        with successful_claude_launch():
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "persist-parent",
                    "--fresh",
                    "--resume-mode",
                    "native",
                    "--child-name",
                    "persist-child",
                ],
            )

        assert result.exit_code == 0

        # Read child manifest from disk and verify derivation fields
        child_store = SessionStore(str(temp_env), "persist-child")
        child_state = child_store.read()

        assert child_state.parent_session == "persist-parent"
        assert child_state.is_fork is False

        deriv = child_state.confirmed.derivation
        assert deriv is not None
        assert deriv.resume_mode == "native"
        assert deriv.strategy is None
        assert deriv.context_file is None
        assert deriv.parent_session == "persist-parent"
        assert deriv.depth == 1
        assert deriv.lineage == ["persist-parent"]


class TestProxyDirectFlags:
    """Tests for --proxy/--no-proxy flag consistency across commands."""

    def test_start_proxy_and_direct_mutually_exclusive(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "start", "test", "--proxy", "foo", "--no-proxy"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_resume_proxy_and_direct_mutually_exclusive(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "resume", "test", "--proxy", "foo", "--no-proxy"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_fork_proxy_and_direct_mutually_exclusive(self, runner: CliRunner, temp_env: Path) -> None:
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "parent", "--no-proxy"])
        result = runner.invoke(main, ["session", "fork", "parent", "--proxy", "foo", "--no-proxy"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_incognito_proxy_and_direct_mutually_exclusive(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "incognito", "--proxy", "foo", "--no-proxy"])
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_resume_direct_overrides_parent_proxy(self, runner: CliRunner, temp_env: Path) -> None:
        """--no-proxy on resume should clear proxy env even if parent had a proxy."""
        manager = SessionManager()
        manager.start_session(
            name="proxy-parent",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8084",
        )

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(main, ["session", "resume", "proxy-parent", "--no-proxy"])

        assert result.exit_code == 0
        kwargs = mock_invoke.call_args.kwargs
        assert "ANTHROPIC_BASE_URL" not in kwargs["env_vars"]
        assert "ANTHROPIC_BASE_URL" in kwargs["unset_env_vars"]

    def test_proxy_routed_resume_ignores_stored_direct_model_env(self, runner: CliRunner, temp_env: Path) -> None:
        """--proxy on resume should not inject a stored direct-model pin."""
        runner.invoke(
            main,
            [
                "session",
                "start",
                "proxy-resume-parent",
                "--model",
                "opus-4-8",
                "--no-launch",
            ],
        )
        routing = session_cli.ResolvedRouting(
            template="litellm-openai",
            base_url="http://localhost:9999",
            proxy_id="test-proxy",
        )

        with (
            patch(
                "forge.cli.session_lifecycle._resolve_routing_from_cli",
                return_value=routing,
            ),
            patch("forge.cli.session_lifecycle._resolve_context_limit", return_value=None),
            successful_claude_launch() as mock_invoke,
        ):
            result = runner.invoke(
                main,
                ["session", "resume", "proxy-resume-parent", "--proxy", "test-proxy"],
            )

        assert result.exit_code == 0, result.output
        env_vars = mock_invoke.call_args.kwargs["env_vars"]
        assert env_vars["ANTHROPIC_BASE_URL"] == "http://localhost:9999"
        assert "ANTHROPIC_MODEL" not in env_vars
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env_vars

    def test_proxy_routed_fork_ignores_stored_direct_model_env(self, runner: CliRunner, temp_env: Path) -> None:
        """--proxy on fork should not inject an inherited direct-model pin."""
        runner.invoke(
            main,
            [
                "session",
                "start",
                "proxy-fork-parent",
                "--model",
                "opus-4-8",
                "--no-launch",
            ],
        )
        store = SessionStore(str(temp_env), "proxy-fork-parent")

        def _confirm_parent(m: object) -> None:
            m.confirmed.claude_session_id = "parent-uuid"  # type: ignore[attr-defined]

        store.update(timeout_s=5.0, mutate=_confirm_parent)
        routing = session_cli.ResolvedRouting(
            template="litellm-openai",
            base_url="http://localhost:9999",
            proxy_id="test-proxy",
        )

        with (
            patch("forge.cli.session_fork._resolve_routing_from_cli", return_value=routing),
            patch("forge.cli.session_fork._resolve_context_limit", return_value=None),
            successful_claude_launch() as mock_invoke,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "proxy-fork-parent",
                    "--name",
                    "proxy-fork-child",
                    "--proxy",
                    "test-proxy",
                ],
            )

        assert result.exit_code == 0, result.output
        env_vars = mock_invoke.call_args.kwargs["env_vars"]
        assert env_vars["ANTHROPIC_BASE_URL"] == "http://localhost:9999"
        assert "ANTHROPIC_MODEL" not in env_vars
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env_vars

    def test_resume_direct_on_sidecar_parent_uses_host_path(self, runner: CliRunner, temp_env: Path) -> None:
        """--no-proxy on resume should override inherited sidecar launch mode."""
        runner.invoke(
            main,
            [
                "session",
                "start",
                "resume-sidecar-parent",
                "--sidecar",
                "--no-launch",
            ],
        )

        with (
            successful_claude_launch() as mock_invoke,
            patch("forge.sidecar.run_sidecar_session", return_value=0) as mock_run_sidecar,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "resume-sidecar-parent",
                    "--fresh",
                    "--child-name",
                    "resume-sidecar-child",
                    "--no-proxy",
                ],
            )

        assert result.exit_code == 0, result.output
        assert mock_invoke.called is True
        assert mock_run_sidecar.called is False

        manager = SessionManager()
        child_state = manager.get_session("resume-sidecar-child")
        assert child_state.intent.proxy is None
        assert child_state.intent.launch is not None
        assert child_state.intent.launch.mode == LAUNCH_MODE_HOST
        assert child_state.intent.launch.sidecar is None

    def test_resume_direct_on_sidecar_launch_in_place_uses_host_env(self, runner: CliRunner, temp_env: Path) -> None:
        """--no-proxy on a never-started sidecar session should launch on host with direct env."""
        runner.invoke(
            main,
            [
                "session",
                "start",
                "resume-sidecar-direct",
                "--sidecar",
                "--no-launch",
            ],
        )

        with (
            patch(
                "forge.cli.session_lifecycle._resolve_context_limit",
                return_value=1048576,
            ) as mock_context_limit,
            successful_claude_launch() as mock_invoke,
            patch("forge.sidecar.run_sidecar_session", return_value=0) as mock_run_sidecar,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "resume",
                    "resume-sidecar-direct",
                    "--no-proxy",
                ],
            )

        assert result.exit_code == 0, result.output
        mock_context_limit.assert_called_once_with(None)
        assert mock_invoke.called is True
        assert mock_run_sidecar.called is False

        kwargs = mock_invoke.call_args.kwargs
        assert "ANTHROPIC_BASE_URL" not in kwargs["env_vars"]
        assert "ACTIVE_TEMPLATE" not in kwargs["env_vars"]
        assert "FORGE_PROXY_WIRE_SHAPE" not in kwargs["env_vars"]
        assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in kwargs["env_vars"]
        assert sorted(kwargs["unset_env_vars"]) == [
            "ACTIVE_TEMPLATE",
            "ANTHROPIC_BASE_URL",
            "FORGE_PROXY_WIRE_SHAPE",
        ]

        state = SessionManager().get_session("resume-sidecar-direct")
        assert state.intent.proxy is None
        assert state.intent.launch is not None
        assert state.intent.launch.mode == LAUNCH_MODE_HOST
        assert state.intent.launch.sidecar is None

    def test_fork_proxy_no_launch_persists_intent(self, runner: CliRunner, temp_env: Path) -> None:
        """--proxy on fork --no-launch should persist routing to manifest."""
        import json

        # Create parent with direct routing
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "persist-parent", "--no-proxy"])

        # Write a proxy registry so resolve_proxy succeeds
        forge_home = Path(os.environ.get("FORGE_HOME", Path.home() / ".forge"))
        registry_path = forge_home / "proxies" / "index.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "proxies": {
                        "test-proxy": {
                            "proxy_id": "test-proxy",
                            "template": "litellm-openai",
                            "base_url": "http://localhost:8085",
                            "port": 8085,
                            "status": "healthy",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        with patch("forge.cli.claude._healthcheck_proxy", lambda **_: None):
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "persist-parent",
                    "--name",
                    "persist-child",
                    "--proxy",
                    "test-proxy",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0, result.output

        # Verify the manifest has the overridden proxy
        manager = SessionManager()
        child_state = manager.get_session("persist-child")
        assert child_state.intent.proxy is not None
        assert child_state.intent.proxy.template == "litellm-openai"
        assert child_state.intent.proxy.base_url == "http://localhost:8085"

    def test_routing_override_preserves_confirmed_proxy_on_disk(self, runner: CliRunner, temp_env: Path) -> None:
        """--proxy/--no-proxy should not clear confirmed.started_with_proxy on disk.

        A failed launch must not leave the manifest with cleared confirmed state.
        Only intent should be persisted; confirmed is hook-owned.
        """
        manager = SessionManager()
        manager.start_session(
            name="confirmed-proxy-test",
            proxy_template="litellm-openai",
            proxy_base_url="http://localhost:8084",
        )

        # Simulate hook confirmation with a proxy snapshot
        store = SessionStore(str(Path.cwd()), "confirmed-proxy-test")
        manifest = store.read()
        manifest.confirmed.started_with_proxy = StartedWithProxy(
            base_url="http://localhost:8084",
            proxy_id="old-proxy",
            template="litellm-openai",
        )
        manifest.confirmed.claude_session_id = "test-uuid-for-resume"
        manifest.confirmed.confirmed_by = "hook:SessionStart:startup"
        store.write(manifest)

        # Resume with --no-proxy (should change intent but not clear confirmed on disk)
        with successful_claude_launch():
            result = runner.invoke(main, ["session", "resume", "confirmed-proxy-test", "--no-proxy"])

        assert result.exit_code == 0, result.output

        # Verify: intent cleared (direct mode), but confirmed proxy preserved on disk
        updated = store.read()
        assert updated.intent.proxy is None, "intent.proxy should be cleared for --no-proxy"
        assert (
            updated.confirmed.started_with_proxy is not None
        ), "confirmed.started_with_proxy should NOT be cleared on disk"
        assert updated.confirmed.started_with_proxy.proxy_id == "old-proxy"


class TestSupervisorProxyFlags:
    """Tests for --supervisor-proxy / --no-supervisor-proxy on start and fork."""

    def test_start_supervisor_proxy_mutual_exclusivity(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(
            main,
            [
                "session",
                "start",
                "test",
                "--supervise",
                "planner",
                "--supervisor-proxy",
                "x",
                "--no-supervisor-proxy",
            ],
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_start_supervisor_proxy_requires_supervise(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "start", "test", "--supervisor-proxy", "x", "--no-launch"])
        assert result.exit_code == 1
        assert "require --supervise" in result.output

    def test_start_no_supervisor_proxy_requires_supervise(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "start", "test", "--no-supervisor-proxy", "--no-launch"])
        assert result.exit_code == 1
        assert "require --supervise" in result.output

    def test_fork_supervisor_proxy_mutual_exclusivity(self, runner: CliRunner, temp_env: Path) -> None:
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "sup-parent", "--no-proxy"])
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "sup-parent",
                "--supervise",
                "--supervisor-proxy",
                "x",
                "--no-supervisor-proxy",
            ],
        )
        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    def test_fork_supervisor_proxy_requires_supervise(self, runner: CliRunner, temp_env: Path) -> None:
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "sup-parent2", "--no-proxy"])
        result = runner.invoke(main, ["session", "fork", "sup-parent2", "--supervisor-proxy", "x"])
        assert result.exit_code == 1
        assert "require --supervise" in result.output

    def test_start_bad_supervisor_proxy_leaves_no_session(self, runner: CliRunner, temp_env: Path) -> None:
        """Bad --supervisor-proxy should fail before creating session state."""
        from unittest.mock import MagicMock

        with patch("forge.policy.semantic.supervisor.validate_supervisor_target") as mock_validate:
            mock_state = MagicMock()
            mock_state.confirmed.started_with_proxy = None
            mock_state.forge_root = None
            mock_validate.return_value = mock_state
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "bad-proxy-test",
                    "--supervise",
                    "planner",
                    "--supervisor-proxy",
                    "nonexistent-proxy",
                    "--no-launch",
                ],
            )
        assert result.exit_code == 1
        assert "no template named" in result.output
        manager = SessionManager()
        sessions = {n for n, _ in manager.list_sessions()}
        assert "bad-proxy-test" not in sessions

    def test_fork_bad_supervisor_proxy_leaves_no_fork(self, runner: CliRunner, temp_env: Path) -> None:
        """Bad --supervisor-proxy should fail before creating fork state."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", "fork-badproxy-parent", "--no-proxy"])
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "fork-badproxy-parent",
                "--supervise",
                "--supervisor-proxy",
                "nonexistent-proxy",
            ],
        )
        assert result.exit_code == 1
        assert "no template named" in result.output
        manager = SessionManager()
        sessions = {n for n, _ in manager.list_sessions()}
        assert "fork-badproxy-parent" in sessions  # parent still exists
        fork_names = {n for n, _ in manager.list_sessions() if n != "fork-badproxy-parent"}
        assert not any("fork-badproxy-parent" in n for n in fork_names)


class TestSupervisorLaunchControls:
    """Tests for --cascade / --checker-* / --supervisor-effort on start and fork.

    These options all require --supervise. They land on the child/session
    manifest's supervisor block (SupervisorConfig). For persistence cases we
    seed a real parent and let apply_supervisor_to_intent write the real
    fields, patching only apply_supervisor_routing (no proxy I/O), mirroring
    test_fork_proxy_no_launch_persists_intent.
    """

    def _seed_supervise_parent(self, runner: CliRunner, temp_env: Path, name: str) -> SessionStore:
        """Start a real parent session and confirm its Claude UUID."""
        with successful_claude_launch():
            runner.invoke(main, ["session", "start", name, "--no-proxy"])
        store = SessionStore(str(temp_env), name)
        store.update(
            timeout_s=5.0,
            mutate=lambda m: setattr(m.confirmed, "claude_session_id", "parent-uuid-x"),
        )
        return store

    # --- validation: launch-control flags require --supervise (no manifest needed) ---

    def test_fork_cascade_without_supervise_errors(self, runner: CliRunner, temp_env: Path) -> None:
        self._seed_supervise_parent(runner, temp_env, "sup-parent")
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "sup-parent",
                "--name",
                "child",
                "--cascade",
                "--no-launch",
            ],
        )
        assert result.exit_code != 0
        assert "require --supervise" in result.output

    def test_start_cascade_without_supervise_errors(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "start", "child-start", "--cascade", "--no-launch"])
        assert result.exit_code != 0
        assert "require --supervise" in result.output

    # --- persistence: --supervise --cascade --no-launch ---

    def test_fork_supervise_cascade_persists_flag_without_plan(self, runner: CliRunner, temp_env: Path) -> None:
        """--cascade at fork sets supervisor.cascade=True and leaves plan_override_path None.

        Launch-time cascade only flips the flag; the runtime hook resolves the plan at
        eval time (a fresh child has no approved snapshot yet).
        """
        self._seed_supervise_parent(runner, temp_env, "sup-parent")

        with patch(
            "forge.policy.semantic.supervisor.apply_supervisor_routing",
            return_value=None,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "sup-parent",
                    "--name",
                    "cascade-child",
                    "--supervise",
                    "--cascade",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0, result.output
        policy = SessionStore(str(temp_env), "cascade-child").read().intent.policy
        assert policy is not None
        sup = policy.supervisor
        assert sup is not None
        assert sup.cascade is True
        assert sup.plan_override_path is None

    def test_start_supervise_cascade_persists_flag_without_plan(self, runner: CliRunner, temp_env: Path) -> None:
        from unittest.mock import MagicMock

        mock_source = MagicMock()
        mock_source.confirmed.started_with_proxy = None
        mock_source.forge_root = str(temp_env)

        with (
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                return_value=mock_source,
            ),
            patch(
                "forge.policy.semantic.supervisor.apply_supervisor_routing",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "cascade-start",
                    "--supervise",
                    "planner",
                    "--cascade",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0, result.output
        policy = SessionStore(str(temp_env), "cascade-start").read().intent.policy
        assert policy is not None
        sup = policy.supervisor
        assert sup is not None
        assert sup.cascade is True
        assert sup.plan_override_path is None

    # --- persistence: checker-* + supervisor-effort (provider normalized dash->underscore) ---

    def test_fork_supervise_checker_options_persist_normalized(self, runner: CliRunner, temp_env: Path) -> None:
        self._seed_supervise_parent(runner, temp_env, "sup-parent")

        with patch(
            "forge.policy.semantic.supervisor.apply_supervisor_routing",
            return_value=None,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "sup-parent",
                    "--name",
                    "checker-child",
                    "--supervise",
                    "--checker-model",
                    "google/gemini-3.5-flash",
                    "--checker-provider",
                    "litellm-local",
                    "--checker-effort",
                    "low",
                    "--supervisor-effort",
                    "medium",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0, result.output
        policy = SessionStore(str(temp_env), "checker-child").read().intent.policy
        assert policy is not None
        sup = policy.supervisor
        assert sup is not None
        assert sup.checker_model == "google/gemini-3.5-flash"
        assert sup.checker_provider == "litellm_local"  # normalized dash->underscore
        assert sup.checker_effort == "low"
        assert sup.supervisor_effort == "medium"

    def test_start_supervise_checker_options_persist_normalized(self, runner: CliRunner, temp_env: Path) -> None:
        from unittest.mock import MagicMock

        mock_source = MagicMock()
        mock_source.confirmed.started_with_proxy = None
        mock_source.forge_root = str(temp_env)

        with (
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                return_value=mock_source,
            ),
            patch(
                "forge.policy.semantic.supervisor.apply_supervisor_routing",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "checker-start",
                    "--supervise",
                    "planner",
                    "--checker-model",
                    "google/gemini-3.5-flash",
                    "--checker-provider",
                    "litellm-local",
                    "--checker-effort",
                    "low",
                    "--supervisor-effort",
                    "medium",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0, result.output
        policy = SessionStore(str(temp_env), "checker-start").read().intent.policy
        assert policy is not None
        sup = policy.supervisor
        assert sup is not None
        assert sup.checker_model == "google/gemini-3.5-flash"
        assert sup.checker_provider == "litellm_local"  # normalized dash->underscore
        assert sup.checker_effort == "low"
        assert sup.supervisor_effort == "medium"

    # --- persistence: --supervisor-runtime writes the consumer-lane binding (not SupervisorConfig) ---

    def test_fork_supervisor_runtime_without_supervise_errors(self, runner: CliRunner, temp_env: Path) -> None:
        self._seed_supervise_parent(runner, temp_env, "sup-parent")
        result = runner.invoke(
            main,
            [
                "session",
                "fork",
                "sup-parent",
                "--name",
                "child",
                "--supervisor-runtime",
                "codex",
                "--no-launch",
            ],
        )
        assert result.exit_code != 0
        assert "require --supervise" in result.output

    def test_start_supervisor_runtime_without_supervise_errors(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(
            main,
            [
                "session",
                "start",
                "child-start",
                "--supervisor-runtime",
                "codex",
                "--no-launch",
            ],
        )
        assert result.exit_code != 0
        assert "require --supervise" in result.output

    def test_fork_supervise_runtime_persists_lane(self, runner: CliRunner, temp_env: Path) -> None:
        # The lane lands in intent.consumer_lanes.supervisor (the binding), not SupervisorConfig;
        # the child gets its own fresh binding, frozen at its first policy check.
        self._seed_supervise_parent(runner, temp_env, "sup-parent")

        with patch(
            "forge.policy.semantic.supervisor.apply_supervisor_routing",
            return_value=None,
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "fork",
                    "sup-parent",
                    "--name",
                    "codex-child",
                    "--supervise",
                    "--supervisor-runtime",
                    "codex",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0, result.output
        lanes = SessionStore(str(temp_env), "codex-child").read().intent.consumer_lanes
        assert lanes is not None
        assert lanes.supervisor == LaneRecord("codex", "chatgpt", "gpt-5-codex")

    def test_start_supervise_runtime_persists_lane(self, runner: CliRunner, temp_env: Path) -> None:
        from unittest.mock import MagicMock

        mock_source = MagicMock()
        mock_source.confirmed.started_with_proxy = None
        mock_source.forge_root = str(temp_env)

        with (
            patch(
                "forge.policy.semantic.supervisor.validate_supervisor_target",
                return_value=mock_source,
            ),
            patch(
                "forge.policy.semantic.supervisor.apply_supervisor_routing",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                main,
                [
                    "session",
                    "start",
                    "codex-start",
                    "--supervise",
                    "planner",
                    "--supervisor-runtime",
                    "codex",
                    "--no-launch",
                ],
            )

        assert result.exit_code == 0, result.output
        lanes = SessionStore(str(temp_env), "codex-start").read().intent.consumer_lanes
        assert lanes is not None
        assert lanes.supervisor == LaneRecord("codex", "chatgpt", "gpt-5-codex")
