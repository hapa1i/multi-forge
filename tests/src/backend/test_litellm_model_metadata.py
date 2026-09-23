"""Verify packaged native-model metadata without LiteLLM's remote map or shared caches."""

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from forge.backend.creation import create_backend_config


def _packaged_cost_map() -> dict:
    distribution = importlib.metadata.distribution("litellm")
    path = Path(str(distribution.locate_file("litellm/model_prices_and_context_window_backup.json")))
    return json.loads(path.read_text())


def _backend_entry(model: str) -> dict:
    config = yaml.safe_load(create_backend_config(adapter_type="litellm").read_text())
    entry = next(entry for entry in config["model_list"] if entry["model_name"] == model)
    entry["litellm_params"]["api_key"] = "test-key"
    return entry


def _run_offline(script: str, payload: dict) -> dict:
    # Router registration changes caches beyond model_cost; isolate all of them.
    result = subprocess.run(
        [sys.executable, "-c", dedent(script)],
        input=json.dumps(payload),
        env={**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "true"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def test_astra_uses_packaged_pricing_without_a_deployment_override() -> None:
    assert "gpt-6-astra" in _packaged_cost_map()
    assert "model_info" not in _backend_entry("openai/gpt-6-astra")


@pytest.mark.parametrize("model", ["gpt-6-sol", "gpt-6-luna", "claude-opus-5-5"])
def test_new_model_metadata_override_is_still_needed(model: str) -> None:
    cost_map = _packaged_cost_map()
    provider = "anthropic" if model.startswith("claude-") else "openai"

    assert not {model, f"{provider}/{model}"}.intersection(cost_map), (
        f"LiteLLM now packages {model}; verify native costs/capabilities, remove its bundled model_info override, "
        "and update this boundary test."
    )


@pytest.mark.parametrize(
    ("model", "cases"),
    [
        (
            "openai/gpt-6-astra",
            [
                (100, 0, 0, 0.001, 0.0005),
                (100, 80, 0, 0.00028, 0.0005),
                (100, 0, 100, 0.00125, 0.0005),
                (272_000, 1_000, 0, 2.711, 0.0005),
                (272_001, 1_000, 500, 5.42452, 0.00075),
            ],
        ),
        (
            "openai/gpt-6-sol",
            [
                (100, 0, 0, 0.0002, 0.0001),
                (100, 80, 0, 0.000056, 0.0001),
                (100, 0, 100, 0.00025, 0.0001),
                (272_000, 1_000, 0, 0.5422, 0.0001),
                (272_001, 1_000, 500, 1.084904, 0.00015),
            ],
        ),
        (
            "openai/gpt-6-luna",
            [
                (100, 0, 0, 0.00001, 0.000005),
                (100, 80, 0, 0.0000028, 0.000005),
                (100, 0, 100, 0.0000125, 0.000005),
                (272_000, 1_000, 0, 0.02711, 0.000005),
                (272_001, 1_000, 500, 0.0542452, 0.0000075),
            ],
        ),
        (
            "anthropic/claude-opus-5-5",
            [
                (100, 0, 0, 0.0004, 0.0002),
                (100, 80, 0, 0.000096, 0.0002),
                (100, 0, 100, 0.0005, 0.0002),
                (900_000, 1_000, 0, 3.5962, 0.0002),
            ],
        ),
    ],
)
def test_native_pricing_without_remote_model_metadata(model: str, cases: list[tuple]) -> None:
    script = """\
        import json
        import sys
        import litellm

        data = json.load(sys.stdin)
        entry = data["entry"]
        provider = entry["model_name"].split("/", 1)[0]
        router = litellm.Router(model_list=[entry])
        deployment_id = router.model_list[0]["model_info"]["id"]
        custom_pricing = "input_cost_per_token" in entry.get("model_info", {})
        cost_model = deployment_id if custom_pricing else entry["model_name"]
        results = {"tiers": []}
        for tier in data["tiers"]:
            costs = []
            response_costs = []
            for prompt, cached, writes, *_ in data["cases"]:
                usage = litellm.Usage(
                    prompt_tokens=prompt, completion_tokens=10,
                    cache_read_input_tokens=cached, cache_creation_input_tokens=writes,
                )
                costs.append(litellm.cost_per_token(
                    model=cost_model, custom_llm_provider=provider, usage_object=usage, service_tier=tier,
                ))
                response = litellm.ModelResponse(model=entry["model_name"], usage=usage, service_tier=tier)
                response_costs.append(litellm.response_cost_calculator(
                    response_object=response, model=entry["model_name"], custom_llm_provider=provider,
                    call_type="completion", optional_params={}, router_model_id=deployment_id,
                    custom_pricing=custom_pricing,
                ))
            results["tiers"].append({"costs": costs, "response_costs": response_costs})
        if provider == "anthropic":
            usage = litellm.Usage(
                prompt_tokens=100, completion_tokens=10, cache_creation_input_tokens=100,
                prompt_tokens_details={"cache_creation_token_details": {"ephemeral_1h_input_tokens": 100}},
            )
            results["hour_cache_cost"] = litellm.cost_per_token(
                model=cost_model, custom_llm_provider=provider, usage_object=usage,
            )
        print(json.dumps(results))
        """
    tiers: dict[str | None, float] = {None: 1.0}
    if model.startswith("openai/"):
        # OpenAI bills Flex at half and Fast/legacy Priority at twice the applicable standard rate.
        tiers.update({"default": 1.0, "flex": 0.5, "priority": 2.0, "fast": 2.0})
    actual = _run_offline(script, {"entry": _backend_entry(model), "cases": cases, "tiers": list(tiers)})

    for tier_result, multiplier in zip(actual["tiers"], tiers.values(), strict=True):
        for costs, response_cost, (*_, expected_input, expected_output) in zip(
            tier_result["costs"], tier_result["response_costs"], cases, strict=True
        ):
            assert costs == pytest.approx((expected_input * multiplier, expected_output * multiplier))
            assert response_cost == pytest.approx((expected_input + expected_output) * multiplier)
    if model == "anthropic/claude-opus-5-5":
        assert actual["hour_cache_cost"] == pytest.approx((0.0008, 0.0002))


def test_registered_opus_5_5_uses_native_adaptive_effort_contract() -> None:
    script = """\
        import json
        import sys
        import litellm
        from litellm.llms.anthropic.chat.transformation import AnthropicConfig

        entry = json.load(sys.stdin)["entry"]
        router = litellm.Router(model_list=[entry])
        config = AnthropicConfig()
        results = {}
        for effort in ("medium", "xhigh", "max"):
            params = config.map_openai_params(
                non_default_params={
                    "reasoning_effort": effort, "max_tokens": 128000, "tool_choice": "auto",
                    "tools": [{"type": "function", "function": {
                        "name": "lookup", "parameters": {"type": "object", "properties": {}},
                    }}],
                },
                optional_params={}, model="claude-opus-5-5", drop_params=False,
            )
            results[effort] = config.transform_request(
                model="claude-opus-5-5", messages=[{"role": "user", "content": "Hello"}],
                optional_params=params, litellm_params={}, headers={},
            )
        disabled = config.map_openai_params(
            non_default_params={"thinking": {"type": "disabled"}}, optional_params={},
            model="claude-opus-5-5", drop_params=False,
        )
        results["disabled"] = config.transform_request(
            model="claude-opus-5-5", messages=[{"role": "user", "content": "Hello"}],
            optional_params=disabled, litellm_params={}, headers={},
        )
        print(json.dumps(results))
        """
    actual = _run_offline(script, {"entry": _backend_entry("anthropic/claude-opus-5-5")})

    for effort in ("medium", "xhigh", "max"):
        assert actual[effort]["thinking"] == {
            "type": "adaptive",
            "display": "summarized",
        }
        assert actual[effort]["output_config"] == {"effort": effort}
        assert actual[effort]["max_tokens"] == 128_000
        assert actual[effort]["tool_choice"] == {"type": "auto"}
        assert actual[effort]["tools"][0]["name"] == "lookup"
    assert "thinking" not in actual["disabled"]
