#!/usr/bin/env python3
"""Execute named B2 probes against the prepared, enrolled fixture.

Raw output and commands remain outside the repository. Each case has an independent
deadline and process record. Failed or unsupported observations remain reviewable.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import runpy
import subprocess
import uuid
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
RUNTIME = runpy.run_path(str(SCRIPTS / "probe-runtime.py"))


@contextlib.contextmanager
def environment(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class Round:
    def __init__(self, root: Path):
        self.root = root
        self.project = root / "captures/fixture/proj"
        self.forge = Path(os.environ["FORGE_DEV"]) / ".venv/bin/forge"
        self.results = root / "captures/b2-results.jsonl"

    def setup(self, *args: str, session: str = "", cwd: Path | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if session:
            env.update(FORGE_SESSION=session, FORGE_FORGE_ROOT=str(cwd or self.project))
        result = subprocess.run(
            [str(self.forge), *args], cwd=cwd or self.project, env=env, capture_output=True, text=True, timeout=30
        )
        RUNTIME["append_json"](
            self.root / "captures/setup.jsonl",
            {
                "command": [str(self.forge), *args],
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
        if result.returncode:
            raise RuntimeError(f"Setup failed: {' '.join(args)}\n{result.stderr}\n{result.stdout}")
        return result

    def session(self, name: str) -> None:
        (self.project / ".forge").mkdir(exist_ok=True)
        if not (self.project / f".forge/sessions/{name}/forge.session.json").exists():
            self.setup("session", "start", name, "--no-launch", "--no-proxy")

    def run(
        self,
        name: str,
        prompt: str,
        *,
        mode: str = "observe",
        session: str = "b2-plain",
        sandbox: str = "workspace-write",
        extra: tuple[str, ...] = (),
        cwd: Path | None = None,
        managed: bool = False,
        reviewer: str = "fast",
        seconds: int = 240,
        reservation: int = 1,
        delay: int = 3,
        command: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> dict:
        capture = self.root / "captures" / name
        if capture.exists():
            raise ValueError(f"Archive/relabel an existing attempt before rerun: {name}")
        nonce = "B2-" + uuid.uuid4().hex
        control = {"capture": str(capture), "mode": mode, "nonce": nonce, "reviewer": reviewer, "delay": delay}
        Path(os.environ["PROBE_CONTROL"]).write_text(json.dumps(control))
        env = {
            "PROBE_CAPTURE_DIR": str(capture),
            "PROBE_TURN_RESERVATION": str(reservation),
            "FORGE_SESSION": "" if managed else session,
            "FORGE_FORGE_ROOT": str(cwd or self.project),
            "LIB_DIR": str(SCRIPTS),
            "HOOKBIN": str(self.root / "captures/fixture/hookbin"),
        }
        env.update(extra_env or {})
        command = command or (
            [str(self.forge), "session", "resume", session, "--task", prompt]
            if managed
            else ["codex", "exec", "--json", "--sandbox", sandbox, "-o", str(capture / "last.txt"), *extra, prompt]
        )
        before = Path.cwd()
        with environment(env):
            subprocess.run(["/bin/bash", "-c", 'source "$LIB_DIR/lib.sh"; fixture_tee_all'], check=True)
            os.chdir(cwd or self.project)
            try:
                code = RUNTIME["bounded_run"](command, capture, seconds, 5, 1)
            finally:
                os.chdir(before)
        events = []
        if not managed:
            for line in (capture / "stdout").read_text().splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        last = (capture / "last.txt").read_text() if (capture / "last.txt").exists() else ""
        managed_result = None
        correlation = capture / "usage-correlation.jsonl"
        if managed and correlation.exists():
            for line in correlation.read_text().splitlines():
                result = json.loads(line)["result"]
                if result["label"] in {"codex-bridge", "codex-resume"}:
                    managed_result = result
                    last = result["stdout"]
        row = {
            "name": name,
            "capture": str(capture),
            "exit": code,
            "nonce": nonce,
            "last": last,
            "nonce_consumed": nonce in last,
            "completed": any(event.get("type") == "turn.completed" for event in events),
            "thread_ids": [event["thread_id"] for event in events if event.get("type") == "thread.started"],
        }
        if managed_result is not None:
            row["completed"] = not managed_result["runtime_is_error"] and managed_result["input_tokens"] is not None
            row["thread_ids"] = [managed_result["runtime_session_id"]]
        RUNTIME["append_json"](self.results, row)
        print(json.dumps(row), flush=True)
        failed_auth = any(
            event.get("type") == "turn.failed"
            and any(word in str(event).lower() for word in ("auth", "quota", "limit"))
            for event in events
        )
        if failed_auth:
            raise RuntimeError("Authentication/quota failure: stop dependent probes without a fallback.")
        errors = (capture / "stderr").read_text()
        if "Independent ChatGPT login is unavailable" in errors or "Probe turn budget exhausted" in errors:
            raise RuntimeError("The probe launcher refused auth/quota admission; stop this batch.")
        return row


def product(round_: Round) -> None:
    round_.session("b2-plain")
    round_.setup("policy", "disable", "--session", "b2-plain")
    round_.session("b2-tdd")
    round_.setup("policy", "enable", "--session", "b2-tdd", "--bundle", "tdd", "--fail-mode", "open")
    round_.run(
        "89-product-deny",
        "Use apply_patch once to add src/blocked_b2.py containing VALUE = 1. "
        "Do not create tests. If blocked, stop; do not try another tool. Then reply DONE.",
        session="b2-tdd",
    )
    round_.run(
        "89-product-tests-first",
        "Use one apply_patch call to add src/paired_b2.py containing VALUE = 2 "
        "and tests/test_paired_b2.py containing def test_value(): assert 2 == 2. Put the implementation chunk "
        "before the test chunk. Do not use other tools. Then reply DONE.",
        session="b2-tdd",
    )
    round_.run(
        "89-absent-hook-control",
        "Use apply_patch once to add src/absent_b2.py containing VALUE = 3. "
        "Do not create tests or use other tools. Then reply DONE.",
        session="b2-tdd",
        extra=("--ignore-user-config",),
    )
    round_.run(
        "89-patch-updated-input",
        "Use apply_patch once to add updated_b2.txt containing ORIGINAL. " "Do not use other tools. Then reply DONE.",
        mode="updated-input",
    )
    round_.run(
        "89-patch-malformed",
        "Use apply_patch once to add malformed_b2.txt containing ORIGINAL. " "Do not use other tools. Then reply DONE.",
        mode="malformed",
    )
    (round_.project / "approved.md").write_text(
        "Allow the synthetic probe to create plain text files in this fixture.\n"
    )
    round_.session("b2-supervised")
    round_.setup(
        "policy",
        "supervisor",
        "set",
        "--session",
        "b2-supervised",
        "--plan",
        "approved.md",
        "--model",
        "sonnet",
        "--no-supervisor-proxy",
        "--timeout",
        "45",
    )
    round_.setup("session", "set", "policy.supervisor.shadow_sample_rate", "0", "--session", "b2-supervised")
    round_.run(
        "89-supervised-allow",
        "Use apply_patch once to add supervised_b2.txt containing ALLOWED. " "Do not use other tools. Then reply DONE.",
        session="b2-supervised",
    )


def warnings(round_: Round) -> None:
    for mode in ("observe", "feedback-explicit", "feedback-context", "system-message", "stderr"):
        target = f"warning_{mode}.txt"
        round_.run(
            f"90-{mode}",
            f"Use apply_patch exactly once to add {target} containing OK. "
            "Do not use other tools. Then reply with any B2- nonce present in hook feedback, or NONE if absent.",
            mode=mode,
        )


def authority(round_: Round, roles: tuple[str, ...] = ("advisory", "producer", "unmarked")) -> None:
    prepare_parent(round_)
    for role in roles:
        session = f"b2-{role}-managed"
        prompt = (
            f"Run exactly one shell command: printf {role.upper()} > {role}_b2.txt. "
            "If blocked, stop without another tool. Reply DONE."
        )
        args = [
            str(round_.forge),
            "session",
            "start",
            session,
            "--runtime",
            "codex",
            "--resume-from",
            "b2-parent",
            "--strategy",
            "full",
            "--task",
            prompt,
        ]
        if role != "unmarked":
            args.extend(["--authority", role])
        round_.run(f"91-{role}-shell", prompt, session=session, managed=True, command=args)
    round_.run(
        "91-advisory-resume",
        "Run exactly one shell command: printf RESUME > advisory_resume_b2.txt. "
        "If blocked, stop without another tool. Reply DONE.",
        session="b2-advisory-managed",
        managed=True,
    )


def prepare_parent(round_: Round) -> str:
    """A synthetic Claude transcript supplies a hook-only transfer sentinel."""
    from forge.session.store import SessionStore

    round_.session("b2-parent")
    transcript = round_.project / "b2-parent.transcript.jsonl"
    nonce_file = round_.root / "parent-nonce.txt"
    if not nonce_file.exists():
        nonce_file.write_text("PARENT-" + uuid.uuid4().hex)
    nonce = nonce_file.read_text()
    body = "Synthetic planning context. " * 250 + " The oracle token is " + nonce + "."
    transcript.write_text(
        json.dumps(
            {
                "requestId": "b2-parent",
                "timestamp": "2026-10-09T00:00:00Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": body}]},
            }
        )
        + "\n"
    )
    store = SessionStore(str(round_.project), "b2-parent")
    store.update(timeout_s=10, mutate=lambda state: setattr(state.confirmed, "transcript_path", str(transcript)))
    return nonce


def context(round_: Round) -> None:
    prepare_parent(round_)
    prompt = (
        "Reply with only the oracle token from your transferred planning context, or NONE if absent. "
        "Do not read files or use tools."
    )
    for label, extra in (("delivered", []), ("undelivered", ["--", "--ignore-user-config"])):
        session = f"b2-context-{label}"
        args = [
            str(round_.forge),
            "session",
            "start",
            session,
            "--runtime",
            "codex",
            "--resume-from",
            "b2-parent",
            "--strategy",
            "full",
            "--task",
            prompt,
            "--context-delivery",
            "hook",
            *extra,
        ]
        round_.run(f"92-context-{label}", prompt, session=session, managed=True, command=args)


def background(round_: Round) -> None:
    round_.run(
        "96-background-live",
        "Run printf START with exec_command, then run sleep 4; printf END "
        "with exec_command and wait for it to finish. In your final reply include any B2- nonce "
        "from hook feedback, or NONE if absent.",
        mode="background",
        delay=1,
    )
    round_.run(
        "96-background-exit",
        "Run printf SHORT once with exec_command, then immediately reply DONE. " "Do not wait or run other tools.",
        mode="background",
        delay=15,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("group", choices=("product", "warnings", "authority", "context", "background"))
    args = parser.parse_args()
    round_ = Round(args.root.resolve())
    {"product": product, "warnings": warnings, "authority": authority, "context": context, "background": background}[
        args.group
    ](round_)


if __name__ == "__main__":
    main()
