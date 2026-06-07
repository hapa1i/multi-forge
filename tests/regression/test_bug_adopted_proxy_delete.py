"""Regression: adopted proxies (pid=None) escape delete+create cycle.

Bug: forge proxy delete on an adopted proxy (pid=None) didn't kill the
process. The next forge proxy create re-adopted the same process, creating
an inescapable loop where proxy logs were always empty.

Root cause: _delete_single_proxy only killed when entry.pid was set,
with no fallback to port-based process discovery.

Fix: _stop_proxy_process finds the process by port via lsof and
health-guards before killing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.proxy.proxies import ProxyEntry, ProxyRegistry, ProxyRegistryStore

pytestmark = pytest.mark.regression


def test_delete_adopted_proxy_kills_by_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Adopted proxy delete should discover PID by port and kill it."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.test.example.com")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.chdir(project)

    # Use a port that won't collide with real proxies (8085 is litellm-openai default)
    test_port = 59999

    # Set up adopted proxy in registry (pid=None, status=healthy)
    store = ProxyRegistryStore()
    store.write(
        ProxyRegistry(
            proxies={
                "orphan-proxy": ProxyEntry(
                    proxy_id="orphan-proxy",
                    template="litellm-openai",
                    base_url=f"http://localhost:{test_port}",
                    port=test_port,
                    pid=None,
                    status="healthy",
                )
            }
        )
    )

    killed_pids: list[int] = []
    monkeypatch.setattr("forge.cli.proxy.find_pid_by_port", lambda port: 99999)
    monkeypatch.setattr("forge.cli.proxy.check_proxy_health", lambda **_: True)
    monkeypatch.setattr("forge.cli.proxy.os.kill", lambda pid, sig: killed_pids.append(pid))

    runner = CliRunner()
    result = runner.invoke(main, ["proxy", "delete", "orphan-proxy", "--yes", "--kill-adopted"])

    assert result.exit_code == 0, result.output
    assert 99999 in killed_pids, f"Expected port-based kill, got: {killed_pids}"
    assert f"Stopped server on port {test_port}" in result.output

    # Registry entry should be gone
    registry = store.read()
    assert "orphan-proxy" not in registry.proxies
