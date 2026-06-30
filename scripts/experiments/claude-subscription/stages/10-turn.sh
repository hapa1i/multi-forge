#!/usr/bin/env bash
# Stage 10 -- one keyless turn -> (a0) non-TTY OAuth feasibility, (a) turn completes,
# (b) cost-present/absent. Runs a single direct `claude -p --output-format json` with
# NO --bare and the proxy unset, so it tests OAuth-to-Anthropic (the Max/Pro path),
# not a backend. Self-guards: refuses to run if a key is resolvable. One model call.
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "10-turn"

run_probe "turn" turn "$@"
rc=$?
[ -f "$PROBE_CAPTURE_DIR/results/verdict.txt" ] && note "verdict: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$rc"
