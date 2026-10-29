"""Fresh model alternatives and saved user snapshots remain separate."""

from pathlib import Path

import pytest
import yaml

from forge.config.loader import load_proxy_instance_config
from forge.proxy.proxy_orchestrator import create_proxy_file

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("family", "model", "slug", "prior"),
    [
        ("kimi", "kimi-k3.1-pro", "moonshotai/kimi-k3.1-pro", "moonshotai/kimi-k3"),
        ("minimax", "minimax-m3.1-flash", "minimax/minimax-m3.1-flash", "minimax/minimax-m3"),
        ("deepseek", "deepseek-v4.1-flash-1017", "deepseek/deepseek-v4.1-flash-1017", "deepseek/deepseek-v4-pro"),
    ],
)
def test_fresh_realization_exposes_alternatives_but_loading_saved_snapshot_never_adds_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, family: str, model: str, slug: str, prior: str
) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    proxy_id = f"october-{family}"
    path = create_proxy_file(
        proxy_id=proxy_id,
        template=f"openrouter-{family}",
        base_url="http://localhost:8100",
        port=8100,
    )
    fresh = load_proxy_instance_config(proxy_id)
    assert fresh is not None
    assert fresh.tiers.sonnet == fresh.tiers.opus == prior
    assert fresh.model_alternatives["sonnet"][model] == slug
    assert fresh.model_alternatives["opus"][model] == slug
    assert fresh.allow_non_zdr is False

    saved = yaml.safe_load(path.read_text())
    for alternatives in saved["model_alternatives"].values():
        alternatives.pop(model, None)
    saved["tier_overrides"]["sonnet"] = {"reasoning_effort": "high"}
    path.write_text(yaml.safe_dump(saved))
    before = path.read_bytes()

    existing = load_proxy_instance_config(proxy_id)

    assert existing is not None
    assert existing.tiers.sonnet == prior
    assert model not in existing.model_alternatives["sonnet"]
    assert existing.tier_overrides.sonnet is not None
    assert existing.tier_overrides.sonnet.reasoning_effort == "high"
    assert path.read_bytes() == before
