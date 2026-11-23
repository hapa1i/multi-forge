"""Follow real LiteLLM Responses pricing through Forge telemetry and spend caps."""

import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml

from forge.backend.adapters.litellm import LiteLLMAdapter
from forge.backend.creation import create_backend_config
from forge.core.paths import get_forge_home
from forge.core.telemetry.downstream import read_downstream_records
from tests.fixtures.proxy import allocate_ephemeral_port, kill_process
from tests.integration.proxy.conftest import (
    FakeOpenAIUpstream,
    _register_proxy_for_test,
    _start_proxy_subprocess,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def cost_proxy(
    model: str,
    cap_usd: int,
    fake_litellm_openai: FakeOpenAIUpstream,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[str]:
    forge_home = get_forge_home()
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "true")
    config_path = create_backend_config("litellm")
    config = yaml.safe_load(config_path.read_text())
    deployment = next(entry for entry in config["model_list"] if entry["model_name"] == model)
    deployment["litellm_params"]["api_base"] = fake_litellm_openai.base_url
    config["model_list"] = [deployment]
    config_path.write_text(yaml.safe_dump(config))

    gateway_port = allocate_ephemeral_port()
    adapter = LiteLLMAdapter()
    gateway = adapter.start("cost-gateway", config_path, gateway_port)
    try:
        template = "codex-responses-local"
        proxy_id = "ultrafast-cost"
        port = allocate_ephemeral_port()
        _register_proxy_for_test(
            proxy_id=proxy_id,
            template=template,
            port=port,
            forge_home=forge_home,
            upstream_base_url=f"http://127.0.0.1:{gateway_port}/v1",
        )
        proxy_path = forge_home / "proxies" / proxy_id / "proxy.yaml"
        proxy_config = yaml.safe_load(proxy_path.read_text())
        proxy_config["costs"] = {
            "caps": {"per_day": cap_usd, "per_month": cap_usd},
            "on_cap_hit": "reject",
        }
        proxy_path.write_text(yaml.safe_dump(proxy_config))
        proc = _start_proxy_subprocess(
            template=template,
            port=port,
            forge_home=forge_home,
            env=dict(os.environ),
            cwd=tmp_path,
            proxy_id=proxy_id,
        )
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            kill_process(proc.pid)
            proc.wait(timeout=5)
    finally:
        adapter.stop(gateway)


@pytest.mark.parametrize(
    ("model", "cap_usd", "expected_costs"),
    [
        ("openai/gpt-6.2-astra", 20, (6_518_400, 4_345_416, 13_036_248)),
        ("openai/gpt-6.2-sol", 5, (1_629_600, 1_086_354, 3_259_062)),
    ],
)
def test_ultrafast_long_context_reaches_caps(
    model: str,
    expected_costs: tuple[int, int, int],
    cost_proxy: str,
    fake_litellm_openai: FakeOpenAIUpstream,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Upstream reports tokens and the served tier, never a price. Only the long-context premium crosses the cap.
    usage = {
        "input_tokens_details": {
            "cached_tokens": 1000,
            "cache_write_tokens": 500,
            "cache_write_tokens_details": {"ttl_30m_tokens": 200, "ttl_12h_tokens": 300},
        },
        "output_tokens": 10,
    }
    monkeypatch.setattr(fake_litellm_openai, "response_usage", usage)
    initial_calls = len(fake_litellm_openai.requests)
    cases = [(272_000, "ultrafast"), (272_001, "default"), (272_001, "ultrafast")]
    total_micros = 0
    with httpx.Client(base_url=cost_proxy, timeout=30) as client:
        for (prompt_tokens, tier), expected_micros in zip(cases, expected_costs, strict=True):
            usage.update(input_tokens=prompt_tokens, total_tokens=prompt_tokens + 10)
            body = {
                "model": model,
                "input": "offline cost fixture",
                "service_tier": tier,
            }
            response = client.post("/v1/responses", json=body)
            assert response.status_code == 200, response.text
            assert response.json()["service_tier"] == tier

            request_id = response.headers["x-request-id"]
            (record,) = read_downstream_records(kind="attempt", request_id=request_id)
            assert (
                record.input_tokens,
                record.cached_tokens,
                record.output_tokens,
            ) == (prompt_tokens, 1000, 10)
            assert record.cost_micros == expected_micros
            assert (record.reporter, record.confidence) == (
                "litellm",
                "gateway_calculated",
            )
            total_micros += expected_micros
            costs = client.get("/").json()["metrics"]["costs"]
            assert costs["total_micros"] == total_micros
            for period in ("daily", "monthly"):
                assert costs["caps"][period]["current_usd"] == pytest.approx(total_micros / 1_000_000)

        blocked = client.post("/v1/responses", json={"model": model, "input": "should be blocked"})
        assert blocked.status_code == 429
        assert blocked.json()["error"]["type"] == "spend_cap_exceeded"
        assert len(fake_litellm_openai.requests) - initial_calls == len(cases)
