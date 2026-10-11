#!/usr/bin/env python3
"""Check retained B4 product captures without inference; never reinterpret cleanup as product success."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text())


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def turn(capture: Path) -> dict:
    return json.loads(read(capture / "supervisor-status.json")["stdout"])["supervisor"]["turn_review"]


def dispatches(capture: Path) -> int:
    return sum(row["kind"] == "dispatch_started" for row in rows(capture / "reviewer.jsonl"))


def wheel_provenance(root: Path) -> None:
    """Compare installed-candidate Python bytes without trusting its unchanged version label."""
    checkout = Path(__file__).resolve().parents[3]
    wheel = next((root / "wheel").glob("*.whl"))
    files = {
        str(path.relative_to(checkout / "src")): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (checkout / "src/forge").rglob("*.py")
    }
    with zipfile.ZipFile(wheel) as archive:
        assert all(hashlib.sha256(archive.read(path)).hexdigest() == sha for path, sha in files.items())
    proof = {
        "revision": subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip(),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "source_python_files": [{"path": path, "sha256": sha} for path, sha in sorted(files.items())],
        "source_python_matches_wheel": True,
        "qualification": "Built from the same Python bytes before the candidate commit; compare content, not package version 1.0.2.",
    }
    (root / "wheel-provenance.json").write_text(json.dumps(proof, indent=2) + "\n")


def verify(root: Path, *, wheel: bool = True) -> dict:
    captures = root / "captures"
    incomplete = captures / "14-product-aggregate"
    assert turn(incomplete)["reason"] == "incomplete_evidence" and dispatches(incomplete) == 0
    aggregate = captures / "15-product-aggregate-carry"
    assert turn(aggregate)["state"] == "reviewed" and dispatches(aggregate) == 1
    evidence = rows(aggregate / "review-events.jsonl")[-1]["payload"]["evidence"]
    assert {"product-a.txt", "product-b.txt", "product-shell.txt"} <= {change["path"] for change in evidence["changes"]}
    assert len(evidence["provenance_turns"]) == 2
    correction = captures / "16-product-source-correction"
    stop = [row for row in rows(correction / "hooks.jsonl") if row["hook"] == ["codex-stop"]]
    assert len(stop) == 2 and dispatches(correction) == 1
    first, second = [json.loads(row["stdout"]) for row in stop]
    assert first["decision"] == "block" and "decision" not in second
    assert "Use GOOD as the value in product-fix.txt." in first["reason"]
    assert "B4-REVIEWER-TEXT" not in first["reason"] and turn(correction)["state"] == "unreviewed"
    carry = captures / "17-product-correction-carry"
    assert turn(carry)["state"] == "reviewed" and not turn(carry)["outstanding"] and dispatches(carry) == 1
    real = read(captures / "18-real-aggregate/real-review.json")
    assert real["dispatches"] == 1 and real["result"]["run_ok"] and real["result"]["parsed"]
    assert real["result"]["dispatched"] is True
    for label, state in (("19-product-deadline", "unavailable"), ("20-product-hook-kill", "incomplete")):
        capture = captures / label
        assert dispatches(capture) == 1 and turn(capture)["state"] == state and turn(capture)["spent"]
        cleanup = read(capture / "run/process-result.json")
        assert not cleanup["survivors_before_sweep"] and not cleanup["remaining"]
    tui = captures / "21c-product-tui-child"
    assert read(tui / "fresh-policy.json")["supervisor"] is None
    assert read(tui / "idle-configuration.json")["returncode"] == 0
    assert turn(tui)["state"] == "reviewed" and dispatches(tui) == 1
    assert "Forge reviewed the bounded" in (tui / "terminal.log").read_text(errors="replace")
    cancel = captures / "22-product-executor-cancel"
    assert read(cancel / "fault.json")["after_dispatch"] and dispatches(cancel) == 1
    assert turn(cancel)["spent"] and turn(cancel)["state"] == "incomplete"
    cleanup = read(cancel / "run/process-result.json")
    assert cleanup["survivors_before_sweep"] and not cleanup["remaining"]
    if wheel:
        wheel_provenance(root)
        assert read(captures / "23-wheel-enrollment/run/stdout")["stop_review_enrolled"]
        final = captures / "24-wheel-correction"
        assert dispatches(final) == 1 and turn(final)["state"] == "unreviewed"
        assert turn(final)["correction_consumed"] and turn(final)["outstanding"]
        for record in rows(final / "hooks.jsonl"):
            assert record["dev_override"] is None and "/wheel-env/" in record["forge_module"]
        for phase in ("lifecycle", "enroll", "correction"):
            report = read(root / ("wheel-" + phase + "-verification.json"))
            assert report["before"] == report["after"] and report["routing_restored"]
    units = sum(row["reserved_turns"] for row in rows(root / "turns.jsonl"))
    assert units <= 32
    return {
        "product_captures_verified": True,
        "installed_wheel_verified": wheel,
        "codex_units_reserved": units,
        "real_claude_dispatches": 1,
        "api_inference": 0,
        "qualifications": [
            "The real Claude control replays a retained native aggregate outside the hook; it does not approve later work.",
            "Capture 14 exposed absolute-path coverage normalization and remains a failed attempt; 15 verifies carry after the fix.",
            "The first TUI helper failed on null fresh policy; its child did not save a resume ID. The completed new-child control is 21c.",
            "Native executor cancellation in 22 required harness cleanup. The later parent-death guard is verified by model-free real-process regression, not another native cancellation turn.",
            "Quota exhaustion did not occur naturally and remains unverified; failure controls use admitted local stubs.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--without-wheel", action="store_true")
    args = parser.parse_args()
    result = verify(args.root, wheel=not args.without_wheel)
    (args.root / "product-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
