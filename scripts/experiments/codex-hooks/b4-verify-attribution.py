#!/usr/bin/env python3
"""Verify and publish the bounded B4 ordinary-use round without private transcripts or credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
CHECKOUT = SCRIPTS.parents[2]


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root: Path) -> dict:
    assert (root / "CLOSED").exists()
    assert not (root / "codex-home/auth.json").exists()
    captures = root / "captures"
    native = captures / "03-attribution"
    cases = {}
    for capture in sorted(captures.iterdir()):
        if not (capture / "completed.json").exists():
            continue  # Preparation-only admission metadata contains no runtime attempt.
        completion = read(capture / "completed.json")
        cases[capture.name] = completion
        assert completion["exit"] == 0
    assert set(cases) == {"01-trust", "02-enrollment", "03-attribution"}
    assert read(captures / "02-enrollment/run/stdout")["stop_review_enrolled"]
    terminal = read(native / "terminal-result.json")
    assert terminal["exited"] and terminal["status"] == 0
    assert sum("submitted_prompt" in row for row in terminal["actions"]) == 5
    rollout = rows(next(native.glob("rollout-*.jsonl")))
    completed = [row for row in rollout if row.get("payload", {}).get("type") == "task_complete"]
    assert len(completed) == 6  # Initial transfer plus five explicit prompts.
    hooks = rows(native / "hooks.jsonl")
    assert all(row["exit_code"] == 0 for row in hooks)
    turns = []
    for number, expected in enumerate(("reviewed", "no_changes", "reviewed", "partial", "reviewed"), 1):
        checkpoint = rows(native / f"after-turn-{number}/review-events.jsonl")[-1]["payload"]
        assert checkpoint["status"] == expected
        assert not checkpoint["correction_consumed"]
        evidence = checkpoint["evidence"]
        if number in {1, 3, 5}:
            assert evidence["complete"] and [row["path"] for row in evidence["changes"]] == ["work.txt"]
            assert checkpoint["dispatched"]
        elif number == 2:
            assert not checkpoint["spent"] and not checkpoint["dispatched"]
            assert checkpoint["unattributed_changes"] == {"count": 2, "paths": [".DS_Store", "notes.txt"]}
        else:
            assert not evidence["complete"] and evidence["omissions"] == ["tool_evidence_byte_limit"]
            assert checkpoint["excluded_work"]["reviewed"] is False
        if number == 5:
            assert checkpoint["excluded_work"]["reviewed"] is False
            assert checkpoint["excluded_work"]["turns"] == 1
        stops = [
            row
            for row in hooks
            if row["hook"] == ["codex-stop"] and json.loads(row["stdin"])["turn_id"] == checkpoint["turn_id"]
        ]
        assert len(stops) == 1
        wire = json.loads(stops[0]["stdout"])
        assert wire.get("decision") != "block"
        turns.append(
            {
                "turn": number,
                "state": checkpoint["status"],
                "turn_id": checkpoint["turn_id"],
                "spent": checkpoint["spent"],
                "dispatched": checkpoint["dispatched"],
                "coverage": checkpoint["coverage"],
                "unattributed_changes": checkpoint["unattributed_changes"],
                "excluded_work": checkpoint["excluded_work"],
                "evidence": evidence,
                "stop_wire": wire,
                "stop_elapsed_seconds": stops[0]["elapsed_seconds"],
            }
        )
    reviewer = rows(native / "reviewer.jsonl")
    dispatches = [row for row in reviewer if row["kind"] == "dispatch_started"]
    assert len(dispatches) == 4 and len({row["pid"] for row in dispatches}) == 4
    assert all(row["synthetic"] for row in reviewer)
    for path in native.glob("reviewer-*.prompt.txt"):
        assert "notes.txt" not in path.read_text() and ".DS_Store" not in path.read_text()
    assert (root / "project/notes.txt").read_text() == "Operator-owned notes between turns. Preserve this exact text.\n"
    assert (root / "project/work.txt").read_text() == "FIRST\nSECOND\nTHIRD\n"
    reservation = rows(root / "turns.jsonl")
    assert sum(row["reserved_turns"] for row in reservation) == 8
    source = read(root / "product-source-hashes.json")
    drift = {
        path: {"run": digest, "current": sha(CHECKOUT / path)}
        for path, digest in source.items()
        if sha(CHECKOUT / path) != digest
    }
    assert set(drift) <= {"src/forge/policy/semantic/stop_review.py"}
    command = read(native / "run/command.json")
    execution_helpers = [
        "b4-attribution.py",
        "b4-terminal.py",
        "b4-product.py",
        "b4-gate.py",
        "b4-cases.py",
        "probe-runtime.py",
        "hooks/b4-hook.py",
        "hooks/b4-reviewer.py",
        "hooks/b3-reviewer.py",
        "b4_instrumentation/sitecustomize.py",
        "b3_instrumentation/sitecustomize.py",
    ]
    for name in execution_helpers:
        assert sha(SCRIPTS / name) == command["harness_files"][name], name
    teardown = read(root / "teardown.json")
    assert not teardown["survivors_before_sweep"] and not teardown["remaining"]
    assert teardown["fixture_auth_removed"]
    return {
        "cases": cases,
        "turns": turns,
        "native_completed_turns": len(completed),
        "reserved_units": 8,
        "local_stub_reviews": 4,
        "real_reviewer_inference": False,
        "identity": read(root / "identity.json"),
        "stub_admission": read(root / "stub-admission.json"),
        "execution_helper_hashes": {name: command["harness_files"][name] for name in execution_helpers},
        "source_files": len(source),
        "source_inventory_sha256": sha(root / "product-source-hashes.json"),
        "post_run_product_drift": drift,
        "drift_qualification": "After this native run, two unexercised missing-tracking branches were tightened: failed baseline capture remains outstanding until exclusion, and an unknown newer Stop counts an unfinished preceding turn as excluded. Automated regressions cover both. No native result is relabelled as testing those changes.",
        "teardown": teardown,
        "publication_helpers": {
            str(path.relative_to(SCRIPTS)): sha(path)
            for path in (
                Path(__file__),
                SCRIPTS / "b4-close.py",
                SCRIPTS / "b4-fixture.py",
                SCRIPTS / "b4-validate-stub.py",
            )
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root.resolve())
    # All published strings come from the owned fixture. Keep normal host paths,
    # raw terminal streams, login files and full rollouts out of the artifact.
    encoded = (
        json.dumps(result, indent=2).replace(str(args.root.resolve()), "<round>").replace(str(CHECKOUT), "<checkout>")
    )
    args.output.write_text(encoded + "\n")
    print(
        json.dumps(
            {"verified": True, "reserved_units": result["reserved_units"], "reviews": result["local_stub_reviews"]}
        )
    )


if __name__ == "__main__":
    main()
