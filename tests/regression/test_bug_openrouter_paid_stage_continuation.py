"""Paid continuations bind prior receipts, key limits and the remaining stages."""

import hashlib
import importlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.regression


@pytest.fixture
def manifest(monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(repo / "scripts/experiments/openrouter/helpers")
    manifest_path = next((repo / "docs/board").glob("*/codex_openrouter_responses/paid-probe-manifest-cost-codex.json"))
    return json.loads(manifest_path.read_bytes()), manifest_path.parent


def test_move_to_done_preserves_pinned_replays_and_receipt_paths(manifest, tmp_path, monkeypatch):
    _, origin = manifest
    codex = importlib.import_module("paid_codex")
    monkeypatch.setattr(codex, "REPO", tmp_path)
    card = tmp_path / "docs/board/doing" / origin.name
    shutil.copytree(origin, card)
    archived = tmp_path / "docs/board/done" / origin.name
    archived.parent.mkdir()
    card.rename(archived)
    binary = tmp_path / "dummy-codex"
    binary.write_bytes(b"offline binary identity fixture")
    manifests = []
    for source in archived.glob("paid-probe-manifest*.json"):
        assert source.read_bytes() == (origin / source.name).read_bytes()
        parsed = json.loads(source.read_bytes())
        if not parsed.get("replay_fixtures"):
            continue
        manifests.append(source.name)
        parsed["binary"]["sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        checked = codex.check_inputs(parsed, archived, binary)
        assert [spec for spec, _ in checked] == parsed["replay_fixtures"]
    assert len(manifests) == 4

    index = json.loads((archived / "evidence/fixture-index.json").read_bytes())
    receipt = json.loads((archived / "evidence/paid-63d4a6f0/codex.json").read_bytes())
    for spec in [*index["replay_fixtures"], *index["offline_fixtures"], *(r["fixture"] for r in receipt["replays"])]:
        original = origin / "evidence/fixtures" / Path(spec["path"]).name
        assert codex.read_fixture(spec, archived) == json.loads(original.read_bytes())

    pin = index["replay_fixtures"][0]
    moved_fixture = archived / "evidence/fixtures" / Path(pin["path"]).name
    moved_fixture.write_bytes(moved_fixture.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum"):
        codex.read_fixture(pin, archived)
    moved_fixture.unlink()
    moved_fixture.symlink_to(origin / "evidence/fixtures" / moved_fixture.name)
    with pytest.raises(ValueError, match="escapes"):
        codex.read_fixture(pin, archived)


@pytest.mark.parametrize("stage", ["cost", "codex"])
def test_changed_prerequisite_stops_before_ledger_and_transport(manifest, stage, monkeypatch, tmp_path):
    parsed, origin = manifest
    relative = Path(parsed["prerequisite"]["path"])
    receipt = tmp_path / relative
    receipt.parent.mkdir(parents=True)
    receipt.write_bytes((origin / relative).read_bytes() + b"\n")
    manifest_path = tmp_path / "approval.json"
    raw = json.dumps(parsed).encode()
    manifest_path.write_bytes(raw)
    monkeypatch.setenv("OPENROUTER_RESPONSES_MANIFEST", str(manifest_path))
    monkeypatch.setenv("OPENROUTER_RESPONSES_APPROVED_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv("OPENROUTER_PROBE_API_KEY", "dummy")
    monkeypatch.setattr("sys.argv", ["paid_probe.py", stage])
    probe = importlib.import_module("paid_probe")
    monkeypatch.setattr(probe, "LEDGER_ROOT", str(tmp_path / "ledger"))
    monkeypatch.setattr(probe, "Upstream", lambda *_: pytest.fail("Unexpected upstream transport"))
    with pytest.raises(ValueError, match="(?i)(sha-?256|digest|checksum|pin)"):
        probe.main()
    assert not (tmp_path / "ledger").exists()


def test_cost_must_pass_before_codex_with_the_same_key(manifest, tmp_path):
    parsed, _ = manifest
    ledger = importlib.import_module("paid_guard").Ledger(tmp_path, parsed["limits"])
    with pytest.raises(ValueError):
        ledger.begin("zdr", key="dummy")
    with pytest.raises(ValueError):
        ledger.begin("codex", key="dummy")
    ledger.begin("cost", key="dummy")
    with pytest.raises(ValueError):
        ledger.begin("codex", key="dummy")
    ledger.finish("cost", "passed")
    with pytest.raises(ValueError):
        ledger.begin("codex", key="another-key")
    ledger.begin("codex", key="dummy")
    state = json.loads((tmp_path / "state.json").read_bytes())
    assert state["stages"] == {"cost": "passed", "codex": "running"}
    assert "dummy" not in json.dumps(state)


@pytest.mark.parametrize(
    ("stage", "operation", "body"),
    [
        ("zdr", "key", None),
        ("cost", "endpoints/zdr", None),
        ("cost", "generation", None),
        ("cost", "responses", {"model": "openai/gpt-6.2-astra"}),
        ("cost", "responses", {"model": "google/gemini-4-carbon", "provider": {"zdr": True}}),
        ("codex", "chat/completions", {"model": "openai/gpt-6.2-astra"}),
        ("codex", "generation", None),
    ],
)
def test_unapproved_requests_stop_before_reservation(manifest, stage, operation, body):
    parsed, _ = manifest
    ledger = SimpleNamespace(reserve=lambda *_: pytest.fail("Unexpected paid reservation"))
    api = importlib.import_module("paid_guard").Upstream(parsed, ledger, stage, float("inf"), "dummy")
    with pytest.raises(ValueError):
        api.request(operation, body, remote_id="unobserved")


@pytest.mark.parametrize(
    ("stage", "kind", "operation", "limit"),
    [
        ("cost", "generation", "responses", 5),
        ("cost", "metadata", "key", 16),
        ("codex", "generation", "responses", 40),
        ("codex", "metadata", "key", 1),
    ],
)
def test_attempts_cannot_exceed_each_stage_limit(manifest, stage, kind, operation, limit, tmp_path, monkeypatch):
    parsed, _ = manifest
    guard = importlib.import_module("paid_guard")
    guard.validate_manifest(parsed)
    assert parsed["limits"]["generation_attempts"] == 45
    assert parsed["limits"]["metadata_attempts"] == 17
    ledger = guard.Ledger(tmp_path, parsed["limits"])
    if stage == "codex":
        ledger.begin("cost", key="dummy")
        ledger.finish("cost", "passed")
    api = guard.Upstream(parsed, ledger, stage, ledger.begin(stage, key="dummy"), "dummy")
    for _ in range(limit):
        ledger.reserve(stage, kind, operation)
    body = (
        dict(guard.tiny("openai/gpt-6.2-astra"), stream=False, provider={"zdr": True}) if kind == "generation" else None
    )
    monkeypatch.setattr(api, "_connect", lambda *_: pytest.fail("Unexpected network dispatch"))
    with pytest.raises(ValueError, match="budget exhausted before dispatch"):
        api.request(operation, body)
    assert len(json.loads((tmp_path / "state.json").read_bytes())["attempts"]) == limit


@pytest.fixture
def codex_only(manifest):
    _, card = manifest
    path = card / "paid-probe-manifest-codex-only.json"
    return path, json.loads(path.read_bytes())


@pytest.mark.parametrize("changed", ["zdr", "cost", "codex"])
def test_standalone_checks_all_pinned_receipts_before_key_read(codex_only, changed, monkeypatch, tmp_path):
    path, spec = codex_only
    raw = path.read_bytes()
    (tmp_path / path.name).write_bytes(raw)
    cost = json.loads((path.parent / spec["prerequisite"]["path"]).read_bytes())
    for pin in (cost["prerequisite"], spec["prerequisite"], spec["previous_attempt"]):
        copy = tmp_path / pin["path"]
        copy.parent.mkdir(parents=True, exist_ok=True)
        data = (path.parent / pin["path"]).read_bytes()
        copy.write_bytes(data + b"\n" if pin["stage"] == changed else data)
    monkeypatch.setenv("OPENROUTER_RESPONSES_MANIFEST", str(tmp_path / path.name))
    monkeypatch.setenv("OPENROUTER_RESPONSES_APPROVED_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv("OPENROUTER_PROBE_API_KEY", "dummy")
    probe = importlib.import_module("paid_probe")
    monkeypatch.setattr(probe, "LEDGER_ROOT", str(tmp_path / "ledger"))
    monkeypatch.setattr(probe, "Upstream", lambda *_: pytest.fail("Unexpected upstream transport"))
    with pytest.raises(ValueError, match="receipt SHA-256"):
        probe.run_stage("codex")
    assert not (tmp_path / "ledger").exists()


def test_previous_approval_cannot_start_the_higher_cap_run(codex_only, monkeypatch):
    path, spec = codex_only
    monkeypatch.setenv("OPENROUTER_RESPONSES_MANIFEST", str(path))
    monkeypatch.setenv("OPENROUTER_RESPONSES_APPROVED_SHA256", spec["prerequisite"]["manifest_sha256"])
    with pytest.raises(ValueError, match="exact manifest SHA-256"):
        importlib.import_module("paid_guard").approved_manifest()


@pytest.mark.parametrize(
    ("limit", "remaining", "reset", "byok", "eligible"),
    [
        (2, 1.99848, None, True, False),
        (5, 2.99, None, True, False),
        (6, 5, None, True, False),
        (5, 5, "daily", True, False),
        (5, 5, None, False, False),
        (5, 3, None, True, True),
    ],
)
def test_standalone_key_preflight(codex_only, limit, remaining, reset, byok, eligible, monkeypatch):
    _, spec = codex_only
    guard = importlib.import_module("paid_guard")
    api = guard.Upstream(spec, None, "codex", float("inf"), "dummy")
    data = {"limit": limit, "limit_remaining": remaining, "limit_reset": reset, "include_byok_in_limit": byok}

    def key_read(operation):
        assert operation == "key"
        return 200, {}, json.dumps({"data": data}).encode()

    monkeypatch.setattr(api, "request", key_read)
    if eligible:
        assert api.validate_credit_limit()["usd_remaining"] == remaining
    else:
        with pytest.raises(ValueError):
            api.validate_credit_limit()


@pytest.mark.parametrize(
    ("stage", "operation"),
    [
        ("cost", "key"),
        ("zdr", "key"),
        ("codex", "generation"),
        ("codex", "endpoints/zdr"),
        ("codex", "chat/completions"),
    ],
)
def test_standalone_forbids_prior_stages_and_unrelated_operations(codex_only, stage, operation):
    _, spec = codex_only
    ledger = SimpleNamespace(reserve=lambda *_: pytest.fail("Unexpected paid reservation"))
    api = importlib.import_module("paid_guard").Upstream(spec, ledger, stage, float("inf"), "dummy")
    body = {"model": spec["models"]["default"]} if operation == "chat/completions" else None
    with pytest.raises(ValueError, match="operation outside"):
        api.request(operation, body)


def test_tui_acceptance_reserves_before_forwarding_and_refuses_a_spent_approval(manifest, tmp_path):
    import httpx

    acc = importlib.import_module("forge_acceptance")
    _, card = manifest
    spec = json.loads((card / "paid-acceptance-manifest.json").read_bytes())
    fixture = acc.FixtureServer(("127.0.0.1", 0), acc.FixtureUpstream)
    fixture.hits, fixture.get_paths = [], []
    fixture.native_tui = True
    ledger = acc.Ledger(tmp_path, spec["limits"], stage_order=("tui",))
    deadline = ledger.begin("tui")
    api = acc.AcceptanceUpstream(spec, ledger, deadline, "fixture", fixture)
    api.model = acc.MODELS[0]
    for _ in range(spec["limits"]["generation_attempts"] - 1):
        ledger.reserve("tui", "generation", "responses")
    body = {"model": api.model, "input": "Hi", "store": False, "stream": True, "provider": {"zdr": True}}
    headers = {"authorization": "Bearer fixture", "x-openrouter-metadata": "enabled"}
    with acc.serving(fixture), acc.serving(acc.gateway(api)) as base, httpx.Client(trust_env=False) as client:
        assert client.post(base + "/responses", json=body, headers=headers).status_code == 200
        assert client.post(base + "/responses", json=body, headers=headers).status_code == 400
        assert fixture.hits == ["/api/v1/responses"]
    with pytest.raises(ValueError, match="already started"):
        ledger.begin("tui")


def test_tui_guard_enforces_absolute_stream_deadline(manifest, tmp_path):
    import time

    import httpx

    acc = importlib.import_module("forge_acceptance")
    _, card = manifest
    spec = json.loads((card / "paid-acceptance-manifest.json").read_bytes())
    fixture = acc.FixtureServer(("127.0.0.1", 0), acc.FixtureUpstream)
    fixture.hits, fixture.get_paths, fixture.trickle = [], [], True
    ledger = acc.Ledger(tmp_path, spec["limits"], stage_order=("tui",))
    ledger.begin("tui")
    api = acc.AcceptanceUpstream(spec, ledger, time.monotonic() + 0.6, "fixture", fixture)
    api.model = acc.MODELS[0]
    with acc.serving(fixture), acc.serving(acc.gateway(api)) as base, httpx.Client(trust_env=False) as client:
        response = client.post(
            base + "/responses",
            headers={"authorization": "Bearer fixture", "x-openrouter-metadata": "enabled"},
            json={"model": api.model, "store": False, "stream": True, "provider": {"zdr": True}},
        )
        assert response.status_code == 200 and 0 < len(response.content) < 35
        assert api.refusals and len(fixture.hits) == 1
