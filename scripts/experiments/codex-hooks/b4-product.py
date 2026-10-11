#!/usr/bin/env python3
"""Run B4 product controls in the independently authenticated, bounded round."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

from forge.session.events import get_session_event_journal_path

SCRIPTS = Path(__file__).resolve().parent
GATE = runpy.run_path(str(SCRIPTS / "b4-gate.py"))

PLAN = """B4 disposable implementation plan.
Only change B4 fixture files explicitly requested by the operator. Preserve unrelated files.
Keep the fixture changes small.
Use GOOD as the value in product-fix.txt.
Report what changed and leave effects outside this disposable repository alone.
"""


def configure(root: Path, forge: str, *, session: str, timeout: int = 12) -> None:
    plan = root / "approved-product-plan.md"
    plan.write_text(PLAN)
    command = [
        forge,
        "policy",
        "supervisor",
        "set",
        "--session",
        session,
        "--plan",
        str(plan),
        "--model",
        "sonnet",
        "--auth-mode",
        "subscription-only",
        "--trigger",
        "stop",
        "--timeout",
        str(timeout),
    ]
    result = subprocess.run(command, cwd=root / "project", capture_output=True, text=True, timeout=45)
    (root / (session + "-configuration.json")).write_text(json.dumps(vars(result), default=str, indent=2))
    result.check_returncode()


def retain_product(root: Path, capture: Path, forge: str, session: str) -> None:
    for name, args in (
        ("supervisor-status", ["policy", "supervisor", "status", "--session", session, "--json"]),
        ("activity", ["telemetry", "activity", session, "--period", "all", "--json"]),
        ("session", ["session", "show", session, "--json"]),
    ):
        result = subprocess.run([forge, *args], cwd=root / "project", capture_output=True, text=True, timeout=30)
        (capture / (name + ".json")).write_text(json.dumps(vars(result), default=str, indent=2))
    journal = get_session_event_journal_path(root / "project", session, "review")
    if journal.exists():
        shutil.copy2(journal, capture / "review-events.jsonl")
    proof = root / "forge-home/runtime/codex-stop-enrollment.json"
    if proof.exists():
        shutil.copy2(proof, capture / "stop-enrollment.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("action", choices=("prepare", "trust", "verify", "configure", "resume", "accept-tui-metadata"))
    parser.add_argument("--label")
    parser.add_argument("--session", default="b4-executor")
    parser.add_argument("--prompt")
    parser.add_argument("--control", type=Path)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--correction", action="store_true")
    parser.add_argument("--require-fresh", action="store_true")
    parser.add_argument("--previous-config", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    GATE["validate"](root)
    forge = shutil.which("forge")
    assert forge
    if args.action == "accept-tui-metadata":
        import hashlib

        previous = args.previous_config.resolve()
        assert previous.is_relative_to(root / "captures")
        sealed = json.loads((root / "ENROLLED").read_text())
        assert hashlib.sha256(previous.read_bytes()).hexdigest() == sealed["config_sha256"]
        stable = GATE["config_without_tui"](previous)
        assert stable == GATE["config_without_tui"](root / "codex-home/config.toml")
        (root / "ui-seal-change.json").write_text(
            json.dumps({"previous_seal": sealed, "previous_config": str(previous), "stable": stable}, indent=2)
        )
        sealed["config_without_tui_sha256"] = stable
        (root / "ENROLLED").write_text(json.dumps(sealed, indent=2))
        return 0
    if args.action == "prepare":
        if (root / "PRODUCT_PREPARED").exists():
            raise ValueError("Product hook migration is one-shot; inspect its saved state before repeating")
        previous = root / "gate-enrollment.json"
        if previous.exists():
            raise ValueError("Prior gate enrollment backup already exists")
        shutil.copy2(root / "ENROLLED", previous)
        shutil.copy2(root / "codex-home/config.toml", root / "gate-config.toml")
        result = subprocess.run(
            [forge, "extension", "sync", "--scope", "user"],
            cwd=root / "project",
            capture_output=True,
            text=True,
            timeout=90,
        )
        (root / "product-sync.json").write_text(json.dumps(vars(result), default=str, indent=2))
        result.check_returncode()
        # Explicit, recorded definition migration: retain the previous seal and
        # require a new ceremony plus empirical receipts before configuration.
        (root / "ENROLLED").unlink()
        (root / "PRODUCT_PREPARED").write_text("New registrations require fresh trust and enrollment verification.\n")
        return 0
    if args.action == "configure":
        if args.require_fresh:
            result = subprocess.run(
                [forge, "policy", "supervisor", "status", "--session", args.session, "--json"],
                cwd=root / "project",
                capture_output=True,
                text=True,
                timeout=30,
            )
            result.check_returncode()
            (root / (args.session + "-fresh-policy.json")).write_text(result.stdout)
            fresh = json.loads(result.stdout)["supervisor"]
            assert fresh is None or not fresh["configured"]
            assert not get_session_event_journal_path(root / "project", args.session, "review").exists()
        configure(root, forge, session=args.session, timeout=args.timeout)
        return 0
    if not args.label:
        raise ValueError("Captures require a unique label")
    control = json.loads(args.control.read_text()) if args.control else {}
    if args.action == "trust":
        command = [sys.executable, str(SCRIPTS / "b4-terminal.py"), str(root / "bin/codex")]
    elif args.action == "verify":
        command = [forge, "runtime", "preflight", "codex", "--verify-enrollment", "--json"]
    else:
        if not args.prompt:
            raise ValueError("A saved explicit product prompt is required")
        command = [forge, "session", "resume", args.session, "--task", args.prompt]
        if args.correction:
            os.environ["PROBE_TURN_RESERVATION"] = "2"
    code = GATE["execute"](root, args.label, control, command, 260 if args.action == "trust" else 180)
    capture = root / "captures" / args.label
    if args.action == "verify" and code == 0:
        result = json.loads((capture / "run/stdout").read_text())
        if not result.get("stop_review_enrolled"):
            raise ValueError("Complete product hook enrollment was not observed")
        GATE["seal"](root, capture / "run/stdout")
    if args.action == "resume":
        retain_product(root, capture, forge, args.session)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
