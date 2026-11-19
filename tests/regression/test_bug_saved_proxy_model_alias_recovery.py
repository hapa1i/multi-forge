"""A repointed model alias must explain how to use or update the saved proxy."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.config.loader import (
    load_proxy_instance_config_from_dict,
    write_proxy_instance_config,
)
from forge.core.ops.session_model_routing import plan_session_model_route_for_state
from forge.proxy.proxies import ProxyEntry, ProxyRegistry, ProxyRegistryStore
from forge.session import SessionStore

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("explicit", [False, True], ids=["reused-at-startup", "named-at-planning"])
@pytest.mark.parametrize(
    ("alias", "prior"),
    [
        ("astra", "gpt-6-astra"),
        ("sol", "gpt-6.1-sol"),
        ("astra-pro", "gpt-6-astra-pro"),
        ("sol-pro", "gpt-6-sol-pro"),
    ],
)
def test_repointed_alias_names_the_concrete_proxy_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    alias: str,
    prior: str,
    explicit: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".forge").mkdir()
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic")
    entry = ProxyEntry(
        "saved-oai",
        "openrouter-openai",
        "http://localhost:8096",
        8096,
        status="healthy",
    )
    config = load_proxy_instance_config_from_dict(
        {
            "proxy_format": 1,
            "template": entry.template,
            "template_digest": "prior-template",
            "provider": "openrouter",
            "backend": "openrouter",
            "proxy_endpoint": entry.base_url,
            "port": entry.port,
            "upstream_base_url": "https://openrouter.ai/api/v1",
            "tiers": {
                "haiku": "openai/gpt-5.4-mini",
                "sonnet": "openai/gpt-6-astra",
                "opus": "openai/gpt-6-astra",
            },
            "model_alternatives": {
                "sonnet": {old: f"openai/{old}" for old in ("gpt-6.1-sol", "gpt-6-astra-pro", "gpt-6-sol-pro")}
            },
        }
    )
    saved = write_proxy_instance_config(entry.proxy_id, config)
    original = saved.read_bytes()
    ProxyRegistryStore().write(ProxyRegistry(proxies={entry.proxy_id: entry}))

    args = ["session", "start", "review", "--no-launch", "--model", alias]
    if explicit:
        args.extend(["--proxy", entry.proxy_id])
    with (
        patch("forge.proxy.proxy_orchestrator.ensure_proxy", return_value=(entry, False)) as ensure,
        patch("forge.cli.claude._healthcheck_proxy"),
    ):
        result = CliRunner().invoke(main, args)
    assert result.exit_code == 1, result.output
    diagnostic = " ".join(result.stderr.split())
    assert f"does not serve model 'gpt-6.2-{alias}'" in diagnostic
    assert "forge proxy edit saved-oai" in diagnostic
    assert "forge proxy show saved-oai --raw" in diagnostic
    assert "--model" in diagnostic
    if explicit:
        ensure.assert_not_called()
    else:
        ensure.assert_called_once_with(entry.template)
    assert not SessionStore(str(tmp_path), "review").exists()
    assert plan_session_model_route_for_state(prior, proxy_name=entry.proxy_id).selected_model == f"openai/{prior}"
    assert saved.read_bytes() == original
