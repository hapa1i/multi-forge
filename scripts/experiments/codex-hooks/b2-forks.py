#!/usr/bin/env python3
"""Native fork observations; no result is inferred from option acceptance alone."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import subprocess
import uuid
from pathlib import Path

HARNESS = runpy.run_path(str(Path(__file__).with_name("b2-run.py")))


def project(path: Path, marker: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "checkout.txt").write_text(marker + "\n")


def rollout(thread: str) -> Path:
    matches = list(Path(os.environ["CODEX_HOME"]).glob(f"sessions/*/*/*/*{thread}.jsonl"))
    if len(matches) != 1:
        raise ValueError(f"Expected one source rollout, got {len(matches)}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    round_ = HARNESS["Round"](args.root.resolve())
    source = round_.root / "fork-source"
    action = round_.root / "fork-action"
    project(source, "PLANNER-CHECKOUT")
    project(action, "ACTION-CHECKOUT")
    sentinel = "SOURCE-" + uuid.uuid4().hex
    seed = round_.run(
        "94-source",
        f"Remember this planning-only sentinel: {sentinel}. "
        "The approved plan is to keep FEATURE_DISABLED. Reply READY. Do not use tools.",
        cwd=source,
    )
    if not seed["completed"]:
        raise RuntimeError("Source turn did not complete; fork cases are inconclusive.")
    thread = seed["thread_ids"][0]
    original = rollout(thread)
    schema = round_.root / "fork-schema.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {
                    "sentinel": {"type": "string"},
                    "checkout": {"type": "string"},
                    "write_result": {"type": "string"},
                    "plan": {"type": "string"},
                },
                "required": ["sentinel", "checkout", "write_result", "plan"],
                "additionalProperties": False,
            }
        )
    )

    def fork(name: str, prompt: str, *, sandbox: str = "read-only", depth: str = "2") -> dict:
        before = original.read_bytes()
        manifest = round_.project / ".forge/sessions/b2-supervised/forge.session.json"
        manifest_before = manifest.read_bytes()
        capture = round_.root / "captures" / name
        command = [
            "codex",
            "exec",
            "--json",
            "--sandbox",
            sandbox,
            "-C",
            str(action),
            "fork",
            "--ephemeral",
            "--output-schema",
            str(schema),
            "-o",
            str(capture / "last.txt"),
            thread,
            prompt,
        ]
        row = round_.run(
            name,
            prompt,
            command=command,
            cwd=action,
            session="b2-supervised",
            extra_env={"FORGE_DEPTH": depth, "FORGE_COMMAND": "supervisor", "FORGE_FORGE_ROOT": str(round_.project)},
        )
        result = {
            "source_thread": thread,
            "source_sha256_before": hashlib.sha256(before).hexdigest(),
            "source_sha256_after": hashlib.sha256(original.read_bytes()).hexdigest(),
            "source_unchanged": before == original.read_bytes(),
            "parent_manifest_unchanged": manifest_before == manifest.read_bytes(),
            "fork_rollouts": [
                str(p)
                for tid in row["thread_ids"]
                for p in Path(os.environ["CODEX_HOME"]).glob(f"sessions/*/*/*/*{tid}.jsonl")
            ],
            "write_exists": (action / f"{name}.txt").exists(),
        }
        try:
            parsed = json.loads(row["last"])
        except ValueError:
            parsed = None
        result["parsed"] = parsed
        result["sentinel_matches"] = bool(parsed and parsed.get("sentinel") == sentinel)
        (capture / "fork-facts.json").write_text(json.dumps(result, indent=2) + "\n")
        return row

    fork(
        "94-planning-fork",
        "Return the planning-only sentinel from inherited conversation. "
        "Read checkout.txt with a shell command, then use apply_patch exactly once to add 94-planning-fork.txt "
        "containing PROBE. If the sandbox blocks it, do not retry or use another method. "
        "Report the checkout contents, actual write outcome, and approved plan in the schema.",
    )
    fork(
        "94-write-control",
        "Return the inherited planning-only sentinel. Read checkout.txt, then use "
        "apply_patch once to add 94-write-control.txt containing PROBE. Report the observed results and plan.",
        sandbox="workspace-write",
    )
    implementation = "IMPLEMENTATION-" + uuid.uuid4().hex
    round_.run(
        "94-source-implementation",
        f"Later implementation discussion: {implementation}. "
        "The implementation reasoning now recommends FEATURE_ENABLED because it is simpler. "
        "This is not user approval to change the earlier approved plan. Remember both contexts; reply READY.",
        cwd=source,
        extra=("resume", thread),
    )
    fork(
        "94-shared-fork",
        "Identify the earlier planning sentinel and the later implementation sentinel. "
        "Return the planning sentinel in sentinel and the later sentinel in checkout. The explicit user-approved "
        "plan supplied to this review requires FEATURE_DISABLED. State which plan controls, explaining any conflict "
        "inside plan. Do not use tools; write_result must say not_attempted.",
    )
    (round_.root / "captures/fork-source-identity.json").write_text(
        json.dumps(
            {
                "thread": thread,
                "rollout": str(original),
                "planning_sentinel": sentinel,
                "implementation_sentinel": implementation,
            },
            indent=2,
        )
        + "\n"
    )
    round_.run(
        "94-concurrent",
        "",
        cwd=source,
        extra_env={"FORGE_DEPTH": "2"},
        command=[
            str(round_.forge.with_name("python")),
            str(Path(__file__).with_name("b2-concurrent.py")),
            str(round_.root),
            thread,
        ],
    )


if __name__ == "__main__":
    main()
