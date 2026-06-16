#!/usr/bin/env bash
# Stage 40 -- PROBE 4: session_id routing/latency impact.
# Repeated large supervisor-style prompts, baseline vs sticky session_id vs sticky
# user, measuring first-token + total latency, cache indicators, provider, failures.
# COST-HEAVY and EXPLICIT-ONLY: reproduce.sh never runs this automatically.
# Run on demand: ./reproduce.sh 40-session-routing   (override count: OPENROUTER_PROBE_REPEATS).
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "40-session-routing"

REPEATS="${OPENROUTER_PROBE_REPEATS:-5}"
note "PROBE 4 is COST-HEAVY: 3 arms x ${REPEATS} repeats of a large prompt (~6 streamed calls/arm)."

run_probe "session-routing" routing --repeats "$REPEATS" "$@"
rc=$?
[ -f "$PROBE_CAPTURE_DIR/results/verdict.txt" ] && note "verdict: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$rc"
