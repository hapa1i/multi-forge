#!/usr/bin/env bash
# Claude-subscription billing Phase 0 probe harness (consumer_lanes T0, operator-gated).
#
# Question: does a *keyless* `claude -p` ride a Claude Max/Pro subscription headlessly,
# and is the auth mode detectable from a stable signal? Pins these before T0's Phase 1
# labels any run `subscription_*`.
#
# OPERATOR GATE (inverted vs the openrouter harness): this needs NO resolvable
# ANTHROPIC_API_KEY -- in the shell AND in ~/.forge/credentials.yaml (note
# auth_ignore_env changes which sources count) -- plus a pre-authenticated Max/Pro
# session (run `claude` once interactively to log in). Stage 00 PROVES keyless-ness
# with the runner's own predicate and ABORTS the run if a key is resolvable.
#
# Usage:
#   ./reproduce.sh             # HEADLESS: 00-precondition (gate) + 10-turn + 20-detection
#   ./reproduce.sh all         # + GUIDED stages (30-quota: optional, draws more quota)
#   ./reproduce.sh 10-turn     # one stage (by number or full name); turn self-guards keyless
#   ./sanitize.sh              # ALWAYS run last (scan-and-fail secret scrub)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

GATE_STAGE="00-precondition"
HEADLESS_STAGES=(00-precondition 10-turn 20-detection)
GUIDED_STAGES=(30-quota) # optional; draws extra quota, rarely surfaces headroom

declare_budget() {
    cat <<'EOB'
Approximate Claude Max/Pro quota draw (keyless turns):
  00-precondition   0 model calls (credential resolution only -- the keyless gate)
  10-turn           1 call (tiny prompt) -> (a0) OAuth feasibility, (a) completes, (b) cost
  20-detection      0 model calls (read-only signal enumeration; no token store is read)
  30-quota          1 call (tiny prompt) -> best-effort quota headroom                [optional]
EOB
}

resolve_stage() {
    local want="$1" s
    for s in "${HEADLESS_STAGES[@]}" "${GUIDED_STAGES[@]}"; do
        case "$s" in "$want" | "$want"-*)
            printf '%s\n' "$s"
            return 0
            ;;
        esac
    done
    echo "ERROR: unknown stage '$want'" >&2
    return 1
}

STAGES=()
if [ "$#" -eq 0 ]; then
    STAGES=("${HEADLESS_STAGES[@]}")
elif [ "$1" = "all" ]; then
    STAGES=("${HEADLESS_STAGES[@]}" "${GUIDED_STAGES[@]}")
else
    for arg in "$@"; do
        s="$(resolve_stage "$arg")" || exit 1
        STAGES+=("$s")
    done
fi

declare_budget
echo
echo "Running stages: ${STAGES[*]}"
echo "Captures -> ${CLAUDE_SUB_CAPTURE_DIR:-$HOME/.cache/forge-claude-sub-probe}"
echo

FAILED=()
for s in "${STAGES[@]}"; do
    echo "==================== stage $s ===================="
    if ! bash "$HERE/stages/$s.sh"; then
        # The precondition is a HARD GATE: a resolvable key means every later stage
        # would silently measure the KEY path. Abort rather than self-deceive.
        if [ "$s" = "$GATE_STAGE" ]; then
            echo "GATE FAILED ($s): keyless precondition not met -- aborting." >&2
            echo "Unset ANTHROPIC_API_KEY (env AND ~/.forge/credentials.yaml; check auth_ignore_env), then re-run." >&2
            exit 1
        fi
        echo "stage $s FAILED (continuing)" >&2
        FAILED+=("$s")
    fi
    echo
done

echo "=================================================="
if [ "${#FAILED[@]}" -ne 0 ]; then
    echo "Failed stages: ${FAILED[*]}" >&2
    echo "Inspect results, then run ./sanitize.sh" >&2
    exit 1
fi
echo "All stages OK."
echo "Next: ./sanitize.sh  (scan-and-fail secret scrub before promoting any result)"
