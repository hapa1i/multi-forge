#!/usr/bin/env bash
# Stage 30 -- PROBE 3: session_id vs user transport.
# Inject session_id (via extra body key) and the OpenAI-standard `user` field,
# and record TRANSPORTED (left in the body) separately from RECOGNIZED (OpenRouter
# echoed/grouped). RECOGNIZED is decided against the POLLED /generation record (the
# lookup is eventually-consistent, so an immediate check would misread a stored field
# as absent) -- each un-echoed field adds up to ~23s. Direct arm runs by default; the
# LiteLLM-gateway arm runs ONLY if OPENROUTER_PROBE_GATEWAY_BASE_URL is provided
# (never auto-created). Headless.
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "30-session-transport"

if [ -n "${OPENROUTER_PROBE_GATEWAY_BASE_URL:-}" ]; then
    note "gateway arm ENABLED (OPENROUTER_PROBE_GATEWAY_BASE_URL set)"
else
    note "gateway arm SKIPPED (set OPENROUTER_PROBE_GATEWAY_BASE_URL to test the LiteLLM-gateway route)"
fi

run_probe "session-transport" session-transport "$@"
rc=$?
[ -f "$PROBE_CAPTURE_DIR/results/verdict.txt" ] && note "verdict: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$rc"
