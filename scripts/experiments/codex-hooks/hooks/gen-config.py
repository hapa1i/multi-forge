#!/usr/bin/env python3
"""Emit Codex hook registration config (JSON or TOML) from compact specs.

Usage:
    gen-config.py --format {json,toml} HOOKSPEC...

HOOKSPEC := EVENT[:MATCHER]=COMMAND

The emitted shapes are the DOC-CLAIMED registration forms (needs binary
confirmation -- that confirmation is stage 10/20's job):

JSON (hooks.json):
    {"hooks": {"PreToolUse": [{"matcher": "...", "hooks":
        [{"type": "command", "command": "/abs/wrapper.sh", "timeout": 60}]}]}}

TOML (config.toml):
    [[hooks.PreToolUse]]
    matcher = "..."
    [[hooks.PreToolUse.hooks]]
    type = "command"
    command = "/abs/wrapper.sh"
    timeout = 60

Matcher is omitted when not given (UserPromptSubmit/Stop doc-claim no matcher
support). Commands are per-label wrapper scripts, so no arg-splitting ambiguity.
"""

from __future__ import annotations

import argparse
import json
import sys


def parse_spec(spec: str) -> tuple[str, str | None, str]:
    head, sep, command = spec.partition("=")
    if not sep or not command:
        raise SystemExit(f"bad HOOKSPEC (want EVENT[:MATCHER]=COMMAND): {spec!r}")
    event, msep, matcher = head.partition(":")
    if not event:
        raise SystemExit(f"bad HOOKSPEC (empty event): {spec!r}")
    return event, (matcher if msep else None), command


def toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=("json", "toml"), required=True)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("specs", nargs="+")
    args = ap.parse_args()

    entries = [parse_spec(s) for s in args.specs]

    if args.format == "json":
        hooks: dict[str, list[dict]] = {}
        for event, matcher, command in entries:
            entry: dict = {}
            if matcher is not None:
                entry["matcher"] = matcher
            entry["hooks"] = [
                {"type": "command", "command": command, "timeout": args.timeout}
            ]
            hooks.setdefault(event, []).append(entry)
        json.dump({"hooks": hooks}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    out: list[str] = []
    for event, matcher, command in entries:
        out.append(f"[[hooks.{event}]]")
        if matcher is not None:
            out.append(f"matcher = {toml_str(matcher)}")
        out.append(f"[[hooks.{event}.hooks]]")
        out.append('type = "command"')
        out.append(f"command = {toml_str(command)}")
        out.append(f"timeout = {args.timeout}")
        out.append("")
    sys.stdout.write("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
