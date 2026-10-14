"""Probe preparation and request caps never need paid inference."""

import gzip
import importlib.util
import json
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[3] / "scripts/experiments/jev/probe.py"
    spec = importlib.util.spec_from_file_location("jev_probe", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_has_four_synthetic_zdr_requests(probe):
    plan = probe.manifest()
    assert plan["max_physical_requests"] == len(plan["requests"]) == 4
    assert plan["estimated_max_usd"] < plan["budget_usd"] == 0.01
    assert all(item["payload"]["provider"]["zdr"] for item in plan["requests"])


@pytest.mark.asyncio
async def test_cap_prevents_dispatch(probe):
    def unexpected(request):
        pytest.fail("No request allowed")

    transport = probe.CaptureTransport(httpx.MockTransport(unexpected), "synthetic-key", 0)
    with pytest.raises(httpx.TransportError, match="cap exhausted"):
        await transport.handle_async_request(httpx.Request("POST", "https://example.invalid"))


def test_dry_run_never_resolves_credentials(probe, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["probe.py"])

    def unexpected():
        pytest.fail("Dry-run cannot resolve credentials")

    monkeypatch.setattr(probe.CredentialManager, "default", unexpected)
    assert probe.main() == 0
    assert '"max_physical_requests": 4' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_capture_does_not_decode_compressed_response_twice(probe):
    body = {"synthetic": "sk-or-v1-example"}
    transport = probe.CaptureTransport(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-encoding": "gzip"}, content=gzip.compress(json.dumps(body).encode())
            )
        ),
        "private-key",
        1,
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post("https://example.invalid", json={"provider": {"zdr": True}})
    assert response.json() == body
    assert transport.records[0]["body"] == {"synthetic": "[REDACTED]"}


def test_measurement_manifest_bounds_every_shape(probe):
    plan = probe.measurement_manifest()
    assert len(plan["requests"]) == plan["max_physical_requests"] == 25
    assert plan["estimated_max_usd"] < plan["budget_usd"] == 0.05
    assert all(entry["payload"]["provider"]["zdr"] for entry in plan["requests"])
    assert sum(bool(entry.get("wire_control")) for entry in plan["requests"]) == 1


@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda body: body.update(model="typesafe/unexpected"), "model_changed"),
        (lambda body: body["usage"].update(cost=1), "unexpected_cost"),
        (lambda body: body["usage"].update(cost=True), "unexpected_cost"),
        (lambda body: body["usage"].update(cost=float("nan")), "unexpected_cost"),
        (lambda body: body["usage"].update(cost=0.00001), "pricing_changed"),
        (lambda body: body["usage"].update(input_tokens=True), "invalid_usage"),
    ],
)
def test_run_accounting_stops(probe, mutation, reason):
    body = {
        "model": "typesafe/jev-1.13-20260917",
        "usage": {"input_tokens": 100, "output_tokens": 3, "cost": 0.0000042},
    }
    mutation(body)
    plan = probe.manifest()
    assert probe.check_response(body, plan, plan["requests"][0]) == reason


@pytest.mark.asyncio
async def test_live_harness_offline_isolated_and_bounded(probe, monkeypatch, tmp_path):
    from forge.core.paths import get_forge_home
    from forge.core.telemetry.downstream import read_downstream_records
    from forge.core.usage.ledger import read_usage_events

    previous_home = get_forge_home()
    before = {str(path): path.read_bytes() for path in previous_home.rglob("*") if path.is_file()}
    monkeypatch.setenv("FORGE_HOME", str(previous_home))
    # Register env cleanup for keys the standalone harness sets in its own process.
    for name in ("FORGE_RUN_ID", "FORGE_ROOT_RUN_ID", "FORGE_SESSION", "FORGE_PARENT_RUN_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    fixtures = Path(__file__).resolve().parents[2] / "fixtures" / "jev"
    bodies = [json.loads((fixtures / f"{label}.json").read_text()) for label, _, _ in probe.cases()]
    called = []

    def handler(request):
        called.append(request)
        body = bodies[len(called) - 1]
        assert json.loads(request.content) == probe.manifest()["requests"][len(called) - 1]["payload"]
        return httpx.Response(400 if len(called) == 4 else 200, json=body)

    monkeypatch.setattr(probe.httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(handler))
    output = tmp_path / "capture"
    assert await probe.run_live(probe.manifest(), output) == 0
    assert len(called) == 4
    assert get_forge_home() == output / "forge-home"
    assert len(read_downstream_records()) == len(read_usage_events()) == 4
    assert {str(path): path.read_bytes() for path in previous_home.rglob("*") if path.is_file()} == before
    record = json.loads((output / "capture.json").read_text())
    assert record["physical_requests"] == 4
    assert "synthetic-key" not in (output / "capture.json").read_text()


@pytest.mark.asyncio
async def test_manifest_mutation_refuses_before_credentials(probe, monkeypatch, tmp_path):
    plan = probe.manifest()
    plan["max_physical_requests"] += 1
    monkeypatch.setattr(probe.CredentialManager, "default", lambda: pytest.fail("No credentials allowed"))
    with pytest.raises(ValueError, match="Manifest differs"):
        await probe.run_live(plan, tmp_path / "capture")
