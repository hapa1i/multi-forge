"""Published diagnostic receipts remain replay evidence beside older calibration journals."""

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/board/paused/jev_rule_pack/evidence"


@pytest.fixture
def capture(monkeypatch, tmp_path):
    modules = {}
    for name, filename in (("calibration", "rule-pack-capture.py"), ("diagnostic", "diagnostic_capture.py")):
        spec = importlib.util.spec_from_file_location(
            f"jev_publication_{name}", ROOT / "scripts/experiments/jev" / filename
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    monkeypatch.setattr(modules["calibration"].CredentialManager, "default", lambda: pytest.fail("No credential reads"))
    evidence = tmp_path / "evidence"
    receipt = evidence / "published" / "capture.json"
    receipt.parent.mkdir(parents=True)
    manifest = json.loads((EVIDENCE / "bounded-capture-manifest.json").read_text())
    manifest_path = evidence / "bounded-capture-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    journal = {
        "schema_version": 1,
        "proposal_id": modules["diagnostic"].proposal_identity(manifest),
        "physical_requests": 1,
        "attempts": [{"dispatched": True}],
        "manifest_reference": {
            "path": "../bounded-capture-manifest.json",
            "manifest_sha256": manifest["manifest_sha256"],
        },
    }
    receipt.write_text(json.dumps(journal))
    monkeypatch.setattr(modules["calibration"], "CAPTURE_EVIDENCE", evidence)
    return SimpleNamespace(
        **modules, evidence=evidence, receipt=receipt, manifest=manifest, manifest_path=manifest_path, journal=journal
    )


def test_foreign_verified_publication_does_not_block_calibration_replay_scan(capture):
    capture.calibration.refuse_consumed_proposal(capture.calibration.manifest())


def test_own_published_diagnostic_still_refuses_after_local_claim_is_lost(capture):
    changed_source = copy.deepcopy(capture.manifest)
    changed_source["implementation_sha256"] = {"updated-executor.py": "0" * 64}
    with pytest.raises(ValueError, match="retained execution evidence"):
        capture.diagnostic._refuse_consumed(changed_source, capture.evidence)
    assert not (capture.evidence / ".diagnostic-proposal-claims").exists()


@pytest.mark.parametrize("guard", ["calibration", "diagnostic"])
@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "absolute",
        "escape",
        "symlink",
        "parent-symlink",
        "symlink-before-parent",
        "digest",
        "contents",
        "duplicate-key",
        "nonfinite",
        "oversized",
        "ambiguous",
    ],
)
def test_unsafe_publication_references_fail_closed(capture, tmp_path, guard, corruption):
    journal = copy.deepcopy(capture.journal)
    reference = journal["manifest_reference"]
    if corruption == "missing":
        capture.manifest_path.unlink()
    elif corruption == "absolute":
        reference["path"] = str(capture.manifest_path)
    elif corruption == "escape":
        (tmp_path / "outside.json").write_text(capture.manifest_path.read_text())
        reference["path"] = "../../outside.json"
    elif corruption == "symlink":
        (capture.evidence / "linked.json").symlink_to(capture.manifest_path)
        reference["path"] = "../linked.json"
    elif corruption == "parent-symlink":
        (capture.evidence / "linked").symlink_to(capture.evidence, target_is_directory=True)
        reference["path"] = "../linked/bounded-capture-manifest.json"
    elif corruption == "symlink-before-parent":
        (capture.evidence / "linked").symlink_to(tmp_path, target_is_directory=True)
        reference["path"] = "../linked/../bounded-capture-manifest.json"
    elif corruption == "digest":
        reference["manifest_sha256"] = "0" * 64
    elif corruption == "contents":
        capture.manifest["limits"]["max_physical_requests"] = 73
        capture.manifest_path.write_text(json.dumps(capture.manifest))
    elif corruption == "duplicate-key":
        capture.manifest_path.write_text('{"proposal_kind":"bounded_diagnostic_comparison","proposal_kind":"other"}')
    elif corruption == "nonfinite":
        capture.manifest_path.write_text('{"proposal_kind":"bounded_diagnostic_comparison","cost":NaN}')
    elif corruption == "oversized":
        capture.manifest_path.write_bytes(b" " * 2_000_001)
    else:
        journal["manifest"] = capture.manifest
    capture.receipt.write_text(json.dumps(journal))
    with pytest.raises((ValueError, OSError)):
        if guard == "calibration":
            capture.calibration.refuse_consumed_proposal(capture.calibration.manifest())
        else:
            capture.diagnostic._refuse_consumed(capture.manifest, capture.evidence)
