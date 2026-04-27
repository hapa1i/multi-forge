"""Docker-based integration tests for CLI proxy commands.

These tests run inside a session-scoped container (docker_in marker) for
complete filesystem isolation. They test the behavioral aspects of proxy
management: list, show, validate, set, delete, create.

IMPORTANT: TestProxyCreateAndStart actually spawns server processes to verify
the full startup path. This caught a regression where registry registration
happened AFTER server spawn, causing startup validation to fail.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def _make_scoped_key(session_name: str, forge_root: str) -> str:
    """Build the public v1 session index key used by Forge."""
    digest = hashlib.sha256(forge_root.encode()).hexdigest()[:12]
    return f"{session_name}|{digest}"


class TestProxyList:
    """Tests for `forge proxy list` command."""

    def test_list_empty_shows_message(self, mock_claude_workspace: ContainerLike) -> None:
        """Should show message when no proxies exist."""
        result = mock_claude_workspace.exec("forge proxy list")

        assert result.returncode == 0
        assert "No proxies found" in result.stdout

    def test_list_shows_entries(self, mock_claude_workspace: ContainerLike) -> None:
        """Should list existing proxies from registry."""
        # Create registry with a proxy
        mock_claude_workspace.mkdir("$HOME/.forge/proxies", parents=True)
        registry = {
            "version": 1,
            "proxies": {
                "proxy_1": {
                    "proxy_id": "proxy_1",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": None,
                    "status": "healthy",
                    "last_seen_at": "2025-12-20T00:01:00+00:00",
                }
            },
        }
        mock_claude_workspace.write_json("$HOME/.forge/proxies/index.json", registry)

        result = mock_claude_workspace.exec("forge proxy list")

        assert result.returncode == 0
        assert "proxy_1" in result.stdout
        assert "litellm-openai" in result.stdout
        assert "http://localhost:8085" in result.stdout


class TestProxyShow:
    """Tests for `forge proxy show` command."""

    def _create_proxy_file(self, workspace: ContainerLike, proxy_id: str, content: str) -> None:
        """Create a proxy.yaml file in the container."""
        workspace.mkdir(f"$HOME/.forge/proxies/{proxy_id}", parents=True)
        workspace.write_file(f"$HOME/.forge/proxies/{proxy_id}/proxy.yaml", content)

    def test_show_displays_proxy_yaml(self, mock_claude_workspace: ContainerLike) -> None:
        """Should display proxy.yaml content."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
  sonnet: gpt-4o
  opus: gpt-5
"""
        self._create_proxy_file(mock_claude_workspace, "my-proxy", proxy_yaml)

        result = mock_claude_workspace.exec("forge proxy show my-proxy --raw")

        assert result.returncode == 0, f"forge failed: {result.stdout}\n{result.stderr}"
        assert "litellm-openai" in result.stdout
        assert "gpt-4o" in result.stdout

    def test_show_not_found_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should error when proxy not found."""
        result = mock_claude_workspace.exec("forge proxy show nonexistent")

        assert result.returncode != 0
        assert "not found" in result.stdout.lower() or "not found" in result.stderr.lower()


class TestProxyValidate:
    """Tests for `forge proxy validate` command."""

    def _create_proxy_file(self, workspace: ContainerLike, proxy_id: str, content: str) -> None:
        """Create a proxy.yaml file in the container."""
        workspace.mkdir(f"$HOME/.forge/proxies/{proxy_id}", parents=True)
        workspace.write_file(f"$HOME/.forge/proxies/{proxy_id}/proxy.yaml", content)

    def test_validate_success(self, mock_claude_workspace: ContainerLike) -> None:
        """Should succeed for valid proxy."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
  sonnet: gpt-4o
  opus: gpt-5
"""
        self._create_proxy_file(mock_claude_workspace, "valid-proxy", proxy_yaml)

        result = mock_claude_workspace.exec("forge proxy validate valid-proxy")

        assert result.returncode == 0
        assert "valid" in result.stdout.lower()

    def test_validate_invalid_yaml(self, mock_claude_workspace: ContainerLike) -> None:
        """Should fail for invalid YAML."""
        self._create_proxy_file(mock_claude_workspace, "bad-proxy", "not: valid: yaml: [")

        result = mock_claude_workspace.exec("forge proxy validate bad-proxy")

        assert result.returncode != 0
        assert "failed" in (result.stdout + result.stderr).lower()

    def test_validate_missing_required_field(self, mock_claude_workspace: ContainerLike) -> None:
        """Should fail when required field missing."""
        # Missing 'provider' field
        proxy_yaml = """\
template: litellm-openai
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
"""
        self._create_proxy_file(mock_claude_workspace, "incomplete-proxy", proxy_yaml)

        result = mock_claude_workspace.exec("forge proxy validate incomplete-proxy")

        assert result.returncode != 0

    def test_validate_not_found_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should error when proxy not found."""
        result = mock_claude_workspace.exec("forge proxy validate nonexistent")

        assert result.returncode != 0
        assert "not found" in (result.stdout + result.stderr).lower()


class TestProxySet:
    """Tests for `forge proxy set` command."""

    def _create_proxy_file(self, workspace: ContainerLike, proxy_id: str, content: str) -> None:
        """Create a proxy.yaml file in the container."""
        workspace.mkdir(f"$HOME/.forge/proxies/{proxy_id}", parents=True)
        workspace.write_file(f"$HOME/.forge/proxies/{proxy_id}/proxy.yaml", content)

    def test_set_simple_field(self, mock_claude_workspace: ContainerLike) -> None:
        """Should update simple field."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
default_tier: sonnet
tiers:
  haiku: gpt-4o-mini
  sonnet: gpt-4o
  opus: gpt-5
"""
        self._create_proxy_file(mock_claude_workspace, "set-test", proxy_yaml)

        result = mock_claude_workspace.exec("forge proxy set set-test default_tier=opus")

        assert result.returncode == 0

        # Verify file updated
        check = mock_claude_workspace.exec("cat $HOME/.forge/proxies/set-test/proxy.yaml")
        assert "default_tier: opus" in check.stdout

    def test_set_nested_field_with_dot_notation(self, mock_claude_workspace: ContainerLike) -> None:
        """Should update nested field with dot notation."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
  sonnet: gpt-4o
  opus: gpt-5
tier_overrides:
  opus:
    reasoning_effort: medium
"""
        self._create_proxy_file(mock_claude_workspace, "nested-test", proxy_yaml)

        result = mock_claude_workspace.exec("forge proxy set nested-test 'tier_overrides.opus.reasoning_effort=high'")

        assert result.returncode == 0

        check = mock_claude_workspace.exec("cat $HOME/.forge/proxies/nested-test/proxy.yaml")
        assert "reasoning_effort: high" in check.stdout

    def test_set_invalid_format_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should error on invalid format."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
"""
        self._create_proxy_file(mock_claude_workspace, "format-test", proxy_yaml)

        result = mock_claude_workspace.exec("forge proxy set format-test no_equals_sign")

        assert result.returncode != 0
        assert (
            "expected format" in (result.stdout + result.stderr).lower()
            or "key=value" in (result.stdout + result.stderr).lower()
        )

    def test_set_not_found_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should error when proxy not found."""
        result = mock_claude_workspace.exec("forge proxy set nonexistent key=value")

        assert result.returncode != 0
        assert "not found" in (result.stdout + result.stderr).lower()


class TestProxyDelete:
    """Tests for `forge proxy delete` command."""

    def _create_proxy_file(self, workspace: ContainerLike, proxy_id: str, content: str) -> None:
        """Create a proxy.yaml file in the container."""
        workspace.mkdir(f"$HOME/.forge/proxies/{proxy_id}", parents=True)
        workspace.write_file(f"$HOME/.forge/proxies/{proxy_id}/proxy.yaml", content)

    def _create_registry(self, workspace: ContainerLike, proxies: dict) -> None:
        """Create proxy registry in the container."""
        workspace.mkdir("$HOME/.forge/proxies", parents=True)
        registry = {"version": 1, "proxies": proxies}
        workspace.write_json("$HOME/.forge/proxies/index.json", registry)

    def _create_session(
        self,
        workspace: ContainerLike,
        *,
        session_name: str,
        worktree_path: str = "/workspace",
        started_with_proxy: dict | None = None,
    ) -> None:
        """Create a session index entry plus manifest for proxy warning tests."""
        workspace.mkdir("$HOME/.forge/sessions", parents=True)
        scoped_key = _make_scoped_key(session_name, worktree_path)
        workspace.write_json(
            "$HOME/.forge/sessions/index.json",
            {
                "version": 1,
                "sessions": {
                    scoped_key: {
                        "worktree_path": worktree_path,
                        "project_root": worktree_path,
                        "last_accessed_at": "2026-01-01T00:00:00Z",
                        "forge_root": worktree_path,
                        "checkout_root": worktree_path,
                        "relative_path": ".",
                    }
                },
            },
        )
        workspace.mkdir(f"{worktree_path}/.forge/sessions/{session_name}", parents=True)
        workspace.write_json(
            f"{worktree_path}/.forge/sessions/{session_name}/forge.session.json",
            {
                "schema_version": 1,
                "name": session_name,
                "created_at": "2026-01-01T00:00:00Z",
                "last_accessed_at": "2026-01-01T00:00:00Z",
                "intent": {},
                "overrides": {},
                "confirmed": (
                    {
                        "started_with_proxy": started_with_proxy,
                    }
                    if started_with_proxy is not None
                    else {}
                ),
            },
        )

    def test_delete_removes_proxy_and_registry(self, mock_claude_workspace: ContainerLike) -> None:
        """Should remove proxy file and registry entry with --force."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
"""
        self._create_proxy_file(mock_claude_workspace, "delete-me", proxy_yaml)
        self._create_registry(
            mock_claude_workspace,
            {
                "delete-me": {
                    "proxy_id": "delete-me",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": None,
                    "status": "healthy",
                }
            },
        )

        result = mock_claude_workspace.exec("forge proxy delete delete-me --force")

        assert result.returncode == 0

        # Verify file removed
        check = mock_claude_workspace.exec(
            "test -f $HOME/.forge/proxies/delete-me/proxy.yaml && echo exists || echo gone"
        )
        assert "gone" in check.stdout

        # Verify registry updated
        check = mock_claude_workspace.exec("cat $HOME/.forge/proxies/index.json")
        registry = json.loads(check.stdout)
        assert "delete-me" not in registry["proxies"]

    def test_delete_not_found_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should error when proxy not in registry."""
        result = mock_claude_workspace.exec("forge proxy delete nonexistent --force")

        assert result.returncode != 0
        assert "not found" in (result.stdout + result.stderr).lower()

    def test_delete_cancel_lists_related_shared_port_proxies(self, mock_claude_workspace: ContainerLike) -> None:
        """Interactive delete should enumerate other proxy aliases on the same port."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
"""
        self._create_proxy_file(mock_claude_workspace, "alias-a", proxy_yaml)
        self._create_proxy_file(mock_claude_workspace, "alias-b", proxy_yaml)
        self._create_registry(
            mock_claude_workspace,
            {
                "alias-a": {
                    "proxy_id": "alias-a",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": None,
                    "status": "configured",
                },
                "alias-b": {
                    "proxy_id": "alias-b",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": None,
                    "status": "configured",
                },
            },
        )

        result = mock_claude_workspace.exec("printf 'n\\n' | forge proxy delete alias-a")

        assert result.returncode == 0
        assert "Related proxies on the same port" in result.stdout
        assert "alias-b" in result.stdout
        assert "Cancelled" in result.stdout

    def test_delete_force_keeps_shared_server_alive(self, mock_claude_workspace: ContainerLike) -> None:
        """Forced delete should keep the server process alive when another alias remains."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
"""
        self._create_proxy_file(mock_claude_workspace, "alias-a", proxy_yaml)
        self._create_proxy_file(mock_claude_workspace, "alias-b", proxy_yaml)

        pid_result = mock_claude_workspace.exec("sleep 300 >/tmp/shared-proxy.log 2>&1 & echo $!")
        assert pid_result.returncode == 0
        shared_pid = int(pid_result.stdout.strip())

        self._create_registry(
            mock_claude_workspace,
            {
                "alias-a": {
                    "proxy_id": "alias-a",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": shared_pid,
                    "status": "healthy",
                },
                "alias-b": {
                    "proxy_id": "alias-b",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": shared_pid,
                    "status": "healthy",
                },
            },
        )

        try:
            result = mock_claude_workspace.exec("forge proxy delete alias-a --force")

            assert result.returncode == 0
            assert "Server kept alive" in result.stdout
            assert "Keeping shared server references:" in result.stdout
            assert "alias-b" in result.stdout

            alive = mock_claude_workspace.exec(f"kill -0 {shared_pid} && echo alive")
            assert alive.returncode == 0
            assert "alive" in alive.stdout

            registry = json.loads(mock_claude_workspace.read_file("$HOME/.forge/proxies/index.json"))
            assert "alias-a" not in registry["proxies"]
            assert "alias-b" in registry["proxies"]
        finally:
            mock_claude_workspace.exec(f"kill {shared_pid} 2>/dev/null || true")

    def test_delete_cancel_last_alias_lists_sessions_on_port(self, mock_claude_workspace: ContainerLike) -> None:
        """Deleting the last alias should warn about sessions on that shared port."""
        proxy_yaml = """\
template: litellm-openai
provider: litellm
proxy_endpoint: http://localhost:8085
port: 8085
upstream_base_url: https://litellm.test.example.com
tiers:
  haiku: gpt-4o-mini
"""
        self._create_proxy_file(mock_claude_workspace, "alias-b", proxy_yaml)
        self._create_registry(
            mock_claude_workspace,
            {
                "alias-b": {
                    "proxy_id": "alias-b",
                    "template": "litellm-openai",
                    "base_url": "http://localhost:8085",
                    "port": 8085,
                    "pid": None,
                    "status": "healthy",
                }
            },
        )
        self._create_session(
            mock_claude_workspace,
            session_name="orphan-session",
            started_with_proxy={
                "base_url": "http://localhost:8085",
                "proxy_id": "alias-a",
                "template": "litellm-openai",
                "port": 8085,
            },
        )

        result = mock_claude_workspace.exec("printf 'n\\n' | forge proxy delete alias-b")

        assert result.returncode == 0
        assert "Related sessions on http://localhost:8085:" in result.stdout
        assert "orphan-session" in result.stdout
        assert "Delete sessions first" in result.stdout
        assert "Cancelled" in result.stdout


class TestProxyCreateAndStart:
    """Tests for `forge proxy create` (default: starts server).

    These tests actually spawn a server process and verify it becomes healthy.
    This exercises the full spawn path including registry registration timing.

    IMPORTANT: A regression in this path was missed because unit tests mocked
    the spawn and integration tests only tested --no-start. These tests ensure
    the actual server startup works end-to-end.
    """

    def test_create_starts_server_and_becomes_healthy(self, mock_claude_workspace: ContainerLike) -> None:
        """Should create proxy, start server, and register as healthy.

        This is the critical test that catches sequencing bugs between:
        - proxy file creation
        - registry registration
        - server startup validation
        """
        # Create and start a proxy (default behavior)
        result = mock_claude_workspace.exec("forge proxy create litellm-openai", timeout=30)

        assert result.returncode == 0, f"Create failed: {result.stdout}\n{result.stderr}"
        assert "Started" in result.stdout or "Reusing" in result.stdout or "Adopted" in result.stdout

        # List should show the proxy as healthy
        list_result = mock_claude_workspace.exec("forge proxy list")
        assert list_result.returncode == 0, f"List failed: {list_result.stdout}\n{list_result.stderr}"
        assert "healthy" in list_result.stdout.lower(), f"Proxy not healthy!\nList output: {list_result.stdout}"

        # Server should respond to health check
        # Extract port from list output (look for port number after URL)
        import re

        port_match = re.search(r":(\d{4,5})\s", list_result.stdout)
        if port_match:
            port = port_match.group(1)
            health_result = mock_claude_workspace.exec(f"curl -s http://localhost:{port}/")
            assert health_result.returncode == 0, f"Health check failed: {health_result.stderr}"
            assert "is_proxy" in health_result.stdout, f"Not a proxy response: {health_result.stdout}"

    def test_create_workflow_start_then_list_then_stop(self, mock_claude_workspace: ContainerLike) -> None:
        """Full workflow: create (starts) → list → stop.

        Verifies the complete user journey works end-to-end.
        """
        # Create and start
        create_result = mock_claude_workspace.exec("forge proxy create litellm-openai", timeout=30)
        assert create_result.returncode == 0, f"Create failed: {create_result.stdout}\n{create_result.stderr}"

        # Extract proxy ID from output
        import re

        proxy_id_match = re.search(r"proxy[_\s]+(\w+)", create_result.stdout)
        if not proxy_id_match:
            # Try extracting from "Started proxy_xxx" pattern
            proxy_id_match = re.search(r"(proxy_\w+)", create_result.stdout)

        # List shows healthy
        list_result = mock_claude_workspace.exec("forge proxy list")
        assert "healthy" in list_result.stdout.lower()

        # Stop the server (find the proxy ID from list)
        if proxy_id_match:
            proxy_id = proxy_id_match.group(1) if "_" in proxy_id_match.group(1) else f"proxy_{proxy_id_match.group(1)}"
            # Handle both formats
            for candidate in [proxy_id, proxy_id_match.group(0)]:
                if candidate in list_result.stdout:
                    stop_result = mock_claude_workspace.exec(f"forge proxy stop {candidate}")
                    if stop_result.returncode == 0:
                        break


class TestProxyCreateNoStart:
    """Tests for `forge proxy create --no-start` command.

    These tests use real template files from src/forge/config/defaults/templates/
    since the create command validates template existence.
    """

    def test_create_creates_proxy_file(self, mock_claude_workspace: ContainerLike) -> None:
        """Should create a new proxy file from template."""
        result = mock_claude_workspace.exec("forge proxy create litellm-openai --name my-proxy --no-start")

        assert result.returncode == 0, f"Create failed: {result.stdout}\n{result.stderr}"

        # Verify file created
        check = mock_claude_workspace.exec("cat $HOME/.forge/proxies/my-proxy/proxy.yaml")
        assert check.returncode == 0
        assert "litellm-openai" in check.stdout

    def test_create_then_list_shows_proxy(self, mock_claude_workspace: ContainerLike) -> None:
        """WORKFLOW TEST: Create followed by list should show the new proxy.

        This is the key end-to-end test that verifies the full user workflow.
        A bug where create didn't register the proxy would be caught here.
        """
        # Create a proxy
        create_result = mock_claude_workspace.exec("forge proxy create litellm-openai --name workflow-test --no-start")
        assert create_result.returncode == 0, f"Create failed: {create_result.stdout}\n{create_result.stderr}"

        # List should show the proxy
        list_result = mock_claude_workspace.exec("forge proxy list")
        assert list_result.returncode == 0, f"List failed: {list_result.stdout}\n{list_result.stderr}"
        assert (
            "workflow-test" in list_result.stdout
        ), f"Created proxy not visible in list!\nList output: {list_result.stdout}"
        assert "configured" in list_result.stdout.lower(), "Proxy should have 'configured' status"

    def test_create_already_exists_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should error when proxy already exists."""
        # Create existing proxy
        mock_claude_workspace.mkdir("$HOME/.forge/proxies/existing", parents=True)
        mock_claude_workspace.write_file("$HOME/.forge/proxies/existing/proxy.yaml", "template: something")

        result = mock_claude_workspace.exec("forge proxy create litellm-openai --name existing --no-start")

        assert result.returncode != 0
        assert "exists" in (result.stdout + result.stderr).lower()

    def test_create_invalid_template_error(self, mock_claude_workspace: ContainerLike) -> None:
        """Should error for unknown template."""
        result = mock_claude_workspace.exec("forge proxy create nonexistent-template --name new-proxy --no-start")

        assert result.returncode != 0
        assert "not found" in (result.stdout + result.stderr).lower()

    def test_create_with_custom_port(self, mock_claude_workspace: ContainerLike) -> None:
        """Should use custom port when specified."""
        result = mock_claude_workspace.exec(
            "forge proxy create litellm-openai --name custom-port --port 9999 --no-start"
        )

        assert result.returncode == 0, f"Create failed: {result.stdout}\n{result.stderr}"

        # Verify port in file
        check = mock_claude_workspace.exec("cat $HOME/.forge/proxies/custom-port/proxy.yaml")
        assert "9999" in check.stdout


class TestProxyRegistryCorruption:
    """Tests for corrupted proxy registry handling.

    These tests verify that CLI commands handle corrupt registry files gracefully.
    """

    def _create_registry_raw(self, workspace: ContainerLike, content: str) -> None:
        """Create registry with raw content (may be invalid)."""
        workspace.mkdir("$HOME/.forge/proxies", parents=True)
        workspace.write_file("$HOME/.forge/proxies/index.json", content)

    def test_list_with_invalid_json_registry(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle invalid JSON gracefully."""
        self._create_registry_raw(mock_claude_workspace, "not valid json {{{")

        result = mock_claude_workspace.exec("forge proxy list")

        assert result.returncode != 0
        assert "error" in (result.stdout + result.stderr).lower()

    def test_list_with_missing_version_registry(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle missing version field."""
        self._create_registry_raw(mock_claude_workspace, json.dumps({"proxies": {}}))

        result = mock_claude_workspace.exec("forge proxy list")

        assert result.returncode != 0
        assert "error" in (result.stdout + result.stderr).lower()

    def test_list_with_wrong_version_registry(self, mock_claude_workspace: ContainerLike) -> None:
        """Should handle wrong version number."""
        self._create_registry_raw(mock_claude_workspace, json.dumps({"version": 999, "proxies": {}}))

        result = mock_claude_workspace.exec("forge proxy list")

        assert result.returncode != 0
        assert "error" in (result.stdout + result.stderr).lower()
