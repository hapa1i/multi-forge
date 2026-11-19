"""Fresh Gemini templates use Neon and Hydrogen without rewriting saved Carbon proxy snapshots."""

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
def test_new_defaults_preserve_saved_carbon_tiers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, template: str, prefix: str
) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    path = create_proxy_file(
        proxy_id="gemini",
        template=template,
        base_url="http://localhost:8100",
        port=8100,
        upstream_base_url="http://gateway.invalid/v1",
    )
    fresh = load_proxy_instance_config("gemini")
    assert fresh is not None
    assert fresh.tiers.sonnet == fresh.tiers.opus == f"{prefix}/gemini-4-neon"
    assert fresh.tiers.haiku == f"{prefix}/gemini-4-hydrogen"
    for tier in ("sonnet", "opus"):
        for prior in ("gemini-4-carbon", "gemini-4-argon"):
            assert fresh.model_alternatives[tier][prior] == f"{prefix}/{prior}"
    assert fresh.model_alternatives["haiku"]["gemini-3.8-flash"] == f"{prefix}/gemini-3.8-flash"
    # Hydrogen's native default is high; Haiku requests without thinking must not inherit it.
    assert fresh.tier_overrides.haiku is not None
    assert fresh.tier_overrides.haiku.reasoning_effort == "low"
    assert fresh.tier_overrides.sonnet is not None
    assert fresh.tier_overrides.sonnet.reasoning_effort == "medium"
    assert fresh.tier_overrides.opus is not None
    assert fresh.tier_overrides.opus.reasoning_effort == "high"
    if prefix == "google":
        assert fresh.allow_non_zdr is False

    saved = yaml.safe_load(path.read_text())
    for tier in ("sonnet", "opus"):
        saved["tiers"][tier] = f"{prefix}/gemini-4-carbon"
        saved["model_alternatives"][tier].pop("gemini-4-carbon")
    saved["tiers"]["haiku"] = f"{prefix}/gemini-3.8-flash"
    saved["model_alternatives"]["haiku"].pop("gemini-3.8-flash")
    saved["tier_overrides"].pop("haiku")
    saved["tier_overrides"]["sonnet"] = {"reasoning_effort": "low"}
    path.write_text(yaml.safe_dump(saved))
    before = path.read_bytes()
    before_stat = path.stat()

    existing = load_proxy_instance_config("gemini")

    assert existing is not None
    assert existing.tiers.sonnet == existing.tiers.opus == f"{prefix}/gemini-4-carbon"
    assert existing.tiers.haiku == f"{prefix}/gemini-3.8-flash"
    for tier, removed in (("haiku", "gemini-3.8-flash"), ("sonnet", "gemini-4-carbon"), ("opus", "gemini-4-carbon")):
        # Saved alternatives load as written; current template alternatives are never merged back in.
        assert removed not in existing.model_alternatives[tier]
        assert existing.model_alternatives[tier] == saved["model_alternatives"][tier]
    assert existing.tier_overrides.haiku is None
    assert existing.tier_overrides.sonnet is not None
    assert existing.tier_overrides.sonnet.reasoning_effort == "low"
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_stat.st_mtime_ns


@pytest.mark.parametrize(
    ("template", "prefix"), [("openrouter-gemini-flash", "google"), ("litellm-gemini-flash-local", "gemini")]
)
def test_flash_templates_use_hydrogen_on_every_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, template: str, prefix: str
) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    create_proxy_file(
        proxy_id="flash",
        template=template,
        base_url="http://localhost:8100",
        port=8100,
        upstream_base_url="http://gateway.invalid/v1",
    )
    fresh = load_proxy_instance_config("flash")

    assert fresh is not None
    assert fresh.tiers.haiku == fresh.tiers.sonnet == fresh.tiers.opus == f"{prefix}/gemini-4-hydrogen"
    for tier, effort in (("haiku", "low"), ("sonnet", "medium"), ("opus", "high")):
        assert fresh.model_alternatives[tier]["gemini-3.8-flash"] == f"{prefix}/gemini-3.8-flash"
        override = getattr(fresh.tier_overrides, tier)
        assert override is not None
        assert override.reasoning_effort == effort
