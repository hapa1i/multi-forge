"""Trusted B4 wheel delivery; an explicitly owned, bounded round is mandatory."""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def test_installed_stop_correction_is_one_review_and_remains_unreviewed_afterward() -> None:
    supplied = os.environ.get("B4_TEST_ROUND")
    if not supplied:
        pytest.fail(
            "Set B4_TEST_ROUND to an independently authenticated, enrolled B4 round; no developer login default"
        )
    root = Path(supplied).resolve()
    assert (root / "B4_ROUND").read_text().strip() == "independent-b4-round-v1"
    assert (root / "ENROLLED").is_file() and not (root / "CLOSED").exists()
    installed = root / "wheel-env"
    label = os.environ.get("B4_TEST_LABEL", "24-wheel-correction")
    script = Path(__file__).resolve().parents[3] / "scripts/experiments/codex-hooks/b4-wheel.py"
    path = ":".join(
        map(
            str,
            (
                installed / "bin",
                root / "stub-bin",
                root / "bin",
                Path("/opt/homebrew/bin"),
                Path("/usr/bin"),
                Path("/bin"),
                Path("/usr/sbin"),
                Path("/sbin"),
            ),
        )
    )
    result = subprocess.run(
        [
            str(root / "run"),
            "/usr/bin/env",
            "-u",
            "FORGE_DEV",
            "PATH=" + path,
            str(installed / "bin/python"),
            str(script),
            str(root),
            "correction",
            "--label",
            label,
        ],
        capture_output=True,
        text=True,
        timeout=220,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    capture = root / "captures" / label
    hooks = [json.loads(line) for line in (capture / "hooks.jsonl").read_text().splitlines()]
    assert hooks and all(Path(h["forge_module"]).is_relative_to(installed) and h["dev_override"] is None for h in hooks)
    starts = [h for h in hooks if h["hook"] == ["codex-turn-start"]]
    stops = [h for h in hooks if h["hook"] == ["codex-stop"]]
    assert len(starts) == 1 and len(stops) == 2
    assert len({json.loads(h["stdin"])["turn_id"] for h in starts + stops}) == 1
    first, second = [json.loads(h["stdout"]) for h in stops]
    assert first["decision"] == "block" and "decision" not in second
    assert "Use GOOD as the value in product-fix.txt." in first["reason"]
    assert "B4-WHEEL-REVIEWER-TEXT" not in first["reason"]
    events = [json.loads(line) for line in (capture / "reviewer.jsonl").read_text().splitlines()]
    assert sum(e["kind"] == "dispatch_started" for e in events) == 1
    assert (root / "project/product-fix.txt").read_text().strip() == "GOOD"
    status = json.loads(json.loads((capture / "supervisor-status.json").read_text())["stdout"])
    turn = status["supervisor"]["turn_review"]
    assert turn["state"] == "unreviewed" and turn["spent"] and turn["correction_consumed"] and turn["outstanding"]
    rollouts = [json.loads(line) for file in capture.glob("rollout-*.jsonl") for line in file.read_text().splitlines()]
    injected = [
        r
        for r in rollouts
        if r.get("type") == "response_item"
        and r["payload"].get("role") == "user"
        and first["reason"] in "".join(c.get("text", "") for c in r["payload"].get("content", []))
    ]
    assert injected and all(r["metadata"]["client_authored"] is False for r in injected)
    stream = [
        json.loads(line) for file in capture.glob("*-native-stream.jsonl") for line in file.read_text().splitlines()
    ]
    assert any(r.get("type") == "turn.completed" and r.get("usage", {}).get("input_tokens", 0) > 0 for r in stream)
    cleanup = json.loads((capture / "run/process-result.json").read_text())
    assert not cleanup["survivors_before_sweep"] and not cleanup["remaining"]
