from __future__ import annotations

from forge.proxy.runtime_truth import ProxyRuntimeTruth


def test_older_runtime_response_defaults_new_route_fields() -> None:
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "proxy": {"proxy_id": "proxy-1", "template": "litellm-openai"},
            "runtime": {"tier_mappings": {"sonnet": "openai/gpt-5"}},
        }
    )

    assert runtime.backend_id is None
    assert runtime.model_alternatives == {}
    assert runtime.tier_mappings == {"sonnet": "openai/gpt-5"}
    assert runtime.has_authoritative_route_truth is False


def test_malformed_route_fields_are_safely_discarded() -> None:
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": "yes",
            "proxy": {"proxy_id": [], "template": 4, "port": True},
            "runtime": {
                "backend_id": {"secret": "value"},
                "tier_mappings": {"sonnet": "openai/gpt-5", "opus": None},
                "model_alternatives": {
                    "sonnet": {"sonnet": "openai/gpt-5", "bad": None},
                    "opus": [],
                },
            },
        }
    )

    assert runtime.is_proxy is False
    assert runtime.proxy_id is None
    assert runtime.template == "unknown"
    assert runtime.port is None
    assert runtime.backend_id is None
    assert runtime.tier_mappings == {"sonnet": "openai/gpt-5"}
    assert runtime.model_alternatives == {"sonnet": {"sonnet": "openai/gpt-5"}}
    assert runtime.has_authoritative_route_truth is False


def test_complete_route_fields_are_authoritative() -> None:
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "runtime": {
                "backend_id": "openrouter",
                "tier_mappings": {"sonnet": "openai/gpt-5"},
                "model_alternatives": {},
            },
        }
    )

    assert runtime.has_authoritative_route_truth is True


def test_known_empty_optional_tier_is_authoritative_but_not_exposed() -> None:
    runtime = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "runtime": {
                "backend_id": "openrouter",
                "tier_mappings": {"haiku": "", "sonnet": "openai/gpt-5"},
                "model_alternatives": {},
            },
        }
    )

    assert runtime.has_authoritative_route_truth is True
    assert runtime.tier_mappings == {"sonnet": "openai/gpt-5"}


def test_route_truth_rejects_unknown_tiers_and_unsafe_backend_ids() -> None:
    unknown_tier = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "runtime": {
                "backend_id": "openrouter",
                "tier_mappings": {"secret": "openai/gpt-5"},
                "model_alternatives": {},
            },
        }
    )
    unsafe_backend = ProxyRuntimeTruth(
        {
            "is_proxy": True,
            "runtime": {
                "backend_id": "openrouter:token",
                "tier_mappings": {"sonnet": "openai/gpt-5"},
                "model_alternatives": {},
            },
        }
    )

    assert unknown_tier.has_authoritative_route_truth is False
    assert unsafe_backend.has_authoritative_route_truth is False
