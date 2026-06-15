#!/usr/bin/env bash
# Stage 20 -- PROBE 2: cancelled-stream remote visibility.
# Cancel a stream IN-PROCESS after the first chunk, then poll /generation for the
# aborted request AND a completed-call baseline (the control), and query /activity.
# Operator-gated: /activity needs a management key (OPENROUTER_PROVISIONING_KEY) and
# the dashboard check needs a human.
# [REMOTE-ABSENT] is the EXPECTED result and a PASS -- it justifies local-only trace.
# The /generation lookup is eventually-consistent (an immediate query 404s even for
# the completed baseline), so the probe polls with backoff (~23s worst case) and only
# asserts [REMOTE-ABSENT] once the baseline DID index while the aborted id did not;
# if even the baseline never indexes in-window it reports [REMOTE-INCONCLUSIVE].
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "20-cancel"

note "PROBE 2 is operator-gated: /activity needs OPENROUTER_PROVISIONING_KEY; the dashboard check needs a human."
note "Polls /generation with backoff (~23s) + makes one completed-call baseline as the absence control."
if [ -z "${OPENROUTER_PROVISIONING_KEY:-}${OPENROUTER_MANAGEMENT_KEY:-}" ]; then
    note "no management key set -> /activity will record 'management key unavailable' (probe still runs)"
fi

run_probe "cancel" cancel "$@"
rc=$?
[ -f "$PROBE_CAPTURE_DIR/results/verdict.txt" ] && note "verdict: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
note "OPERATOR: open the OpenRouter dashboard Activity view and confirm whether this aborted request appears."
exit "$rc"
