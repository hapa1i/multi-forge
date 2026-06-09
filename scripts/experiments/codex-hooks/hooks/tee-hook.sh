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
# everything else. Values matching KEY|TOKEN|SECRET|AUTH are elided even inside the
# allowlist -- secrets never reach disk, before sanitize.sh ever runs.
env | LC_ALL=C sort | awk -F= '
    $1 ~ /KEY|TOKEN|SECRET|AUTH|PASSWORD/ { print $1 "=<elided>"; next }
    $1 ~ /^(FORGE_|CODEX_|PROBE_|PWD$|HOME$)/ { print; next }
    { print $1 "=<elided>" }' >"$DIR/$LABEL-$TS.env"

exit 0
