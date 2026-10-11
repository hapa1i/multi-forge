#!/usr/bin/env python3
"""Check B4 native receipts, turn boundaries, Stop feedback and watchdog controls without inference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def events(root: Path, case: str, event: str) -> list[dict]:
    capture = root / "captures" / case
    rows = []
    for path in capture.glob(event + "-*.stdin.json"):
        stem = path.name.removesuffix(".stdin.json")
        rows.append(
            {
                "payload": json.loads(path.read_text()),
                "begin": json.loads((capture / (stem + ".begin.json")).read_text()),
            }
        )
    return sorted(rows, key=lambda r: r["begin"]["started_at"])


def verify(root: Path) -> dict:
    captures = root / "captures"
    enrollment = json.loads((captures / "02-enrollment/run/stdout").read_text())
    assert enrollment["enrolled"] and enrollment["codex_succeeded"]
    assert list((captures / "02-enrollment").glob("*-observation-receipt.json"))
    assert events(root, "02-enrollment", "UserPromptSubmit") and events(root, "02-enrollment", "Stop")
    first = events(root, "03-managed-start", "UserPromptSubmit")
    edits = events(root, "03-managed-start", "PreToolUse")
    stop = events(root, "03-managed-start", "Stop")
    assert len(first) == len(stop) == 1 and len(edits) == 2
    assert first[0]["begin"]["started_at"] < edits[0]["begin"]["started_at"] < stop[0]["begin"]["started_at"]
    assert len({e["payload"]["turn_id"] for e in first + edits + stop}) == 1
    assert "first.txt" not in first[0]["begin"]["snapshot"]["files"]
    assert "first.txt" in stop[0]["begin"]["snapshot"]["files"]
    resume = events(root, "04-managed-resume", "UserPromptSubmit")
    end = events(root, "04-managed-resume", "Stop")
    assert first[0]["payload"]["session_id"] == resume[0]["payload"]["session_id"]
    assert first[0]["payload"]["turn_id"] != resume[0]["payload"]["turn_id"]
    assert resume[0]["begin"]["snapshot"] == end[0]["begin"]["snapshot"]
    tui_start = events(root, "05-tui-multiple", "UserPromptSubmit")
    tui_stop = events(root, "05-tui-multiple", "Stop")
    assert len(tui_start) == len(tui_stop) == 2
    assert len({e["payload"]["turn_id"] for e in tui_start}) == 2
    for start, finish in zip(tui_start, tui_stop, strict=True):
        assert start["payload"]["turn_id"] == finish["payload"]["turn_id"]
        assert start["begin"]["started_at"] < finish["begin"]["started_at"]
    assert "B4-STOP-OPERATOR-NOTICE" in (captures / "05-tui-multiple/terminal.log").read_text()
    for case, marker in (
        ("06-stop-correction", "B4-CORRECTION-RECEIVED"),
        ("07-stop-source", "SOURCE-APPROVED"),
    ):
        starts, stops = events(root, case, "UserPromptSubmit"), events(root, case, "Stop")
        assert len(starts) == 1 and len(stops) == 2
        assert [e["payload"]["stop_hook_active"] for e in stops] == [False, True]
        assert len({e["payload"]["turn_id"] for e in starts + stops}) == 1
        assert marker in (captures / case / "run/stdout").read_text()
        messages = []
        for path in (captures / case).glob("rollout-*.jsonl"):
            for line in path.read_text().splitlines():
                row = json.loads(line)
                if "<hook_prompt " in line and marker in line:
                    messages.append(row)
        assert messages and all(
            m["payload"]["role"] == "user" and m["metadata"]["client_authored"] is False for m in messages
        )
    corrections = events(root, "06-stop-correction", "Stop")
    assert "corrected.txt" not in corrections[0]["begin"]["snapshot"]["files"]
    assert "corrected.txt" in corrections[1]["begin"]["snapshot"]["files"]
    raw_expiry = json.loads((captures / "08-stop-native-expiry/run/process-result.json").read_text())
    assert raw_expiry["survivors_before_sweep"] and not raw_expiry["remaining"]
    for case in ("09-stop-guarded-deadline", "10-stop-guarded-expiry"):
        result = json.loads((captures / case / "run/process-result.json").read_text())
        assert not result["survivors_before_sweep"] and not result["remaining"]
        calls = [json.loads(line) for line in (captures / case / "reviewer.jsonl").read_text().splitlines()]
        assert sum(e["kind"] == "dispatch_started" for e in calls) == 1
        assert any(e["kind"] == "signal" for e in calls)
        assert all(e["begin"]["launch_parent_verified"] for e in events(root, case, "Stop"))
    reservations = [json.loads(line)["reserved_turns"] for line in (root / "turns.jsonl").read_text().splitlines()]
    assert sum(reservations) <= 32
    return {
        "decision": "go",
        "version": json.loads((root / "identity.json").read_text())["version"],
        "turn_units_reserved": sum(reservations),
        "constraints": [
            "Only verified managed launch parents on the measured version are admitted.",
            "UserPromptSubmit is the baseline event; SessionStart alone is insufficient.",
            "Automatic Stop correction keeps the turn ID and does not create a new allowance.",
            "Stop block reason enters user authority; source-only rendering must cover that field.",
            "Stop systemMessage is operator-visible in the TUI; no model receipt is claimed for it.",
            "Native expiry does not own detached descendants; B1 parent-death watchdog is required.",
            "The 90-second guarded-expiry transport is a fault injection, not the product budget.",
            "These are candidate fixtures; all product acceptance and one-dispatch durability checks remain required.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = verify(args.root.resolve())
    (args.root / "gate-decision.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
