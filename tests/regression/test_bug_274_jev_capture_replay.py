"""Consumed calibration proposals cannot replay through a fresh output directory or source edit."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/board/doing/jev_rule_pack/evidence"


@pytest.fixture
def capture(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-capture.py"
    spec = importlib.util.spec_from_file_location("jev_capture_replay_regression", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.CredentialManager, "default", lambda: pytest.fail("No credential access allowed"))
    return module


@pytest.mark.parametrize("directory", ["calibration-2026-10-16", "calibration-boundary-2026-10-17"])
@pytest.mark.asyncio
async def test_retained_consumed_manifest_refuses_before_credentials_and_output(capture, tmp_path, directory):
    journal = json.loads((EVIDENCE / directory / "capture.json").read_text())
    assert journal["physical_requests"] > 0
    with pytest.raises(ValueError, match="already dispatched"):
        await capture.run_live(journal["manifest"], tmp_path / "new-output")
    assert not (tmp_path / "new-output").exists()


def retain(capture, monkeypatch, tmp_path, plan, count, attempts):
    evidence = tmp_path / "evidence"
    receipt = evidence / "previous" / "capture.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"manifest": plan, "physical_requests": count, "attempts": attempts}))
    monkeypatch.setattr(capture, "CAPTURE_EVIDENCE", evidence)
    return receipt


@pytest.mark.parametrize(
    "count,attempts",
    [
        (9, [{"dispatched": True, "failure": None}]),
        (1, [{"dispatched": True, "failure": "interrupted"}]),
        (0, [{"dispatched": True, "failure": "ambiguous_timeout"}]),
        (1, []),
    ],
)
@pytest.mark.asyncio
async def test_dispatch_consumes_proposal_across_implementation_changes(
    capture, monkeypatch, tmp_path, count, attempts
):
    current = capture.manifest()
    previous = copy.deepcopy(current)
    previous.pop("proposal_id")  # Historical journals precede the explicit proposal identity.
    previous["implementation_sha256"] = {"scripts/experiments/jev/rule-pack-capture.py": "0" * 64}
    assert capture.proposal_identity(previous) == current["proposal_id"]
    retain(capture, monkeypatch, tmp_path, previous, count, attempts)
    with pytest.raises(ValueError, match="already dispatched"):
        await capture.run_live(current, tmp_path / "new-output")
    assert not (tmp_path / "new-output").exists()


@pytest.mark.parametrize("fresh_id", [False, True])
@pytest.mark.asyncio
async def test_undispatched_or_separately_named_proposal_can_reach_credential_lookup(
    capture, monkeypatch, tmp_path, fresh_id
):
    original = capture.manifest()
    plan = capture.manifest("separately-reviewed-repeat") if fresh_id else original
    retain(
        capture,
        monkeypatch,
        tmp_path,
        original,
        int(fresh_id),
        [{"dispatched": fresh_id, "failure": "interrupted" if fresh_id else "validation"}],
    )

    class FixtureBoundary(Exception):
        pass

    def credentials_boundary():
        raise FixtureBoundary("Reached credential boundary without reading credentials")

    monkeypatch.setattr(capture.CredentialManager, "default", credentials_boundary)
    with pytest.raises(FixtureBoundary):
        await capture.run_live(plan, tmp_path / "new-output")
    assert not (tmp_path / "new-output").exists()


@pytest.mark.parametrize("corruption", ["truncated", "bad-count", "bad-attempt"])
@pytest.mark.asyncio
async def test_unverifiable_matching_journal_refuses_with_evidence_path(capture, monkeypatch, tmp_path, corruption):
    plan = capture.manifest()
    receipt = retain(capture, monkeypatch, tmp_path, plan, 0, [])
    journal = json.loads(receipt.read_text())
    if corruption == "truncated":
        receipt.write_text('{"manifest":')
    else:
        if corruption == "bad-count":
            journal["physical_requests"] = "unknown"
        else:
            journal["attempts"] = [{"failure": "interrupted"}]
        receipt.write_text(json.dumps(journal))
    with pytest.raises(ValueError, match="Cannot verify retained capture journal") as error:
        await capture.run_live(plan, tmp_path / "new-output")
    assert str(receipt) in str(error.value)
    assert "inspect and repair" in str(error.value)
    assert not (tmp_path / "new-output").exists()
