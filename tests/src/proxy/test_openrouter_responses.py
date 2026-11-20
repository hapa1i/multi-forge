"""OpenRouter source restrictions and the two provider ZDR refusal forms."""

import json
from types import SimpleNamespace

import pytest

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
        route.validate_base(base)


@pytest.mark.parametrize(
    "base", ["https://router.test/prefix/v1", "http://[::1]:8106", "http://localhost:8081/api", "http://127.0.0.1"]
)
def test_tls_and_loopback_bases(base):
    route.validate_base(base)


@pytest.mark.parametrize(
    "fields",
    [
        {"tools": [{"type": "namespace", "tools": [{"type": "web_search"}]}]},
        {"input": [{"type": "additional_tools", "tools": [{"type": "namespace", "tools": [{"type": "new_hosted"}]}]}]},
        {"tools": [False]},
        {"tools": {}},
        {"tools": [{"type": "namespace", "tools": {}}]},
        {"provider": None},
    ],
)
def test_required_zdr_fails_closed(fields):
    with pytest.raises(ValueError):
        route.prepare_request({"model": "requested", **fields}, SimpleNamespace(allow_non_zdr=False))


def test_generic_endpoint_404_passes_through():
    assert route.zdr_refusal(404, b'{"error":{"message":"No endpoints found for this model."}}', "m", "req") is None


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
    assert "ZDR-eligible" in message and "qwen/qwen4-max" in message and "account" not in message


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
