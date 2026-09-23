"""GPT-6 sampling must follow the effort that survives OpenRouter parameter translation."""

import pytest

from forge.core.llm.clients.openai_compat import build_chat_completion_kwargs
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import ModelHyperparameters, ModelReasoningEffort

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("model", ["openai/gpt-6-sol", "openai/gpt-6-luna"])
@pytest.mark.parametrize(
    ("flat_effort", "nested_effort", "effective_effort"),
    [("none", "medium", "none"), ("medium", "none", "medium"), (None, "none", "none"), (None, "medium", "medium")],
)
def test_sampling_follows_the_reasoning_effort_sent_to_openrouter(
    model: str, flat_effort: ModelReasoningEffort | None, nested_effort: str, effective_effort: str
) -> None:
    params = ModelHyperparameters(
        temperature=0.7,
        top_p=0.8,
        reasoning_effort=flat_effort,
        extra={"openai": {"extra_body": {"reasoning": {"effort": nested_effort}, "temperature": 0.6, "top_p": 0.9}}},
    )

    request = OpenRouterClient._translate_params(build_chat_completion_kwargs(model, [], None, params))
    extra_body = request.pop("extra_body")
    wire_body = {**request, **extra_body}

    assert wire_body["reasoning"] == {"effort": effective_effort}
    if effective_effort == "none":
        assert wire_body["temperature"] == 0.6
        assert wire_body["top_p"] == 0.9
    else:
        assert "temperature" not in wire_body
        assert "top_p" not in wire_body
