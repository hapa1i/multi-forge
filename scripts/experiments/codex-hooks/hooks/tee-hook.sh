#!/usr/bin/env bash
# tee-hook.sh <event-label> -- pure observer: capture stdin payload + allowlisted
# env + pwd, then get out of the way (exit 0, NO stdout -- stdout may be parsed
# as a hook response, which is exactly what we are not testing here).
#
# The label is baked into the per-label wrapper at registration time, so capture
# attribution never depends on the doc-claimed `hook_event_name` payload field
# (that field's presence/name is itself under test).
set -u
LABEL="${1:?event label}"
DIR="${PROBE_CAPTURE_DIR:?}/payloads"
mkdir -p "$DIR"
TS="$(date +%s)$$"

cat >"$DIR/$LABEL-$TS.stdin.json"
pwd >"$DIR/$LABEL-$TS.pwd"

# Env: full values ONLY for an allowlist of probe-relevant prefixes; name-only for
# everything else. Values matching KEY|TOKEN|SECRET|AUTH|PASSWORD are elided even
# inside the allowlist -- secrets never reach disk, before sanitize.sh ever runs.
#
# Iterate os.environ in Python (not `env | awk`): awk is line-oriented, so a multiline
# env value splits across records and a continuation line could be printed in full,
# leaking a secret fragment. Python handles each variable atomically. (macOS `env`
# lacks `-0`, so NUL-delimiting is not portable; python3 is already a probe dependency.)
python3 - "$DIR/$LABEL-$TS.env" <<'PY'
import os, re, sys

secret = re.compile(r"KEY|TOKEN|SECRET|AUTH|PASSWORD")
allow = re.compile(r"^(FORGE_|CODEX_|PROBE_)|^(PWD|HOME)$")
lines = []
for name in sorted(os.environ):
    if secret.search(name):
        lines.append(f"{name}=<elided>")
    elif allow.search(name):
        lines.append(f"{name}={os.environ[name]}")
    else:
        lines.append(f"{name}=<elided>")
with open(sys.argv[1], "w") as fh:
    fh.write("\n".join(lines) + "\n")
PY

exit 0
