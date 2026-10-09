#!/usr/bin/env python3
"""Bound a probe process tree and account for calls to one retained Codex binary.

Python hook/reviewer fixtures call register_process at startup. The outer owner
also polls descendants, retaining their identities after they detach or reparent.
Cleanup evidence describes survivors before the harness sends any signal.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path


def process_table() -> dict[int, dict]:
    """Read identity and ancestry without collecting command arguments or environments."""
    output = subprocess.check_output(["ps", "-axo", "pid=,ppid=,pgid=,stat=,lstart="], text=True)
    rows = {}
    for line in output.splitlines():
        parts = line.split(maxsplit=4)
        if len(parts) == 5:
            pid, parent, group, status, started = parts
            rows[int(pid)] = {
                "pid": int(pid),
                "ppid": int(parent),
                "pgid": int(group),
                "status": status,
                "started": started,
            }
    return rows


def append_json(path: Path, value: dict) -> None:
    """Append one private, locked record; no payload or auth values are captured."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()


def register_process() -> None:
    """Record a fixture process before it starts work, including detached reviewers."""
    registry = os.environ.get("PROBE_PROCESS_REGISTRY")
    owner = os.environ.get("PROBE_PROCESS_OWNER")
    if registry and owner:
        row = process_table().get(os.getpid())
        if row:
            append_json(Path(registry), {**row, "owner": owner, "recorded_at": time.time()})


def read_registered(path: Path, owner: str) -> dict[int, dict]:
    """Ignore an append still in progress; only accept this run's identity records."""
    found = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("owner") == owner:
                found[row["pid"]] = row
    return found


def same_process(row: dict, current: dict | None) -> bool:
    return current is not None and row["started"] == current["started"]


def living(known: dict[int, dict]) -> list[dict]:
    current = process_table()
    return [
        row
        for pid, row in known.items()
        if same_process(row, current.get(pid)) and not current[pid]["status"].startswith("Z")
    ]


def signal_owned(rows: list[dict], sig: int) -> None:
    """Recheck identity for every signal; never signal a whole unverified process group."""
    for row in rows:
        current = process_table().get(row["pid"])
        if same_process(row, current):
            try:
                os.kill(row["pid"], sig)
            except ProcessLookupError:
                pass


def bounded_run(command: list[str], evidence: Path, seconds: float, grace: float, settle: float = 0) -> int:
    """Run GNU timeout under an independent owner, then sweep registered descendants."""
    if not command or seconds <= 0 or grace <= 0 or settle < 0:
        raise ValueError("A command and positive timeout/grace are required.")
    timeout = shutil.which("timeout") or shutil.which("gtimeout")
    if not timeout or "GNU coreutils" not in subprocess.check_output([timeout, "--version"], text=True):
        raise ValueError("GNU timeout is required; no unbounded fallback.")
    process_table()  # Refuse before spawning if the outer sandbox forbids process inspection.
    evidence.mkdir(parents=True, exist_ok=False)
    provenance: dict = {"command": command, "cwd": str(Path.cwd()), "started_at": time.time()}
    identity_file = os.environ.get("PROBE_RUNTIME_IDENTITY")
    if identity_file:
        provenance["codex_identity"] = json.loads(Path(identity_file).read_text())
    checkout = os.environ.get("FORGE_DEV")
    if checkout:
        provenance["forge_revision"] = subprocess.check_output(
            ["git", "-C", checkout, "rev-parse", "HEAD"], text=True
        ).strip()
        diff = subprocess.check_output(["git", "-C", checkout, "diff", "HEAD", "--", "src", "scripts", "tests"])
        provenance["source_diff_sha256"] = hashlib.sha256(diff).hexdigest()
    provenance["harness_files"] = {
        str(path.relative_to(Path(__file__).parent)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(Path(__file__).parent.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }
    (evidence / "command.json").write_text(json.dumps(provenance, indent=2) + "\n")
    owner = uuid.uuid4().hex
    registry = evidence / "processes.jsonl"
    env = dict(os.environ, PROBE_PROCESS_OWNER=owner, PROBE_PROCESS_REGISTRY=str(registry))
    started = time.monotonic()
    known: dict[int, dict] = {}
    with (evidence / "stdout").open("wb") as stdout, (evidence / "stderr").open("wb") as stderr:
        child = subprocess.Popen(
            [timeout, f"--kill-after={grace}s", f"{seconds}s", *command],
            stdout=stdout,
            stderr=stderr,
            env=env,
            start_new_session=True,
        )
        try:
            while child.poll() is None:
                table = process_table()
                if child.pid in table:
                    known.setdefault(child.pid, table[child.pid])
                known.update(read_registered(registry, owner))
                changed = True
                while changed:
                    changed = False
                    for pid, row in table.items():
                        parent = known.get(row["ppid"])
                        if pid not in known and parent and same_process(parent, table.get(row["ppid"])):
                            known[pid] = row
                            changed = True
                if time.monotonic() - started > seconds + grace + 2:
                    break
                time.sleep(0.02)
            if settle:
                time.sleep(settle)
        finally:
            known.update(read_registered(registry, owner))
            survivors = living(known)
            signal_owned(survivors, signal.SIGTERM)
            until = time.monotonic() + grace
            while living(known) and time.monotonic() < until:
                time.sleep(0.05)
            killed = living(known)
            signal_owned(killed, signal.SIGKILL)
            child.wait(timeout=grace + 2)
            # Give the OS a bounded interval to reap orphaned children.
            until = time.monotonic() + grace
            remaining = living(known)
            while remaining and time.monotonic() < until:
                time.sleep(0.05)
                remaining = living(known)
            result = {
                "returncode": child.returncode,
                "elapsed_seconds": time.monotonic() - started,
                "survivors_before_sweep": survivors,
                "kill_escalation": killed,
                "remaining": remaining,
                "owner": owner,
            }
            if identity_file:
                identity = provenance["codex_identity"]
                result["codex_sha256_after"] = hashlib.sha256(Path(identity["retained_path"]).read_bytes()).hexdigest()
                result["codex_identity_unchanged"] = result["codex_sha256_after"] == identity["sha256"]
            (evidence / "process-result.json").write_text(json.dumps(result, indent=2) + "\n")
    return child.returncode if not remaining else 125


def reserve_turn(ledger: Path, ceiling: int, count: int = 1) -> None:
    """Reserve quota before exec; failed launches still consume the conservative budget."""
    if ceiling < 1 or count < 1:
        raise ValueError("Turn ceiling and reservation must be positive.")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a+", encoding="utf-8") as stream:
        os.chmod(ledger, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        used = sum(json.loads(line)["reserved_turns"] for line in stream if line.strip())
        if used + count > ceiling:
            raise ValueError(f"Probe turn budget exhausted: {used}/{ceiling}; requested {count}.")
        stream.write(json.dumps({"reserved_turns": count, "at": time.time(), "pid": os.getpid()}) + "\n")
        stream.flush()


def required_environment(name: str) -> str:
    """Refuse an incomplete second-terminal environment before launching Codex."""
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Set {name} in the clean round launcher and run this command through that launcher.")
    return value


def codex_exec(identity_path: Path, argv: list[str]) -> None:
    """Use only the retained binary and file login; count execution entry points."""
    if any(
        value and (name.endswith("API_KEY") or name in {"CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL"})
        for name, value in os.environ.items()
    ):
        raise ValueError("Remove API credentials and provider overrides before running subscription probes.")
    login_home = Path(required_environment("CODEX_HOME"))
    if (
        login_home.resolve() == (Path.home() / ".codex").resolve()
        or not (login_home / ".forge-codex-probe-home").is_file()
    ):
        raise ValueError("An independently owned probe login home is required.")
    identity = json.loads(identity_path.read_text())
    binary = Path(identity["retained_path"])
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if digest != identity["sha256"]:
        raise ValueError("Retained Codex binary changed; start a new recorded round.")
    read_only = bool(argv) and argv[0] in {"login", "features", "doctor", "completion", "debug", "mcp"}
    if not read_only and not any(flag in argv for flag in ("--help", "-h", "--version", "-V")):
        budget = required_environment("PROBE_TURN_CEILING")
        try:
            ceiling = int(budget)
        except ValueError as exc:
            raise ValueError("PROBE_TURN_CEILING must be a positive integer in the clean round launcher.") from exc
        if ceiling < 1:
            raise ValueError("PROBE_TURN_CEILING must be a positive integer in the clean round launcher.")
        status = subprocess.run(
            [str(binary), "-c", 'cli_auth_credentials_store="file"', "login", "status"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if status.returncode or "Logged in using ChatGPT" not in status.stdout + status.stderr:
            raise ValueError("Independent ChatGPT login is unavailable; stop probes and restore that login.")
        reserve_turn(
            identity_path.parent / "turns.jsonl",
            ceiling,
            int(os.environ.get("PROBE_TURN_RESERVATION", "1")),
        )
    register_process()
    config = ["-c", 'cli_auth_credentials_store="file"', "-c", 'model_reasoning_effort="low"']
    if identity.get("model"):
        config.extend(["-c", f'model="{identity["model"]}"'])
    os.execv(binary, [str(binary), *config, *argv])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    run = commands.add_parser("run")
    run.add_argument("--evidence", type=Path, required=True)
    run.add_argument("--seconds", type=float, default=240)
    run.add_argument("--grace", type=float, default=5)
    run.add_argument("--settle", type=float, default=0)
    run.add_argument("command", nargs=argparse.REMAINDER)
    codex = commands.add_parser("codex")
    codex.add_argument("--identity", type=Path, required=True)
    codex.add_argument("args", nargs=argparse.REMAINDER)
    commands.add_parser("register")
    args = parser.parse_args()
    try:
        if args.operation == "run":
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            return bounded_run(command, args.evidence, args.seconds, args.grace, args.settle)
        if args.operation == "codex":
            argv = args.args[1:] if args.args[:1] == ["--"] else args.args
            codex_exec(args.identity, argv)
        else:
            register_process()
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
