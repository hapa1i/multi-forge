"""Regression for proxy ownership loss after a required stop fails (O002).

The merged-main CLI treated ``_stop_proxy_process() == "error"`` as success. ``proxy stop``
exited zero, while ``proxy delete`` removed the registry row and config before ignoring the
failed stop and printing ``Deleted``. A required stop failure must instead retain both forms
of actionable ownership and return a failing command status.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.proxy.proxies import ProxyEntry, ProxyRegistry, ProxyRegistryStore

pytestmark = pytest.mark.regression


def test_required_stop_failure_preserves_stop_and_delete_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))

    proxy_id = "stop-failure"
    proxy_file = tmp_path / "proxies" / proxy_id / "proxy.yaml"
    proxy_file.parent.mkdir(parents=True)
    proxy_file.write_text("template: litellm-openai\nport: 8085\n")

    entry = ProxyEntry(
        proxy_id=proxy_id,
        template="litellm-openai",
        base_url="http://localhost:8085",
        port=8085,
        pid=4242,
        status="healthy",
    )
    store = ProxyRegistryStore()
    store.write(ProxyRegistry(proxies={proxy_id: entry}))

    stop_attempts: list[str] = []

    def fail_stop(*args: object, **kwargs: object) -> str:
        stop_attempts.append(proxy_id)
        return "error"

    monkeypatch.setattr("forge.cli.proxy._stop_proxy_process", fail_stop)
    runner = CliRunner()

    stop_result = runner.invoke(main, ["proxy", "stop", proxy_id])
    stop_ownership = proxy_id in store.read().proxies and proxy_file.exists()

    delete_result = runner.invoke(main, ["proxy", "delete", proxy_id, "--yes"])
    delete_ownership = proxy_id in store.read().proxies and proxy_file.exists()

    assert (
        stop_result.exit_code,
        stop_ownership,
        delete_result.exit_code,
        delete_ownership,
        "Deleted" in delete_result.output,
        stop_attempts,
    ) == (1, True, 1, True, False, [proxy_id, proxy_id])
