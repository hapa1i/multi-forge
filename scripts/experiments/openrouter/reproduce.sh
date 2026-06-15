#!/usr/bin/env bash
# OpenRouter provider-trace Phase 0 probe harness (operator-gated).
#
# Pins the live OpenRouter externals the code cannot answer, before the later
# phases of the openrouter_observability card populate any provider-id field.
# Needs a live OPENROUTER_API_KEY resolvable by Forge (env or credentials.yaml).
#
# Usage:
#   ./reproduce.sh             # HEADLESS stages (preflight + genid + session-transport)
#   ./reproduce.sh all         # + GUIDED stages (20-cancel: management key + dashboard)
#   ./reproduce.sh 10-genid    # one stage (by number or full name)
#   ./reproduce.sh 40-session-routing   # explicit-only, cost-heavy
#   ./sanitize.sh              # ALWAYS run last (scan-and-fail secret scrub)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

HEADLESS_STAGES=(00-preflight 10-genid 30-session-transport)
GUIDED_STAGES=(20-cancel)
EXPLICIT_STAGES=(40-session-routing) # never auto-run; explicit name only

declare_budget() {
    cat <<'EOB'
Approximate OpenRouter call budget (cheap model):
  00-preflight          0 model calls (credential resolution only)
  10-genid              ~3 calls (non-stream + stream + canonical drop-check) + polled /generation GETs (~23s)
  20-cancel             ~2 calls (cancelled + completed baseline) + polled /generation + /activity GETs (~23s)   [operator]
  30-session-transport  ~2-4 calls (session_id + user, x direct[, gateway])
  40-session-routing    ~18 calls (3 arms x 5 repeats, LARGE prompt)                            [explicit-only]
EOB
}

resolve_stage() {
    local want="$1" s
    for s in "${HEADLESS_STAGES[@]}" "${GUIDED_STAGES[@]}" "${EXPLICIT_STAGES[@]}"; do
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
echo "Captures -> ${OPENROUTER_CAPTURE_DIR:-$HOME/.cache/forge-openrouter-probe}"
echo

FAILED=()
for s in "${STAGES[@]}"; do
    echo "==================== stage $s ===================="
    if ! bash "$HERE/stages/$s.sh"; then
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
