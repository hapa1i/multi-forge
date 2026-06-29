#!/usr/bin/env python3
"""Claude-subscription billing Phase 0 probe helper (consumer_lanes T0).

Operator-gated. Answers, with verbatim evidence, whether a *keyless* ``claude -p``
rides a Claude Max/Pro subscription headlessly, and whether the auth mode is
detectable from a stable signal. Run via
``uv run python helpers/claude_probe.py <subcommand> --capture-dir <dir> --label <l>``
so ``forge.*`` imports resolve against the project venv.

Design constraints (see the harness README + the T0 checklist):

* **Read-only against Forge state.** Reuses ``can_use_bare`` (the *exact* predicate
  ``session_runner.py`` uses) to PROVE no key is resolvable; never writes ``~/.forge``.
* **Never prints or persists a key or OAuth token.** Records are metadata-only:
  booleans, source labels, dollar cost numbers, and token *counts* -- never the key,
  the token, or the credential-store contents.
* **Fail closed on the gate.** If the keyless check cannot run (import failure), the
  precondition errors rather than assuming keyless -- assuming keyless when unverifiable
  is the exact self-deception T0 must avoid.
* **One turn, three reads.** ``turn`` runs a single keyless ``claude -p`` and reads
  (a0) non-TTY OAuth feasibility, (a) turn-completes, and (b) cost-present/absent from
  one envelope -- minimizing real quota draw.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

HELPER_VERSION = "1"

# The keyless turn deliberately omits --bare (omitting it is what PERMITS OAuth)
# and forces DIRECT routing (no proxy) so it tests OAuth-to-Anthropic, not a backend.
PROBE_PROMPT = os.environ.get("CLAUDE_SUB_PROBE_PROMPT", "Reply with exactly: ok")
PROBE_MODEL = os.environ.get("CLAUDE_SUB_PROBE_MODEL") or None  # None => claude's default
# Inner per-call guard (lib.sh's with_timeout is the outer guard).
TURN_TIMEOUT = int(os.environ.get("CLAUDE_SUB_TURN_TIMEOUT", "150"))

# Recorded by NAME only (never value) in meta/run.json. CLAUDE_CODE_OAUTH_TOKEN /
# ANTHROPIC_AUTH_TOKEN matter for (a0): a non-TTY OAuth turn satisfied by a token
# env var is a *different mechanism* than riding the keychain Max session.
_ENV_CANDIDATES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_SUB_PROBE_MODEL",
    "CLAUDE_SUB_CAPTURE_DIR",
)

# Generic auth/login markers (NOT secrets) used to classify a failed turn as
# "auth required non-TTY" (kill #1) vs an unrelated failure (inconclusive).
_AUTH_MARKERS = (
    "login",
    "log in",
    "oauth",
    "not authenticated",
    "authentication",
    "unauthorized",
    "credential",
    "api key",
    "invalid x-api-key",
    "please run `claude`",
    "run claude login",
    "401",
)


# --------------------------------------------------------------------------- #
# Small IO + provenance helpers (no secrets ever written)
# --------------------------------------------------------------------------- #
def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _git_short_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _prefix(value: str | None) -> str | None:
    """Record only an id *prefix* (never the unique id)."""
    if not value:
        return None
    return value.split("-")[0] + "-" if "-" in value else value[:6]


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def _results_dir(capture_dir: Path) -> Path:
    d = capture_dir / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_record(capture_dir: Path, label: str, record: dict[str, Any]) -> None:
    _write_json(_results_dir(capture_dir) / f"{label}.record.json", record)


def write_verdict(capture_dir: Path, text: str) -> None:
    (_results_dir(capture_dir) / "verdict.txt").write_text(text + "\n")
    print(f"[claude_probe] verdict: {text}")


def append_oracle(capture_dir: Path, label: str, line: str) -> None:
    with (_results_dir(capture_dir) / f"{label}.oracle.txt").open("a") as fh:
        fh.write(line + "\n")


def write_run_manifest(capture_dir: Path, stage_label: str, intent: str) -> None:
    meta = capture_dir / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": stage_label,
        "started_at": _utcnow(),
        "auth_intent": intent,
        "model": PROBE_MODEL or "<claude-default>",
        "helper_version": HELPER_VERSION,
        "git_short_sha": _git_short_sha(),
        # NAMES only -- never values.
        "env_vars_present": [name for name in _ENV_CANDIDATES if os.environ.get(name)],
    }
    _write_json(meta / "run.json", manifest)


def _maybe_debug_raw(args: argparse.Namespace, capture_dir: Path, name: str, text: str) -> None:
    """Write a raw payload to the cache only when --debug-raw is set (scrubbed by sanitize.sh)."""
    if not getattr(args, "debug_raw", False):
        return
    try:
        d = capture_dir / "streams"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.raw.txt").write_text(text)
    except Exception:
        pass


def _auth_ignore_env() -> bool:
    try:
        from forge.runtime_config import get_runtime_config

        return bool(get_runtime_config().auth_ignore_env)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# The keyless gate -- the SAME predicate the runner uses (session_runner.py:183)
# --------------------------------------------------------------------------- #
def keyless_state() -> dict[str, Any]:
    """Resolve whether Forge would consider an API key available for a headless run.

    Calls ``can_use_bare()`` (env.py) -- which delegates to
    ``resolve_env_or_credential`` and honors ``auth_ignore_env`` -- so the probe's
    notion of "keyless" matches the runner's exactly. Returns metadata only
    (booleans + a source label), never the key value. Raises on import failure so
    the caller fails closed.
    """
    from forge.core.auth.template_secrets import resolve_env_or_credential_with_source
    from forge.core.reactive.env import can_use_bare

    resolvable = can_use_bare()  # None => os.environ + credential file, honors auth_ignore_env
    _value, source = resolve_env_or_credential_with_source("ANTHROPIC_API_KEY")
    del _value  # never persisted, never printed
    return {
        "key_resolvable": bool(resolvable),
        "key_source": source,  # "env" | "credential_file" | "none"
        "auth_ignore_env": _auth_ignore_env(),
        "anthropic_base_url_set": bool(os.environ.get("ANTHROPIC_BASE_URL")),
        "oauth_token_env_present": bool(
            os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        ),
    }


# --------------------------------------------------------------------------- #
# Envelope parsing -- proven shape from headless-cost-report (CC 2.1.165):
# `--output-format json` emits [system, assistant, result]; cost/usage live in
# the LAST type=="result" element. Metadata-only extraction (no model text).
# --------------------------------------------------------------------------- #
def classify_envelope(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except Exception:
        return {"valid_json": False, "has_result": False}
    res: dict[str, Any] | None = None
    if isinstance(data, list):
        results = [x for x in data if isinstance(x, dict) and x.get("type") == "result"]
        res = results[-1] if results else None
    elif isinstance(data, dict):
        res = data if data.get("type") == "result" else None
    if res is None:
        return {"valid_json": True, "has_result": False}
    cost = res.get("total_cost_usd")
    usage_raw = res.get("usage")
    usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
    return {
        "valid_json": True,
        "has_result": True,
        "cost_present": isinstance(cost, (int, float)),
        "cost_value": cost if isinstance(cost, (int, float)) else None,
        "has_usage": usage.get("input_tokens") is not None,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "is_error": bool(res.get("is_error")),
        "subtype": res.get("subtype"),
        "session_id_prefix": _prefix(res.get("session_id")),
    }


def _run_keyless_turn() -> tuple[int, str, str, bool]:
    """Run one keyless, direct ``claude -p --output-format json`` turn.

    Returns (returncode, stdout, stderr, timed_out). Pops ANTHROPIC_API_KEY (defense
    in depth -- the precondition already proved it absent) and forces DIRECT routing
    by unsetting any proxy so the turn tests OAuth-to-Anthropic, not a backend. Runs
    in a disposable CWD so transcripts land harmlessly under ~/.claude/projects.
    """
    env = os.environ.copy()
    for var in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "FORGE_SUBPROCESS_PROXY",
        "FORGE_SUBPROCESS_BASE_URL",
        "FORGE_SUBPROCESS_PROXY_ID",
    ):
        env.pop(var, None)
    cmd = ["claude", "-p", PROBE_PROMPT, "--output-format", "json"]
    if PROBE_MODEL:
        cmd += ["--model", PROBE_MODEL]
    # No --bare: omitting it is what PERMITS the OAuth/keychain path (the point of a0).
    workdir = tempfile.mkdtemp(prefix="claude-sub-probe-")
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=TURN_TIMEOUT,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        errout = exc.stderr or ""
        out = out.decode() if isinstance(out, bytes) else out
        errout = errout.decode() if isinstance(errout, bytes) else errout
        return 124, out, errout, True
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _auth_marker_seen(*texts: str) -> bool:
    blob = " ".join(t.lower() for t in texts if t)
    return any(marker in blob for marker in _AUTH_MARKERS)


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
def cmd_precondition(args: argparse.Namespace) -> int:
    """GATE: prove the keyless path is actually keyless, or refuse to proceed."""
    capture_dir = Path(args.capture_dir)
    write_run_manifest(capture_dir, args.label, intent="keyless_check")
    try:
        state = keyless_state()
    except Exception as exc:  # fail CLOSED: unverifiable != keyless
        write_record(capture_dir, args.label, {"kind": "precondition", "check_error": str(exc)[:200]})
        write_verdict(capture_dir, "[PRECONDITION-ERROR]")
        print(f"ERROR: could not run the keyless check (forge import failed): {exc}", file=sys.stderr)
        return 2
    write_record(capture_dir, args.label, {"kind": "precondition", **state})
    if state["key_resolvable"]:
        write_verdict(capture_dir, "[KEY-RESOLVABLE]")
        append_oracle(
            capture_dir,
            args.label,
            f"A key is resolvable via {state['key_source']} (auth_ignore_env="
            f"{state['auth_ignore_env']}). The runner would add --bare and the probe "
            f"would measure the KEY path, not the subscription. Unset it and re-run.",
        )
        print(
            "ERROR: ANTHROPIC_API_KEY is resolvable -- the keyless path cannot be measured.\n"
            f"  source={state['key_source']}  auth_ignore_env={state['auth_ignore_env']}\n"
            "  Unset ANTHROPIC_API_KEY in the shell AND remove it from ~/.forge/credentials.yaml\n"
            "  (note: auth_ignore_env changes which sources count), then re-run.",
            file=sys.stderr,
        )
        return 1
    note = "keyless confirmed (can_use_bare False)."
    if state["anthropic_base_url_set"]:
        note += " ANTHROPIC_BASE_URL is set; the turn forces DIRECT routing anyway."
    if state["oauth_token_env_present"]:
        note += " An OAuth token env var IS present: a passing turn may ride that token, not the keychain Max session."
    append_oracle(capture_dir, args.label, note)
    write_verdict(capture_dir, "[KEYLESS-OK]")
    return 0


def cmd_turn(args: argparse.Namespace) -> int:
    """(a0)+(a)+(b): one keyless turn; read OAuth feasibility, completion, and cost."""
    capture_dir = Path(args.capture_dir)
    write_run_manifest(capture_dir, args.label, intent="keyless_direct_turn")

    # Self-guard: refuse to make a billable call if a key is resolvable (defense in
    # depth -- running `./reproduce.sh 10-turn` alone must still be keyless).
    try:
        state = keyless_state()
    except Exception as exc:
        write_record(capture_dir, args.label, {"kind": "turn", "check_error": str(exc)[:200]})
        write_verdict(capture_dir, "[PRECONDITION-ERROR]")
        print(f"ERROR: keyless check failed; refusing to run a turn: {exc}", file=sys.stderr)
        return 2
    if state["key_resolvable"]:
        write_record(capture_dir, args.label, {"kind": "turn", **state})
        write_verdict(capture_dir, "[KEY-RESOLVABLE]")
        print("ERROR: key resolvable; refusing to run (would measure the key path).", file=sys.stderr)
        return 1

    rc, out, errout, timed_out = _run_keyless_turn()
    _maybe_debug_raw(args, capture_dir, "turn.stdout", out)
    _maybe_debug_raw(args, capture_dir, "turn.stderr", errout)
    env = classify_envelope(out)
    auth_marker = _auth_marker_seen(out, errout)
    completed = rc == 0 and env.get("has_result") and not env.get("is_error")

    # (a0) non-TTY OAuth feasibility
    if completed:
        a0 = "[OAUTH-NONTTY-OK]"
    elif auth_marker:
        a0 = "[OAUTH-NONTTY-FAILED]"  # kill #1 candidate: headless auth needs a TTY/login
    else:
        a0 = "[OAUTH-NONTTY-INCONCLUSIVE]"  # timeout / non-auth error

    # (b) billing signal (only meaningful if the turn completed)
    if not completed:
        b = "[COST-INCONCLUSIVE]"
    elif env.get("cost_present"):
        b = "[COST-PRESENT]"
    else:
        b = "[COST-ABSENT]"

    # Composite shape. KEY FINDING (live Max run, 2026-06-29): a keyless turn that
    # completes MUST have ridden OAuth -- with no API key and no proxy there is nothing
    # to bill an API per-token -- so it is a subscription run REGARDLESS of the cost
    # field. total_cost_usd is an API-list-price ESTIMATE present even on Max ($0.041 for
    # a 4-token reply), so it is NOT a billing discriminator: record it as evidence, keep
    # it `unavailable` for the cost plane (design 3.14), never let it flip the label.
    if a0 == "[OAUTH-NONTTY-FAILED]":
        shape = "[OAUTH-NONTTY-FAILED]"  # architectural kill: keyless auth needs a TTY/login
    elif not completed:
        shape = "[TURN-INCONCLUSIVE]"
    else:
        shape = "[SHAPE-SUBSCRIPTION]"  # keyless + completed => rode the subscription

    record = {
        "kind": "turn",
        "returncode": rc,
        "timed_out": timed_out,
        "auth_marker_seen": auth_marker,
        "oauth_token_env_present": state["oauth_token_env_present"],
        "a0_oauth_nontty": a0,
        "a_turn_completed": bool(completed),
        "b_cost_signal": b,
        "shape": shape,
        "envelope": env,
    }
    write_record(capture_dir, args.label, record)
    append_oracle(capture_dir, args.label, f"(a0) non-TTY OAuth: {a0}")
    append_oracle(capture_dir, args.label, f"(a) turn completed: {bool(completed)} (rc={rc}, timed_out={timed_out})")
    append_oracle(
        capture_dir,
        args.label,
        f"(b) cost signal: {b} (cost_value={env.get('cost_value')!r}, "
        f"usage in/out={env.get('input_tokens')}/{env.get('output_tokens')})",
    )
    if completed:
        append_oracle(
            capture_dir,
            args.label,
            "NOTE: cost_value is an API-list-price ESTIMATE present even on Max -- not a billing "
            "discriminator. Keyless + completed => subscription; keep cost `unavailable` (design 3.14).",
        )
    if state["oauth_token_env_present"] and completed:
        append_oracle(
            capture_dir,
            args.label,
            "NOTE: an OAuth token env var was present -- this turn may have ridden that token, "
            "not the interactive keychain Max session. Re-run with it unset to isolate the keychain path.",
        )
    write_verdict(capture_dir, shape)
    # rc maps to the *probe*'s success (did we get a usable reading?), not the turn's.
    return 0 if shape != "[TURN-INCONCLUSIVE]" else 3


def _stat_mode(path: Path) -> str | None:
    try:
        return stat.filemode(path.stat().st_mode)
    except Exception:
        return None


def cmd_detection(args: argparse.Namespace) -> int:
    """(c): enumerate auth-mode detection candidates read-only; report stability.

    NEVER reads the contents of a token store. ``claude config get`` is captured for
    key NAMES only; credential files are checked for existence/mode only; the OS
    keychain is NOT queried (it would surface the token).
    """
    capture_dir = Path(args.capture_dir)
    write_run_manifest(capture_dir, args.label, intent="detection_signal")
    home = Path(os.path.expanduser("~"))
    candidates: list[dict[str, Any]] = []

    # Candidate 0 (the real signal): key-resolvability via can_use_bare -- the SAME
    # predicate session_runner uses to decide --bare. Forge-owned, preflight, stable,
    # non-leaking. can_use_bare False => the run is keyless => a completing turn (stage
    # 10) rode OAuth/subscription; True => the runner adds --bare => api. Phase 1 keys
    # off this, and it needs no unowned external schema. The live Max run showed the
    # envelope-cost signal does NOT discriminate (cost is present even on Max), so this
    # input-side predicate -- not any run artifact -- is the dependable signal.
    cub: dict[str, Any] = {
        "name": "can_use_bare (key-resolvability; the runner's own predicate)",
        "available_preflight": True,
        "stable_contract": True,
        "leaks_secret": False,
    }
    try:
        ks = keyless_state()
        cub["key_resolvable"] = ks["key_resolvable"]
        cub["implied_auth_path"] = "api (--bare)" if ks["key_resolvable"] else "keyless (OAuth/subscription)"
    except Exception as exc:
        cub["error"] = str(exc)[:120]
        cub["stable_contract"] = False  # cannot read the predicate here -> not usable
    candidates.append(cub)

    # Candidate 1: `claude config get` -- key NAMES only, never values. Secondary: the
    # live run showed it hangs / has no clean non-TTY contract.
    cfg: dict[str, Any] = {
        "name": "claude config get",
        "available_preflight": True,
        "stable_contract": False,  # no documented JSON contract naming auth mode
        "leaks_secret": False,
    }
    try:
        # A timeout here is itself a finding: `claude config get` can hang (interactive
        # config picker / no clean non-TTY contract), so a bounded wait that records
        # "timed out" is evidence the candidate is NOT a stable scriptable signal.
        proc = subprocess.run(
            ["claude", "config", "get"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        cfg["returncode"] = proc.returncode
        try:
            parsed = json.loads(proc.stdout)
            cfg["json"] = True
            cfg["top_level_keys"] = sorted(parsed.keys()) if isinstance(parsed, dict) else None
            keys = cfg["top_level_keys"] or []
            cfg["auth_mode_key_present"] = any(
                k for k in keys if any(w in k.lower() for w in ("auth", "login", "subscription", "oauth"))
            )
            # A documented, auth-naming, parseable key would make this stable-preflight.
            cfg["stable_contract"] = bool(cfg["auth_mode_key_present"])
        except Exception:
            cfg["json"] = False
            cfg["top_level_keys"] = None
            cfg["auth_mode_key_present"] = False
    except Exception as exc:
        cfg["error"] = str(exc)[:120]
    candidates.append(cfg)

    # Candidate 2: ~/.claude credential files -- existence/mode ONLY (holds the token).
    for rel in (".claude/.credentials.json", ".claude/credentials.json"):
        p = home / rel
        candidates.append(
            {
                "name": f"~/{rel} (presence only)",
                "available_preflight": True,
                "stable_contract": False,  # CC-owned schema, unowned by Forge; presence != active sub
                "leaks_secret": True,  # contents hold the OAuth token -> never read
                "exists": p.exists(),
                "mode": _stat_mode(p) if p.exists() else None,
            }
        )

    # Candidate 3: OS keychain -- NOT probed by design (querying surfaces the token).
    candidates.append(
        {
            "name": "OS keychain (macOS Keychain / libsecret)",
            "available_preflight": True,
            "stable_contract": False,  # OS-specific, unowned schema
            "leaks_secret": True,
            "probed": False,
            "note": "not queried by design -- a read would surface the OAuth token",
        }
    )

    # Candidate 4: envelope cost-null -- a RUNTIME-only signal (only after a turn).
    candidates.append(
        {
            "name": "envelope total_cost_usd null (see stage 10-turn)",
            "available_preflight": False,  # only observable AFTER a turn
            "stable_contract": True,  # the field is part of the documented envelope
            "leaks_secret": False,
            "note": "runtime-only: cannot classify auth at preflight, only post-hoc",
        }
    )

    stable_preflight = [
        c for c in candidates if c["available_preflight"] and c["stable_contract"] and not c["leaks_secret"]
    ]
    runtime_only_viable = any(
        (not c["available_preflight"]) and c["stable_contract"] and not c["leaks_secret"] for c in candidates
    )
    if stable_preflight:
        chosen = stable_preflight[0]["name"]
        v = "[SIGNAL-STABLE-PREFLIGHT]"
    elif runtime_only_viable:
        chosen = "envelope total_cost_usd null"
        v = "[SIGNAL-RUNTIME-ONLY]"
    else:
        chosen = "none"
        v = "[SIGNAL-NONE]"

    write_record(
        capture_dir,
        args.label,
        {"kind": "detection", "chosen_signal": chosen, "verdict": v, "candidates": candidates},
    )
    for c in candidates:
        append_oracle(
            capture_dir,
            args.label,
            f"candidate: {c['name']} -- preflight={c['available_preflight']} "
            f"stable={c['stable_contract']} leaks={c['leaks_secret']}",
        )
    append_oracle(capture_dir, args.label, f"chosen: {chosen} -> {v}")
    append_oracle(
        capture_dir,
        args.label,
        "NOTE: can_use_bare is the preflight discriminator of the INTENDED path; a completing "
        "keyless turn (stage 10) confirms it actually rode subscription.",
    )
    write_verdict(capture_dir, v)
    return 0


def cmd_quota(args: argparse.Namespace) -> int:
    """(d, optional): does a keyless turn surface any quota/rate-limit headroom?

    Best-effort. ``claude -p --output-format json`` does not expose rate-limit
    headers, so the honest default is [QUOTA-UNOBSERVED]. Inspects the result
    element for any quota/rate/limit-named fields (names only).
    """
    capture_dir = Path(args.capture_dir)
    write_run_manifest(capture_dir, args.label, intent="quota_draw")
    try:
        state = keyless_state()
    except Exception as exc:
        write_record(capture_dir, args.label, {"kind": "quota", "check_error": str(exc)[:200]})
        write_verdict(capture_dir, "[PRECONDITION-ERROR]")
        return 2
    if state["key_resolvable"]:
        write_record(capture_dir, args.label, {"kind": "quota", **state})
        write_verdict(capture_dir, "[KEY-RESOLVABLE]")
        print("ERROR: key resolvable; refusing to run.", file=sys.stderr)
        return 1

    turn = _run_keyless_turn()
    rc, out, timed_out = turn[0], turn[1], turn[3]
    _maybe_debug_raw(args, capture_dir, "quota.stdout", out)
    quota_fields: list[str] = []
    try:
        data = json.loads(out)
        elements = data if isinstance(data, list) else [data]
        for el in elements:
            if isinstance(el, dict):
                for k in el.keys():
                    if any(w in k.lower() for w in ("quota", "rate", "limit", "reset", "remaining")):
                        quota_fields.append(k)
    except Exception:
        pass
    observed = bool(quota_fields)
    v = "[QUOTA-OBSERVED]" if observed else "[QUOTA-UNOBSERVED]"
    write_record(
        capture_dir,
        args.label,
        {
            "kind": "quota",
            "returncode": rc,
            "timed_out": timed_out,
            "quota_fields_seen": sorted(set(quota_fields)),
            "note": "claude -p does not surface anthropic-ratelimit-* headers; this is best-effort.",
        },
    )
    append_oracle(capture_dir, args.label, f"(d) quota fields in envelope: {sorted(set(quota_fields)) or 'none'}")
    write_verdict(capture_dir, v)
    return 0


# --------------------------------------------------------------------------- #
DISPATCH: dict[str, Callable[[argparse.Namespace], int]] = {
    "precondition": cmd_precondition,
    "turn": cmd_turn,
    "detection": cmd_detection,
    "quota": cmd_quota,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claude-subscription billing Phase 0 probe helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in DISPATCH:
        sp = sub.add_parser(name)
        sp.add_argument("--capture-dir", required=True)
        sp.add_argument("--label", default=name)
        sp.add_argument(
            "--debug-raw",
            action="store_true",
            help="dump raw stdout/stderr to the cache (never committed; scrubbed by sanitize.sh)",
        )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return DISPATCH[args.cmd](args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
