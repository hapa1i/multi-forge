"""Regression test for H9: forge proxy create --name/--port options ignored.

Bug: cli/proxy.py create_cmd accepted --name and --port but when --no-start was
not set, called start_proxy(template=...) without passing the user-provided name
or port. start_proxy() had no proxy_id or port parameter at all.

Impact: `forge proxy create --name my-proxy --port 9999` created a proxy with
an auto-generated name on the default port. The UX promised "start this proxy"
but behavior was "start any proxy for this template."

Fix: Added proxy_id and port parameters to start_proxy(). CLI now passes
--name as proxy_id and --port as port to start_proxy().

Fixed in: src/forge/cli/proxy.py, src/forge/proxy/proxy_orchestrator.py
(action plan Step 8b, H9)
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.regression


def test_create_cmd_passes_name_and_port_to_start_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI create command must forward --name and --port to start_proxy()."""
    from click.testing import CliRunner

    from forge.cli.proxy import create_cmd

    captured_kwargs: dict = {}

    def mock_start_proxy(**kwargs):
        captured_kwargs.update(kwargs)
        # Return a minimal result to satisfy the CLI
        result = MagicMock()
        result.proxy = MagicMock()
        result.proxy.proxy_id = kwargs.get("proxy_id", "auto-id")
        result.proxy.base_url = f"http://localhost:{kwargs.get('port', 8085)}"
        result.proxy.template = kwargs["template"]
        result.proxy.port = kwargs.get("port", 8085)
        result.source = "spawn"
        return result

    monkeypatch.setattr("forge.cli.proxy.start_proxy", mock_start_proxy)

    runner = CliRunner()
    result = runner.invoke(create_cmd, ["litellm-openai", "--name", "my-proxy", "--port", "9999"])

    # The CLI must have passed both args through
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert (
        captured_kwargs.get("proxy_id") == "my-proxy"
    ), f"proxy_id not passed; got {captured_kwargs.get('proxy_id')!r}"
    assert captured_kwargs.get("port") == 9999, f"port not passed; got {captured_kwargs.get('port')!r}"


def test_create_cmd_without_name_passes_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When --name is omitted, proxy_id should be None (auto-generated)."""
    from click.testing import CliRunner

    from forge.cli.proxy import create_cmd

    captured_kwargs: dict = {}

    def mock_start_proxy(**kwargs):
        captured_kwargs.update(kwargs)
        result = MagicMock()
        result.proxy = MagicMock()
        result.proxy.proxy_id = "auto-id"
        result.proxy.base_url = "http://localhost:8085"
        result.proxy.template = kwargs["template"]
        result.proxy.port = 8085
        result.source = "spawn"
        return result

    monkeypatch.setattr("forge.cli.proxy.start_proxy", mock_start_proxy)

    runner = CliRunner()
    result = runner.invoke(create_cmd, ["litellm-openai"])

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert captured_kwargs.get("proxy_id") is None
