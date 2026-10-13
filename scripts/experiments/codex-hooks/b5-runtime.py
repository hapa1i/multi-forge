#!/usr/bin/env python3
"""Account for B5 starts and enforce fixture authorization before native dispatch."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import runpy
import subprocess
import sys
import time
import uuid
from pathlib import Path

CASE_LIMITS = {
    "G0": 11,
    "G1": 2,
    "G2": 2,
    "G3": 2,
    "G4": 1,
    "G5": 2,
    "G6": 2,
    "G7": 2,
    "G8": 2,
    "G9": 2,
    "G10": 1,
    "G11": 2,
    "G12": 4,
    "G13": 1,
    "G14": 1,
    "P1": 8,
    "P2": 4,
    "R": 11,
}


def reserve_start(root: Path, identity: dict, auth_mode: str, authorization: dict) -> dict:
    """Count every attempted inference start, including nested and failed launches."""
    case = os.environ.get("PROBE_CASE", "")
    model = os.environ.get("PROBE_MODEL", "")
    role = os.environ.get("PROBE_ROLE", "")
    if case not in CASE_LIMITS or not model or role not in {"source", "executor", "reviewer"}:
        raise ValueError("Inference requires an allocated PROBE_CASE, PROBE_MODEL and PROBE_ROLE.")
    if case in {"P1", "P2"} and not (root / "PRODUCT_GATE_APPROVED").exists():
        raise ValueError("Product probes require the reviewed runtime gate decision.")
    reviewer = role == "reviewer"
    role_limit = CASE_LIMITS[case]
    if (
        case == "G0"
        and reviewer
        or case in {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10", "G11", "G13", "G14"}
        and not reviewer
    ):
        raise ValueError("This case does not allocate starts to the selected role.")
    if case in {"G12", "P1", "P2"}:
        role_limit //= 2
    if auth_mode != "api" and not authorization["subscription_extra_usage_off_confirmed"]:
        raise ValueError("Confirm the fixture account has extra usage off before subscription inference.")
    with (root / "starts.jsonl").open("a+") as stream:
        os.chmod(stream.name, 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.seek(0)
        rows = [json.loads(line) for line in stream if line.strip()]
        if len(rows) >= 60 or sum(row["case"] == case for row in rows) >= CASE_LIMITS[case]:
            raise ValueError(f"B5 total or {case} allocation exhausted; revise before dispatch.")
        if sum(row["case"] == case and (row["role"] == "reviewer") == reviewer for row in rows) >= role_limit:
            raise ValueError(f"B5 {case}/{role} allocation exhausted; revise before dispatch.")
        if auth_mode == "api":
            api_starts = sum(row["auth_mode"] == "api" for row in rows)
            if api_starts >= min(4, authorization["api_starts_authorized"]):
                raise ValueError("No authorized API slots remain.")
        record = {
            "id": uuid.uuid4().hex,
            "started_at": time.time(),
            "case": case,
            "role": role,
            "model": model,
            "auth_mode": auth_mode,
            "binary_sha256": identity["sha256"],
            "pid": os.getpid(),
            "ppid": os.getppid(),
            "capture": os.environ.get("PROBE_CAPTURE"),
        }
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        return record


def run_native(
    command: list[str],
    child_env: dict[str, str],
    *,
    json_events: bool,
    progress_path: Path | None = None,
) -> dict:
    """Forward output unchanged while timing native JSON events, without inventing absent usage."""
    started = time.monotonic()
    observation: dict = {
        "first_event_seconds": None,
        "usage_events": [],
        "thread_ids": [],
    }
    if json_events:
        with subprocess.Popen(command, env=child_env, stdout=subprocess.PIPE) as child:
            assert child.stdout is not None
            argv = subprocess.run(
                ["ps", "-p", str(child.pid), "-o", "args="],
                capture_output=True,
                text=True,
                check=False,
            )
            observation["observed_process_argv"] = argv.stdout.strip() if argv.returncode == 0 else None
            for line in child.stdout:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if progress_path is not None:
                    with progress_path.open("a") as progress:
                        progress.write(json.dumps(event) + "\n")
                if observation["first_event_seconds"] is None:
                    observation["first_event_seconds"] = time.monotonic() - started
                if event.get("type") == "turn.completed" and "usage" in event:
                    observation["usage_events"].append(event["usage"])
                if event.get("type") == "thread.started":
                    observation["thread_ids"].append(event.get("thread_id"))
            code = child.wait()
    else:
        code = subprocess.run(command, env=child_env, check=False).returncode
    return {
        **observation,
        "returncode": code,
        "elapsed_seconds": time.monotonic() - started,
    }


def main() -> int:
    root = Path(os.environ["PROBE_ROUND_ROOT"])
    if (
        root.resolve() != root
        or (root / "B5_ROUND").read_text() != "independent-b5-round-v1\n"
        or (root / "CLOSED").exists()
    ):
        raise ValueError("A canonical, open, owned B5 round is required.")
    for variable, relative in (("HOME", "home"), ("FORGE_HOME", "forge-home")):
        if Path(os.environ[variable]) != root / relative:
            raise ValueError(f"Unexpected {variable}; launch through the fixture's run script.")
    codex_home = Path(os.environ["CODEX_HOME"])
    if codex_home.resolve() != codex_home or codex_home.parent != root:
        raise ValueError("Codex home must be a canonical direct child of the owned round.")
    if (codex_home / ".forge-codex-probe-home").read_text() != "independent-login-v1\n":
        raise ValueError("An independently prepared Codex home is required.")
    if os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        raise ValueError("Disable dotenv before dispatch.")
    auth_mode = os.environ.get("PROBE_AUTH_MODE", "subscription-only")
    if auth_mode not in {"subscription-only", "api", "api-without-key-control"}:
        raise ValueError("Choose an explicit supported auth case.")
    for name, value in os.environ.items():
        credential = name.endswith("API_KEY") or name in {
            "CODEX_ACCESS_TOKEN",
            "OPENAI_BASE_URL",
        }
        if value and credential and not (auth_mode == "api" and name == "CODEX_API_KEY"):
            raise ValueError("Ambient API credentials or proxy routing are forbidden.")
    identity = json.loads((root / "identity.json").read_text())
    binary = Path(identity["retained_path"])
    with binary.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != identity["sha256"]:
            raise ValueError("Retained runtime changed.")
    argv = sys.argv[1:]
    if not argv:
        raise ValueError("Specify a command; interactive inference must use an allocated case.")
    local_only = ("--" not in argv and any(flag in argv for flag in ("--help", "-h", "--version", "-V"))) or argv in (
        ["login", "status"],
        ["login", "--device-auth"],
        ["features", "list"],
        ["debug", "models"],
        ["doctor", "--json"],
    )
    if any("forced_login_method" in arg or "cli_auth_credentials_store" in arg for arg in argv):
        raise ValueError("The fixture owns its child authentication controls.")
    authorization = json.loads((root / "authorization.json").read_text())
    child_env = dict(os.environ)
    if auth_mode == "api":
        if authorization["api_starts_authorized"] <= 0:
            raise ValueError("The API route needs separate user authorization.")
        if not os.environ.get("CODEX_API_KEY") or not (root / "API_NEGATIVE_PASSED").exists():
            raise ValueError("API execution requires an explicit key and a passing no-login-fallback control.")
    if auth_mode == "api-without-key-control" and os.environ.get("PROBE_CASE") != "R":
        raise ValueError("The no-key negative consumes an explicitly recorded reserve slot.")
    forced_method = "chatgpt" if auth_mode == "subscription-only" else "api"
    credential_store = "file" if auth_mode == "subscription-only" else "ephemeral"
    controls = [
        "-c",
        f'cli_auth_credentials_store="{credential_store}"',
        "-c",
        f'forced_login_method="{forced_method}"',
    ]
    if argv[0] == "exec":
        # This retained CLI ignores parent-level -c flags in nested commands.
        # Probe argv is controlled by this harness; put auth on its actual leaf.
        leaf = next(
            (argv.index(name) for name in ("fork", "resume", "review") if name in argv),
            0,
        )
        command = [str(binary), *argv[: leaf + 1], *controls, *argv[leaf + 1 :]]
    else:
        command = [str(binary), *controls, *argv]
    runtime = runpy.run_path(str(Path(__file__).with_name("probe-runtime.py")))
    runtime["register_process"]()
    record = None if local_only else reserve_start(root, identity, auth_mode, authorization)
    runtime["append_json"](
        root / "invocations.jsonl",
        {
            "id": record["id"] if record else None,
            "command": command,
            "cwd": str(Path.cwd()),
            "local_only": local_only,
            "codex_home": str(codex_home),
            "at": time.time(),
        },
    )
    capture = os.environ.get("PROBE_CAPTURE")
    result = run_native(
        command,
        child_env,
        json_events=not local_only and "--json" in argv,
        progress_path=Path(capture) / "native-events.jsonl" if capture else None,
    )
    if record is not None:
        runtime["append_json"](root / "outcomes.jsonl", {"id": record["id"], **result})
    return result["returncode"]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, KeyError, ValueError) as exc:
        sys.exit(f"B5 fixture refusal: {exc}")
