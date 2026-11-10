"""Fresh Gemini defaults must not rewrite saved Argon proxy snapshots."""

from pathlib import Path

import pytest
import yaml

from forge.config.loader import load_proxy_instance_config
from forge.proxy.proxy_orchestrator import create_proxy_file

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("template", "prefix"),
    [("openrouter-gemini", "google"), ("litellm-gemini", "vertex_ai"), ("litellm-gemini-local", "gemini")],
)
def test_carbon_defaults_preserve_saved_argon_tiers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, template: str, prefix: str
) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    path = create_proxy_file(
        proxy_id="carbon",
        template=template,
        base_url="http://localhost:8100",
        port=8100,
        upstream_base_url="http://gateway.invalid/v1",
    )
    fresh = load_proxy_instance_config("carbon")
    assert fresh is not None
    assert fresh.tiers.sonnet == fresh.tiers.opus == f"{prefix}/gemini-4-carbon"
    assert fresh.tiers.haiku == f"{prefix}/gemini-3.8-flash"
    for tier in ("sonnet", "opus"):
        assert fresh.model_alternatives[tier]["gemini-4-argon"] == f"{prefix}/gemini-4-argon"
    if prefix == "google":
        assert fresh.allow_non_zdr is False

    saved = yaml.safe_load(path.read_text())
    for tier in ("sonnet", "opus"):
        saved["tiers"][tier] = f"{prefix}/gemini-4-argon"
        saved["model_alternatives"][tier].pop("gemini-4-argon")
    saved["tier_overrides"]["sonnet"] = {"reasoning_effort": "low"}
    path.write_text(yaml.safe_dump(saved))
    before = path.read_bytes()
    before_stat = path.stat()

    existing = load_proxy_instance_config("carbon")

    assert existing is not None
    assert existing.tiers.sonnet == existing.tiers.opus == f"{prefix}/gemini-4-argon"
    assert "gemini-4-carbon" not in existing.model_alternatives["sonnet"]
    assert existing.tier_overrides.sonnet is not None
    assert existing.tier_overrides.sonnet.reasoning_effort == "low"
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_stat.st_mtime_ns
