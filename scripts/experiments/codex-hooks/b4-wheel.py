#!/usr/bin/env python3
"""Verify a clean B4 wheel with owned lifecycle homes and the trusted round dispatcher."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
GATE = runpy.run_path(str(SCRIPTS / "b4-gate.py"))
PRODUCT = runpy.run_path(str(SCRIPTS / "b4-product.py"))


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def lifecycle(root: Path, forge: Path) -> dict:
    sandbox = root / "wheel-lifecycle"
    sandbox.mkdir(exist_ok=False)
    for name in ("home", "codex-home", "forge-home", "project"):
        (sandbox / name).mkdir()
    env = dict(
        os.environ,
        HOME=str(sandbox / "home"),
        CODEX_HOME=str(sandbox / "codex-home"),
        FORGE_HOME=str(sandbox / "forge-home"),
    )
    config = sandbox / "codex-home/config.toml"
    unrelated = '# B4 unrelated operator setting\nmodel = "gpt-6.1-sol"\n'
    config.write_text(unrelated)
    report: dict[str, Any] = {"commands": []}
    commands = [
        ["runtime", "list", "--json"],
        ["extension", "enable", "--scope", "user", "--runtime", "all", "--profile", "full"],
        ["extension", "status", "--json"],
        ["extension", "sync", "--scope", "user"],
        ["extension", "disable", "--scope", "user", "--runtime", "codex", "--yes"],
        ["extension", "status", "--json"],
        ["extension", "sync", "--scope", "user"],
        ["extension", "disable", "--scope", "user", "--yes"],
    ]
    for command in commands:
        result = subprocess.run(
            [str(forge), *command], env=env, cwd=sandbox / "project", capture_output=True, text=True, timeout=90
        )
        report["commands"].append(vars(result))
        (root / "wheel-lifecycle.json").write_text(json.dumps(report, default=str, indent=2))
        result.check_returncode()
        if command[:2] == ["extension", "enable"]:
            for event in ("codex-turn-start", "codex-turn-tool", "codex-stop"):
                assert event in config.read_text()
            assert (sandbox / "home/.agents/skills/smoke-test/SKILL.md").is_file()
    assert config.read_text() == unrelated
    report["unrelated_config_preserved"] = True
    (root / "wheel-lifecycle.json").write_text(json.dumps(report, default=str, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("action", choices=("lifecycle", "enroll", "correction"))
    parser.add_argument("--label")
    parser.add_argument("--session", default="b4-tui-child-final")
    args = parser.parse_args()
    root = args.root.resolve()
    GATE["validate"](root)
    installed = root / "wheel-env"
    if "FORGE_DEV" in os.environ or Path(sys.prefix) != installed:
        raise ValueError("Use the clean wheel Python without FORGE_DEV")
    import forge
    from forge.core.reactive.session_runner import run_claude_session

    if not Path(forge.__file__).is_relative_to(installed):
        raise ValueError("Forge must import from the installed wheel")
    launcher = installed / "bin/forge"
    paths = [root / "codex-home/config.toml", root / "forge-home/bin/forge-hook"]
    before = {str(path): digest(path) for path in paths}
    metadata = root / "forge-home/runtime.json"
    original = metadata.read_bytes()
    routing = json.loads(original)
    routing["forge_binary_path"] = str(launcher)
    metadata.write_text(json.dumps(routing, indent=2) + "\n")
    report = {
        "wheel_sha256": digest(next((root / "wheel").glob("*.whl"))),
        "forge_module": forge.__file__,
        "before": before,
        "metadata_override": routing,
        "qualification": "Only the owned fixture launcher metadata is temporarily overridden; trusted dispatcher bytes stay fixed.",
        "source_revision": subprocess.check_output(
            ["git", "-C", str(SCRIPTS.parents[2]), "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_diff_sha256": hashlib.sha256(
            subprocess.check_output(
                ["git", "-C", str(SCRIPTS.parents[2]), "diff", "HEAD", "--", "src", "scripts/experiments/codex-hooks"]
            )
        ).hexdigest(),
    }
    try:
        doctor = subprocess.run(
            [str(launcher), "extension", "doctor", "--json"], capture_output=True, text=True, timeout=30
        )
        doctor.check_returncode()
        report["doctor"] = json.loads(doctor.stdout)
        assert report["doctor"]["hook_dispatcher"]["dev_override"]["effective"] is False
        if args.action == "lifecycle":
            report["lifecycle"] = lifecycle(root, launcher)
            refusal = run_claude_session(
                "Must never infer",
                worker=True,
                direct=True,
                read_only=True,
                subscription_only=True,
                extra_env={"B4_STUB_LOGGED_OUT": "1"},
                cwd=str(root / "project"),
                timeout_seconds=12,
            )
            report["logged_out_refusal"] = asdict(refusal)
            assert not refusal.success and not refusal.dispatched
            return 0
        if not args.label:
            raise ValueError("Native controls need a unique capture label")
        if args.action == "enroll":
            command = [str(launcher), "runtime", "preflight", "codex", "--verify-enrollment", "--json"]
            code = GATE["execute"](root, args.label, {}, command, 180)
            if code == 0:
                result_path = root / "captures" / args.label / "run/stdout"
                assert json.loads(result_path.read_text())["stop_review_enrolled"]
                GATE["seal"](root, result_path)
        else:
            PRODUCT["configure"](root, str(launcher), session=args.session)
            os.environ["PROBE_TURN_RESERVATION"] = "2"
            control = {
                "verdict": {
                    "verdict": "divergent",
                    "confidence": 0.99,
                    "violations": [
                        {
                            "severity": "high",
                            "evidence": "B4-WHEEL-REVIEWER-TEXT: product-fix.txt uses BAD.",
                            "suggested_fix": "B4-WHEEL-REVIEWER-TEXT: use GOOD.",
                            "citations": ["Use GOOD as the value in product-fix.txt."],
                        }
                    ],
                }
            }
            command = [
                str(launcher),
                "session",
                "resume",
                args.session,
                "--task",
                "Use apply_patch to set product-fix.txt to BAD. Preserve other files and finish.",
            ]
            code = GATE["execute"](root, args.label, control, command, 180)
            PRODUCT["retain_product"](root, root / "captures" / args.label, str(launcher), args.session)
        report["capture"] = args.label
        report["exit"] = code
        return code
    finally:
        metadata.write_bytes(original)
        report["after"] = {str(path): digest(path) for path in paths}
        report["routing_restored"] = metadata.read_bytes() == original
        (root / ("wheel-" + args.action + "-verification.json")).write_text(
            json.dumps(report, default=str, indent=2) + "\n"
        )
        assert before == report["after"]


if __name__ == "__main__":
    raise SystemExit(main())
