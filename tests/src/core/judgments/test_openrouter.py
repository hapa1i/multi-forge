"""Offline request shaping and early contract controls."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from forge.core.judgments import JudgmentError, NoulQuestion, OpenRouterJudgmentClient
from forge.core.judgments.openrouter import decisions_url
from forge.core.llm.credentials import CredentialManager


@pytest.fixture
def question():
    return NoulQuestion(
        instructions="Is this synthetic?",
        criteria={"true": "Synthetic", "false": "Real"},
    )


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-probe-key")
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    return CredentialManager()


@pytest.mark.asyncio
async def test_zdr_and_optional_metadata(question, credentials):
    options = {"zdr": False, "order": ["typesafe"]}

    async def handler(request):
        assert str(request.url) == "https://openrouter.ai/api/alpha/decisions"
        payload = json.loads(request.content)
        assert payload["provider"] == {"zdr": True, "order": ["typesafe"]}
        assert payload["questions"]["q"]["criteria"] == {
            "true": "Synthetic",
            "false": "Real",
        }
        return httpx.Response(
            200,
            json={
                "model": "typesafe/jev-1.13-20260917",
                "answers": {"q": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 30, "output_tokens": 2},
            },
        )

    result = await OpenRouterJudgmentClient(credentials=credentials, transport=httpx.MockTransport(handler)).judge(
        "Synthetic input",
        {"q": question},
        provider_options=options,
        deadline=time.monotonic() + 2,
    )
    assert result.response.usage.cost is None
    assert result.response.provider is None
    assert result.attempts[0].request_id.startswith("req_")
    assert options["zdr"] is False


@pytest.mark.parametrize(
    "base,expected",
    [
        ("https://openrouter.ai/api/v1", "https://openrouter.ai/api/alpha/decisions"),
        (
            "https://gateway.invalid/prefix/api/v1/",
            "https://gateway.invalid/prefix/api/alpha/decisions",
        ),
        ("http://localhost:8000", "http://localhost:8000/api/alpha/decisions"),
    ],
)
def test_url_resolution(base, expected):
    assert decisions_url(base) == expected


@pytest.mark.parametrize(
    "base",
    [
        "https://gateway.invalid/wrong",
        "https://secret@gateway.invalid/api/v1",
        "https://gateway.invalid/api/v1?key=secret",
    ],
)
def test_invalid_url(base):
    with pytest.raises(JudgmentError, match="OpenRouter"):
        decisions_url(base)


@pytest.mark.asyncio
async def test_expired_deadline_never_dispatches(question, credentials):
    def handler(request):
        pytest.fail("No dispatch allowed")

    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=credentials, transport=httpx.MockTransport(handler)).judge(
            "x", {"q": question}, deadline=time.monotonic() - 1
        )
    assert caught.value.kind == "deadline"
    assert not caught.value.attempts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "env_key,ignore_env,expected",
    [
        ("env-synthetic", False, "env-synthetic"),
        (None, False, "file-synthetic"),
        ("env-synthetic", True, "file-synthetic"),
    ],
)
async def test_no_dotenv_auth_precedence(question, tmp_path, monkeypatch, env_key, ignore_env, expected):
    from forge.core.auth.secrets import (
        ChainSecretsProvider,
        EnvSecretsProvider,
        FileSecretsProvider,
    )

    path = tmp_path / "credentials.yaml"
    path.write_text("version: 1\nprofiles:\n  default:\n    OPENROUTER_API_KEY: file-synthetic\n")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    if env_key:
        monkeypatch.setenv("OPENROUTER_API_KEY", env_key)
    else:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("forge.runtime_config.get_runtime_config", lambda: SimpleNamespace(auth_ignore_env=ignore_env))
    creds = CredentialManager(secrets=ChainSecretsProvider(EnvSecretsProvider(), FileSecretsProvider(path=path)))

    def handler(request):
        assert request.headers["Authorization"] == f"Bearer {expected}"
        return httpx.Response(400, json={"error": {"code": 400, "message": "synthetic rejection"}})

    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=creds, transport=httpx.MockTransport(handler)).judge(
            "x", {"q": question}, deadline=time.monotonic() + 2
        )
    assert caught.value.kind == "validation"


@pytest.mark.asyncio
async def test_missing_key_is_actionable_without_dispatch(question, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(JudgmentError, match="OPENROUTER_API_KEY") as caught:
        await OpenRouterJudgmentClient(credentials=CredentialManager()).judge(
            "x", {"q": question}, deadline=time.monotonic() + 1
        )
    assert caught.value.kind == "authentication"
    assert not caught.value.attempts


@pytest.mark.asyncio
async def test_credential_wait_consumes_deadline(question, credentials, monkeypatch):
    async def delayed(provider):
        await asyncio.sleep(1)
        pytest.fail("Must be cancelled before credentials return")

    monkeypatch.setattr(credentials, "get_credentials", delayed)
    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=credentials).judge(
            "x", {"q": question}, deadline=time.monotonic() + 0.01
        )
    assert caught.value.kind == "deadline"
    assert not caught.value.attempts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,kind",
    [
        (400, "validation"),
        (401, "authentication"),
        (402, "insufficient_credit"),
        (403, "permission"),
        (404, "unsupported_route"),
        (413, "payload_too_large"),
        (429, "rate_limit"),
        (500, "provider_error"),
        (502, "provider_error"),
        (503, "provider_error"),
        (524, "ambiguous_timeout"),
        (529, "overloaded"),
    ],
)
async def test_status_taxonomy_and_error_redaction(question, credentials, status, kind):
    def handler(request):
        return httpx.Response(status, json={"error": {"code": status, "message": "synthetic-probe-key private text"}})

    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(
            credentials=credentials, transport=httpx.MockTransport(handler), max_attempts=1
        ).judge("x", {"q": question}, deadline=time.monotonic() + 1)
    assert caught.value.kind == kind
    assert len(caught.value.attempts) == 1
    assert "synthetic-probe-key" not in str(caught.value)
    assert "private text" not in str(caught.value)


@pytest.mark.asyncio
async def test_oversized_response_retains_dispatch(question, credentials):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 256001))
    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=credentials, transport=transport).judge(
            "x", {"q": question}, deadline=time.monotonic() + 1
        )
    assert caught.value.kind == "invalid_response"
    assert len(caught.value.attempts) == 1


def success_body():
    return {
        "model": "typesafe/jev-1.13-20260917",
        "answers": {"q": {"type": "noul", "noul": 0.9}},
        "usage": {"input_tokens": 30, "output_tokens": 2, "cost": 0.00000126},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503, 529])
async def test_transient_retry_preserves_every_attempt_and_zdr(question, credentials, monkeypatch, status):
    from forge.core.telemetry.downstream import read_downstream_records
    from forge.core.usage.ledger import read_usage_events

    monkeypatch.setenv("FORGE_RUN_ID", "run_jev")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_jev")
    requests = []

    def handler(request):
        requests.append(request)
        assert json.loads(request.content)["provider"]["zdr"] is True
        body = success_body()
        if len(requests) == 1:
            body.pop("answers")
            return httpx.Response(status, json=body, headers={"retry-after": "0"})
        return httpx.Response(200, json=body)

    result = await OpenRouterJudgmentClient(credentials=credentials, transport=httpx.MockTransport(handler)).judge(
        "x", {"q": question}, deadline=time.monotonic() + 2, provider_options={"zdr": False}
    )
    assert len(result.attempts) == 2
    assert len({attempt.request_id for attempt in result.attempts}) == 2
    assert len({attempt.downstream_event_id for attempt in result.attempts}) == 2
    assert len(read_downstream_records()) == len(read_usage_events()) == 2
    assert all(record.cost_micros == 1 for record in read_downstream_records())
    assert [event.status for event in read_usage_events()] == ["error", "success"]


@pytest.mark.asyncio
async def test_retry_after_longer_than_deadline_never_redispatches(question, credentials):
    transport = httpx.MockTransport(lambda request: httpx.Response(429, headers={"retry-after": "3600"}))
    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=credentials, transport=transport).judge(
            "x", {"q": question}, deadline=time.monotonic() + 1
        )
    assert caught.value.kind == "deadline"
    assert len(caught.value.attempts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 413, 524, 418])
async def test_permanent_or_unknown_status_is_not_retried(question, credentials, status):
    transport = httpx.MockTransport(lambda request: httpx.Response(status))
    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=credentials, transport=transport).judge(
            "x", {"q": question}, deadline=time.monotonic() + 1
        )
    assert len(caught.value.attempts) == 1


@pytest.mark.asyncio
async def test_invalid_answer_keeps_independent_cost_and_tokens(question, credentials):
    body = success_body()
    body["answers"] = {}
    body["usage"]["input_tokens"] = True
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=credentials, transport=transport).judge(
            "x", {"q": question}, deadline=time.monotonic() + 1
        )
    assert caught.value.kind == "invalid_response"
    assert len(caught.value.attempts) == 1
    usage = caught.value.attempts[0].usage
    assert usage.input_tokens is None
    assert usage.output_tokens == 2
    assert usage.cost == 0.00000126


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_deadline_and_external_cancellation_close_and_record_once(question, credentials, cancel):
    from forge.core.telemetry.downstream import read_downstream_records

    entered = asyncio.Event()

    class SlowTransport(httpx.AsyncBaseTransport):
        closed = False

        async def handle_async_request(self, request):
            entered.set()
            await asyncio.sleep(10)
            pytest.fail("deadline or cancellation must interrupt the request")

        async def aclose(self):
            self.closed = True

    transport = SlowTransport()
    task = asyncio.create_task(
        OpenRouterJudgmentClient(credentials=credentials, transport=transport).judge(
            "x", {"q": question}, deadline=time.monotonic() + (2 if cancel else 0.02)
        )
    )
    await entered.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(JudgmentError) as caught:
            await task
        assert caught.value.kind == "ambiguous_timeout"
        assert len(caught.value.attempts) == 1
    assert transport.closed
    records = read_downstream_records()
    assert len(records) == 1
    assert records[0].failed
    assert records[0].timeout_seen is (not cancel)
    assert records[0].client_disconnected is cancel


def test_retry_after_http_date(monkeypatch):
    from forge.core.judgments.openrouter import retry_after

    monkeypatch.setattr("forge.core.judgments.openrouter.time.time", lambda: 0)
    assert retry_after("Thu, 01 Jan 1970 00:00:12 GMT") == 12
    assert retry_after("-1") is None
    assert retry_after("garbage") is None


@pytest.mark.asyncio
async def test_final_attribution_fields_cannot_escape_byte_cap(question, credentials, monkeypatch):
    from forge.core.judgments.openrouter import (
        MAX_INPUT_BYTES,
        build_payload,
        encode_payload,
    )

    monkeypatch.setattr("forge.core.judgments.openrouter.resolve_direct_provider_user", lambda role: "x" * 200)
    base = len(encode_payload(build_payload("typesafe/jev-1.13", "", {"q": question})))
    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(credentials=credentials).judge(
            "x" * (MAX_INPUT_BYTES - base), {"q": question}, deadline=time.monotonic() + 1
        )
    assert caught.value.kind == "payload_too_large"
    assert not caught.value.attempts


@pytest.mark.asyncio
async def test_captured_400_size_error_is_not_generic_validation(question, credentials):
    from pathlib import Path

    body = json.loads((Path(__file__).resolve().parents[3] / "fixtures/jev/over-limit.json").read_text())
    with pytest.raises(JudgmentError) as caught:
        await OpenRouterJudgmentClient(
            credentials=credentials, transport=httpx.MockTransport(lambda request: httpx.Response(400, json=body))
        ).judge("x", {"q": question}, deadline=time.monotonic() + 1)
    assert caught.value.kind == "payload_too_large"
    assert len(caught.value.attempts) == 1


@pytest.mark.parametrize(
    "base", ["https://[invalid", "https://example.invalid:abc/api/v1", "https://example.invalid:99999/api/v1"]
)
def test_malformed_url_is_a_typed_refusal(base):
    with pytest.raises(JudgmentError) as caught:
        decisions_url(base)
    assert caught.value.kind == "unsupported_route"
