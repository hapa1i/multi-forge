#!/usr/bin/env bash
# Stage 10 -- PROBE 1: generation-id source.
# Where does OpenRouter expose a gen-id? Non-streaming body.id, streaming
# chunk.id, a response header, or only via GET /generation lookup? Also records
# that Forge's canonical CompletionResponse drops the provider id (Phase 2/3 input).
# Headless.
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "10-genid"

run_probe "genid" genid "$@"
rc=$?
[ -f "$PROBE_CAPTURE_DIR/results/verdict.txt" ] && note "verdict: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$rc"
