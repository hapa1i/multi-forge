"""Regression: a removed ``costs.cap_mode`` key must be rejected, not silently ignored.

Phase 3 of the metric-evidence card removed ``cap_mode`` (and the strict pre-flight cost
estimate) — caps now have one behavior: post-event enforcement. The ``costs`` block is
leniently parsed (``value.get(...)``), so without an explicit guard a stale ``cap_mode``
line would be silently dropped, hiding that the user's pre-flight expectation no longer
holds. Two surfaces must reject it with an actionable message:

1. Config parse (``_coerce_cost_config`` via ``load_proxy_instance_config_from_dict``).
2. The ``forge proxy set`` edit path, which validates before writing (``cli/proxy.py``) —
   the rejected set must not persist the key.

Affected: ``src/forge/config/schema.py`` (tombstone), ``src/forge/cli/proxy.py`` (set guard).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression

_VALID_PROXY = {
    "proxy_format": 1,
    "template": "litellm-openai",
    "template_digest": "sha256:test",
    "provider": "litellm",
    "proxy_endpoint": "http://localhost:8085",
    "port": 8085,
    "upstream_base_url": "https://litellm.test.example.com",
    "tiers": {"haiku": "openai/gpt-5-mini", "sonnet": "openai/gpt-5.5", "opus": "openai/gpt-5.5"},
}

_PROXY_YAML = """\
proxy_format: 1
template: litellm-openai
template_digest: abc123
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


@pytest.mark.parametrize("stale", ["strict", "post"])
def test_cap_mode_in_costs_dict_rejected_at_parse(stale: str) -> None:
    """Any cap_mode value (even the old default ``post``) fails to load with a named message."""
    from forge.config.loader import load_proxy_instance_config_from_dict

    with pytest.raises(ValueError, match="cap_mode is no longer supported"):
        load_proxy_instance_config_from_dict({**_VALID_PROXY, "costs": {"caps": {"per_day": 10.0}, "cap_mode": stale}})


def _create_proxy(proxy_id: str) -> Path:
    proxy_dir = Path(os.environ["FORGE_HOME"]) / "proxies" / proxy_id
    proxy_dir.mkdir(parents=True, exist_ok=True)
    proxy_file = proxy_dir / "proxy.yaml"
    proxy_file.write_text(_PROXY_YAML)
    return proxy_file


@pytest.mark.parametrize("stale", ["post", "strict"])
def test_proxy_set_cap_mode_rejected_without_persisting(stale: str) -> None:
    """`forge proxy set <id> costs.cap_mode=...` errors (validate-before-write) and writes nothing."""
    runner = CliRunner()
    proxy_file = _create_proxy("cap-mode-removed")
    before = proxy_file.read_text()

    result = runner.invoke(main, ["proxy", "set", "cap-mode-removed", f"costs.cap_mode={stale}"])

    assert result.exit_code != 0
    assert "cap_mode is no longer supported" in result.output
    # validate-before-write: the rejected set must leave proxy.yaml byte-for-byte unchanged.
    assert proxy_file.read_text() == before
    assert "cap_mode" not in proxy_file.read_text()
