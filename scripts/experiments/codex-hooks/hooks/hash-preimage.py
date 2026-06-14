#!/usr/bin/env python3
"""Reverse-engineer Codex's hook `trusted_hash` from harvested (registration ->
hash) pairs, then optionally forge a `[hooks.state]` record to prove programmatic
pre-enrollment.

Stage 80 enrolls a fixture whose user config.toml carries `[hooks.state]` records
(one per registered hook), each with a `trusted_hash = "sha256:<hex>"`. Codex hashes
*something* about each hook's definition to key trust to it. This tool:

  1. parses the trust state + the registrations (project + user config),
  2. joins each trust key to the hook definition it refers to (the key embeds the
     registering config's absolute path + snake_case event + matcher/hook indices),
  3. tries a battery of candidate canonicalizations, sha256s each, and reports any
     that reproduce the stored hash ACROSS ALL pairs (one match per pair is a
     coincidence; the same candidate winning every pair is the algorithm),
  4. with --emit-state, reuses the winning candidate to compute the hash for a NEW
     registration and prints the `[hooks.state."..."]` TOML block to forge.

If NO candidate wins, that is a finding, not a failure: the posture decision lands
on "guided one-time ceremony" and the next step is a source-dive of the codex-cli
release (openai/codex, Rust) for the hooks/trust hashing code -- encode it here and
re-run. Honest about provenance: only the stage-80 harvested pairs are trustworthy
vectors; a --known-hash from an earlier round whose registration was not captured is
printed for reference but cannot be tested.

Pure stdlib. TOML via tomllib (py3.11+); falls back to a minimal line parser for the
constrained shapes Codex/gen-config.py emit when tomllib is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Callable

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised only on <3.11
    tomllib = None  # type: ignore[assignment]


# --- TOML loading -----------------------------------------------------------


def load_toml(path: str) -> dict:
    """Parse a TOML file. Prefer tomllib; fall back to a minimal parser that only
    understands the shapes this probe emits (`[[hooks.EVENT]]`, `[hooks.state."k"]`,
    scalar `key = "value"` / `key = int`)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if tomllib is not None:
        return tomllib.loads(raw.decode("utf-8"))
    return _minimal_toml(raw.decode("utf-8"))


def _minimal_toml(text: str) -> dict:
    """Tiny TOML subset parser (fallback only). Handles array-of-tables headers
    `[[a.b]]`, table headers `[a.b."quoted"]`, and `key = "str"` / `key = int`."""
    root: dict = {}

    def descend(path: list[str], make_list: bool) -> dict:
        node = root
        for i, part in enumerate(path):
            last = i == len(path) - 1
            if last and make_list:
                lst = node.setdefault(part, [])
                if not isinstance(lst, list):
                    raise ValueError(f"expected array-of-tables at {part!r}")
                tbl: dict = {}
                lst.append(tbl)
                return tbl
            nxt = node.get(part)
            if isinstance(nxt, list):
                nxt = nxt[-1]
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        return node

    def split_dotted(s: str) -> list[str]:
        # Split on '.' except inside double quotes; strip quotes from each part.
        parts: list[str] = []
        buf: list[str] = []
        in_q = False
        for ch in s:
            if ch == '"':
                in_q = not in_q
            elif ch == "." and not in_q:
                parts.append("".join(buf))
                buf = []
                continue
            buf.append(ch)
        parts.append("".join(buf))
        return [p[1:-1] if p.startswith('"') and p.endswith('"') else p for p in parts]

    cur = root
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("[[") and s.endswith("]]"):
            cur = descend(split_dotted(s[2:-2].strip()), make_list=True)
        elif s.startswith("[") and s.endswith("]"):
            cur = descend(split_dotted(s[1:-1].strip()), make_list=False)
        elif "=" in s:
            k, _, v = s.partition("=")
            k, v = k.strip(), v.strip()
            if k.startswith('"') and k.endswith('"'):
                k = k[1:-1]
            if v.startswith('"') and v.endswith('"'):
                cur[k] = v[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            elif v.lstrip("-").isdigit():
                cur[k] = int(v)
            else:
                cur[k] = v.strip('"')
    return root


# --- model -------------------------------------------------------------------

_EVENT_SNAKE = re.compile(r"(?<!^)(?=[A-Z])")


def snake(event: str) -> str:
    return _EVENT_SNAKE.sub("_", event).lower()


class Entry:
    """A registered hook definition joined to its trust key + stored hash."""

    def __init__(self, key, config_path, event, matcher, command, htype, timeout, stored_hash):
        self.key = key
        self.config_path = config_path
        self.event = event
        self.matcher = matcher
        self.command = command
        self.type = htype
        self.timeout = timeout
        self.stored_hash = stored_hash  # hex, no "sha256:" prefix

    def __repr__(self) -> str:
        return f"<Entry {self.event} cmd={self.command!r} hash={self.stored_hash[:12]}…>"


def collect_registrations(config: dict) -> dict[tuple[str, int, int], dict]:
    """Map (snake_event, matcher_idx, hook_idx) -> hook definition for one config."""
    out: dict[tuple[str, int, int], dict] = {}
    hooks = config.get("hooks", {})
    for event, blocks in hooks.items():
        if event == "state" or not isinstance(blocks, list):
            continue
        for mi, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            matcher = block.get("matcher")
            inner = block.get("hooks", [])
            if not isinstance(inner, list):
                continue
            for hi, hook in enumerate(inner):
                if not isinstance(hook, dict):
                    continue
                out[(snake(event), mi, hi)] = {
                    "event": event,
                    "matcher": matcher,
                    "command": hook.get("command"),
                    "type": hook.get("type"),
                    "timeout": hook.get("timeout"),
                }
    return out


def parse_trust_state(user_config: dict) -> dict[str, str]:
    """Return {trust_key: hex_hash} from `[hooks.state]`."""
    out: dict[str, str] = {}
    state = user_config.get("hooks", {}).get("state", {})
    if not isinstance(state, dict):
        return out
    for key, val in state.items():
        if isinstance(val, dict) and "trusted_hash" in val:
            h = str(val["trusted_hash"])
            out[key] = h.split(":", 1)[1] if ":" in h else h
    return out


def split_key(key: str) -> tuple[str, str, int, int] | None:
    """`<config-abs>:<snake_event>:<matcher_idx>:<hook_idx>` -> parts (path may
    contain ':' on exotic systems, so split from the right)."""
    parts = key.rsplit(":", 3)
    if len(parts) != 4:
        return None
    path, event, mi, hi = parts
    if not (mi.isdigit() and hi.isdigit()):
        return None
    return path, event, int(mi), int(hi)


def join_pairs(trust: dict[str, str], regs: list[tuple[str, dict]]) -> tuple[list[Entry], list[str]]:
    """Join trust keys to registrations. `regs` is a list of (config_abs_path, regmap).
    Match by exact path, else by path suffix (captured copies may sit elsewhere)."""
    entries: list[Entry] = []
    unmatched: list[str] = []
    for key, stored in trust.items():
        sp = split_key(key)
        if not sp:
            unmatched.append(f"{key} (unparseable key)")
            continue
        keypath, event, mi, hi = sp
        chosen = None
        for cfg_path, regmap in regs:
            if cfg_path == keypath or keypath.endswith(_tail(cfg_path)) or cfg_path.endswith(_tail(keypath)):
                if (event, mi, hi) in regmap:
                    chosen = (cfg_path, regmap[(event, mi, hi)])
                    break
        if not chosen:
            unmatched.append(f"{key} (no registration entry)")
            continue
        d = chosen[1]
        entries.append(Entry(key, keypath, d["event"], d["matcher"], d["command"], d["type"], d["timeout"], stored))
    return entries, unmatched


def _tail(path: str) -> str:
    """Last two path components (e.g. `.codex/config.toml`) for tolerant matching."""
    bits = path.replace("\\", "/").rstrip("/").split("/")
    return "/".join(bits[-2:])


# --- candidate preimages -----------------------------------------------------
# Each candidate maps an Entry to the bytes Codex MIGHT hash. The winner is the
# candidate whose sha256 reproduces stored_hash for EVERY harvested pair.

CandidateFn = Callable[[Entry], bytes]


def _json_compact(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _struct(e: Entry, *, with_matcher=False, with_event=False, with_type=True, with_timeout=True) -> dict:
    o: dict = {"command": e.command}
    if with_type:
        o["type"] = e.type
    if with_timeout and e.timeout is not None:
        o["timeout"] = e.timeout
    if with_matcher and e.matcher is not None:
        o["matcher"] = e.matcher
    if with_event:
        o["event"] = e.event
    return o


CANDIDATES: dict[str, CandidateFn] = {
    "command": lambda e: (e.command or "").encode(),
    "command+nl": lambda e: ((e.command or "") + "\n").encode(),
    "type:command": lambda e: f"{e.type}:{e.command}".encode(),
    "command:timeout": lambda e: f"{e.command}:{e.timeout}".encode(),
    "type:command:timeout": lambda e: f"{e.type}:{e.command}:{e.timeout}".encode(),
    "event:command": lambda e: f"{e.event}:{e.command}".encode(),
    "json{command}": lambda e: _json_compact({"command": e.command}),
    "json{type,command}": lambda e: _json_compact(_struct(e, with_timeout=False)),
    "json{type,command,timeout}": lambda e: _json_compact(_struct(e)),
    "json{type,command,timeout,matcher}": lambda e: _json_compact(_struct(e, with_matcher=True)),
    "json{event,type,command,timeout}": lambda e: _json_compact(_struct(e, with_event=True)),
    "key": lambda e: e.key.encode(),
    "keypath:command": lambda e: f"{e.config_path}:{e.command}".encode(),
    "nl(type,command,timeout)": lambda e: "\n".join([str(e.type), str(e.command), str(e.timeout)]).encode(),
    "toml-block": lambda e: _toml_block(e).encode(),
}


def _toml_block(e: Entry) -> str:
    """Reconstruct the gen-config.py `[[hooks.EVENT]]` block bytes for this entry."""
    out = [f"[[hooks.{e.event}]]"]
    if e.matcher is not None:
        out.append(f'matcher = "{e.matcher}"')
    out.append(f"[[hooks.{e.event}.hooks]]")
    out.append(f'type = "{e.type}"')
    out.append(f'command = "{e.command}"')
    out.append(f"timeout = {e.timeout}")
    return "\n".join(out)


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def find_winner(entries: list[Entry]) -> tuple[str | None, dict[str, list[bool]]]:
    """Return (winning_candidate_or_None, per-candidate match vector)."""
    results: dict[str, list[bool]] = {}
    for name, fn in CANDIDATES.items():
        vec = []
        for e in entries:
            try:
                vec.append(sha256_hex(fn(e)) == e.stored_hash.lower())
            except Exception:  # noqa: BLE001 - a candidate may not apply to an entry
                vec.append(False)
        results[name] = vec
    winner = next((n for n, v in results.items() if v and all(v)), None)
    return winner, results


# --- emit-state --------------------------------------------------------------


def emit_state(winner_fn: CandidateFn, *, config_path, event, command, matcher, htype, timeout, mi, hi) -> str:
    e = Entry("", config_path, event, matcher, command, htype, timeout, "")
    digest = sha256_hex(winner_fn(e))
    key = f"{config_path}:{snake(event)}:{mi}:{hi}"
    return f'[hooks.state."{key}"]\ntrusted_hash = "sha256:{digest}"\n'


# --- main --------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-config", required=True, help="enrolled user config.toml (carries [hooks.state])")
    ap.add_argument("--project-config", help="project .codex/config.toml (registrations)")
    ap.add_argument("--known-hash", action="append", default=[], help="reference-only sha256:<hex> (untestable)")
    # --emit-state forges a [hooks.state] block for a NEW registration using the
    # discovered algorithm (exit nonzero if no candidate won).
    ap.add_argument("--emit-state", action="store_true")
    ap.add_argument("--state-config-path", help="absolute path of the target config (embeds in the key)")
    ap.add_argument("--state-event", default="SessionStart")
    ap.add_argument("--state-command")
    ap.add_argument("--state-matcher", default=None)
    ap.add_argument("--state-type", default="command")
    ap.add_argument("--state-timeout", type=int, default=60)
    ap.add_argument("--state-matcher-idx", type=int, default=0)
    ap.add_argument("--state-hook-idx", type=int, default=0)
    args = ap.parse_args()

    user_cfg = load_toml(args.user_config)
    trust = parse_trust_state(user_cfg)

    regs: list[tuple[str, dict]] = []
    import os

    regs.append((os.path.realpath(args.user_config), collect_registrations(user_cfg)))
    if args.project_config:
        proj_cfg = load_toml(args.project_config)
        regs.append((os.path.realpath(args.project_config), collect_registrations(proj_cfg)))

    entries, unmatched = join_pairs(trust, regs)

    if args.emit_state:
        winner, _ = find_winner(entries)
        if not winner:
            print("ERROR: no candidate algorithm matched -- cannot forge a state record.", file=sys.stderr)
            return 3
        if not (args.state_config_path and args.state_command):
            print("ERROR: --emit-state needs --state-config-path and --state-command.", file=sys.stderr)
            return 2
        sys.stdout.write(
            emit_state(
                CANDIDATES[winner],
                config_path=args.state_config_path,
                event=args.state_event,
                command=args.state_command,
                matcher=args.state_matcher,
                htype=args.state_type,
                timeout=args.state_timeout,
                mi=args.state_matcher_idx,
                hi=args.state_hook_idx,
            )
        )
        return 0

    # Report mode.
    print(f"trust keys: {len(trust)}; joined pairs: {len(entries)}; unmatched: {len(unmatched)}")
    for u in unmatched:
        print(f"  UNMATCHED {u}")
    if not entries:
        print("NO PAIRS -- nothing to analyze. Did stage 80 enroll? Are the config paths the LIVE fixture files?")
        return 1
    print("\nharvested pairs:")
    for e in entries:
        print(f"  {e.event:18} hash={e.stored_hash[:16]}… cmd={e.command}")

    winner, results = find_winner(entries)
    print("\ncandidate scan (matched / total pairs):")
    for name, vec in sorted(results.items(), key=lambda kv: (-sum(kv[1]), kv[0])):
        print(f"  {name:38} {sum(vec)}/{len(vec)}")

    print()
    if winner:
        print(f"PREIMAGE FOUND: '{winner}' reproduces every harvested trusted_hash.")
        print("-> programmatic pre-enrollment is COMPUTABLE; stage 83 can forge a [hooks.state] record.")
        print("-> posture decision input: installer MAY write trust records (explicit, documented).")
    else:
        print("NO CANDIDATE MATCHED across all pairs.")
        print("-> NOT a failure: the posture decision lands on a GUIDED one-time ceremony.")
        print("-> next step (optional): source-dive openai/codex for the hooks/trust hashing code at the")
        print("   installed version, encode the algorithm as a new CANDIDATES entry, and re-run.")

    for kh in args.known_hash:
        print(f"\nreference-only --known-hash {kh}: registration not captured this round; untested (lower fidelity).")
    return 0 if winner else 1


if __name__ == "__main__":
    raise SystemExit(main())
