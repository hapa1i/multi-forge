"""Docker-based integration tests for status-line CLI command.

These tests run inside a session-scoped container (docker_in marker) for
complete filesystem isolation. They test the behavioral aspects of:
- CLI status-line command invocation
- Registry fallback behavior
- Session discovery from worktree

Note: Pure logic tests (ProxyRuntimeTruth parsing, get_tier_display formatting)
remain in unit tests since they don't touch protected paths.
"""

from __future__ import annotations

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def _create_registry(workspace: ContainerLike, proxies: dict) -> None:
    """Create proxy registry in the container."""
    workspace.mkdir("$HOME/.forge/proxies", parents=True)
    registry = {"version": 1, "proxies": proxies}
    workspace.write_json("$HOME/.forge/proxies/index.json", registry)


class TestStatusLineCommand:
    """Tests for `forge status-line` CLI command."""

    def test_status_line_returns_output(self, mock_claude_workspace: ContainerLike) -> None:
        """forge status-line should return some output without crashing."""
        result = mock_claude_workspace.exec("echo '{}' | forge status-line")

        assert result.returncode == 0
        assert result.stdout.strip() != ""

    def test_status_line_with_cwd_session(self, mock_claude_workspace: ContainerLike) -> None:
        """Status line should show session info when manifest exists in CWD."""
        mock_claude_workspace.exec("cd /workspace && forge session start test-session")

        result = mock_claude_workspace.exec("cd /workspace && echo '{}' | forge status-line")

        assert result.returncode == 0
        assert "test-session" in result.stdout or result.stdout.strip() != ""

    def test_status_line_exempt_from_queue_processing(self, mock_claude_workspace: ContainerLike) -> None:
        """forge status-line is exempt from startup queue processing."""
        mock_claude_workspace.exec("mkdir -p $HOME/.forge/pending-work")
        marker_data = {
            "schema_version": 1,
            "kind": "stop",
            "session_id": "test-marker-456",
            "session_name": "test-session",
            "worktree_path": "/workspace",
            "artifacts": {
                "transcript_snapshot_rel": ".forge/artifacts/test/transcripts/test.jsonl",
            },
            "created_at": "2025-01-01T00:00:00Z",
        }
        mock_claude_workspace.write_json("$HOME/.forge/pending-work/test-marker-456.json", marker_data)

        mock_claude_workspace.exec("echo '{}' | forge status-line")

        check = mock_claude_workspace.exec(
            "test -f $HOME/.forge/pending-work/test-marker-456.json && echo exists || echo missing"
        )
        assert "exists" in check.stdout, "status-line should NOT process pending-work queue"


class TestStatusLineSourcePlan:
    """Installed-CLI instrumentation for registry-owned proxy/session acquisition."""

    def test_configured_layout_acquires_only_declared_sources(
        self,
        mock_claude_workspace: ContainerLike,
    ) -> None:
        instrument_dir = "/tmp/d018-statusline-instrument"
        proxy_marker = "/tmp/d018-proxy-probes"
        session_marker = "/tmp/d018-session-probes"
        mock_claude_workspace.mkdir(instrument_dir, parents=True)
        mock_claude_workspace.write_file(proxy_marker, "")
        mock_claude_workspace.write_file(session_marker, "")
        mock_claude_workspace.write_file(
            f"{instrument_dir}/sitecustomize.py",
            """from pathlib import Path
from forge.cli.statusline import sources

def _detect_proxy():
    with Path('/tmp/d018-proxy-probes').open('a', encoding='utf-8') as handle:
        handle.write('1')
    return False, None, False

def _discover_session():
    with Path('/tmp/d018-session-probes').open('a', encoding='utf-8') as handle:
        handle.write('1')
    return None, False

sources.detect_proxy = _detect_proxy
sources.discover_session = _discover_session
""",
        )
        mock_claude_workspace.mkdir("$HOME/.forge", parents=True)
        mock_claude_workspace.write_json(
            "/tmp/d018-statusline-input.json",
            {
                "workspace": {"current_dir": "/workspace"},
                "model": {"display_name": "Claude"},
            },
        )

        mock_claude_workspace.write_file(
            "$HOME/.forge/config.yaml",
            "statusline:\n  segments: [path, branch]\n",
        )
        zero_source = mock_claude_workspace.exec(
            f"env PYTHONPATH={instrument_dir} forge status-line < /tmp/d018-statusline-input.json"
        )

        assert zero_source.returncode == 0
        assert "/workspace" in zero_source.stdout
        assert mock_claude_workspace.read_file(proxy_marker) == ""
        assert mock_claude_workspace.read_file(session_marker) == ""

        mock_claude_workspace.write_file(
            "$HOME/.forge/config.yaml",
            "statusline:\n  segments: [model, breadcrumb]\n",
        )
        mixed = mock_claude_workspace.exec(
            f"env PYTHONPATH={instrument_dir} forge status-line < /tmp/d018-statusline-input.json"
        )

        assert mixed.returncode == 0
        assert mock_claude_workspace.read_file(proxy_marker) == "1"
        assert mock_claude_workspace.read_file(session_marker) == "1"

        reset = mock_claude_workspace.exec("forge config reset statusline")
        assert reset.returncode == 0


class TestStatusLineRegistryFallback:
    """Tests for status-line registry fallback behavior.

    When ANTHROPIC_BASE_URL points to localhost but proxy is unreachable,
    status-line falls back to registry lookup for proxy info.
    """

    def test_fallback_with_matching_registry_entry(self, mock_claude_workspace: ContainerLike) -> None:
        """When proxy unreachable but registry has matching entry, uses fallback."""
        _create_registry(
            mock_claude_workspace,
            {
                "fallback-proxy": {
                    "proxy_id": "fallback-proxy",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": None,
                    "status": "healthy",
                }
            },
        )

        mock_claude_workspace.write_json("/tmp/status-line-input.json", {})

        result = mock_claude_workspace.exec(
            "env ANTHROPIC_BASE_URL=http://localhost:8085 forge status-line < /tmp/status-line-input.json"
        )

        assert result.returncode == 0

    def test_no_registry_match_continues_without_proxy(self, mock_claude_workspace: ContainerLike) -> None:
        """When proxy unreachable and no registry match, continues gracefully."""
        _create_registry(mock_claude_workspace, {})

        mock_claude_workspace.write_json("/tmp/status-line-input.json", {})

        result = mock_claude_workspace.exec(
            "env ANTHROPIC_BASE_URL=http://localhost:8085 forge status-line < /tmp/status-line-input.json"
        )

        assert result.returncode == 0


class TestLaunchMetadata:
    """Real-CLI coverage for confirmed.launch recording (G3) + the launch segment."""

    def _manifest_path(self, name: str) -> str:
        return f"/workspace/.forge/sessions/{name}/forge.session.json"

    def test_session_start_records_launch_metadata(self, mock_claude_workspace: ContainerLike) -> None:
        """record_launch_confirmed runs before invoke_claude, so a real start writes it."""
        mock_claude_workspace.exec("cd /workspace && forge session start launch-rec")

        manifest = mock_claude_workspace.read_json(self._manifest_path("launch-rec"))
        launch = manifest["confirmed"]["launch"]
        # Default start is direct (no --proxy); api_key_source is always recorded.
        assert launch["routing_mode"] == "direct"
        assert launch["api_key_source"] in {"env", "credential_file", "none"}

    def test_omit_records_omitted_by_config(self, mock_claude_workspace: ContainerLike) -> None:
        """interactive_anthropic_api_key=omit is the status-line breadcrumb for Bug #1."""
        mock_claude_workspace.mkdir("$HOME/.forge", parents=True)
        mock_claude_workspace.write_file(
            "$HOME/.forge/config.yaml",
            "interactive_anthropic_api_key: omit\n",
        )
        mock_claude_workspace.exec("cd /workspace && env ANTHROPIC_API_KEY=sk-ant-test forge session start launch-omit")

        manifest = mock_claude_workspace.read_json(self._manifest_path("launch-omit"))
        launch = manifest["confirmed"]["launch"]
        assert launch["api_key_available_to_child"] is False
        assert launch["api_key_source"] == "omitted_by_config"

    def test_launch_segment_renders_from_manifest(self, mock_claude_workspace: ContainerLike) -> None:
        """The opt-in launch segment renders confirmed.launch via the real status-line CLI."""
        mock_claude_workspace.exec("cd /workspace && forge session start launch-seg")
        mock_claude_workspace.mkdir("$HOME/.forge", parents=True)
        mock_claude_workspace.write_file(
            "$HOME/.forge/config.yaml",
            "statusline:\n  segments: [path, model, launch]\n",
        )
        mock_claude_workspace.write_json("/tmp/sl-input.json", {"model": {"display_name": "Claude"}})

        result = mock_claude_workspace.exec(
            "cd /workspace && env FORGE_SESSION=launch-seg forge status-line < /tmp/sl-input.json"
        )

        assert result.returncode == 0
        assert "direct" in result.stdout  # routing_mode from confirmed.launch


class TestStatusLineInputContract:
    """Tests for status-line JSON input contract handling."""

    def test_handles_empty_json(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle empty JSON object input."""
        result = mock_claude_workspace.exec("echo '{}' | forge status-line")
        assert result.returncode == 0

    def test_non_object_json_is_bounded(self, mock_claude_workspace: ContainerLike) -> None:
        """A valid JSON scalar must not escape the fail-open status-line boundary."""
        mock_claude_workspace.write_file("/tmp/status-line-input.json", "null")

        result = mock_claude_workspace.exec("forge status-line < /tmp/status-line-input.json")

        assert result.returncode == 0
        assert "Invalid input" in result.stdout
        assert "Traceback" not in result.stderr

    def test_null_workspace_falls_back(self, mock_claude_workspace: ContainerLike) -> None:
        """A wrong-typed workspace is treated as missing workspace data."""
        mock_claude_workspace.write_json("/tmp/status-line-input.json", {"workspace": None})

        result = mock_claude_workspace.exec("forge status-line < /tmp/status-line-input.json")

        assert result.returncode == 0
        assert result.stdout.strip()
        assert "Traceback" not in result.stderr

    def test_malformed_proxy_url_falls_back(self, mock_claude_workspace: ContainerLike) -> None:
        """Malformed proxy URL syntax does not break status-line rendering."""
        mock_claude_workspace.write_json("/tmp/status-line-input.json", {})

        result = mock_claude_workspace.exec(
            "env ANTHROPIC_BASE_URL='http://[' forge status-line < /tmp/status-line-input.json"
        )

        assert result.returncode == 0
        assert result.stdout.strip()
        assert "Traceback" not in result.stderr

    def test_handles_minimal_input(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle minimal Claude Code input with model dict."""
        input_data = {"model": {"display_name": "Claude"}}
        mock_claude_workspace.write_json("/tmp/status-line-input.json", input_data)

        result = mock_claude_workspace.exec("forge status-line < /tmp/status-line-input.json")
        assert result.returncode == 0

    def test_handles_full_claude_code_input(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle full Claude Code status line input."""
        input_data = {
            "model": {"display_name": "Claude 3.5 Sonnet", "id": "claude-3-5-sonnet"},
            "cwd": "/workspace",
            "session_id": "uuid-123",
        }
        mock_claude_workspace.write_json("/tmp/status-line-input.json", input_data)

        result = mock_claude_workspace.exec("forge status-line < /tmp/status-line-input.json")
        assert result.returncode == 0

    def test_shows_rate_limits_for_direct_sessions(self, mock_claude_workspace: ContainerLike) -> None:
        """Direct sessions surface rate limits when the rate_limits segment is enabled."""
        mock_claude_workspace.mkdir("$HOME/.forge", parents=True)
        mock_claude_workspace.write_file(
            "$HOME/.forge/config.yaml",
            "statusline:\n  segments: [path, model, rate_limits]\n",
        )
        input_data = {
            "model": {"display_name": "Claude 3.5 Sonnet", "id": "claude-3-5-sonnet"},
            "cwd": "/workspace",
            "session_id": "uuid-123",
            "rate_limits": [{"type": "requests_per_5_hours", "used_percentage": 30}],
        }
        mock_claude_workspace.write_json("/tmp/status-line-input.json", input_data)

        result = mock_claude_workspace.exec("forge status-line < /tmp/status-line-input.json")

        assert result.returncode == 0
        assert "5h:" in result.stdout
        assert "30%" in result.stdout

    def test_hides_rate_limits_for_proxy_sessions(self, mock_claude_workspace: ContainerLike) -> None:
        """Proxy sessions suppress Claude Code rate limits even when the segment is enabled."""
        _create_registry(
            mock_claude_workspace,
            {
                "fallback-proxy": {
                    "proxy_id": "fallback-proxy",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": None,
                    "status": "healthy",
                }
            },
        )
        mock_claude_workspace.mkdir("$HOME/.forge", parents=True)
        mock_claude_workspace.write_file(
            "$HOME/.forge/config.yaml",
            "statusline:\n  segments: [path, model, rate_limits]\n",
        )
        input_data = {
            "model": {"display_name": "Claude 3.5 Sonnet", "id": "claude-3-5-sonnet"},
            "cwd": "/workspace",
            "session_id": "uuid-123",
            "rate_limits": [{"type": "requests_per_5_hours", "used_percentage": 30}],
        }
        mock_claude_workspace.write_json("/tmp/status-line-input.json", input_data)

        result = mock_claude_workspace.exec(
            "env ANTHROPIC_BASE_URL=http://localhost:8085 forge status-line < /tmp/status-line-input.json"
        )

        assert result.returncode == 0
        assert "5h:" not in result.stdout
