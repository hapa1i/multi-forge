#!/usr/bin/env python3
"""Assert and export B5 product facts without copying auth or native histories."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def export(root: Path, output: Path) -> None:
    assert (root / "B5_ROUND").read_text() == "independent-b5-round-v1\n"
    starts = rows(root / "starts.jsonl")
    product = [row for row in starts if row["case"] in {"P1", "P2"}]
    assert len(starts) == 60 and len(product) == 12
    assert sum(row["auth_mode"] == "api" for row in starts) == 3
    assert sum(row["role"] == "reviewer" for row in product) == 6
    invocations = {row["id"]: row for row in rows(root / "product-invocations.jsonl")}
    outcomes = {row["id"]: row for row in rows(root / "product-outcomes.jsonl")}
    usage = [row for path in (root / "forge-home/usage/events").glob("*.jsonl") for row in rows(path)]
    attempts = []
    for path in (root / "forge-home/telemetry/supervisor_attempts").glob("*.json"):
        row = json.loads(path.read_text())
        native = row.get("native_review")
        if not native or not native.get("reviewer_thread_id"):
            continue
        assert row["state"] == "completed" and native["inputs_preserved"]
        matched = [event for event in usage if event["run_id"] == row["model_run_id"]]
        assert len(matched) == 1
        event = matched[0]
        assert event["command"] == "supervisor" and event["session"] == row["session"]
        assert event["billing_mode"] == "subscription_quota" and event["cost_micro_usd"] is None
        for key in ("input_tokens", "output_tokens", "cached_tokens"):
            assert native["review_usage"][key] == native["terminal_usage"][key] - native["inherited_usage"][key]
            assert event[key] == native["review_usage"][key]
        for prefix in native["prefixes"]:
            paths = list((root / "codex-home/sessions").rglob(f'*{prefix["thread_id"]}.jsonl'))
            assert len(paths) == 1
            with paths[0].open("rb") as stream:
                assert hashlib.sha256(stream.read(prefix["bytes"])).hexdigest() == prefix["sha256"]
        attempts.append(
            {
                key: row[key]
                for key in (
                    "attempt_id",
                    "session",
                    "origin",
                    "tool_name",
                    "plan_digest",
                    "model",
                    "effort",
                    "auth_mode",
                    "state",
                    "verdict",
                    "model_run_id",
                    "native_review",
                )
            }
        )
    assert len(attempts) == 6
    cases = {}
    for label in sorted({Path(row["capture"]).name for row in product}):
        capture = root / "captures" / label
        hooks = rows(capture / "product-hooks.jsonl")
        compact = []
        for hook in hooks:
            assert hook["dev_override"] is None and "/site-packages/forge/" in hook["forge_module"]
            payload = json.loads(hook["stdin"])
            wire = json.loads(hook["stdout"]) if hook["stdout"].strip() else {}
            compact.append(
                {
                    "hook": hook["hook"],
                    "elapsed_seconds": hook["elapsed_seconds"],
                    "executor_thread_id": payload.get("session_id"),
                    "turn_id": payload.get("turn_id"),
                    "forge_module": hook["forge_module"],
                    "wire": wire,
                }
            )
            model_text = wire.get("reason") or wire.get("hookSpecificOutput", {}).get("permissionDecisionReason")
            if model_text and payload.get("session_id"):
                paths = list((root / "codex-home/sessions").rglob(f'*{payload["session_id"]}.jsonl'))
                assert len(paths) == 1
                compact[-1]["model_feedback_in_native_history"] = any(
                    model_text in json.dumps(item, ensure_ascii=False).replace("\\n", "\n").replace('\\"', '"')
                    for item in rows(paths[0])
                )
                assert compact[-1]["model_feedback_in_native_history"]
        cases[label] = {"hooks": compact}
    for label in ("product-shared-stop", "product-wheel-stop"):
        stops = [hook for hook in cases[label]["hooks"] if hook["hook"] == ["codex-stop"]]
        assert len(stops) == 2 and stops[0]["wire"]["decision"] == "block" and "decision" not in stops[1]["wire"]
        assert len({hook["turn_id"] for hook in stops}) == 1
    assert (root / "action/product-allow.txt").read_text().strip() == "amber"
    assert not (root / "action/product-deny.txt").exists() and not (root / "action/product-p2-deny.txt").exists()
    assert all(
        (root / f"action/{name}").read_text().strip() == "COBALT"
        for name in ("product-stop.txt", "product-p2-stop.txt")
    )
    source_only = next(h for h in cases["product-wheel-source-only"]["hooks"] if h["hook"] == ["codex-policy-check"])
    assert "No verified plan quotation" in source_only["wire"]["hookSpecificOutput"]["permissionDecisionReason"]
    last_stop = next(h for h in cases["product-wheel-stop"]["hooks"] if h["hook"] == ["codex-stop"])
    assert "verified approved-plan quotations" in last_stop["wire"]["reason"]
    selected = []
    for row in product:
        invocation, outcome = invocations[row["id"]], outcomes[row["id"]]
        assert outcome["returncode"] == 0
        if row["role"] == "reviewer":
            assert not {
                "FORGE_SESSION",
                "FORGE_FORGE_ROOT",
                "FORGE_DEV",
                "FORGE_RUN_ID",
                "FORGE_CODEX_EXECUTOR_IDENTITY",
            } & set(invocation["env_keys"])
            assert invocation["argv"][-1] == "-"
            assert invocation["argv"].index('forced_login_method="chatgpt"') > invocation["argv"].index("fork")
            if Path(row["capture"]).name == "product-wheel-stop":
                assert outcome["global_ignore_sentinel_seen"] is False
        selected.append({**row, "invocation": invocation, "outcome": outcome})
    repo = Path(__file__).resolve().parents[3]
    installed = next((root / "product-final-wheel/lib").glob("python*/site-packages/forge"))
    code_hashes = {
        str(path.relative_to(installed)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in installed.rglob("*.py")
    }
    drift = [
        name
        for name, digest in code_hashes.items()
        if hashlib.sha256(
            (
                repo / "src" / name.removeprefix("_extensions/")
                if name.startswith("_extensions/")
                else repo / "src/forge" / name
            ).read_bytes()
        ).hexdigest()
        != digest
    ]
    assert not drift, drift
    previous = json.loads((root / "product-p1-source-hashes.json").read_text())
    report = {
        "total_starts": len(starts),
        "api_starts": 3,
        "product_starts": selected,
        "attempts": attempts,
        "cases": cases,
        "wheel": json.loads((root / "product-wheel-identity.json").read_text()),
        "installed_source_sha256": [{"path": name, "sha256": digest} for name, digest in sorted(code_hashes.items())],
        "p1_to_final_changed_modules": [name for name, digest in code_hashes.items() if previous.get(name) != digest],
        "operator_surfaces": [
            row for row in json.loads((root / "product-operator-surfaces.json").read_text()) if row["returncode"] != 2
        ],
        "qualifications": [
            "P1 and the first P2 pair precede the final stale-input revalidation guard; final P2 Stop uses the final wheel.",
            "P1 Claude adapter uses a synthetic hook payload with a real Codex reviewer; no real Claude executor was started.",
            "Claude adapter observer failed at exit on an empty byte-write probe; native result, usage and attempt evidence survived.",
            "Product API setup uses a synthetic key without inference; runtime API evidence is the three earlier gate starts.",
            "Original active executor sources advance after Stop returns; each selected prefix remains byte-identical.",
        ],
    }
    encoded = json.dumps(report, sort_keys=True, indent=2).replace(str(root), "$ROUND").replace(str(repo), "$WORKSPACE")
    output.write_text(encoded + "\n")
    print(json.dumps({"output": str(output), "reviewers": len(attempts), "starts": len(starts), "source_drift": drift}))


if __name__ == "__main__":
    export(Path(sys.argv[1]), Path(sys.argv[2]))
