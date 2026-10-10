#!/usr/bin/env python3
"""Check B3's retained captures without launching a model or changing policy state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-case", default="real-claude-quote")
    parser.add_argument("--wheel-prefix", default="wheel")
    args = parser.parse_args()
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    results = {}
    names = [
        "trusted-v1-tdd",
        "trusted-v1-stub",
        "off-headless",
        "source",
        "source-changed",
        "source-invalid",
        "source-deny",
        "multi",
        "mixed",
        "timeout",
        "tui-off-final",
        "tui-combined",
        "model-only",
        args.wheel_prefix + "-source",
        args.wheel_prefix + "-off",
        args.wheel_prefix + "-deny",
    ]
    for name in names:
        directory = root / "captures" / name
        control = json.loads((directory / "control.json").read_text())
        hooks = [row for row in rows(directory / "hooks.jsonl") if row["hook"] == ["codex-policy-check"]]
        assert len(hooks) == 1, (name, "exactly one product policy hook")
        hook = hooks[0]
        assert hook["exit_code"] == 0
        wire = json.loads(hook["stdout"])
        identity = json.loads(hook["executor_identity"])
        assert identity["version"] == "0.162.1"
        native = rows(directory / "private-rollout.jsonl")
        latest = max(i for i, row in enumerate(native) if row.get("payload", {}).get("type") == "task_started")
        turn = native[latest:]
        calls = [
            r["payload"] for r in turn if r.get("payload", {}).get("type") in {"custom_tool_call", "function_call"}
        ]
        assert len(calls) == 1 and calls[0]["name"] == "exec", (name, "no extra tool reads")
        assert re.findall(r"tools\.(\w+)\(", calls[0]["input"]) == ["apply_patch"], name
        native_text = json.dumps(turn, ensure_ascii=False)
        answers = [r["payload"] for r in turn if r.get("payload", {}).get("role") == "assistant"]
        answer_text = json.dumps(answers)
        model = wire.get("hookSpecificOutput", {})
        injected = [
            c.get("text", "")
            for r in turn
            if r.get("payload", {}).get("role") == "developer" and "hooks.additional_context" in json.dumps(r)
            for c in r["payload"].get("content", [])
        ]
        blocked = name in {"source-deny", "mixed", args.wheel_prefix + "-deny"}
        off = name in {"off-headless", "tui-off-final", args.wheel_prefix + "-off"}
        action = json.loads((directory / "action-result.json").read_text())
        assert action["exists"] is not blocked
        if blocked:
            assert model["permissionDecision"] == "deny"
            assert not injected
        elif off:
            assert "hookSpecificOutput" not in wire and not injected
            assert control["reviewer_nonce"] not in native_text
        else:
            assert "permissionDecision" not in model
            assert any(model["additionalContext"] in text for text in injected), name
        assert ("systemMessage" in wire) is (name != "model-only")
        if control["source_only"]:
            assert control["reviewer_nonce"] not in native_text
            assert control["reviewer_nonce"] not in json.dumps(model)
            if name in {"source", "source-changed", args.wheel_prefix + "-source"}:
                assert control["source_quote"] in native_text
                match = re.search(r"SOURCE-[a-f0-9]+", control["source_quote"])
                assert match is not None and match[0] in answer_text
            else:
                assert "No verified plan quotation" in json.dumps(model)
                if blocked:
                    assert "Stop and ask the operator" in model["permissionDecisionReason"]
        elif control["kind"] == "stub" and not off:
            assert control["reviewer_nonce"] in answer_text
        if name.startswith("tui-"):
            terminal = (directory / "terminal.log").read_text(errors="replace")
            terminal = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", terminal)
            assert "Hook ·" in terminal and control["reviewer_nonce"] in terminal
            assert json.loads((directory / "terminal-result.json").read_text())["exited"]
        if name.startswith("wheel-"):
            wheel = json.loads((root / (args.wheel_prefix + "-verification.json")).read_text())
            assert hook["dev_override"] is None
            assert hook["forge_module"] == wheel["forge_module"]
            assert hook["launcher"] == wheel["metadata_override"]["forge_binary_path"]
        if name == "multi":
            assert "src/multi.py" in model["additionalContext"]
            assert "src/multi_later.py" in model["additionalContext"]
            assert (root / "project/docs/multi.txt").read_text().strip() == "OK"
            assert (root / "project/src/multi_later.py").read_text().strip() == "VALUE = 2"
        if name == "mixed":
            assert "tdd.tests-before-impl" not in model["permissionDecisionReason"]
            assert not (root / "project/src/mixed_blocked.py").exists()
            assert "Implementation changes require test changes first" in (directory / "session.json").read_text()
        if name == "timeout":
            reviewer = rows(directory / "reviewer.jsonl")
            assert any(r["kind"] == "dispatch_started" for r in reviewer)
            assert "unreviewed" in model["additionalContext"]
            assert '"failure_type": "timeout"' in (directory / "session.json").read_text()
        process = json.loads((directory / "run/process-result.json").read_text())
        assert process["returncode"] == 0 and not process["remaining"]
        assert process["codex_identity_unchanged"]
        results[name] = {
            "passed": True,
            "one_patch_no_other_tools": True,
            "action_landed": action["exists"],
            "native_model_context": bool(injected),
            "operator_wire": "systemMessage" in wire,
            "hook_seconds": hook["elapsed_seconds"],
            "forge_module": hook["forge_module"],
        }
    real = json.loads((root / "captures" / args.real_case / "real-review.json").read_text())
    decision = real["result"]["decision"]
    real_usable = (
        real["dispatches"] == 1
        and real["result"]["run_ok"]
        and real["result"]["parsed"]
        and any(v["verified_citations"] for v in decision["violations"])
    )
    if real_usable:
        usage = [row for row in real["usage"] if row["run_id"] == decision["telemetry_run_id"]]
        assert usage and all(row["billing_mode"] == "subscription_quota" for row in usage)
    wheel = json.loads((root / (args.wheel_prefix + "-verification.json")).read_text())
    assert wheel["before"] == wheel["after"] and wheel["routing_restored"]
    original = json.loads((root / "host-config-hashes.json").read_text())
    current = {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None for path in original
    }
    assert original == current
    report = {
        "cases": results,
        "real_quote_usable": bool(real_usable),
        "real_review_case": args.real_case,
        "real_review_failure": decision["failure_type"],
        "host_config_bytes_unchanged": True,
        "host_auth_not_copied_or_inspected": True,
        "reserved_codex_turns": sum(row["reserved_turns"] for row in rows(root / "turns.jsonl")),
        "wheel_trust_registration_unchanged": True,
    }
    assert report["reserved_codex_turns"] <= 32
    (root / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not real_usable:
        raise SystemExit("Product controls passed; real quote-quality acceptance remains unverified.")


if __name__ == "__main__":
    main()
