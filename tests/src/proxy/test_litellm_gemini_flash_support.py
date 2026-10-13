"""Pin the offline LiteLLM support boundary for current Gemini routes."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from forge.backend.creation import create_backend_config

# Verified packaged support floor for Gemini 3.8 and native Argon thinkingConfig passthrough.
MIN_PACKAGED_SUPPORT = (1, 102, 0)

PACKAGED_MODELS = (
    "gemini/gemini-3.6-flash",
    "vertex_ai/gemini-3.6-flash",
    "gemini/gemini-3.7-flash",
    "vertex_ai/gemini-3.7-flash",
    "gemini/gemini-3.8-flash",
    "vertex_ai/gemini-3.8-flash",
)


def _installed_litellm_version() -> tuple[int, int, int]:
    parts = importlib.metadata.version("litellm").split(".")[:3]
    numeric = []
    for part in parts:
        match = re.match(r"\d+", part)
        numeric.append(int(match.group()) if match else 0)
    while len(numeric) < 3:
        numeric.append(0)
    return (numeric[0], numeric[1], numeric[2])


def _packaged_cost_map() -> dict[str, object]:
    distribution = importlib.metadata.distribution("litellm")
    path = Path(str(distribution.locate_file("litellm/model_prices_and_context_window_backup.json")))
    return json.loads(path.read_text(encoding="utf-8"))


def test_litellm_version_has_current_gemini_support() -> None:
    version = _installed_litellm_version()

    assert (
        version >= MIN_PACKAGED_SUPPORT
    ), f"litellm {version} predates the verified Gemini adapter; require at least {MIN_PACKAGED_SUPPORT}"


@pytest.mark.parametrize("model_key", PACKAGED_MODELS)
def test_supported_gemini_flash_routes_exist_in_packaged_cost_map(model_key: str) -> None:
    assert model_key in _packaged_cost_map(), f"LiteLLM must package pricing and capability metadata for {model_key}"


@pytest.mark.parametrize("model_key", ["gemini/gemini-3.8-flash", "vertex_ai/gemini-3.8-flash"])
def test_gemini_38_has_offline_reasoning_tool_and_cost_metadata(model_key: str) -> None:
    metadata = _packaged_cost_map()[model_key]
    assert isinstance(metadata, dict)
    assert metadata["supports_reasoning"] is True
    assert metadata["supports_function_calling"] is True
    assert metadata["supports_vision"] is True
    assert metadata["max_input_tokens"] == 1_048_576
    assert metadata["max_output_tokens"] == 65_536
    assert metadata["input_cost_per_token"] > 0
    assert metadata["output_cost_per_token"] > 0
    assert metadata["output_cost_per_reasoning_token"] > 0


def test_argon_metadata_override_is_still_needed() -> None:
    assert not {
        "gemini-4-argon",
        "gemini/gemini-4-argon",
        "vertex_ai/gemini-4-argon",
    }.intersection(_packaged_cost_map()), (
        "LiteLLM now packages Argon; verify native costs/capabilities, remove the bundled model_info override, "
        "and update this boundary test."
    )


@pytest.mark.parametrize("model_name", ["gemini/gemini-4-argon", "gemini-4-argon"])
def test_registered_argon_preserves_native_thinking_levels(model_name: str) -> None:
    config = yaml.safe_load(create_backend_config(adapter_type="litellm").read_text())
    entry = next(entry for entry in config["model_list"] if entry["model_name"] == model_name)
    entry["litellm_params"]["api_key"] = "test-key"
    script = """\
        import json
        import sys
        import litellm
        from litellm.llms.vertex_ai.gemini.transformation import _transform_request_body
        from litellm.utils import get_optional_params

        entry = json.load(sys.stdin)
        provider, model = entry["litellm_params"]["model"].split("/", 1)
        router = litellm.Router(model_list=[entry])
        results = {
            "reasoning": litellm.supports_reasoning(model=model, custom_llm_provider=provider),
            "tools": litellm.supports_function_calling(model=model, custom_llm_provider=provider),
            "efforts": {},
        }
        for effort in ("low", "medium", "high"):
            params = get_optional_params(
                model=model, custom_llm_provider=provider,
                thinkingConfig={"thinkingLevel": effort, "includeThoughts": True},
                max_tokens=65536, tool_choice="auto", drop_params=False,
                tools=[{"type": "function", "function": {
                    "name": "lookup", "parameters": {"type": "object", "properties": {}},
                }}],
            )
            results["efforts"][effort] = _transform_request_body(
                messages=[{"role": "user", "content": "Hello"}], model=model,
                optional_params=params, custom_llm_provider=provider, litellm_params={}, cached_content=None,
            )
        print(json.dumps(results))
        """
    # Router registration changes capability caches; isolate it from other model tests.
    result = subprocess.run(
        [sys.executable, "-c", dedent(script)],
        input=json.dumps(entry),
        env={**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "true"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    actual = json.loads(result.stdout)

    assert actual["reasoning"] is True
    assert actual["tools"] is True
    for effort, body in actual["efforts"].items():
        generation = body["generationConfig"]
        assert generation["thinkingConfig"] == {"thinkingLevel": effort, "includeThoughts": True}
        assert generation["max_output_tokens"] == 65_536
        assert body["tools"][0]["function_declarations"][0]["name"] == "lookup"
        assert body["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
