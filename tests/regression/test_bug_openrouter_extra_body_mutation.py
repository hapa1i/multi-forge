"""OpenRouter effort translation must not leak settings into the next request.

The translator mutated a shared hyperparameter extra_body in place, so one
request's reasoning/verbosity persisted in later calls that omitted them.
"""

import pytest

from forge.core.llm.clients.openai_compat import build_chat_completion_kwargs
from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import ModelHyperparameters

pytestmark = pytest.mark.regression


def test_explicit_effort_and_verbosity_do_not_contaminate_shared_provider_settings() -> None:
    params = ModelHyperparameters(extra={"openai": {"extra_body": {"provider": {"zdr": True}}}})
    first = build_chat_completion_kwargs("minimax/minimax-m3.1-flash", [], None, params)
    first.update(reasoning_effort="low", verbosity="low")

    translated = OpenRouterClient._translate_params(first)
    next_request = OpenRouterClient._translate_params(
        build_chat_completion_kwargs("minimax/minimax-m3.1-flash", [], None, params)
    )

    assert translated["extra_body"] == {"provider": {"zdr": True}, "reasoning": {"effort": "low"}, "verbosity": "low"}
    assert next_request["extra_body"] == {"provider": {"zdr": True}}
    assert params.extra == {"openai": {"extra_body": {"provider": {"zdr": True}}}}
