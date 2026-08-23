from __future__ import annotations

from types import SimpleNamespace

from forge.proxy.model_routes import effective_proxy_model_maps


def _proxy(provider: object) -> SimpleNamespace:
    return SimpleNamespace(
        preferred_provider="openrouter",
        get_provider=lambda _provider: provider,
    )


def test_mapping_provider_respects_non_zdr_opt_out() -> None:
    provider = {
        "tiers": {"sonnet": "qwen/qwen3.8-max"},
        "model_alternatives": {},
        "allow_non_zdr": True,
        "zdr_fallbacks": {},
    }

    tiers, alternatives = effective_proxy_model_maps(_proxy(provider))

    assert tiers == {"sonnet": "qwen/qwen3.8-max"}
    assert alternatives == {}


def test_mapping_provider_applies_user_zdr_fallbacks_to_defaults_and_alternatives() -> None:
    provider = {
        "tiers": {"sonnet": "vendor/default"},
        "model_alternatives": {"sonnet": {"special": "vendor/special"}},
        "allow_non_zdr": False,
        "zdr_fallbacks": {
            "vendor/default": "vendor/default-zdr",
            "vendor/special": "vendor/special-zdr",
        },
    }

    tiers, alternatives = effective_proxy_model_maps(_proxy(provider))

    assert tiers == {"sonnet": "vendor/default-zdr"}
    assert alternatives == {"sonnet": {"special": "vendor/special-zdr"}}
