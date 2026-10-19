"""Exercise the complete frozen diagnostic study through local fixture transports only."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import os
import stat
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/board/retired/jev_rule_pack/evidence"
SECRET = "synthetic-capture-secret"
CREDENTIALS = {"base_url": "https://openrouter.ai/api/v1", "api_key": SECRET}


def load_module(monkeypatch, name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def study(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts/experiments/jev"))
    module = load_module(
        monkeypatch,
        "jev_diagnostic_capture_test",
        ROOT / "scripts/experiments/jev/diagnostic_capture.py",
    )
    formatter = load_module(
        monkeypatch,
        "jev_diagnostic_capture_manifest_test",
        ROOT / "scripts/experiments/jev/diagnostic_manifest.py",
    )
    review = json.loads((EVIDENCE / "diagnostic-review-2026-10-18-batch-6.json").read_text())
    catalog = json.loads((EVIDENCE / "bounded-catalog-2026-10-18.json").read_text())
    # Every test admits the complete reviewed study through the production validator.
    plan = formatter.build_manifest(review, catalog)
    assert len(plan["slots"]) == 72
    assert len(plan["scoring"]["cases"]) == 12
    (tmp_path / "retained").mkdir(mode=0o700)
    return SimpleNamespace(
        module=module,
        formatter=formatter,
        review=review,
        catalog=catalog,
        plan=plan,
        evidence_root=tmp_path / "retained",
        output=tmp_path / "capture",
    )


def wire(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def fixture_response(study, payload, *, wrong=False):
    case = next(row for row in study.plan["scoring"]["cases"] if row["case_id"] == payload["case_id"])
    answers = dict(case["gold_answers"])
    questions = next(row for row in study.plan["payloads"] if row["payload_id"] == f"J:{payload['case_id']}")["body"][
        "questions"
    ]
    if wrong:
        sentinel = case["sentinel_keys"][0]
        answers[sentinel] = next(key for key in questions[sentinel]["criteria"] if key != answers[sentinel])
    if payload["arm"] == "J":
        return {
            "model": "typesafe/jev-1.13-20260917",
            "provider": "TypeSafe",
            "id": "fixture-generation",
            "usage": {"input_tokens": 1, "output_tokens": 0, "cost": 0.000000042},
            "answers": {
                key: {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 1.0,
                    "probabilities": {option: float(option == choice) for option in questions[key]["criteria"]},
                }
                for key, choice in answers.items()
            },
        }
    return {
        "model": "anthropic/claude-opus-5.5",
        "provider": "Google",
        "id": "fixture-generation",
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "cost": 0.0006},
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(answers)},
            }
        ],
    }


class FixtureTransport:
    """Only known public GETs and exact, locally frozen POST bodies can reach this fixture."""

    def __init__(self, study, post=None, mutate_catalog=None):
        self.study = study
        self.post = post
        self.mutate_catalog = mutate_catalog
        self.requests = []
        self.posts = []
        self.payloads = []
        self.repetitions = Counter()
        self.transport = httpx.MockTransport(self.handle)

    async def handle(self, request):
        self.requests.append(request)
        if request.method == "GET":
            source = next(row for row in self.study.catalog["sources"] if row["url"] == str(request.url))
            assert "authorization" not in request.headers
            if source["id"] == "zdr-endpoints":
                body = {"data": [copy.deepcopy(row["zdr_endpoint"]) for row in self.study.catalog["arms"].values()]}
            else:
                arm = "J" if source["id"] == "jev-endpoints" else "R"
                body = {"data": {"endpoints": [copy.deepcopy(self.study.catalog["arms"][arm]["endpoint"])]}}
            if self.mutate_catalog:
                self.mutate_catalog(source["id"], body)
            return httpx.Response(200, json=body)
        assert request.method == "POST"
        payload = next(row for row in self.study.plan["payloads"] if wire(row["body"]) == request.content)
        assert str(request.url) == self.study.plan["arms"][payload["arm"]]["endpoint"]
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        self.posts.append(request)
        self.payloads.append(payload)
        self.repetitions[payload["payload_id"]] += 1
        if self.post:
            response = self.post(request, payload, self.repetitions[payload["payload_id"]])
            if hasattr(response, "__await__"):
                return await response
            return response
        return httpx.Response(200, json=fixture_response(self.study, payload))


async def execute(study, fixture, **kwargs):
    return await study.module.run_capture(
        study.plan,
        study.review,
        study.catalog,
        kwargs.pop("output", study.output),
        transport=fixture.transport,
        credentials=kwargs.pop("credentials", CREDENTIALS),
        evidence_root=study.evidence_root,
        **kwargs,
    )


def read_journal(study):
    return json.loads((study.output / "capture.json").read_text())


@pytest.mark.asyncio
async def test_all_72_fixed_slots_have_exact_bodies_private_storage_and_restored_ambient_state(
    study, monkeypatch, tmp_path
):
    from forge.runtime_config import get_runtime_config, reset_runtime_config

    home = tmp_path / "ambient-home"
    home.mkdir()
    (home / "keep.txt").write_text("unchanged")
    for name, value in {
        "FORGE_HOME": str(home),
        "FORGE_SESSION": "private-session",
        "FORGE_RUN_ID": "prior-run",
        "FORGE_ROOT_RUN_ID": "prior-root",
        "FORGE_PARENT_RUN_ID": "prior-parent",
    }.items():
        monkeypatch.setenv(name, value)
    reset_runtime_config()
    get_runtime_config().provider_trace.inject_provider_user = True
    before = os.environ.copy()

    def post(request, payload, repetition):
        assert os.environ["FORGE_HOME"] == str(study.output / "forge-home")
        assert "FORGE_SESSION" not in os.environ
        assert not any(
            value in request.content for value in (b"hapa1i", b"prior-run", b"private-session", SECRET.encode())
        )
        state = (
            payload["body"]["state"]
            if payload["arm"] == "J"
            else json.loads(payload["body"]["messages"][1]["content"])["state"]
        )
        assert "review" not in state and "gold_answers" not in state
        body = fixture_response(study, payload)
        body["private_metadata"] = {"account_id": "private-account", "key_echo": SECRET}
        return httpx.Response(200, json=body)

    fixture = FixtureTransport(study, post)
    journal = await execute(study, fixture)
    assert journal["status"] == "completed"
    assert journal["physical_requests"] == len(fixture.posts) == 72
    assert Counter(row["arm"] for row in fixture.payloads) == {"J": 36, "R": 36}
    assert [row["payload_id"] for row in fixture.payloads] == [row["payload_id"] for row in study.plan["slots"]]
    assert [row["slot"] for row in journal["attempts"]] == list(range(1, 73))
    assert all(row["dispatched"] and row["failure"] is None for row in journal["attempts"])
    assert os.environ == before
    assert list(home.iterdir()) == [home / "keep.txt"]
    assert (home / "keep.txt").read_text() == "unchanged"
    for path in [study.output, *study.output.rglob("*")]:
        assert not path.is_symlink()
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()
            assert b"private-account" not in path.read_bytes()
    assert {key: value for key, value in read_journal(study).items() if key != "updated_at"} == {
        key: value for key, value in journal.items() if key != "updated_at"
    }
    assert len([request for request in fixture.requests if request.method == "GET"]) == 3


@pytest.mark.parametrize("stopped_arms,expected_count", [({"J"}, 38), ({"R"}, 38), ({"J", "R"}, 4)])
@pytest.mark.asyncio
async def test_second_noncorrect_sentinel_stops_only_that_arm(study, stopped_arms, expected_count):
    fixture = FixtureTransport(
        study,
        lambda request, payload, repetition: httpx.Response(
            200,
            json=fixture_response(study, payload, wrong=payload["arm"] in stopped_arms),
        ),
    )
    journal = await execute(study, fixture)
    assert journal["physical_requests"] == len(fixture.posts) == expected_count
    assert journal["status"] == ("semantic_stop" if len(stopped_arms) == 2 else "completed")
    assert set(journal["stopped_arms"]) == stopped_arms
    expected_slots = [
        slot
        for slot in study.plan["slots"]
        if slot["arm"] not in stopped_arms or (slot["case_id"] == "validation-boundary" and slot["repetition"] <= 2)
    ]
    assert [row["slot"] for row in journal["attempts"]] == [row["slot"] for row in expected_slots]
    assert all(row["failure"] is None for row in journal["attempts"])
    assert Counter(row["arm"] for row in fixture.payloads) == {
        arm: 2 if arm in stopped_arms else 36 for arm in ("J", "R")
    }


@pytest.mark.parametrize("status", [401, 403, 429, 500, 524, 529])
@pytest.mark.asyncio
async def test_any_http_failure_stops_the_whole_study_without_retry(study, status):
    fixture = FixtureTransport(study, lambda *_: httpx.Response(status, json={"error": "synthetic failure"}))
    journal = await execute(study, fixture)
    assert journal["status"] == "technical_stop"
    assert journal["physical_requests"] == len(fixture.posts) == 1
    assert journal["attempts"][0]["failure"]
    assert journal["attempts"][0]["status_code"] == status


@pytest.mark.parametrize("kind", ["timeout", "network", "interruption"])
@pytest.mark.asyncio
async def test_ambiguous_dispatch_is_reserved_before_io_and_never_replayed(study, kind, tmp_path):
    def post(request, payload, repetition):
        saved = read_journal(study)
        assert saved["physical_requests"] == 1
        assert saved["attempts"][0]["dispatched"] is True
        assert saved["attempts"][0]["request_id"] == request.headers["x-request-id"]
        assert saved["attempts"][0]["event_id"]
        if kind == "interruption":
            raise asyncio.CancelledError()
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        raise httpx.ConnectError("synthetic network failure", request=request)

    fixture = FixtureTransport(study, post)
    journal = await execute(study, fixture)
    assert journal["status"] == "technical_stop"
    assert journal["physical_requests"] == len(fixture.posts) == 1
    assert journal["attempts"][0]["failure"] == kind
    with pytest.raises(ValueError, match="(?i)(claim|consum|resume|already)"):
        await execute(study, fixture, output=tmp_path / "new-output")
    assert len(fixture.posts) == 1
    assert not (tmp_path / "new-output").exists()


@pytest.mark.parametrize("arm", ["J", "R"])
@pytest.mark.parametrize(
    "mutation,reason",
    [
        (lambda body: body.pop("usage"), "missing_cost"),
        (lambda body: body["usage"].pop("cost"), "missing_cost"),
        (lambda body: body["usage"].update(cost=None), "missing_cost"),
        (lambda body: body.update(model="other/model"), "changed_model"),
        (lambda body: body.update(provider="Other"), "changed_provider"),
        (lambda body: body["usage"].update(cost=9.0), "price_bound"),
    ],
)
@pytest.mark.asyncio
async def test_required_cost_and_identity_failures_stop_both_arms(study, arm, mutation, reason):
    def post(request, payload, repetition):
        body = fixture_response(study, payload)
        if payload["arm"] == arm:
            mutation(body)
        return httpx.Response(200, json=body)

    fixture = FixtureTransport(study, post)
    journal = await execute(study, fixture)
    assert journal["status"] == "technical_stop"
    assert journal["physical_requests"] == len(fixture.posts) == (1 if arm == "J" else 2)
    failed = journal["attempts"][-1]
    assert failed["failure"] == reason
    if reason == "missing_cost":
        assert failed["result"]["usage"].get("cost") is None


@pytest.mark.asyncio
async def test_switch_between_permitted_reference_identities_is_still_drift(study):
    def post(request, payload, repetition):
        body = fixture_response(study, payload)
        if payload["arm"] == "R" and repetition == 2:
            body["model"] = "anthropic/claude-opus-5.5-20260921"
        return httpx.Response(200, json=body)

    fixture = FixtureTransport(study, post)
    journal = await execute(study, fixture)
    assert journal["status"] == "technical_stop"
    assert journal["physical_requests"] == 3
    assert journal["attempts"][-1]["failure"] == "changed_model"


@pytest.mark.parametrize("malformed", ["invalid_json", "truncated", "missing_answer", "oversized"])
@pytest.mark.asyncio
async def test_malformed_reference_answers_end_the_study_without_replacement(study, malformed):
    def post(request, payload, repetition):
        body = fixture_response(study, payload)
        if payload["arm"] == "R":
            if malformed == "invalid_json":
                return httpx.Response(200, content=b'{"partial":')
            if malformed == "oversized":
                return httpx.Response(200, content=b"x" * 256_001)
            if malformed == "truncated":
                body["choices"][0]["finish_reason"] = "length"
            else:
                answers = json.loads(body["choices"][0]["message"]["content"])
                answers.pop(next(iter(answers)))
                body["choices"][0]["message"]["content"] = json.dumps(answers)
        return httpx.Response(200, json=body)

    fixture = FixtureTransport(study, post)
    journal = await execute(study, fixture)
    assert journal["status"] == "technical_stop"
    assert len(fixture.posts) == journal["physical_requests"] == 2
    assert journal["attempts"][-1]["failure"]
    assert (study.output / "capture.json").stat().st_size < 32 * 1024 * 1024


@pytest.mark.parametrize(
    "source_id,field,value",
    [
        ("jev-endpoints", "name", "TypeSafe | changed"),
        ("reference-endpoints", "tag", "anthropic"),
        ("reference-endpoints", "supported_parameters", []),
        (
            "reference-endpoints",
            "pricing",
            {"prompt": "0.000005", "completion": "0.00002"},
        ),
        ("zdr-endpoints", "status", 1),
    ],
)
@pytest.mark.asyncio
async def test_refreshed_public_catalog_drift_refuses_before_any_paid_post(study, source_id, field, value):
    def mutate(identifier, body):
        if identifier == source_id:
            row = body["data"][0] if identifier == "zdr-endpoints" else body["data"]["endpoints"][0]
            row[field] = value

    fixture = FixtureTransport(study, mutate_catalog=mutate)
    with pytest.raises(ValueError, match="(?i)(catalog|endpoint|changed|drift|support|selected)"):
        await execute(study, fixture)
    assert fixture.posts == []


@pytest.mark.parametrize(
    "base_url",
    [
        "http://openrouter.ai/api/v1",
        "https://example.invalid/api/v1",
        "https://openrouter.ai.evil.invalid/api/v1",
        "https://secret@openrouter.ai/api/v1",
        "https://openrouter.ai/api/v1?key=secret",
        "https://openrouter.ai/api/v1#fragment",
        "https://openrouter.ai:444/api/v1",
        "https://openrouter.ai/api/v1/extra",
    ],
)
@pytest.mark.asyncio
async def test_nonpublic_or_ambiguous_base_urls_refuse_before_network(study, base_url):
    fixture = FixtureTransport(study)
    with pytest.raises(ValueError, match="(?i)(base|public|openrouter|endpoint)"):
        await execute(study, fixture, credentials={**CREDENTIALS, "base_url": base_url})
    assert fixture.requests == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda plan: plan["slots"].pop(),
        lambda plan: plan["limits"].update(max_physical_requests=73),
        lambda plan: plan["slots"][0].update(arm="R"),
        lambda plan: plan["payloads"][0]["body"]["provider"].update(zdr=False),
        lambda plan: plan["scoring"]["cases"][0]["gold_answers"].update({"parser.prior_definition": "not_supplied"}),
    ],
)
@pytest.mark.asyncio
async def test_changed_complete_manifest_refuses_even_with_recomputed_digest(study, mutation):
    mutation(study.plan)
    study.plan["manifest_sha256"] = study.formatter.digest(
        {key: value for key, value in study.plan.items() if key != "manifest_sha256"}
    )
    fixture = FixtureTransport(study)
    with pytest.raises(ValueError, match="Manifest differs"):
        await execute(study, fixture)
    assert fixture.requests == []
    assert not study.output.exists()


@pytest.mark.parametrize(
    "path_kind",
    ["relative", "existing", "symlink_parent", "symlink_output", "symlink_claims"],
)
@pytest.mark.asyncio
async def test_unsafe_output_or_claim_paths_refuse_without_post(study, tmp_path, path_kind):
    if path_kind == "relative":
        study.output = Path("relative-output")
    elif path_kind == "existing":
        study.output.mkdir()
    elif path_kind == "symlink_parent":
        (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
        study.output = tmp_path / "link/output"
    elif path_kind == "symlink_output":
        study.output.symlink_to(tmp_path / "missing", target_is_directory=True)
    else:
        (study.evidence_root / ".diagnostic-proposal-claims").symlink_to(tmp_path, target_is_directory=True)
    fixture = FixtureTransport(study)
    with pytest.raises((ValueError, OSError)):
        await execute(study, fixture)
    assert fixture.posts == []


@pytest.mark.asyncio
async def test_claim_is_exclusive_even_if_first_dispatch_has_not_completed(study, tmp_path):
    async def post(request, payload, repetition):
        second = FixtureTransport(study)
        with pytest.raises(ValueError, match="(?i)(claim|consum|resume|already)"):
            await execute(study, second, output=tmp_path / "competing-output")
        assert second.posts == []
        return httpx.Response(401, json={"error": "stop fixture"})

    fixture = FixtureTransport(study, post)
    await execute(study, fixture)
    assert len(fixture.posts) == 1
    assert not (tmp_path / "competing-output").exists()


@pytest.mark.parametrize("arm", ["J", "R"])
@pytest.mark.asyncio
async def test_per_call_deadline_cancels_transport_without_retry(study, monkeypatch, arm):
    monkeypatch.setattr(
        study.module,
        "DEADLINE_SECONDS",
        {"J": 0.03 if arm == "J" else 30, "R": 0.03 if arm == "R" else 45},
    )
    cancelled = []

    async def post(request, payload, repetition):
        if payload["arm"] == arm:
            try:
                await asyncio.sleep(2)
            finally:
                cancelled.append(arm)
        return httpx.Response(200, json=fixture_response(study, payload))

    fixture = FixtureTransport(study, post)
    journal = await execute(study, fixture)
    assert cancelled == [arm]
    assert journal["status"] == "technical_stop"
    assert journal["physical_requests"] == len(fixture.posts) == (1 if arm == "J" else 2)
    assert journal["attempts"][-1]["failure"] == "timeout"


@pytest.mark.asyncio
async def test_each_call_inherits_the_earlier_whole_run_deadline(study, monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    timers = []
    monkeypatch.setattr(study.module, "WHOLE_RUN_SECONDS", 10)
    monkeypatch.setattr(study.module, "time", SimpleNamespace(monotonic=lambda: clock.now))

    def timeout_at(deadline):
        # Arm the real cancellation only after fixture dispatch, independently of local I/O speed.
        timer = asyncio.timeout(None)
        timers.append((deadline, timer))
        return timer

    monkeypatch.setattr(
        study.module,
        "asyncio",
        SimpleNamespace(timeout_at=timeout_at, CancelledError=asyncio.CancelledError),
    )
    cancelled = []

    def catalog_elapsed(source_id, body):
        clock.now = 1007.0

    async def post(request, payload, repetition):
        deadline, timer = timers[-1]
        assert deadline == 1010.0
        assert request.extensions["timeout"]["read"] == 3.0
        clock.now = deadline
        timer.reschedule(asyncio.get_running_loop().time())
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
        return httpx.Response(200, json=fixture_response(study, payload))

    fixture = FixtureTransport(study, post, mutate_catalog=catalog_elapsed)
    journal = await execute(study, fixture)
    assert cancelled == [True]
    assert journal["status"] == "technical_stop"
    assert journal["physical_requests"] == len(fixture.posts) == 1
    assert journal["attempts"][0]["failure"] == "whole_run_deadline"
    assert journal["stop_reason"] == "whole_run_deadline"
    assert read_journal(study)["attempts"][0]["failure"] == "whole_run_deadline"


@pytest.mark.asyncio
async def test_journal_byte_cap_is_enforced_before_any_dispatch(study, monkeypatch):
    monkeypatch.setattr(study.module, "MAX_JOURNAL_BYTES", 1)
    fixture = FixtureTransport(study)
    journal = await execute(study, fixture)
    assert journal["status"] == "technical_stop"
    assert fixture.posts == []
    assert not (study.output / "capture.json").exists()


@pytest.mark.asyncio
async def test_separate_arm_run_ids_and_request_event_joins_reach_real_cli_readers(study, monkeypatch):
    from forge.cli.main import main
    from forge.core.telemetry.downstream import read_downstream_records
    from forge.core.usage.ledger import read_usage_events
    from forge.runtime_config import reset_runtime_config

    # Complete both arms' first two repetitions, retaining an unknown billed outcome on slot five.
    def post(request, payload, repetition):
        body = fixture_response(study, payload)
        if payload["arm"] == "J" and repetition == 3:
            body["usage"].pop("cost")
        return httpx.Response(200, json=body)

    fixture = FixtureTransport(study, post)
    journal = await execute(study, fixture)
    assert journal["physical_requests"] == 5
    attempts = journal["attempts"]
    by_arm = {arm: {row["run_id"] for row in attempts if row["arm"] == arm} for arm in ("J", "R")}
    assert len(by_arm["J"]) == len(by_arm["R"]) == 1
    assert by_arm["J"].isdisjoint(by_arm["R"])
    assert len({row["request_id"] for row in attempts}) == len({row["event_id"] for row in attempts}) == 5
    assert Decimal(attempts[0]["result"]["usage"]["cost"]) == Decimal("0.000000042")
    assert attempts[-1]["result"]["usage"].get("cost") is None

    monkeypatch.setenv("FORGE_HOME", str(study.output / "forge-home"))
    reset_runtime_config()
    try:
        downstream = {row.request_id: row for row in read_downstream_records()}
        events = {row.event_id: row for row in read_usage_events()}
        assert set(downstream) == {row["request_id"] for row in attempts}
        assert set(events) == {row["event_id"] for row in attempts}
        for row in attempts:
            physical = downstream[row["request_id"]]
            event = events[row["event_id"]]
            assert physical.downstream_event_id == row["downstream_event_id"]
            assert physical.forge_run_id == event.run_id == row["run_id"]
            assert event.event_id == f"evt_{physical.downstream_event_id}"
            assert event.session is None
        failed = downstream[attempts[-1]["request_id"]]
        assert failed.cost_micros is None
        assert failed.confidence == "unavailable"
        assert events[attempts[-1]["event_id"]].cost_micro_usd is None

        runner = CliRunner()
        result = runner.invoke(main, ["telemetry", "trace", "list", "--period", "all", "--json"])
        assert result.exit_code == 0, result.output
        assert {row["request_id"] for row in json.loads(result.stdout)} == set(downstream)
        for verb in ("show", "explain"):
            result = runner.invoke(main, ["telemetry", "trace", verb, attempts[-1]["request_id"], "--json"])
            assert result.exit_code == 0, result.output
            assert json.loads(result.stdout)["request_id"] == attempts[-1]["request_id"]
        for breakdown in ("--by-model", "--by-verb"):
            result = runner.invoke(main, ["telemetry", "costs", "show", "--period", "all", breakdown])
            assert result.exit_code == 0, result.output
        result = runner.invoke(main, ["telemetry", "costs", "show", "--period", "all", "--json"])
        assert result.exit_code == 0, result.output
        costs = json.loads(result.stdout)
        assert costs["total_requests"] == 5
        assert costs["reported_requests"] == 4
        assert costs["unavailable_requests"] == 1
        assert costs["total_cost_micros"] == 1200
        assert costs["by_verb"]["jev-diagnostic-j"]["request_count"] == 3
        assert costs["by_verb"]["jev-diagnostic-r"]["request_count"] == 2
        assert all(row["invocations"] == 1 for row in costs["by_verb"].values())
    finally:
        reset_runtime_config()


@pytest.mark.asyncio
async def test_failed_reservation_persistence_prevents_network_and_keeps_claim(study, monkeypatch, tmp_path):
    original = study.module._persist

    def refuse_reservation(output, journal, limit):
        if journal["physical_requests"]:
            raise OSError("synthetic fsync failure")
        original(output, journal, limit)

    monkeypatch.setattr(study.module, "_persist", refuse_reservation)
    fixture = FixtureTransport(study)
    journal = await execute(study, fixture)
    assert journal["status"] == "technical_stop"
    assert fixture.posts == []
    assert read_journal(study)["physical_requests"] == 0
    with pytest.raises(ValueError, match="(?i)(claim|consum|resume|already)"):
        await execute(study, fixture, output=tmp_path / "retry-output")
    assert fixture.posts == []


@pytest.mark.parametrize("kind", ["byte_cap", "deadline", "redirect", "duplicate_endpoint"])
@pytest.mark.asyncio
async def test_public_preflight_is_bounded_and_cannot_dispatch_a_substitute(study, monkeypatch, kind):
    original = FixtureTransport(study)
    if kind == "byte_cap":
        monkeypatch.setattr(study.module, "MAX_CATALOG_BYTES", 1)
    if kind == "deadline":
        monkeypatch.setattr(study.module, "CATALOG_TIMEOUT_SECONDS", 0.01)

    async def handler(request):
        assert request.method == "GET"
        if kind == "deadline":
            await asyncio.sleep(2)
        if kind == "redirect":
            return httpx.Response(302, headers={"location": "https://example.invalid/substitute"})
        response = await original.handle(request)
        if kind == "duplicate_endpoint":
            body = json.loads(response.content)
            if isinstance(body["data"], list):
                body["data"] *= 2
            else:
                body["data"]["endpoints"] *= 2
            return httpx.Response(200, json=body)
        return response

    fixture = FixtureTransport(study)
    with pytest.raises((ValueError, TimeoutError)):
        await execute(study, fixture, catalog_transport=httpx.MockTransport(handler))
    assert fixture.requests == []
    assert not study.output.exists()


def test_default_cli_validation_reads_no_credentials_or_network_and_writes_nothing(
    study, monkeypatch, tmp_path, capsys
):
    paths = []
    for name, value in (
        ("manifest", study.plan),
        ("review", study.review),
        ("catalog", study.catalog),
    ):
        path = tmp_path / f"{name}.json"
        path.write_bytes(wire(value))
        paths.extend([f"--{name}", str(path)])
    before = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    def unexpected(*args, **kwargs):
        pytest.fail("Validation must not access provider credentials or transports")

    monkeypatch.setattr(study.module.CredentialManager, "default", unexpected)
    monkeypatch.setattr(study.module.httpx, "AsyncClient", unexpected)
    monkeypatch.setattr(sys, "argv", ["diagnostic_capture.py", *paths])
    assert study.module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["physical_request_slots"] == 72
    assert {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == before
    assert not study.output.exists()
    assert list(study.evidence_root.iterdir()) == []


@pytest.mark.parametrize("extra", [["--live"], ["--output", "/private/tmp/unapproved-output"]])
def test_cli_requires_both_explicit_live_selection_and_output(study, monkeypatch, extra):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "diagnostic_capture.py",
            "--manifest",
            "manifest.json",
            "--review",
            "review.json",
            "--catalog",
            "catalog.json",
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as error:
        study.module.main()
    assert error.value.code == 2


@pytest.mark.asyncio
async def test_timed_out_local_write_cannot_race_later_stop_persistence(study, monkeypatch):
    import threading

    monkeypatch.setattr(study.module, "DEADLINE_SECONDS", {"J": 0.03, "R": 45})
    original = study.module._persist
    delayed = False
    saved_failures = []

    def slow_first_reservation(output, journal, limit):
        nonlocal delayed
        if journal["physical_requests"] and not delayed:
            delayed = True
            # An OS write may continue after asyncio cancels its awaiting future.
            threading.Event().wait(0.1)
        original(output, journal, limit)
        if journal["attempts"]:
            saved_failures.append(journal["attempts"][-1]["failure"])

    monkeypatch.setattr(study.module, "_persist", slow_first_reservation)
    fixture = FixtureTransport(study)
    journal = await execute(study, fixture)
    assert delayed
    assert fixture.posts == []
    assert journal["status"] == "technical_stop"
    assert journal["stop_reason"] == "timeout"
    assert journal["physical_requests"] == 1
    assert journal["attempts"][0]["failure"] == "timeout"
    assert saved_failures[0] == "interruption"
    assert saved_failures[1:] and set(saved_failures[1:]) == {"timeout"}
    assert read_journal(study)["attempts"][0]["failure"] == "timeout"
    assert not list(study.output.glob("*.tmp"))


@pytest.mark.asyncio
async def test_retained_execution_blocks_replay_even_if_the_claim_file_is_lost(study, tmp_path):
    study.output = study.evidence_root / "capture"
    fixture = FixtureTransport(study, lambda *_: httpx.Response(401, json={"error": "synthetic stop"}))
    journal = await execute(study, fixture)
    claim = Path(journal["proposal_claim"])
    assert stat.S_IMODE(claim.stat().st_mode) == 0o600
    claim.unlink()
    next_fixture = FixtureTransport(study)
    with pytest.raises(ValueError, match="(?i)(retained|consum|resume)"):
        await execute(study, next_fixture, output=tmp_path / "new-output")
    assert next_fixture.requests == []
    assert not (tmp_path / "new-output").exists()


@pytest.mark.asyncio
async def test_late_telemetry_stays_isolated_and_preserves_the_completed_attempt_outcome(study, monkeypatch, tmp_path):
    import threading

    ambient = tmp_path / "ambient-home"
    ambient.mkdir()
    (ambient / "keep.txt").write_text("unchanged")
    monkeypatch.setenv("FORGE_HOME", str(ambient))
    monkeypatch.setattr(study.module, "WHOLE_RUN_SECONDS", 0.5)
    original = study.module.capture_io.persist_telemetry
    completed = threading.Event()

    def slow_emission(*args):
        threading.Event().wait(0.6)
        try:
            original(*args)
        finally:
            completed.set()

    monkeypatch.setattr(study.module.capture_io, "persist_telemetry", slow_emission)
    fixture = FixtureTransport(study)
    journal = await execute(study, fixture)
    assert await asyncio.to_thread(completed.wait, 1)
    assert os.environ["FORGE_HOME"] == str(ambient)
    assert list(ambient.iterdir()) == [ambient / "keep.txt"]
    assert journal["status"] == "technical_stop"
    assert journal["stop_reason"] == "whole_run_deadline"
    assert len(fixture.posts) == journal["physical_requests"] == 1
    attempt = journal["attempts"][0]
    assert attempt["failure"] is None
    assert attempt["result"]["failure"] is None
    assert attempt["evidence_finalization_ms"] >= 600
    assert journal["evidence_finalization_deadline"] is True
    for relative in ("telemetry/downstream", "usage/events"):
        records = [
            json.loads(line)
            for path in (study.output / "forge-home" / relative).glob("*.jsonl")
            for line in path.read_text().splitlines()
        ]
        assert len(records) == 1
        if relative == "telemetry/downstream":
            assert records[0]["request_id"] == attempt["request_id"]
            assert records[0]["failed"] is False
        else:
            assert records[0]["event_id"] == attempt["event_id"]
            assert records[0]["status"] == "success"
    assert read_journal(study)["attempts"][0]["failure"] is None
