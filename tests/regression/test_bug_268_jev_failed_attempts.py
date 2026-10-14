"""PR 268: unexpected Jev response/transport errors must not become successful attempts."""

import json
import time

import httpx
import pytest

from forge.core.judgments import JudgmentError, NoulQuestion, OpenRouterJudgmentClient
from forge.core.llm.credentials import CredentialManager
from forge.core.telemetry.downstream import read_downstream_records
from forge.core.usage.ledger import read_usage_events

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["nested_body", "nested_error", "transport", "close"])
async def test_unusable_response_is_typed_and_never_recorded_as_success(monkeypatch, case):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setenv("FORGE_RUN_ID", "run_jev_failure")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_jev_failure")
    calls = []
    nested = "[" * 20000 + "0" + "]" * 20000
    valid = {
        "model": "typesafe/jev-1.13",
        "answers": {"q": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 30, "output_tokens": 2, "cost": 0.00000126},
    }

    class BrokenClose(httpx.Response):
        close_calls = 0

        async def aclose(self):
            self.close_calls += 1
            await super().aclose()
            if self.close_calls == 2:
                raise RuntimeError("synthetic-key private transport detail")

    def handler(request):
        calls.append(request)
        if case == "nested_body":
            return httpx.Response(200, content=nested)
        if case == "nested_error":
            return httpx.Response(400, json={"error": {"message": "HTTP 400: " + nested}})
        if case == "transport":
            raise RuntimeError("synthetic-key private transport detail")
        return BrokenClose(200, stream=httpx.ByteStream(json.dumps(valid).encode()))

    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=CredentialManager(), transport=httpx.MockTransport(handler)).judge(
            "Synthetic input",
            {"q": NoulQuestion(instructions="Synthetic?", criteria={"true": "Synthetic", "false": "Real"})},
            deadline=time.monotonic() + 2,
        )

    kind = {"nested_body": "invalid_response", "nested_error": "validation"}.get(case, "internal_error")
    assert caught.value.kind == kind
    assert "private" not in str(caught.value) and "synthetic-key" not in str(caught.value)
    assert len(calls) == len(caught.value.attempts) == 1
    assert caught.value.attempts[0].failure == kind
    (record,) = read_downstream_records()
    (event,) = read_usage_events()
    assert record.failed is True
    assert event.status == "error"
    if case == "close":
        assert record.cost_micros == event.cost_micro_usd == 1
        assert record.input_tokens == event.input_tokens == 30


@pytest.mark.asyncio
async def test_deep_local_input_is_typed_without_dispatch():
    state = []
    for _ in range(20000):
        state = [state]
    transport = httpx.MockTransport(lambda request: pytest.fail("Local rejection must not dispatch"))
    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=CredentialManager(), transport=transport).judge(
            state,
            {"q": NoulQuestion(instructions="Synthetic?", criteria={"true": "Synthetic", "false": "Real"})},
            deadline=time.monotonic() + 2,
        )
    assert caught.value.kind == "validation"
    assert not caught.value.attempts
    assert read_downstream_records() == []
