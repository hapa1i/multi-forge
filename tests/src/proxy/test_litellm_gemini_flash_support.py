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
from forge.core.llm.clients.litellm import (
    _PLACEHOLDER_THOUGHT_SIGNATURE,
    _THOUGHT_SIGNATURE_SEPARATOR,
    LiteLLMClient,
)
from forge.core.llm.clients.openai_compat import message_to_openai
from forge.core.llm.types import Message, ModelHyperparameters, ToolCall
from forge.core.models import get_model_spec

# Verified packaged support floor for Gemini 3.8 and native Gemini 4 thinkingConfig passthrough.
MIN_PACKAGED_SUPPORT = (1, 102, 0)

PACKAGED_MODELS = (
    "gemini/gemini-3.6-flash",
    "vertex_ai/gemini-3.6-flash",
    "gemini/gemini-3.7-flash",
    "vertex_ai/gemini-3.7-flash",
    "gemini/gemini-3.8-flash",
    "vertex_ai/gemini-3.8-flash",
)
GEMINI_4_MODELS = ["gemini-4-argon", "gemini-4-carbon", "gemini-4-neon", "gemini-4-hydrogen"]


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


@pytest.mark.parametrize("model", GEMINI_4_MODELS)
def test_gemini_4_metadata_override_is_still_needed(model: str) -> None:
    assert not {
        model,
        f"gemini/{model}",
        f"vertex_ai/{model}",
    }.intersection(_packaged_cost_map()), (
        f"LiteLLM now packages {model}; verify native costs/capabilities, remove the bundled model_info override, "
        "and update this boundary test."
    )


@pytest.mark.parametrize("prefix", ["gemini/", ""])
@pytest.mark.parametrize("model", GEMINI_4_MODELS)
def test_registered_gemini_4_preserves_native_thinking_levels(model: str, prefix: str) -> None:
    config = yaml.safe_load(create_backend_config(adapter_type="litellm").read_text())
    entry = next(entry for entry in config["model_list"] if entry["model_name"] == f"{prefix}{model}")
    entry["litellm_params"]["api_key"] = "test-key"
    efforts = entry["model_info"]["reasoning_effort_levels"]
    assert tuple(efforts) == get_model_spec(model).litellm_reasoning_efforts
    assert entry["model_info"]["default_reasoning_effort"] == get_model_spec(model).default_reasoning_effort
    script = """\
        import json
        import sys
        import litellm
        from litellm.llms.vertex_ai.gemini.transformation import _transform_request_body
        from litellm.utils import get_optional_params

        payload = json.load(sys.stdin)
        entry = payload["entry"]
        provider, model = entry["litellm_params"]["model"].split("/", 1)
        router = litellm.Router(model_list=[entry])
        results = {
            "reasoning": litellm.supports_reasoning(model=model, custom_llm_provider=provider),
            "tools": litellm.supports_function_calling(model=model, custom_llm_provider=provider),
            "efforts": {},
        }
        for effort in payload["efforts"]:
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
        input=json.dumps({"entry": entry, "efforts": efforts}),
        env={**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "true"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    actual = json.loads(result.stdout)

    assert actual["reasoning"] is True
    assert actual["tools"] is True
    assert list(actual["efforts"]) == efforts
    for effort, body in actual["efforts"].items():
        generation = body["generationConfig"]
        assert generation["thinkingConfig"] == {"thinkingLevel": effort, "includeThoughts": True}
        assert generation["max_output_tokens"] == 65_536
        assert body["tools"][0]["function_declarations"][0]["name"] == "lookup"
        assert body["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"


@pytest.mark.parametrize("prefix", ["gemini/", ""])
@pytest.mark.parametrize("model", GEMINI_4_MODELS)
def test_registered_gemini_4_sends_system_instruction_and_signed_tool_history(model: str, prefix: str) -> None:
    config = yaml.safe_load(create_backend_config(adapter_type="litellm").read_text())
    entry = next(entry for entry in config["model_list"] if entry["model_name"] == f"{prefix}{model}")
    entry["litellm_params"]["api_key"] = "test-key"
    # Another provider's model made this tool call, so it carries no Gemini thought signature.
    history = [
        Message(role="system", content="Follow the rules."),
        Message(role="user", content="Look it up."),
        Message(role="assistant", content="", tool_calls=[ToolCall(id="toolu_01A", name="lookup", arguments={})]),
        Message(role="tool", content="found", tool_call_id="toolu_01A"),
    ]
    client = LiteLLMClient(f"{prefix}{model}", provider="litellm_local")
    histories = {
        "unsigned": [message_to_openai(message) for message in history],
        "forge": client._build_request_kwargs(history, None, ModelHyperparameters())[0]["messages"],
    }
    script = """\
        import json
        import sys
        import litellm
        from litellm.litellm_core_utils.prompt_templates import factory
        from litellm.llms.vertex_ai.gemini.transformation import _transform_request_body

        payload = json.load(sys.stdin)
        entry = payload["entry"]
        provider, model = entry["litellm_params"]["model"].split("/", 1)
        router = litellm.Router(model_list=[entry])
        results = {
            "placeholder": factory._get_dummy_thought_signature(),
            "separator": factory.THOUGHT_SIGNATURE_SEPARATOR,
        }
        for name, messages in payload["histories"].items():
            results[name] = _transform_request_body(
                messages=messages, model=model, optional_params={},
                custom_llm_provider=provider, litellm_params={}, cached_content=None,
            )
        print(json.dumps(results))
        """
    # Router registration changes capability caches; isolate it from other model tests.
    result = subprocess.run(
        [sys.executable, "-c", dedent(script)],
        input=json.dumps({"entry": entry, "histories": histories}),
        env={**os.environ, "LITELLM_LOCAL_MODEL_COST_MAP": "true"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    actual = json.loads(result.stdout)

    assert actual["placeholder"] == _PLACEHOLDER_THOUGHT_SIGNATURE
    assert actual["separator"] == _THOUGHT_SIGNATURE_SEPARATOR
    for name in histories:
        body = actual[name]
        # Without supports_system_messages, LiteLLM folds the system prompt into the first user turn.
        assert body["system_instruction"] == {"parts": [{"text": "Follow the rules."}]}
        assert [content["role"] for content in body["contents"]] == ["user", "model", "user"]
        assert body["contents"][0]["parts"] == [{"text": "Look it up."}]
    unsigned_call, forge_call = (
        next(part for part in actual[name]["contents"][1]["parts"] if "function_call" in part) for name in histories
    )
    assert "thoughtSignature" not in unsigned_call, (
        f"LiteLLM now signs unsigned {model} tool calls; verify it against Google AI, remove Forge's placeholder, "
        "and update this boundary test."
    )
    assert forge_call["thoughtSignature"] == _PLACEHOLDER_THOUGHT_SIGNATURE
