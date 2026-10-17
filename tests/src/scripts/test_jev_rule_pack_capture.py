"""Calibration capture preparation and every network boundary are exercised with fixture transports."""

import asyncio
import copy
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def capture(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "jev_rule_pack_capture", ROOT / "scripts/experiments/jev/rule-pack-capture.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    # Fixture dispatches have no relationship to the consumed production calibration proposals.
    monkeypatch.setattr(module, "CAPTURE_EVIDENCE", tmp_path / "retained-evidence")
    return module


def response_body(capture):
    return {
        "model": capture.EXPECTED_MODEL,
        "answers": {
            name: {"type": "noul", "noul": value}
            for name, value in (("coverage", 0.9), ("compatibility_retention", 0.9), ("independent_boundary", 0.1))
        },
        "usage": {"input_tokens": 100, "output_tokens": 3, "cost": 0.0000042},
    }


@pytest.fixture
def mock_credentials(capture, monkeypatch):
    calls = []

    class Credentials:
        async def get_credentials(self, provider):
            calls.append(provider)
            return {"base_url": "https://openrouter.ai/api/v1", "api_key": "synthetic-secret"}

    monkeypatch.setattr(capture.CredentialManager, "default", Credentials)
    return calls


def mock_transport(capture, monkeypatch, handler):
    def create(**kwargs):
        assert kwargs == {"retries": 0}
        return httpx.MockTransport(handler)

    monkeypatch.setattr(capture.httpx, "AsyncHTTPTransport", create)


def test_manifest_has_only_nine_adjudicated_calibration_payloads(capture, monkeypatch, capsys):
    monkeypatch.setattr(capture.CredentialManager, "default", lambda: pytest.fail("No credential access allowed"))
    monkeypatch.setattr(sys, "argv", ["rule-pack-capture.py"])
    assert capture.main() == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["proposal_id"].startswith("calibration-")
    assert {row["case_id"] for row in plan["requests"]} == capture.CALIBRATION_CASES
    assert len(plan["requests"]) == plan["max_physical_requests"] == 9
    assert plan["estimated_max_usd"] == pytest.approx(0.036288)
    assert plan["budget_usd"] == 0.05
    assert plan["deadline_seconds"] == 30
    assert plan["runtime_comparison_seconds"] == 5
    for row in plan["requests"]:
        assert row["payload"]["provider"] == {"zdr": True}
        assert len(row["payload"]["questions"]) == 3
        assert row["provenance"]["kind"] == "constructed"
        assert set(row["payload"]["state"]) == {"action", "scope_facts"}
        assert "basis" not in row["payload"]["state"]["scope_facts"]


@pytest.mark.parametrize(
    "change",
    [
        lambda plan: plan.update(max_physical_requests=10),
        lambda plan: plan.update(expected_model="other/model"),
        lambda plan: plan.update(split="held_out"),
        lambda plan: plan["requests"][0]["payload"]["provider"].update(zdr=False),
        lambda plan: plan["requests"][0]["payload"].update(state="different evidence"),
        lambda plan: plan["implementation_sha256"].update(unreviewed="0" * 64),
    ],
)
@pytest.mark.asyncio
async def test_modified_manifest_refuses_before_credentials(capture, monkeypatch, tmp_path, change):
    plan = capture.manifest()
    change(plan)
    monkeypatch.setattr(capture.CredentialManager, "default", lambda: pytest.fail("No credential access allowed"))
    with pytest.raises(ValueError, match="Manifest differs"):
        await capture.run_live(plan, tmp_path / "capture")
    assert not (tmp_path / "capture").exists()


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.asyncio
async def test_invalid_output_refuses_before_credentials(capture, monkeypatch, tmp_path, existing):
    output = tmp_path if existing else Path("relative-capture")
    monkeypatch.setattr(capture.CredentialManager, "default", lambda: pytest.fail("No credential access allowed"))
    with pytest.raises(ValueError, match="new absolute"):
        await capture.run_live(capture.manifest(), output)


@pytest.mark.asyncio
async def test_offline_live_path_isolates_restores_and_exports(capture, mock_credentials, monkeypatch, tmp_path):
    from forge.runtime_config import get_runtime_config, reset_runtime_config

    home = tmp_path / "original-home"
    home.mkdir()
    (home / "keep.txt").write_text("unchanged")
    monkeypatch.setenv("FORGE_HOME", str(home))
    monkeypatch.setenv("FORGE_SESSION", "private-session")
    monkeypatch.setenv("FORGE_RUN_ID", "prior-run")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "prior-root")
    monkeypatch.setenv("FORGE_PARENT_RUN_ID", "prior-parent")
    reset_runtime_config()
    get_runtime_config().provider_trace.inject_provider_user = True
    before_env = os.environ.copy()
    received = []
    plan = capture.manifest()

    def handler(request):
        index = len(received)
        received.append(request)
        assert json.loads(request.content) == plan["requests"][index]["payload"]
        assert request.url == capture.ENDPOINT
        assert request.headers["authorization"] == "Bearer synthetic-secret"
        assert os.environ["FORGE_HOME"] == str(tmp_path / "output/forge-home")
        assert "FORGE_SESSION" not in os.environ
        body = response_body(capture)
        body["extra"] = {"user_id": "private-account", "key_echo": "synthetic-secret"}
        if index == 0:
            body["usage"].pop("cost")
        return httpx.Response(200, json=body)

    mock_transport(capture, monkeypatch, handler)
    assert await capture.run_live(plan, tmp_path / "output") == 0
    assert mock_credentials == ["openrouter"]
    assert len(received) == 9
    assert os.environ == before_env
    assert (home / "keep.txt").read_text() == "unchanged"
    assert list(home.iterdir()) == [home / "keep.txt"]
    text = (tmp_path / "output/capture.json").read_text()
    assert "synthetic-secret" not in text
    assert "private-account" not in text
    record = json.loads(text)
    assert record["physical_requests"] == 9
    assert type(record["dirty"]) is bool
    assert all(row["dispatched"] and row["failure"] is None for row in record["attempts"])
    saved = capture.evaluator.SavedPredictions.model_validate_json((tmp_path / "output/predictions.json").read_text())
    assert len(saved.predictions) == 9
    assert saved.predictions[0].response["usage"].get("cost") is None
    assert all(row.response_bytes > 0 and row.status_code == 200 for row in saved.predictions)
    assert record["run_id"] != "prior-run"
    request_ids = {request.headers["X-Request-ID"] for request in received}
    assert len(request_ids) == 9
    assert {row["request_id"] for row in record["attempts"]} == request_ids
    downstream = [
        json.loads(line)
        for path in (tmp_path / "output/forge-home/telemetry/downstream").glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert {row["request_id"] for row in downstream} == request_ids
    assert all(row["forge_run_id"] == record["run_id"] for row in downstream)


@pytest.mark.parametrize(
    "change,reason",
    [
        (lambda body: body.update(model="other/model"), "model_changed"),
        (lambda body: body["usage"].update(cost=1), "unexpected_cost"),
        (lambda body: body["usage"].update(cost=0.00005), "pricing_changed"),
        (lambda body: body["usage"].update(input_tokens=96_001, cost=None), "input_token_bound_exceeded"),
        (lambda body: body["answers"].pop("coverage"), "invalid_response"),
    ],
)
@pytest.mark.asyncio
async def test_first_failed_response_stops_and_retains_evidence(
    capture, mock_credentials, monkeypatch, tmp_path, change, reason
):
    calls = []
    body = response_body(capture)
    change(body)

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    mock_transport(capture, monkeypatch, handler)
    output = tmp_path / "capture"
    assert await capture.run_live(capture.manifest(), output) == 1
    assert len(calls) == 1
    journal = json.loads((output / "capture.json").read_text())
    saved = json.loads((output / "predictions.json").read_text())
    assert journal["physical_requests"] == 1
    assert journal["attempts"][0]["failure"] == reason
    assert saved["predictions"][0]["failure"] == reason
    assert saved["predictions"][0]["response"] is None
    assert journal["attempts"][0]["body"] == body


@pytest.mark.parametrize("status", [401, 429, 524, 529])
@pytest.mark.asyncio
async def test_http_failure_never_retries(capture, mock_credentials, monkeypatch, tmp_path, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "synthetic failure"}})

    mock_transport(capture, monkeypatch, handler)
    output = tmp_path / "capture"
    assert await capture.run_live(capture.manifest(), output) == 1
    assert len(calls) == 1
    row = json.loads((output / "predictions.json").read_text())["predictions"][0]
    assert row["status_code"] == status
    assert row["response_bytes"] > 0
    assert row["failure"]


@pytest.mark.parametrize("extra", ["NaN", "Infinity", "1e400", '"\\ud800"'])
@pytest.mark.asyncio
async def test_nonfinite_and_surrogate_extras_are_saved_as_failures(
    capture, mock_credentials, monkeypatch, tmp_path, extra
):
    body = json.dumps(response_body(capture))[:-1] + ', "provider_extra": ' + extra + "}"
    mock_transport(capture, monkeypatch, lambda request: httpx.Response(200, content=body.encode()))
    output = tmp_path / "capture"
    assert await capture.run_live(capture.manifest(), output) == 1
    saved = capture.evaluator.SavedPredictions.model_validate_json((output / "predictions.json").read_text())
    assert saved.predictions[0].failure == "invalid_json_response"
    assert saved.predictions[0].response is None
    journal = capture.read_json(output / "capture.json")
    assert journal["attempts"][0]["response_bytes"] == len(body.encode())


@pytest.mark.asyncio
async def test_oversized_body_is_bounded_and_retained(capture, mock_credentials, monkeypatch, tmp_path):
    raw = b"x" * (capture.MAX_RESPONSE_BYTES + 40_000)
    mock_transport(capture, monkeypatch, lambda request: httpx.Response(200, content=raw))
    output = tmp_path / "capture"
    assert await capture.run_live(capture.manifest(), output) == 1
    record = json.loads((output / "capture.json").read_text())
    row = record["attempts"][0]
    assert row["response_truncated"] is True
    assert row["response_bytes"] == len(raw)
    assert row["response_body_redacted"] == capture.WITHHELD_RESPONSE
    assert row["failure"] == "transport"
    assert len(record["attempts"]) == 1


@pytest.mark.asyncio
async def test_interruption_persists_ambiguous_dispatch_and_restores_home(
    capture, mock_credentials, monkeypatch, tmp_path
):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "original"))
    output = tmp_path / "capture"

    def handler(request):
        journal = json.loads((output / "capture.json").read_text())
        assert journal["physical_requests"] == 1
        assert journal["attempts"][0]["dispatched"] is True
        raise asyncio.CancelledError()

    mock_transport(capture, monkeypatch, handler)
    with pytest.raises(asyncio.CancelledError):
        await capture.run_live(capture.manifest(), output)
    assert os.environ["FORGE_HOME"] == str(tmp_path / "original")
    saved = json.loads((output / "predictions.json").read_text())
    assert saved["predictions"][0]["failure"] == "interrupted"


@pytest.mark.parametrize("change", ["cap", "endpoint", "payload"])
@pytest.mark.asyncio
async def test_transport_blocks_unapproved_wire_requests(capture, tmp_path, change):
    plan = capture.manifest()
    journal = {"manifest": plan, "physical_requests": 0, "attempts": [{"failure": "interrupted"}]}
    transport = capture.CaptureTransport(
        httpx.MockTransport(lambda request: pytest.fail("No dispatch allowed")), journal, lambda: None, "synthetic-key"
    )
    payload = copy.deepcopy(plan["requests"][0]["payload"])
    endpoint = capture.ENDPOINT
    if change == "cap":
        journal["physical_requests"] = 9
    elif change == "endpoint":
        endpoint = "https://example.invalid/api/alpha/decisions"
    else:
        payload["provider"]["zdr"] = False
    with pytest.raises(httpx.TransportError):
        await transport.handle_async_request(httpx.Request("POST", endpoint, content=capture.encode_payload(payload)))


@pytest.mark.parametrize(
    "args", [["--manifest", "x"], ["--output", "/tmp/x"], ["--live"], ["--live", "--manifest", "x"]]
)
def test_cli_requires_explicit_complete_live_selection(capture, monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["rule-pack-capture.py", *args])
    with pytest.raises(SystemExit) as error:
        capture.main()
    assert error.value.code == 2


def test_explicit_proposal_id_is_preparation_only(capture, monkeypatch, capsys):
    monkeypatch.setattr(capture.CredentialManager, "default", lambda: pytest.fail("No credential access allowed"))
    monkeypatch.setattr(sys, "argv", ["rule-pack-capture.py", "--proposal-id", "reviewed-repeat-2"])
    assert capture.main() == 0
    assert json.loads(capsys.readouterr().out)["proposal_id"] == "reviewed-repeat-2"
    monkeypatch.setattr(
        sys,
        "argv",
        ["rule-pack-capture.py", "--live", "--manifest", "x", "--output", "/tmp/x", "--proposal-id", "override"],
    )
    with pytest.raises(SystemExit) as error:
        capture.main()
    assert error.value.code == 2
    assert "preparation-only" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "has spaces", "A", "../escape", "x" * 81, None, 17])
def test_invalid_proposal_id_refuses(capture, value):
    with pytest.raises(ValueError, match="proposal_id must contain"):
        capture.proposal_identity({"proposal_id": value})


@pytest.mark.parametrize("status,dirty", [("", False), (" M scripts/experiments/jev/rule-pack-capture.py\n", True)])
@pytest.mark.asyncio
async def test_journal_records_checkout_dirtiness(capture, mock_credentials, monkeypatch, tmp_path, status, dirty):
    def git_metadata(args, **kwargs):
        assert kwargs == {"cwd": ROOT, "check": True, "capture_output": True, "text": True}
        return SimpleNamespace(stdout="fixture-revision\n" if args == ["git", "rev-parse", "HEAD"] else status)

    monkeypatch.setattr(capture.subprocess, "run", git_metadata)
    mock_transport(capture, monkeypatch, lambda request: httpx.Response(401, json={"error": "synthetic"}))
    output = tmp_path / "output"
    assert await capture.run_live(capture.manifest(), output) == 1
    journal = capture.read_json(output / "capture.json")
    assert journal["dirty"] is dirty
    assert journal["revision"] == "fixture-revision"
    assert journal["implementation_sha256"] == capture.implementation_hashes()


def test_redaction_handles_escaped_keys_secrets_and_numeric_accounts(capture):
    text = r'{"us\u0065r_id": "account-7", "nested": {"account_id": 12345}, "echo": "synthetic\u002dsecret"}'
    sanitized = json.loads(capture.redact(text, "synthetic-secret"))
    assert sanitized == {"user_id": "[REDACTED]", "nested": {"account_id": "[REDACTED]"}, "echo": "[REDACTED]"}


@pytest.mark.parametrize("value", [123.5, -123, None, True, ["private-account"], {"id": "private-account"}])
def test_redaction_replaces_complete_sensitive_values(capture, value):
    text = json.dumps({"nested": [{"ACCOUNT_ID": value}], "usage": {"cost": 0.0042}})
    assert json.loads(capture.redact(text, "synthetic-secret")) == {
        "nested": [{"ACCOUNT_ID": "[REDACTED]"}],
        "usage": {"cost": 0.0042},
    }


@pytest.mark.parametrize(
    "text",
    [
        '{"account_id": "private-account"',
        "upstream error: user_id=private-account key=synthetic-secret",
        '{"account_id": "first", "account_id": "second"}',
        '{"account_id": NaN}',
        r'{"account_id": "\ud800"}',
    ],
)
def test_redaction_withholds_malformed_or_nonfinite_bodies(capture, text):
    assert capture.redact(text, "synthetic-secret") == capture.WITHHELD_RESPONSE


@pytest.mark.asyncio
async def test_undispatched_failure_stays_in_journal_without_saved_observation(
    capture, mock_credentials, monkeypatch, tmp_path
):
    async def refuse(*args, **kwargs):
        raise capture.JudgmentError("validation", "Synthetic pre-dispatch refusal")

    monkeypatch.setattr(capture.OpenRouterJudgmentClient, "judge", refuse)
    mock_transport(capture, monkeypatch, lambda request: pytest.fail("No dispatch allowed"))
    output = tmp_path / "capture"
    assert await capture.run_live(capture.manifest(), output) == 1
    journal = json.loads((output / "capture.json").read_text())
    assert journal["physical_requests"] == 0
    assert len(journal["attempts"]) == 1
    assert journal["attempts"][0]["failure"] == "validation"
    assert journal["attempts"][0]["dispatched"] is False
    assert "request_id" not in journal["attempts"][0]
    saved = capture.evaluator.SavedPredictions.model_validate_json((output / "predictions.json").read_text())
    assert saved.predictions == []


@pytest.mark.asyncio
async def test_timeout_is_ambiguous_and_not_retried(capture, mock_credentials, monkeypatch, tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    mock_transport(capture, monkeypatch, handler)
    output = tmp_path / "capture"
    assert await capture.run_live(capture.manifest(), output) == 1
    saved = capture.evaluator.SavedPredictions.model_validate_json((output / "predictions.json").read_text())
    assert len(calls) == len(saved.predictions) == 1
    assert saved.predictions[0].failure == "ambiguous_timeout"
    assert saved.predictions[0].response_bytes is None


@pytest.mark.asyncio
async def test_malformed_and_duplicate_key_bodies_stop(capture, mock_credentials, monkeypatch, tmp_path):
    raw = json.dumps(response_body(capture))[:-1] + ', "model": "other/model"}'
    mock_transport(capture, monkeypatch, lambda request: httpx.Response(200, content=raw))
    output = tmp_path / "capture"
    assert await capture.run_live(capture.manifest(), output) == 1
    saved = capture.evaluator.SavedPredictions.model_validate_json((output / "predictions.json").read_text())
    assert saved.predictions[0].failure == "invalid_json_response"
    assert saved.predictions[0].response_bytes == len(raw)
