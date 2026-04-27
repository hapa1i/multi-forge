"""Docker-based integration tests for UserPromptSubmit dispatcher.

These tests run inside a session-scoped container (docker_in marker) for
complete filesystem isolation. They test the behavioral aspects of the
`forge hook user-prompt-submit` command which handles `%<cmd>` parsing.

Note: Clipboard integration tests verify response structure but don't test
actual clipboard operations since pbcopy isn't available in the container.
"""

from __future__ import annotations

import json

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


class TestCommandRecognition:
    """Tests for % command recognition.

    The dispatcher blocks recognized commands and lets unknown prompts through.
    """

    def _invoke_user_prompt(self, workspace: ContainerLike, prompt: str, transcript_path: str = "") -> tuple[int, str]:
        """Invoke user-prompt-submit hook and return (returncode, stdout)."""
        payload = json.dumps({"prompt": prompt, "transcript_path": transcript_path})
        result = workspace.exec(f"cd /workspace && echo '{payload}' | forge hook user-prompt-submit")
        return result.returncode, result.stdout

    @pytest.mark.parametrize("prompt", ["%h", "%help", "%session list", "%plan"])
    def test_recognized_commands_block(self, mock_claude_workspace: ContainerLike, prompt: str) -> None:
        """Known % commands should block and return JSON response."""
        returncode, stdout = self._invoke_user_prompt(mock_claude_workspace, prompt)

        assert returncode == 0
        output = json.loads(stdout)
        assert output["decision"] == "block"

    def test_cancel_verification_recognized(self, mock_claude_workspace: ContainerLike) -> None:
        """cancel-verification requires a session; test it separately."""
        # Create a session so the command can find it
        mock_claude_workspace.exec("cd /workspace && forge session start test-session")
        payload = json.dumps({"prompt": "%cancel-verification", "transcript_path": ""})
        result = mock_claude_workspace.exec(
            f"cd /workspace && export FORGE_SESSION=test-session && echo '{payload}' | forge hook user-prompt-submit"
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["decision"] == "block"

    @pytest.mark.parametrize("prompt", ["  %help", "\t%h"])
    def test_leading_whitespace_stripped(self, mock_claude_workspace: ContainerLike, prompt: str) -> None:
        """Leading whitespace should be stripped before command recognition."""
        returncode, stdout = self._invoke_user_prompt(mock_claude_workspace, prompt)

        assert returncode == 0
        output = json.loads(stdout)
        assert output["decision"] == "block"

    @pytest.mark.parametrize("prompt", ["hello world", "what is %help?"])
    def test_non_commands_pass_through(self, mock_claude_workspace: ContainerLike, prompt: str) -> None:
        """Non-% prompts and % not at start should pass through (empty output)."""
        returncode, stdout = self._invoke_user_prompt(mock_claude_workspace, prompt)

        assert returncode == 0
        assert stdout.strip() == ""

    @pytest.mark.parametrize("prompt", ["%unknown_xyz", "%notacommand"])
    def test_unknown_percent_commands_pass_through(self, mock_claude_workspace: ContainerLike, prompt: str) -> None:
        """Unknown % commands should pass through to Claude."""
        returncode, stdout = self._invoke_user_prompt(mock_claude_workspace, prompt)

        assert returncode == 0
        assert stdout.strip() == ""


class TestPlanCommand:
    """Tests for %plan direct command."""

    def _invoke_plan(self, workspace: ContainerLike, prompt: str = "%plan", session_name: str | None = None) -> dict:
        """Invoke %plan and return parsed response."""
        payload = json.dumps({"prompt": prompt, "transcript_path": ""})
        if session_name is None:
            result = workspace.exec(f"cd /workspace && echo '{payload}' | forge hook user-prompt-submit")
        else:
            result = workspace.exec(
                f"cd /workspace && export FORGE_SESSION={session_name} && echo '{payload}' | forge hook user-prompt-submit"
            )
        return json.loads(result.stdout)

    def test_plan_blocks_with_plan_path(self, mock_claude_workspace: ContainerLike) -> None:
        """Should return the manifest-recorded plan path for the current session."""
        session_name = "test-session"
        mock_claude_workspace.exec(f"cd /workspace && forge session start {session_name} --no-launch")

        manifest = mock_claude_workspace.read_json(f"/workspace/.forge/sessions/{session_name}/forge.session.json")
        manifest["confirmed"]["latest_plan_path"] = ".claude/plans/example.md"
        mock_claude_workspace.write_json(f"/workspace/.forge/sessions/{session_name}/forge.session.json", manifest)

        output = self._invoke_plan(mock_claude_workspace, session_name=session_name)

        assert output["decision"] == "block"
        assert "Plan (draft):" in output["reason"]
        assert ".claude/plans/example.md" in output["reason"]
        assert "file missing" in output["reason"]


class TestHelpCommand:
    """Tests for %help and %h commands."""

    def _invoke_help(self, workspace: ContainerLike) -> dict:
        """Invoke %help and return parsed response."""
        payload = json.dumps({"prompt": "%help", "transcript_path": ""})
        result = workspace.exec(f"cd /workspace && echo '{payload}' | forge hook user-prompt-submit")
        return json.loads(result.stdout)

    def test_help_blocks_with_help_text(self, mock_claude_workspace: ContainerLike) -> None:
        """Should return help text listing available commands."""
        output = self._invoke_help(mock_claude_workspace)

        assert output["decision"] == "block"
        assert "%session" in output["reason"]
        assert "%help" in output["reason"] or "commands" in output["reason"].lower()


class TestCancelVerification:
    """Tests for %cancel-verification command."""

    def _setup_session_with_verification(self, workspace: ContainerLike, session_name: str = "test-session") -> None:
        """Create a session with verification policy configured."""
        workspace.exec(f"cd /workspace && forge session start {session_name}")

        # Read manifest and add verification config
        result = workspace.exec(f"cat /workspace/.forge/sessions/{session_name}/forge.session.json")
        manifest = json.loads(result.stdout)
        manifest["intent"]["verification"] = {
            "promise": "<done>COMPLETE</done>",
            "max_iterations": 3,
        }
        manifest_json = json.dumps(manifest)
        workspace.exec(
            f"cat > /workspace/.forge/sessions/{session_name}/forge.session.json << 'EOF'\n{manifest_json}\nEOF"
        )

    def _invoke_cancel_verification(self, workspace: ContainerLike, session_name: str = "test-session") -> dict:
        """Invoke %cancel-verification and return parsed response."""
        payload = json.dumps({"prompt": "%cancel-verification", "transcript_path": ""})
        result = workspace.exec(
            f"cd /workspace && export FORGE_SESSION={session_name} && echo '{payload}' | forge hook user-prompt-submit"
        )
        return json.loads(result.stdout)

    def test_cancel_verification_blocks(self, mock_claude_workspace: ContainerLike) -> None:
        """Should block and confirm verification bypass."""
        self._setup_session_with_verification(mock_claude_workspace)

        output = self._invoke_cancel_verification(mock_claude_workspace)

        assert output["decision"] == "block"

    def test_cancel_verification_sets_override(self, mock_claude_workspace: ContainerLike) -> None:
        """Should set verification.bypass override in manifest."""
        self._setup_session_with_verification(mock_claude_workspace)

        self._invoke_cancel_verification(mock_claude_workspace)

        # Verify override was set in manifest
        result = mock_claude_workspace.exec("cat /workspace/.forge/sessions/test-session/forge.session.json")
        manifest = json.loads(result.stdout)

        overrides = manifest.get("overrides", {})
        verification = overrides.get("verification", {})
        assert verification.get("bypass") is True


class TestSessionListCommand:
    """Tests for %session list command."""

    def _invoke_session_list(self, workspace: ContainerLike) -> dict:
        """Invoke %session list and return parsed response."""
        payload = json.dumps({"prompt": "%session list", "transcript_path": ""})
        result = workspace.exec(f"cd /workspace && echo '{payload}' | forge hook user-prompt-submit")
        return json.loads(result.stdout)

    def test_session_list_blocks(self, mock_claude_workspace: ContainerLike) -> None:
        """Should block and show session info."""
        output = self._invoke_session_list(mock_claude_workspace)

        assert output["decision"] == "block"
        assert "sessions" in output["reason"].lower() or "session" in output["reason"].lower()


class TestProxyCommands:
    """Tests for %proxy command variants.

    Tests proxy list, show, and error handling.
    """

    def _create_proxy_registry(self, workspace: ContainerLike, proxies: dict) -> None:
        """Create proxy registry in ~/.forge/proxies/."""
        workspace.exec("mkdir -p ~/.forge/proxies")
        registry = {
            "version": 1,
            "proxies": proxies,
        }
        registry_json = json.dumps(registry)
        workspace.exec(f"cat > ~/.forge/proxies/index.json << 'EOF'\n{registry_json}\nEOF")

    def _invoke_proxy(self, workspace: ContainerLike, prompt: str) -> dict:
        """Invoke %proxy command and return parsed response."""
        payload = json.dumps({"prompt": prompt, "transcript_path": ""})
        result = workspace.exec(f"cd /workspace && echo '{payload}' | forge hook user-prompt-submit")
        return json.loads(result.stdout)

    def test_proxy_list_no_leases(self, mock_claude_workspace: ContainerLike) -> None:
        """Should show message when no proxies exist."""
        output = self._invoke_proxy(mock_claude_workspace, "%proxy list")

        assert output["decision"] == "block"
        assert "no proxies" in output["reason"].lower() or "empty" in output["reason"].lower()

    def test_proxy_list_with_leases(self, mock_claude_workspace: ContainerLike) -> None:
        """Should list existing proxies."""
        self._create_proxy_registry(
            mock_claude_workspace,
            {
                "test-proxy": {
                    "proxy_id": "test-proxy",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": None,
                    "status": "healthy",
                }
            },
        )

        output = self._invoke_proxy(mock_claude_workspace, "%proxy list")

        assert output["decision"] == "block"
        assert "test-proxy" in output["reason"]
        assert "litellm-openai" in output["reason"]

    def test_proxy_show_details(self, mock_claude_workspace: ContainerLike) -> None:
        """Should show detailed proxy information."""
        self._create_proxy_registry(
            mock_claude_workspace,
            {
                "my-proxy": {
                    "proxy_id": "my-proxy",
                    "template": "litellm-gemini",
                    "base_url": "http://localhost:8086",
                    "port": 8086,
                    "pid": None,
                    "status": "healthy",
                }
            },
        )

        output = self._invoke_proxy(mock_claude_workspace, "%proxy show my-proxy")

        assert output["decision"] == "block"
        assert "my-proxy" in output["reason"]
        assert "litellm-gemini" in output["reason"]
        assert "8086" in output["reason"]

    def test_proxy_show_not_found(self, mock_claude_workspace: ContainerLike) -> None:
        """Should show error for nonexistent proxy."""
        output = self._invoke_proxy(mock_claude_workspace, "%proxy show nonexistent")

        assert output["decision"] == "block"
        assert "error" in output["reason"].lower() or "not found" in output["reason"].lower()

    def test_proxy_show_requires_id(self, mock_claude_workspace: ContainerLike) -> None:
        """Should show usage error when ID missing."""
        output = self._invoke_proxy(mock_claude_workspace, "%proxy show")

        assert output["decision"] == "block"
        assert "usage" in output["reason"].lower()

    def test_proxy_no_subcommand_shows_usage(self, mock_claude_workspace: ContainerLike) -> None:
        """Should show usage when no subcommand provided."""
        output = self._invoke_proxy(mock_claude_workspace, "%proxy")

        assert output["decision"] == "block"
        assert "usage" in output["reason"].lower()

    def test_proxy_unknown_subcommand_shows_usage(self, mock_claude_workspace: ContainerLike) -> None:
        """Should show usage for unknown subcommand."""
        output = self._invoke_proxy(mock_claude_workspace, "%proxy foobar")

        assert output["decision"] == "block"
        assert "usage" in output["reason"].lower()
