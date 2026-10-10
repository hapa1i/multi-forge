#!/usr/bin/env python3
"""Run B3 controls through enrolled product hooks and the round's quota guard."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import uuid
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = runpy.run_path(str(SCRIPTS / "probe-runtime.py"))


class Round:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.project = self.root / "project"
        forge = shutil.which("forge")
        if not forge or (self.root / "B3_ROUND").read_text().strip() != "independent-b3-round-v1":
            raise ValueError("Use the owned B3 round's clean launcher.")
        self.forge = forge
        for key, directory in (("HOME", "home"), ("CODEX_HOME", "codex-home"), ("FORGE_HOME", "forge-home")):
            if Path(os.environ.get(key, "")).resolve() != self.root / directory:
                raise ValueError(f"Explicit independent {key} is required.")
        enrollment = json.loads((self.root / "ENROLLED").read_text())
        digest = hashlib.sha256((self.root / "codex-home/config.toml").read_bytes()).hexdigest()
        if digest != enrollment["config_sha256"] or not enrollment["preflight"]["enrolled"]:
            raise ValueError("Enrollment/config changed; verify it before running another control.")
        if any(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY")):
            raise ValueError("The round forbids API credentials.")
        if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
            raise ValueError("Disable dotenv for the whole round.")

    def setup(self, *args: str) -> subprocess.CompletedProcess:
        result = subprocess.run([self.forge, *args], cwd=self.project, capture_output=True, text=True, timeout=40)
        RUNTIME["append_json"](
            self.root / "setup.jsonl",
            {"argv": list(args), "exit": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
        )
        if result.returncode:
            raise ValueError(f"Setup failed: {args}: {result.stderr or result.stdout}")
        return result

    def execute(self, label: str, command: list[str], control: dict) -> Path:
        directory = self.root / "captures" / label
        directory.mkdir(exist_ok=False)
        control = {**control, "capture": str(directory)}
        (directory / "control.json").write_text(json.dumps(control, indent=2))
        Path(os.environ["PROBE_CONTROL"]).write_text(json.dumps(control))
        previous = Path.cwd()
        os.chdir(self.project)
        try:
            code = RUNTIME["bounded_run"](command, directory / "run", 200, 3)
        finally:
            os.chdir(previous)
        print(json.dumps({"case": label, "exit": code, "capture": str(directory)}), flush=True)
        if code:
            raise ValueError(f"Probe {label} failed; retain this capture before retrying.")
        return directory

    def seed(self, name: str) -> None:
        from forge.session.store import SessionStore

        store = SessionStore(str(self.project), name)
        if store.exists():
            codex = store.read().confirmed.codex
            if not codex or not codex.thread_id:
                raise ValueError("Existing fixture session has no completed seed; use a new name.")
            return
        parent = SessionStore(str(self.project), "b3-parent")
        if not parent.exists():
            self.setup("session", "start", "b3-parent", "--no-launch", "--no-proxy")
        transcript = self.root / "parent.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "requestId": "b3-parent",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "Synthetic fixture. Follow the operator's requested file-edit task.",
                            }
                        ],
                    },
                }
            )
            + "\n"
        )
        parent.update(timeout_s=5, mutate=lambda state: setattr(state.confirmed, "transcript_path", str(transcript)))
        self.execute(
            "seed-" + name,
            [
                self.forge,
                "session",
                "start",
                name,
                "--runtime",
                "codex",
                "--resume-from",
                "b3-parent",
                "--strategy",
                "full",
                "--task",
                "Do not use tools. Reply READY.",
            ],
            {"kind": "seed"},
        )

    def case(
        self, label: str, kind: str, *, session: str = "b3-executor", tui: bool = False, feedback: bool = True
    ) -> Path:
        self.seed(session)
        self.setup("config", "set", "policy_summary_feedback=" + ("on" if feedback else "off"))
        source = kind in {"source", "source-changed", "source-invalid", "source-deny"}
        self.setup("config", "set", "codex_policy_feedback_format=" + ("source-only" if source else "normal"))
        self.setup("policy", "disable", "--session", session)
        self.setup("policy", "supervisor", "remove", "--session", session)
        control: dict = {"kind": kind, "session": session, "feedback": feedback, "source_only": source}
        nonce = "B3-" + uuid.uuid4().hex
        control["reviewer_nonce"] = nonce
        target = f"src/{label.replace('-', '_')}.py"
        patch_task = f"add {target} containing VALUE = 1"
        if kind in {"tdd", "multi", "mixed"}:
            args = ["policy", "enable", "--session", session, "--bundle", "tdd", "--permissive"]
            if kind == "mixed":
                args += ["--bundle", "coding_standards"]
                patch_task += f" and src/{label}_blocked.py containing the two lines 'if TYPE_CHECKING:' and '    pass'"
            if kind == "multi":
                patch_task = f"add docs/{label}.txt containing OK, then {target} containing VALUE = 1 and src/{label}_later.py containing VALUE = 2"
            self.setup(*args)
        else:
            plan = self.root / f"{label}-approved-plan.txt"
            quote = "Use the approved interface. Source marker: SOURCE-" + uuid.uuid4().hex + "."
            plan.write_text(quote + "\nOnly change the approved interface adapter.\n")
            control.update(plan_path=str(plan), source_quote=quote)
            citations = ["fabricated quotation " + nonce] if kind in {"source-invalid", "source-deny"} else [quote]
            control["verdict"] = {
                "verdict": "divergent",
                "confidence": 0.95 if kind == "source-deny" else 0.5,
                "violations": [
                    {
                        "severity": "medium",
                        "evidence": "Reviewer prose " + nonce,
                        "suggested_fix": "Reviewer fix " + nonce,
                        "citations": citations,
                    }
                ],
            }
            if kind == "source-changed":
                control["replace_plan"] = "The on-disk plan changed after review started.\n"
            if kind == "timeout":
                control["reviewer"] = "sleep"
            self.setup(
                "policy",
                "supervisor",
                "set",
                "--session",
                session,
                "--plan",
                str(plan),
                "--model",
                "sonnet",
                "--no-supervisor-proxy",
                "--timeout",
                "1" if kind == "timeout" else "10",
            )
            self.setup("session", "set", "policy.supervisor.shadow_sample_rate", "0", "--session", session)
        prompt = f"Use apply_patch exactly once to {patch_task}. Do not read files or use any other tool. If blocked, stop without retrying. Then reply with any B3- or SOURCE- marker you received in hook feedback, or NONE if absent."
        control.update(prompt=prompt, target=target)
        command = [self.forge, "session", "resume", session]
        if tui:
            prompt_file = self.root / f"{label}-prompt.txt"
            prompt_file.write_text(prompt)
            command = [
                sys_python(),
                str(SCRIPTS / "b3-terminal.py"),
                "--close-after-turn",
                "--prompt-file",
                str(prompt_file),
                "--",
                *command,
            ]
        else:
            command += ["--task", prompt]
        directory = self.execute(label, command, control)
        self.setup("session", "show", session, "--json")
        from dataclasses import asdict

        from forge.core.usage.ledger import read_usage_events
        from forge.session.store import SessionStore

        state = SessionStore(str(self.project), session).read()
        (directory / "session.json").write_text(json.dumps(asdict(state), indent=2))
        if state.confirmed.codex and state.confirmed.codex.rollout_path:
            shutil.copyfile(state.confirmed.codex.rollout_path, directory / "private-rollout.jsonl")
        (directory / "usage.json").write_text(
            json.dumps([asdict(e) for e in read_usage_events() if e.session == session], indent=2)
        )
        (directory / "action-result.json").write_text(
            json.dumps(
                {
                    "target": target,
                    "exists": (self.project / target).exists(),
                    "content": (self.project / target).read_text() if (self.project / target).exists() else None,
                },
                indent=2,
            )
        )
        return directory


def sys_python() -> str:
    import sys

    return sys.executable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument(
        "kind",
        choices=[
            "tdd",
            "multi",
            "mixed",
            "stub",
            "source",
            "source-changed",
            "source-invalid",
            "source-deny",
            "timeout",
        ],
    )
    parser.add_argument("--session", default="b3-executor")
    parser.add_argument("--tui", action="store_true")
    parser.add_argument("--off", action="store_true")
    args = parser.parse_args()
    Round(Path(os.environ["PROBE_ROUND_ROOT"])).case(
        args.label, args.kind, session=args.session, tui=args.tui, feedback=not args.off
    )


if __name__ == "__main__":
    main()
