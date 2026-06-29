#!/usr/bin/env bash
# Stage 00 -- PRECONDITION (the gate). Prove the keyless path is actually keyless.
# Calls the SAME predicate the runner uses (can_use_bare -> resolve_env_or_credential,
# honoring auth_ignore_env). If a key is resolvable, every later stage would silently
# measure the KEY path and falsely conclude "no subscription" -- so this stage FAILS
# and reproduce.sh aborts the run. Fails CLOSED on an import error (unverifiable !=
# keyless). No model call.
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "00-precondition"

run_probe "precondition" precondition
rc=$?
[ -f "$PROBE_CAPTURE_DIR/results/verdict.txt" ] && note "verdict: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$rc"
