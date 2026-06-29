#!/usr/bin/env bash
# Stage 30 -- quota draw (d, optional; informs T5/T7). Does a keyless turn surface
# any quota / rate-limit headroom? `claude -p` does not expose anthropic-ratelimit-*
# headers, so [QUOTA-UNOBSERVED] is the honest default. GUIDED/optional. One model
# call (draws Max quota). Self-guards on keyless-ness.
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "30-quota"

run_probe "quota" quota "$@"
rc=$?
[ -f "$PROBE_CAPTURE_DIR/results/verdict.txt" ] && note "verdict: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$rc"
