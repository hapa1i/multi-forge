"""An immediate start could reuse a process whose saved policy had just changed."""

from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.proxy.proxies import ProxyEntry, ProxyRegistryStore

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("pid,flags", [(4242, []), (None, ["--kill-adopted"])])
def test_stop_waits_for_signaled_proxy_to_release_its_identity(monkeypatch, pid, flags):
    store = ProxyRegistryStore()
    registry = store.read()
    entry = ProxyEntry(
        proxy_id="draining",
        template="codex-responses-openrouter",
        port=8106,
        base_url="http://127.0.0.1:8106",
        status="healthy",
        pid=pid,
    )
    registry.proxies[entry.proxy_id] = entry
    store.write(registry)
    monkeypatch.setattr("forge.cli.proxy._stop_proxy_process", lambda *a, **kw: "stopped")
    check = Mock(side_effect=[True, False])
    monkeypatch.setattr("forge.cli.proxy.check_proxy_health", check)
    result = CliRunner().invoke(main, ["proxy", "stop", entry.proxy_id, *flags])
    assert result.exit_code == 0, result.output
    assert check.call_count == 2
    assert check.call_args.kwargs["expected_proxy_id"] == "draining"
    assert store.read().proxies[entry.proxy_id].status == "stopped"
