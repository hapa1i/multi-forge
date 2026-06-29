#!/usr/bin/env bash
# Stage 20 -- detection signal (c). Enumerate each auth-mode detection candidate
# read-only and pick the most stable (or report none qualifies). NEVER reads a token
# store's contents: `claude config get` is captured for key NAMES only, credential
# files for existence/mode only, the OS keychain is not queried. No model call.
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "20-detection"

run_probe "detection" detection
rc=$?
[ -f "$PROBE_CAPTURE_DIR/results/verdict.txt" ] && note "verdict: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$rc"
