#!/usr/bin/env python3
"""Capture real Codex TUI and exec wire behavior against one private loopback stub per case."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path
from typing import Any

from responses_stub import REFUSALS, ResponsesStub

VERSIONS = ("0.141.0", "0.149.1", "0.161.0", "0.170.0")
MODELS = ("openai/gpt-6.2-astra", "google/gemini-4-carbon")
MODES = ("exec", "tui")
FIRST = "Read fixture.txt with a local shell tool. Reply with the fixture value."
FOLLOWUP = "FORGE_FOLLOWUP: Use the value read in the previous turn to answer again."
TOKEN_ENV = "FORGE_CODEX_PROXY_TOKEN"
ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
HERE = Path(__file__).resolve()
OWNER = HERE.parents[2] / "codex-hooks" / "probe-runtime.py"


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def child_env(root: Path, binary: Path) -> dict[str, str]:
    for name in ("home", "codex", "tmp", "work"):
        (root / name).mkdir()
    return {
        "HOME": str(root / "home"),
        "CODEX_HOME": str(root / "codex"),
        "TMPDIR": str(root / "tmp"),
        "PATH": f"{binary.parent}:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "SHELL": "/bin/sh",
        "TERM": "xterm-256color",
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        TOKEN_ENV: "loopback-probe",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "localhost,127.0.0.1,::1",
    }


def rollout_types(home: Path) -> list[str]:
    events = []
    for path in home.glob("sessions/**/rollout-*.jsonl"):
        for line in path.read_bytes().splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get("type") == "event_msg":
                events.append(item.get("payload", {}).get("type", ""))
    return events


def commands(binary: Path, base: str, model: str, web: str, scenario: str) -> list[str]:
    args = [
        str(binary),
        "--sandbox",
        "workspace-write",
        "-a",
        "never",
        "-c",
        "model_provider=forge_proxy",
        "-c",
        'model_providers.forge_proxy.name="Forge Proxy"',
        "-c",
        f'model_providers.forge_proxy.base_url="{base}"',
        "-c",
        'model_providers.forge_proxy.wire_api="responses"',
        "-c",
        f'model_providers.forge_proxy.env_key="{TOKEN_ENV}"',
        "-m",
        model,
    ]
    if web == "disabled":
        args.extend(["-c", 'web_search="disabled"'])
    if scenario == "compaction":
        args.extend(["-c", "model_auto_compact_token_limit=1000"])
    return args


def visibility(text: str, scenario: str) -> dict:
    normalized = " ".join(text.lower().split())
    expected = {
        "hosted": "allow_non_zdr=true",
        "subresource": "supports only post /v1/responses",
        "unreported": "costs.on_unreported_cost=allow",
        "unreported400": "costs.on_unreported_cost=allow",
        "zdr": "allow_non_zdr=true",
        "cap": "spend cap",
        "cap_native": "costs.caps.per_day",
    }.get(scenario)
    return {
        "visible_refusal": bool(expected and expected in normalized),
        "visible_tag": f"FORGE_REFUSAL_{scenario.upper()}" in text,
        "visible_generic_429": "429" in normalized
        and ("too many requests" in normalized or "retry limit" in normalized),
        "fallback_metadata_warning": "fallback metadata" in normalized,
        "visible_done": "FORGE_PROBE_DONE" in text,
        "visible_followup": "FORGE_FOLLOWUP_DONE" in text,
    }


def run_tui(
    args: list[str],
    scenario: str,
    path: Path,
    cwd: Path,
    env: dict[str, str],
    seconds: int,
    *,
    prompts: tuple[str, str] = (FIRST, FOLLOWUP),
) -> dict:
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 55, 190, 0, 0))
    command = [
        sys.executable,
        str(HERE),
        "terminal-child",
        *args,
        "--no-alt-screen",
        prompts[0],
    ]
    with subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    ) as proc:
        os.close(slave)
        started = time.monotonic()
        data = bytearray()
        followup_sent = False
        exit_at = None
        notice_opened = False
        notice_closed = False
        done_reason = "client_exit"
        last_poll = 0.0
        try:
            while proc.poll() is None:
                now = time.monotonic()
                if now - started >= seconds:
                    done_reason = "deadline"
                    os.killpg(proc.pid, signal.SIGTERM)
                    break
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    data.extend(chunk)
                    if b"\x1b[6n" in chunk:
                        os.write(master, b"\x1b[1;1R")
                    if b"\x1b]11;?" in chunk:
                        os.write(master, b"\x1b]11;rgb:0000/0000/0000\x1b\\")
                if now - last_poll < 0.3:
                    continue
                last_poll = now
                events = rollout_types(Path(env["CODEX_HOME"]))
                complete = events.count("task_complete")
                if scenario in REFUSALS:
                    if complete or ("error" in events and ("FORGE_REFUSAL_" + scenario.upper()).encode() in data):
                        exit_at = exit_at or now + 1
                elif not followup_sent and complete:
                    os.write(master, b"\x1b[200~" + prompts[1].encode() + b"\x1b[201~")
                    time.sleep(0.24)
                    os.write(master, b"\r")
                    followup_sent = True
                elif followup_sent and complete >= 2:
                    if not notice_opened:
                        os.write(master, b"\x1bOQ")
                        notice_opened = True
                    exit_at = exit_at or now + 0.6
                if exit_at is not None and now > exit_at:
                    if notice_opened and not notice_closed:
                        os.write(master, b"\x1b")
                        notice_closed = True
                    else:
                        os.write(master, b"\x04")
                    exit_at = now + 0.5
                    done_reason = "turn_ended"
        finally:
            os.close(master)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        path.joinpath("terminal.raw").write_bytes(data)
        rendered = ANSI.sub(b"", bytes(data)).decode(errors="replace")
        path.joinpath("terminal.txt").write_text(rendered)
        return {
            "code": proc.returncode,
            "stop": done_reason,
            "followup_sent": followup_sent,
            **visibility(rendered, scenario),
        }


def run_exec(
    args: list[str],
    scenario: str,
    path: Path,
    cwd: Path,
    env: dict[str, str],
    seconds: int,
) -> dict:
    started = time.monotonic()

    def turn(argv: list[str], label: str) -> tuple[int | None, str, str]:
        try:
            result = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                env=env,
                cwd=cwd,
                capture_output=True,
                timeout=max(1, seconds - (time.monotonic() - started)),
            )
            code, out, err = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as exc:
            code, out, err = None, exc.stdout or b"", exc.stderr or b""
        path.joinpath(label + ".jsonl").write_bytes(out)
        path.joinpath(label + ".stderr").write_bytes(err)
        return code, out.decode(errors="replace"), err.decode(errors="replace")

    code, out, err = turn([*args, "exec", "--skip-git-repo-check", "--json", FIRST], "exec")
    follow_code, follow_out = None, ""
    if code == 0 and scenario not in REFUSALS:
        thread = next(
            (json.loads(s)["thread_id"] for s in out.splitlines() if '"thread.started"' in s),
            None,
        )
        if thread:
            follow_code, follow_out, _ = turn(
                [
                    *args,
                    "exec",
                    "resume",
                    "--skip-git-repo-check",
                    "--json",
                    thread,
                    FOLLOWUP,
                ],
                "resume",
            )
    return {
        "code": code,
        "followup_code": follow_code,
        "stop": (
            "deadline"
            if code is None or (code == 0 and scenario not in REFUSALS and follow_code is None)
            else "client_exit"
        ),
        **visibility(out + err + follow_out, scenario),
    }


MEASURED = {
    "refusal-visible",
    "refusal-hidden",
    "compaction-observed",
    "tool-and-followup",
}


def case_verdict(scenario: str, outcome: dict, records: list[dict]) -> str:
    if outcome["stop"] == "deadline" or any(r["sent"] == "limit" for r in records):
        return "harness-cutoff"
    primary = [
        r
        for r in records
        if r["method"] == "POST" and r["path"] == "/v1/responses" and not r["shape"].get("title_request")
    ]
    if not primary:
        return "no-generation-request"
    if scenario in REFUSALS:
        if (
            not all(r["sent"] == "refusal" and r["status"] == REFUSALS[scenario][0] for r in primary)
            or "task_complete" not in outcome["events"]
        ):
            return "refusal-unconfirmed"
        return "refusal-visible" if outcome["visible_refusal"] else "refusal-hidden"
    if not outcome["visible_followup"] or outcome["events"].count("task_complete") < 2:
        return "followup-unconfirmed"
    if scenario == "compaction":
        compacted = "context_compacted" in outcome["events"] or any(
            r["shape"].get("compaction_prompt") for r in primary
        )
        resumed = any(r["shape"].get("compacted_history") and r["shape"].get("followup") for r in primary)
        return "compaction-observed" if compacted and resumed else "compaction-unconfirmed"
    replay = any(r["shape"].get("fixture_result") and r["shape"].get("followup") for r in primary)
    return "tool-and-followup" if replay and outcome["visible_done"] else "tool-or-followup-unconfirmed"


def run_case(args: argparse.Namespace) -> int:
    path = args.case_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="forge-or-codex-") as temporary:
        root = Path(temporary).resolve()
        env = child_env(root, args.binary)
        work = root / "work"
        (work / "fixture.txt").write_text("FORGE_FIXTURE_173\n")
        config = (
            f'check_for_update_on_startup = false\ncli_auth_credentials_store = "file"\n'
            f"[analytics]\nenabled = false\n[feedback]\nenabled = false\n"
            f'[projects.{json.dumps(str(work))}]\ntrust_level = "trusted"\n'
        )
        (root / "codex" / "config.toml").write_text(config)
        with ResponsesStub(path, args.scenario) as stub:
            argv = commands(args.binary, stub.base_url, args.model, args.web, args.scenario)
            driver = run_tui if args.mode == "tui" else run_exec
            outcome = driver(argv, args.scenario, path, work, env, args.seconds)
            outcome["events"] = rollout_types(root / "codex")
        records = list(stub.records)
        save(path / "requests.json", records)
        outcome["verdict"] = case_verdict(args.scenario, outcome, records)
        outcome.update(
            {
                "version": args.version,
                "model": args.model,
                "web": args.web,
                "mode": args.mode,
                "scenario": args.scenario,
                "requests": len(records),
            }
        )
        save(path / "result.json", outcome)
    return 0


def cases(versions: dict, selected: set[str]):
    for version in versions:
        for mode in MODES:
            for model in MODELS:
                for web in ("default", "disabled"):
                    if "normal" in selected:
                        yield version, mode, model, web, "normal"
                if "compaction" in selected:
                    yield version, mode, model, "disabled", "compaction"
            for scenario in REFUSALS:
                if scenario in selected:
                    yield version, mode, MODELS[0], "disabled", scenario


def main() -> int:
    if sys.argv[1:2] == ["terminal-child"]:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        os.execv(sys.argv[2], sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binaries", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--scenarios", default="normal,compaction," + ",".join(REFUSALS))
    parser.add_argument("--version")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--web", choices=("default", "disabled"))
    parser.add_argument("--scenario", choices=("normal", "compaction", *REFUSALS))
    parser.add_argument("--case-dir", type=Path)
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    os.umask(0o077)
    if args.case_dir:
        return run_case(args)
    if not args.binaries or not args.output:
        parser.error("Supply --binaries and --output.")
    selected = set(args.scenarios.split(","))
    if selected - {"normal", "compaction", *REFUSALS} or args.workers < 1:
        parser.error("Unknown scenarios or invalid worker count.")
    versions = {v: Path(b).resolve(strict=True) for v, b in json.loads(args.binaries.read_text()).items()}
    if set(versions) != set(VERSIONS):
        parser.error("Supply exactly the four pinned Codex versions.")
    args.output = args.output.resolve()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    identity = {}
    for version, binary in versions.items():
        with tempfile.TemporaryDirectory(prefix="forge-or-version-") as scratch:
            env = child_env(Path(scratch), binary)
            banner = subprocess.check_output([str(binary), "--version"], text=True, timeout=10, env=env).strip()
        if banner.split()[-1] != version:
            raise ValueError(f"Expected {version}, got {banner}")
        with binary.open("rb") as stream:
            identity[version] = {
                "path": str(binary),
                "version": version,
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
            }
    save(args.output / "binaries.json", identity)

    def execute(case: tuple) -> dict:
        version, mode, model, web, scenario = case
        name = "__".join([version, mode, model.split("/")[1], web, scenario])
        target = args.output / name
        target.mkdir()
        command = [
            sys.executable,
            str(HERE),
            "--case-dir",
            str(target),
            "--binary",
            str(versions[version]),
            "--version",
            version,
            "--mode",
            mode,
            "--model",
            model,
            "--web",
            web,
            "--scenario",
            scenario,
            "--seconds",
            str(args.seconds),
        ]
        child = subprocess.run(
            [
                sys.executable,
                str(OWNER),
                "run",
                "--evidence",
                str(target / "owner"),
                "--seconds",
                str(args.seconds + 6),
                "--grace",
                "2",
                "--",
                *command,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
        )
        if child.stderr:
            (target / "owner.stderr").write_bytes(child.stderr)
        summary = json.loads((target / "result.json").read_text()) if (target / "result.json").is_file() else {}
        summary.update({"case": name, "owner_exit": child.returncode})
        print(
            f"{name}: owner={child.returncode} requests={summary.get('requests')} stop={summary.get('stop')}",
            flush=True,
        )
        return summary

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as workers:
        result = list(workers.map(execute, cases(versions, selected)))
    save(args.output / "matrix.json", result)
    return int(any(row["owner_exit"] or row.get("verdict") not in MEASURED for row in result))


if __name__ == "__main__":
    raise SystemExit(main())
