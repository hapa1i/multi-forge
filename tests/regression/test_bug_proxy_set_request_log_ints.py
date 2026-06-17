"""Regression (proxy_log_hygiene review): `forge proxy set` could not set two new int fields.

Root cause: the `forge proxy set` value coercer int-casts a fixed tuple of leaf keys but was not
extended for the card's new `logging.requests.max_file_mb` and `logging.requests.stream_chunk_max_bytes`.
They stayed strings and then failed `RequestLogConfig.__post_init__` ("must be a non-negative int"),
so the documented edit surface was broken for part of the new config.

Affected file: ``src/forge/cli/proxy.py`` (the set-command coercer).
Fix: add both leaf keys to the int-cast tuple. (`stream_chunks` already coerced via the bool branch.)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from ruamel.yaml import YAML

from forge.cli.main import main
from forge.config.loader import load_proxy_instance_config_from_dict

pytestmark = pytest.mark.regression

_PROXY_YAML = """\
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


@pytest.fixture
def proxy_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.test.example.com")
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    monkeypatch.chdir(project)
    # FORGE_HOME comes from the autouse isolate_forge_home fixture (tests/conftest.py).
    proxy_dir = Path(os.environ["FORGE_HOME"]) / "proxies" / "ints-test"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    pf = proxy_dir / "proxy.yaml"
    pf.write_text(_PROXY_YAML)
    return pf


@pytest.mark.parametrize(
    ("key", "value"),
    [("logging.requests.max_file_mb", "32"), ("logging.requests.stream_chunk_max_bytes", "4096")],
)
def test_proxy_set_coerces_new_request_log_ints(proxy_file: Path, key: str, value: str) -> None:
    result = CliRunner().invoke(main, ["proxy", "set", "ints-test", f"{key}={value}"])

    assert result.exit_code == 0, result.output
    assert "Invalid value" not in result.output

    with open(proxy_file) as f:
        data = YAML().load(f)
    leaf = key.split(".")[-1]
    stored = data["logging"]["requests"][leaf]
    assert stored == int(value) and isinstance(stored, int)  # int, not the string

    # And the stored shape loads through the proxy config without raising.
    cfg = load_proxy_instance_config_from_dict(dict(data))
    assert getattr(cfg.logging.requests, leaf) == int(value)


def test_proxy_set_stream_chunks_still_coerces_bool(proxy_file: Path) -> None:
    """Guard the generic bool branch: stream_chunks must remain a real bool, not the string 'true'."""
    result = CliRunner().invoke(main, ["proxy", "set", "ints-test", "logging.requests.stream_chunks=true"])

    assert result.exit_code == 0, result.output
    with open(proxy_file) as f:
        data = YAML().load(f)
    assert data["logging"]["requests"]["stream_chunks"] is True
