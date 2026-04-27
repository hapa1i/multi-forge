"""Docker-based E2E tests for workflow runner CLIs (forge workflow).

Covers real component wiring:
- forge workflow panel -> review engine -> claude subprocess + env
- forge workflow debate -> adversarial runner -> stance injection into stdin
- forge workflow panel --code -> multi-model code review with target injection
- forge workflow debate --code -> adversarial code evaluation with target injection
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from forge.core.models.catalog import get_compact_name, get_default_model
from tests.fixtures.docker import ContainerLike

OPENAI_DEFAULT = get_compact_name(get_default_model("openai", "opus"))

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def _write_proxy_registry(workspace: ContainerLike, *, proxy_id: str, base_url: str, port: int) -> None:
    workspace.mkdir("$HOME/.forge/proxies", parents=True)
    workspace.write_json(
        "$HOME/.forge/proxies/index.json",
        {
            "version": 1,
            "proxies": {
                proxy_id: {
                    "proxy_id": proxy_id,
                    "template": "litellm-openai",
                    "base_url": base_url,
                    "port": port,
                    "pid": None,
                    "status": "healthy",
                }
            },
        },
    )


def _assert_invocation_count(workspace: ContainerLike, expected: int) -> None:
    """Verify exact number of claude subprocess invocations before reading captures."""
    log = workspace.read_file("/tmp/claude_invocations.log").strip()
    actual = len([line for line in log.splitlines() if line])
    assert actual == expected, f"Expected {expected} claude invocation(s), got {actual}:\n{log}"


class TestRunMultiReviewE2E:
    def test_sets_anthropic_base_url_from_registry(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
    ) -> None:
        _write_proxy_registry(
            mock_claude_workspace,
            proxy_id="litellm-openai",
            base_url="http://127.0.0.1:4001",
            port=4001,
        )

        result = mock_claude_workspace.exec(
            f"cd /workspace && forge workflow panel --models {OPENAI_DEFAULT} -p 'ping' --timeout 5 --json",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        _assert_invocation_count(mock_claude_workspace, 1)

        invocations = mock_claude_workspace.read_file("/tmp/claude_invocations.log")
        assert "claude -p" in invocations

        env_text = claude_capture_file("/tmp/claude_env_*.log")
        assert "ANTHROPIC_BASE_URL=http://127.0.0.1:4001" in env_text
        assert "FORGE_DEPTH=1" in env_text

    def test_context_resume_adds_resume_flag(self, mock_claude_workspace: ContainerLike) -> None:
        _write_proxy_registry(
            mock_claude_workspace,
            proxy_id="litellm-openai",
            base_url="http://127.0.0.1:4001",
            port=4001,
        )

        result = mock_claude_workspace.exec(
            f"cd /workspace && forge workflow panel --models {OPENAI_DEFAULT} --context resume:abc-123 -p 'ping' --timeout 5",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        invocations = mock_claude_workspace.read_file("/tmp/claude_invocations.log")
        assert "--resume abc-123" in invocations

    def test_direct_anthropic_unsets_stale_base_url(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
    ) -> None:
        result = mock_claude_workspace.exec(
            "cd /workspace && ANTHROPIC_BASE_URL=http://stale forge workflow panel --models claude-opus -p 'ping' --timeout 5",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        _assert_invocation_count(mock_claude_workspace, 1)

        env_text = claude_capture_file("/tmp/claude_env_*.log")
        # ANTHROPIC_BASE_URL should not appear at all for direct Anthropic models
        env_lines = env_text.splitlines()
        base_url_lines = [line for line in env_lines if line.startswith("ANTHROPIC_BASE_URL=")]
        assert not base_url_lines, f"ANTHROPIC_BASE_URL should be absent for direct Anthropic, got: {base_url_lines}"

    def test_direct_anthropic_uses_bare_with_api_key(self, mock_claude_workspace: ContainerLike) -> None:
        result = mock_claude_workspace.exec(
            "cd /workspace && ANTHROPIC_API_KEY=test-key forge workflow panel --models claude-opus -p 'ping' --timeout 5",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        invocations = mock_claude_workspace.read_file("/tmp/claude_invocations.log")
        assert "claude -p --bare" in invocations

    def test_check_mode_fails_on_nonzero_exit(self, mock_claude_workspace: ContainerLike) -> None:
        result = mock_claude_workspace.exec(
            "cd /workspace && FORGE_MOCK_CLAUDE_EXIT_CODE=1 forge workflow panel --models claude-opus -p 'ping' --timeout 5 --check",
            timeout=30,
        )
        assert result.returncode == 1

        data = json.loads(result.stdout)
        assert data["passed"] is False


class TestRunDebateE2E:
    def test_debate_positional_proposal(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
    ) -> None:
        result = mock_claude_workspace.exec(
            "cd /workspace && forge workflow debate 'Should we use event sourcing?' --models claude-opus --timeout 5 --json",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        _assert_invocation_count(mock_claude_workspace, 1)

        stdin_text = claude_capture_file("/tmp/claude_stdin_*.log")
        # Marker must be replaced (not left as literal placeholder)
        assert "{stance_prompt}" not in stdin_text
        # Ethical guardrail from adversarial.py is appended to every stance
        assert "structured evaluation exercise" in stdin_text
        # Proposal text injected
        assert "event sourcing" in stdin_text

    def test_check_mode_fails_closed_without_verdict(self, mock_claude_workspace: ContainerLike) -> None:
        result = mock_claude_workspace.exec(
            "cd /workspace && forge workflow debate 'Test proposal' --models claude-opus --timeout 5 --check",
            timeout=30,
        )
        assert result.returncode == 1

        data = json.loads(result.stdout)
        assert data["passed"] is False


class TestRunDebateCodeE2E:
    def test_code_mode_injects_target(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
    ) -> None:
        result = mock_claude_workspace.exec(
            "cd /workspace && forge workflow debate src/ --code --models claude-opus --timeout 5 --json",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        _assert_invocation_count(mock_claude_workspace, 1)

        stdin_text = claude_capture_file("/tmp/claude_stdin_*.log")
        # Stance marker must be replaced (not left as literal placeholder)
        assert "{stance_prompt}" not in stdin_text
        # Ethical guardrail from adversarial.py is appended to every stance
        assert "structured evaluation exercise" in stdin_text
        # Target path injected into code evaluation template
        assert "src/" in stdin_text
        # Code-specific content present
        assert "Code Under Evaluation" in stdin_text

    def test_code_mode_check_fails_closed(self, mock_claude_workspace: ContainerLike) -> None:
        result = mock_claude_workspace.exec(
            "cd /workspace && forge workflow debate src/ --code --models claude-opus --timeout 5 --check",
            timeout=30,
        )
        assert result.returncode == 1

        data = json.loads(result.stdout)
        assert data["passed"] is False


class TestRunPanelCodeE2E:
    def test_positional_target_invokes_worker(
        self,
        mock_claude_workspace: ContainerLike,
        claude_capture_file: Callable[[str], str],
    ) -> None:
        _write_proxy_registry(
            mock_claude_workspace,
            proxy_id="litellm-openai",
            base_url="http://127.0.0.1:4001",
            port=4001,
        )

        result = mock_claude_workspace.exec(
            f"cd /workspace && forge workflow panel src/ --code --models {OPENAI_DEFAULT} --timeout 5 --json",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

        _assert_invocation_count(mock_claude_workspace, 1)

        stdin_text = claude_capture_file("/tmp/claude_stdin_*.log")
        assert "## Review Target" in stdin_text
        assert "src/" in stdin_text

        env_text = claude_capture_file("/tmp/claude_env_*.log")
        assert "ANTHROPIC_BASE_URL=http://127.0.0.1:4001" in env_text

    def test_prompt_flag_still_works(self, mock_claude_workspace: ContainerLike) -> None:
        result = mock_claude_workspace.exec(
            "cd /workspace && forge workflow panel -p 'review src/' --models claude-opus --timeout 5 --json",
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
