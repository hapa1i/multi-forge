"""Stage 60: the paid probe discarded the Qwen 404's structured routing reason."""

import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.regression

# Reconstructed wire bytes match the SHA-256 recorded for the November 19 Qwen baseline.
QWEN_404 = (
    b'{"error":{"message":"0 endpoints out of 1 requested are available matching your guardrail restrictions and data '
    b"policy. We removed them for the following reasons (an endpoint may have matched multiple reasons):\\n"
    b'ZDR violation (account settings): 1 endpoint excluded; configurable at https://openrouter.ai/settings/privacy",'
    b'"code":404,'
    b'"metadata":{"input_endpoint_count":1,"ineligibility_reasons":[{"reason":"zdr-violation-by-account",'
    b'"endpoint_count":1,"configure_url":"https://openrouter.ai/settings/privacy"}],'
    b'"routing_funnel":[{"step":"Initial Endpoints","endpoint_count":1}],'
    b'"failed_routing_step":"Filter by Guardrails"}}}'
)
ACCOUNT_REASON = "zdr-violation-by-account"
REQUEST_REASON = "zdr-violation-by-request"
PRIVACY_URL = "https://openrouter.ai/settings/privacy"


def test_responses_route_translates_exact_account_refusal():
    from forge.proxy.openrouter_responses import zdr_refusal

    response = zdr_refusal(404, QWEN_404, "qwen/qwen4-max", "req-account")
    assert response.status_code == 400
    message = json.loads(response.body)["error"]["message"]
    assert "account ZDR" in message and "qwen/qwen4-max" in message and PRIVACY_URL in message


@pytest.fixture(autouse=True)
def probe_path(monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).resolve().parents[2] / "scripts/experiments/openrouter/helpers")


def diagnose(raw):
    provider_diagnostic = importlib.import_module("paid_diagnostics").provider_diagnostic
    return provider_diagnostic(404, {"content-type": "application/json"}, raw, None, "")


def test_exact_qwen_404_preserves_the_account_reason():
    expected_digest = "6ae1793c7b1c43899a5569ce8adf967485e631f164e20024034e64e9a1e623ab"
    assert len(QWEN_404) == 625
    assert hashlib.sha256(QWEN_404).hexdigest() == expected_digest

    error = diagnose(QWEN_404)
    assert error["sha256"] == expected_digest
    assert error["ineligibility_reasons"] == [
        {"reason": ACCOUNT_REASON, "endpoint_count": 1, "configure_url": PRIVACY_URL}
    ]


def test_private_metadata_and_malformed_fields_stay_out_of_receipts():
    error = json.loads(QWEN_404)["error"]
    error["metadata"]["ineligibility_reasons"] = [
        {"reason": ACCOUNT_REASON, "endpoint_count": True, "configure_url": PRIVACY_URL + "?private-token"},
        {"reason": "private-guardrail-name", "endpoint_count": 1},
        {"reason": {"private-stack": 1}},
        "private-remark",
    ]

    diagnostic = diagnose(json.dumps({"error": error}).encode())
    assert diagnostic["ineligibility_reasons"] == [{"reason": ACCOUNT_REASON}]
    assert diagnostic["ineligibility_reasons_omitted"] == 3
    assert "private" not in json.dumps(diagnostic)


@pytest.mark.parametrize(
    ("message", "metadata"),
    [
        ("No endpoints found matching your data policy", {}),
        ("No endpoints available due to account-level ZDR", {}),
        ("No ZDR endpoints", {"ineligibility_reasons": {"reason": ACCOUNT_REASON}}),
    ],
)
def test_ambiguous_or_malformed_routing_errors_cannot_prove_request_zdr(message, metadata):
    wire = json.dumps({"error": {"code": 404, "message": message, "metadata": metadata}}).encode()
    assert not importlib.import_module("paid_probe").is_zdr_refusal(diagnose(wire))


@pytest.mark.parametrize(
    ("synthetic_reasons", "passes"),
    [
        (None, False),
        ([REQUEST_REASON], True),
        ([REQUEST_REASON, ACCOUNT_REASON], False),
        ([REQUEST_REASON, "unknown-private-guardrail"], False),
    ],
)
def test_stage_only_accepts_request_zdr_after_completed_baseline(synthetic_reasons, passes):
    refusal = QWEN_404
    if synthetic_reasons is not None:
        error = json.loads(QWEN_404)["error"]
        error["message"] = error["message"].splitlines()[0]
        error["metadata"]["ineligibility_reasons"] = [{"reason": r, "endpoint_count": 1} for r in synthetic_reasons]
        refusal = json.dumps({"error": error}).encode()

    stage_zdr = importlib.import_module("paid_probe").stage_zdr
    api = stage_api(refusal)
    evidence = {}
    if passes:
        stage_zdr(api, evidence)
        assert evidence["positive"]["response"]["status"] == "completed"
    else:
        with pytest.raises(ValueError, match="ZDR policy denial"):
            stage_zdr(api, evidence)
        assert "positive" not in evidence
    assert evidence["baseline"]["response"]["status"] == "completed"


def test_qwen_baseline_404_records_the_reason_and_stops():
    stage_zdr = importlib.import_module("paid_probe").stage_zdr
    api = stage_api(QWEN_404, fail_baseline=True)
    evidence = {}
    with pytest.raises(ValueError, match="Responses request returned HTTP 404"):
        stage_zdr(api, evidence)

    baseline = evidence["baseline"]
    assert baseline["http"] == 404
    assert baseline["error"]["ineligibility_reasons"] == [
        {"reason": ACCOUNT_REASON, "endpoint_count": 1, "configure_url": PRIVACY_URL}
    ]
    assert [(call["model"], call["zdr"]) for call in api.observations] == [("qwen/qwen4-max", None)]
    assert "refusal" not in evidence and "positive" not in evidence


@pytest.fixture
def account_manifest_path():
    board = Path(__file__).resolve().parents[2] / "docs/board"
    return next(board.glob("*/codex_openrouter_responses/paid-probe-manifest-qwen-account-zdr.json"))


@pytest.fixture
def account_manifest(account_manifest_path):
    return json.loads(account_manifest_path.read_bytes())


@pytest.mark.parametrize("digest", ["sha256", "body_sha256"])
def test_account_stage_requires_the_original_baseline_before_sending(account_manifest, account_manifest_path, digest):
    api = SimpleNamespace(manifest=account_manifest, request=lambda *_: pytest.fail("Unexpected upstream request"))
    account_manifest["zdr_control"]["baseline"][digest] = "0" * 64
    with pytest.raises(ValueError):
        importlib.import_module("paid_probe").stage_zdr(api, {}, manifest_dir=account_manifest_path.parent)


def test_account_stage_accepts_the_same_manifest_and_receipt_in_another_directory(account_manifest_path, tmp_path):
    relocated = tmp_path / account_manifest_path.name
    relocated.write_bytes(account_manifest_path.read_bytes())
    manifest = json.loads(relocated.read_bytes())
    receipt = Path(manifest["zdr_control"]["baseline"]["path"])
    (relocated.parent / receipt).parent.mkdir(parents=True)
    (relocated.parent / receipt).write_bytes((account_manifest_path.parent / receipt).read_bytes())

    api = stage_api(QWEN_404)
    api.manifest = manifest
    evidence = {}
    importlib.import_module("paid_probe").stage_zdr(api, evidence, manifest_dir=relocated.parent)
    assert evidence["historical_baseline"]["path"] == str(receipt)
    assert evidence["positive"]["response"]["status"] == "completed"


@pytest.mark.parametrize("path", ["../outside.json", "/outside.json"])
def test_account_stage_rejects_baseline_outside_the_manifest_directory(account_manifest, account_manifest_path, path):
    api = SimpleNamespace(manifest=account_manifest, request=lambda *_: pytest.fail("Unexpected upstream request"))
    account_manifest["zdr_control"]["baseline"]["path"] = path
    with pytest.raises(ValueError):
        importlib.import_module("paid_probe").stage_zdr(api, {}, manifest_dir=account_manifest_path.parent)


def test_account_stage_requires_a_model_id_on_every_catalog_row(account_manifest, account_manifest_path):
    operations = []

    def request(operation, body=None):
        operations.append(operation)
        assert operation == "endpoints/zdr"
        return 200, {}, b'{"data":[{"model_id":"openai/gpt-6.2-astra"},{"provider":"Alibaba"}]}'

    api = SimpleNamespace(manifest=account_manifest, request=request)
    with pytest.raises(ValueError, match="ZDR catalog"):
        importlib.import_module("paid_probe").stage_zdr(api, {}, manifest_dir=account_manifest_path.parent)
    assert operations == ["endpoints/zdr"]


def test_single_stage_manifest_requires_an_explicit_account_criterion(account_manifest):
    del account_manifest["zdr_control"]["criterion"]
    with pytest.raises(ValueError):
        importlib.import_module("paid_guard").validate_manifest(account_manifest)


@pytest.mark.parametrize("provider", [None, {"zdr": False}, {"zdr": 1}])
def test_account_transport_rejects_unflagged_generations_before_reserving(account_manifest, provider):
    guard = importlib.import_module("paid_guard")
    ledger = SimpleNamespace(reserve=lambda *_: pytest.fail("Unexpected paid reservation"))
    api = guard.Upstream(account_manifest, ledger, "zdr", float("inf"), "dummy")
    body = {"model": "qwen/qwen4-max"}
    if provider is not None:
        body["provider"] = provider
    with pytest.raises(ValueError, match="provider.zdr=true"):
        api.request("responses", body)


@pytest.mark.parametrize("stage", ["cost", "codex"])
def test_account_approval_cannot_open_a_later_stage(account_manifest, stage, tmp_path, monkeypatch):
    probe = importlib.import_module("paid_probe")
    manifest_path = tmp_path / "manifest.json"
    raw = json.dumps(account_manifest).encode()
    manifest_path.write_bytes(raw)
    monkeypatch.setenv("OPENROUTER_RESPONSES_MANIFEST", str(manifest_path))
    monkeypatch.setenv("OPENROUTER_RESPONSES_APPROVED_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv("OPENROUTER_PROBE_API_KEY", "dummy")
    monkeypatch.setattr("sys.argv", ["paid_probe.py", stage])
    monkeypatch.setattr(probe, "LEDGER_ROOT", str(tmp_path / "ledger"))
    monkeypatch.setattr(probe, "Upstream", lambda *_: pytest.fail("Unexpected upstream transport"))
    with pytest.raises(ValueError):
        probe.main()
    assert not (tmp_path / "ledger").exists()


@pytest.mark.parametrize(
    ("status", "reasons"),
    [
        (200, [ACCOUNT_REASON]),
        (502, [ACCOUNT_REASON]),
        (404, []),
        (404, ["model-ignored-by-guardrail"]),
        (404, [ACCOUNT_REASON, "model-ignored-by-guardrail"]),
        (404, [ACCOUNT_REASON, "private-name"]),
    ],
)
def test_account_stage_stops_on_served_or_inconclusive_qwen(account_manifest, account_manifest_path, status, reasons):
    error = json.loads(QWEN_404)["error"]
    error["metadata"]["ineligibility_reasons"] = [{"reason": reason, "endpoint_count": 1} for reason in reasons]
    api = stage_api(json.dumps({"error": error}).encode(), refusal_status=status)
    api.manifest = account_manifest
    evidence = {}
    with pytest.raises(ValueError):
        importlib.import_module("paid_probe").stage_zdr(api, evidence, manifest_dir=account_manifest_path.parent)
    assert [(call["model"], call["zdr"]) for call in api.observations] == [("qwen/qwen4-max", True)]
    assert evidence["refusal"]["http"] == status
    assert "positive" not in evidence


def test_account_stage_requires_a_completed_text_positive(account_manifest, account_manifest_path):
    api = stage_api(QWEN_404, success_body=b'{"status":"completed","output":[]}')
    api.manifest = account_manifest
    evidence = {}
    with pytest.raises(ValueError, match="completed text"):
        importlib.import_module("paid_probe").stage_zdr(api, evidence, manifest_dir=account_manifest_path.parent)
    assert [(call["model"], call["zdr"]) for call in api.observations] == [
        ("qwen/qwen4-max", True),
        ("openai/gpt-6.2-astra", True),
    ]
    assert evidence["independent_request_zdr"] == "unverified"
    assert "baseline" not in evidence


@pytest.fixture
def continuation_manifest(account_manifest_path):
    return json.loads(account_manifest_path.with_name("paid-probe-manifest-astra-positive.json").read_bytes())


def test_positive_continuation_uses_the_accepted_refusal_without_repeating_qwen(
    continuation_manifest, account_manifest_path
):
    api = stage_api(QWEN_404)
    api.manifest = continuation_manifest
    evidence = {}
    importlib.import_module("paid_probe").stage_zdr(api, evidence, manifest_dir=account_manifest_path.parent)
    assert api.observations == [{"model": "openai/gpt-6.2-astra", "zdr": True}]
    pin = continuation_manifest["zdr_control"]["accepted_refusal"]
    receipt = account_manifest_path.parent / pin["path"]
    assert receipt.parent.name == "paid-2feeec7f"
    assert evidence["accepted_refusal"] == {
        "path": pin["path"],
        "receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "body_sha256": "1c77a1dda340b6aef7f83c07465f232af64cfaea2f3b4270fd269add4a499eca",
        "http": 404,
        "model": "qwen/qwen4-max",
        "message": "No endpoints found matching your data policy (Zero data retention). Configure: " + PRIVACY_URL,
        "manifest_sha256": "2feeec7f089df57f2927735a7f36d0e5244bb4afb4844971c0924f641a2e0163",
    }
    assert evidence["criterion"] == "account_zdr_accepted_refusal"
    assert evidence["historical_baseline"]["reason"] == ACCOUNT_REASON
    assert evidence["positive"]["response"]["status"] == "completed"
    assert evidence["independent_request_zdr"] == "unverified"
    assert "baseline" not in evidence and "refusal" not in evidence


@pytest.mark.parametrize("digest", ["sha256", "body_sha256"])
def test_positive_continuation_checks_the_accepted_refusal_pin_before_requests(
    continuation_manifest, account_manifest_path, digest
):
    continuation_manifest["zdr_control"]["accepted_refusal"][digest] = "0" * 64
    api = SimpleNamespace(manifest=continuation_manifest, request=lambda *_: pytest.fail("Unexpected request"))
    with pytest.raises(ValueError):
        importlib.import_module("paid_probe").stage_zdr(api, {}, manifest_dir=account_manifest_path.parent)


def test_positive_continuation_requires_the_original_manifest(continuation_manifest):
    continuation_manifest["continues_manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        importlib.import_module("paid_guard").validate_manifest(continuation_manifest)


@pytest.mark.parametrize(
    ("changes", "metadata"),
    [
        ({"model": "qwen/qwen4-max"}, False),
        ({"models": ["openai/gpt-6.2-astra", "qwen/qwen4-max"]}, False),
        ({}, True),
    ],
    ids=["qwen", "fallback-models", "extra-metadata-header"],
)
def test_positive_continuation_transport_rejects_another_control_before_reserving(
    continuation_manifest, changes, metadata
):
    ledger = SimpleNamespace(reserve=lambda *_: pytest.fail("Unexpected paid reservation"))
    api = importlib.import_module("paid_guard").Upstream(continuation_manifest, ledger, "zdr", float("inf"), "dummy")
    body = importlib.import_module("paid_probe").tiny("openai/gpt-6.2-astra")
    body["provider"] = {"zdr": True}
    body.update(changes)
    with pytest.raises(ValueError):
        api.request("responses", body, metadata=metadata)


@pytest.mark.parametrize(("status", "text"), [("completed", "  \n"), ("incomplete", "OK")])
def test_positive_continuation_requires_completed_nonblank_text(
    continuation_manifest, account_manifest_path, status, text
):
    message = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}
    body = json.dumps({"status": status, "output": [message]}).encode()
    api = stage_api(QWEN_404, success_body=body)
    api.manifest = continuation_manifest
    with pytest.raises(ValueError, match="completed text"):
        importlib.import_module("paid_probe").stage_zdr(api, {}, manifest_dir=account_manifest_path.parent)
    assert api.observations == [{"model": "openai/gpt-6.2-astra", "zdr": True}]


def stage_api(refusal, *, fail_baseline=False, refusal_status=404, success_body=None):
    models = {"default": "openai/gpt-6.2-astra", "non_zdr": "qwen/qwen4-max"}
    observed = []
    ok = (
        b'{"status":"completed","output":[{"role":"assistant","type":"message",'
        b'"content":[{"type":"output_text","text":"OK"}]}]}'
    )

    def request(operation, body=None):
        if operation == "endpoints/zdr":
            return 200, {}, json.dumps({"data": [{"model_id": models["default"]}]}).encode()
        assert operation == "responses"
        call = {"model": body["model"], "zdr": body.get("provider", {}).get("zdr")}
        observed.append(call)
        if body["model"] == models["non_zdr"] and (fail_baseline or call["zdr"]):
            if refusal_status == 200:
                return 200, {}, ok
            call["error"] = diagnose(refusal)
            return refusal_status, {}, refusal
        return 200, {}, ok if success_body is None else success_body

    return SimpleNamespace(manifest={"models": models}, observations=observed, request=request)
