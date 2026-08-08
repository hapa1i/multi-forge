"""Regression for split JSON and false success after proxy-create smoke failure (D016)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.proxy.proxies import ProxyEntry
from forge.proxy.proxy_orchestrator import ProxyStartResult

pytestmark = pytest.mark.regression


def test_proxy_create_failed_smoke_is_one_json_result_and_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = ProxyEntry(
        proxy_id="smoke-json",
        template="litellm-openai",
        base_url="http://localhost:18085",
        port=18085,
        pid=4242,
        status="healthy",
    )
    monkeypatch.setattr("forge.cli.proxy.prune_stale_proxies", lambda: None)
    monkeypatch.setattr(
        "forge.cli.proxy.start_proxy",
        lambda **kwargs: ProxyStartResult(proxy=entry, source="spawn"),
    )
    monkeypatch.setattr(
        "forge.proxy.proxy_orchestrator.smoke_test_proxy",
        lambda **kwargs: (False, "injected upstream verification fault"),
    )

    result = CliRunner().invoke(
        main,
        [
            "proxy",
            "create",
            "litellm-openai",
            "--name",
            entry.proxy_id,
            "--port",
            str(entry.port),
            "--json",
            "--smoke-test",
        ],
    )

    documents = [json.loads(line) for line in result.stdout.splitlines()]
    expected_smoke = {"passed": False, "detail": "injected upstream verification fault"}
    assert (
        result.exit_code,
        len(documents),
        documents[0].get("smoke_test"),
        documents[-1].get("smoke_test"),
    ) == (1, 1, expected_smoke, expected_smoke)
