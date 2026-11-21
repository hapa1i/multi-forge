"""OpenRouter source restrictions and the two provider ZDR refusal forms."""

import json
from types import SimpleNamespace

import pytest

from forge.backend.responses import validate_base
from forge.proxy import openrouter_responses as route


@pytest.mark.parametrize(
    "base",
    [
        "http://router.test/v1",
        "http://127.0.0.11:1234",
        "http://localhost.router.test",
        "https://user@router.test",
        "https://@router.test",
        "https://router.test/?x=1",
        "https://router.test/#",
        "https://router.test?",
        "https://router.test:invalid",
        "file:///v1",
        "https://",
        "https://router. test",
        "https://router.test\\path",
    ],
)
def test_bad_base_rejected(base):
    with pytest.raises(ValueError):
        validate_base(base)


@pytest.mark.parametrize(
    "base", ["https://router.test/prefix/v1", "http://[::1]:8106", "http://localhost:8081/api", "http://127.0.0.1"]
)
def test_tls_and_loopback_bases(base):
    validate_base(base)


@pytest.mark.parametrize(
    "fields",
    [
        {"tools": [{"type": "namespace", "tools": [{"type": "web_search"}]}]},
        {"input": [{"type": "additional_tools", "tools": [{"type": "namespace", "tools": [{"type": "new_hosted"}]}]}]},
        {"tools": [False]},
        {"tools": {}},
        {"tools": [{"type": "namespace", "tools": {}}]},
        {"provider": None},
        {"plugins": [{"id": "web"}]},
        {"plugins": [{"id": "other", "enabled": True}]},
        {"plugins": [{"id": "web", "enabled": 0}]},
        {"plugins": {"id": "web"}},
        {"model": "fixture:free:online"},
        {"models": ["alternate:online"]},
        {"models": "alternate:online"},
        {"background": True},
    ],
)
def test_required_zdr_fails_closed(fields):
    with pytest.raises(ValueError):
        route.prepare_request({"model": "requested", **fields}, SimpleNamespace(allow_non_zdr=False))


def test_generic_endpoint_404_passes_through():
    assert route.zdr_refusal(404, b'{"error":{"message":"No endpoints found for this model."}}', "m", "req") is None


def test_configured_fallback_cannot_enable_online_search():
    provider = SimpleNamespace(allow_non_zdr=False, zdr_fallbacks={"requested": "mapped:online"})
    with pytest.raises(ValueError, match="Online model"):
        route.prepare_request({"model": "requested"}, provider)


@pytest.mark.parametrize("plugins", [[], [{"id": "web", "enabled": False}]])
def test_required_zdr_disables_account_default_web_plugin(plugins):
    provider = SimpleNamespace(allow_non_zdr=False)
    body = {
        "model": "m",
        "plugins": [{"id": "other", "enabled": False}, *plugins],
        "models": ["alternate"],
    }
    result = route.prepare_request(body, provider)
    assert result["plugins"] == [
        {"id": "other", "enabled": False},
        {"id": "web", "enabled": False},
    ]
    assert result["models"] == ["alternate"] and len(body["plugins"]) == len(plugins) + 1
    assert route.prepare_request({"model": "m"}, provider)["plugins"] == [{"id": "web", "enabled": False}]


def test_unrestricted_search_fields_pass_through():
    body = {
        "model": "m:online",
        "plugins": [{"id": "web", "max_results": 1}],
        "models": ["alternate:online"],
    }
    assert route.prepare_request(body, SimpleNamespace(allow_non_zdr=True)) == body


def test_text_only_qwen_404_names_the_restriction():
    wire = json.dumps(
        {
            "error": {
                "code": 404,
                "message": "No endpoints found matching your data policy (Zero data retention). Configure: https://openrouter.ai/settings/privacy",
            }
        }
    ).encode()
    translated = route.zdr_refusal(404, wire, "qwen/qwen4-max", "req")
    assert translated.status_code == 400
    message = json.loads(translated.body)["error"]["message"]
    assert "ZDR-eligible" in message and "qwen/qwen4-max" in message
    assert "allow_non_zdr=true" in message and "If account and guardrail policies permit" in message


@pytest.mark.parametrize(
    "amount,expected",
    [
        (0, 0),
        (0.0000005, 1),
        (0.123214, 123214),
        (False, None),
        (-1, None),
        ("0.00", None),
        (float("inf"), None),
        (float("nan"), None),
    ],
)
def test_only_reported_terminal_account_credit_counts(amount, expected):
    observed = []
    attempt = route.OpenRouterResponseEvidence(lambda: observed.append(1))
    attempt.observe({"id": "resp_only", "usage": {"cost": 42}}, "in_progress")
    assert attempt.cost_micros is None and not observed
    attempt.observe(
        {"usage": {"cost": amount, "is_byok": True, "cost_details": {"upstream_inference_cost": 123}}}, "incomplete"
    )
    attempt.observe({"usage": {"cost": 999}}, "completed")
    assert attempt.cost_micros == expected and len(observed) == int(expected is None)
    assert attempt.response_id == "resp_only" and attempt.generation_id is None


@pytest.mark.parametrize(
    "backend,provider,base,eligible",
    [
        ("openrouter", "openrouter", "https://router.example/v1", True),
        ("", "openrouter", "http://127.0.0.1:9010/gateway/v1", True),
        ("", "openrouter", "http://router.example/v1", False),
        ("openrouter", "litellm", "https://router.example/v1", False),
        ("codex-responses-local", "openrouter", "https://router.example/v1", False),
        ("undeclared", "openrouter", "https://router.example/v1", False),
    ],
)
def test_only_matching_saved_sources_enable_direct_responses(backend, provider, base, eligible):
    from forge.backend.responses import available_responses_source

    for shape in ("openai_translated", "openai_responses_passthrough"):
        source = available_responses_source(backend, provider, shape, base)
        assert (source is not None) is eligible
