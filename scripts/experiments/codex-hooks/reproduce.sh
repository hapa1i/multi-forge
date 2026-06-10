#!/usr/bin/env bash
# Codex hooks/frontend probe -- Phase 6 (evaluation only) of the
# runtime_abstraction card. Pins the unverified Codex facts that gate the
# Codex-frontend deliverables; see README.md for the fact list, doc-leads,
# verdict vocabulary, and safety/cost notes.
#
# Usage:
#   ./reproduce.sh              # headless set: 00 05 10 20 30 60 70
#   ./reproduce.sh all          # + operator-guided 40 50 80 (needs a TTY)
#   ./reproduce.sh 00 30        # specific stages, in the given order
#   ./reproduce.sh 80           # round-3 enrollment ceremony (builds the fixture)
#   ./reproduce.sh 81 82 83     # round-3 headless probes (require the stage-80 fixture)
#
# Captures land OUTSIDE the repo at ${CODEX_HOOKS_CAPTURE_DIR:-~/.cache/forge-codex-hooks-probe}.
# Deliberately NOT `set -e`: several probes measure failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

HEADLESS_STAGES=(00-preflight 05-config-schema 10-headless-fire 20-payloads 30-responses 60-exec-resume 70-bypass)
# 80 (enroll the round-3 fixture) is guided: it needs a TTY for the trust ceremony.
GUIDED_STAGES=(40-trust 50-interactive 80-enroll-fixture)
# 81-83 consume the stage-80 enrolled fixture and run headless. EXPLICIT-ONLY:
# excluded from both './reproduce.sh' and './reproduce.sh all' (running them blind
# would burn quota against a fixture that may not exist), but resolve_stage must
# still recognize them by name so `./reproduce.sh 81` works.
FIXTURE_STAGES=(81-enrolled-coverage 82-trust-dimensions 83-preimage)

declare_budget() {
    cat <<'EOB'
Approximate model-turn budget (short, one-word-reply prompts; ChatGPT quota):
  00-preflight      0 turns
  05-config-schema  0 turns (bogus-model rejections only)
  10-headless-fire  1-2 turns
  20-payloads       2 turns
  30-responses      8 turns
  40-trust          3 turns + 1 operator-guided interactive run
  50-interactive    2 turns + 1 operator-guided interactive run
  60-exec-resume    4 turns
  70-bypass         1 turn
  --- round 3 (enrollment mechanics; explicit-only) ---
  80-enroll-fixture 2 turns + 1 operator-guided trust ceremony (builds the fixture)
  81-enrolled-...   ~11 turns (event matrix + 30a-30h response contracts)
  82-trust-dims     4 turns (40e command-string, user-vs-project, worktree x2)
  83-preimage       0-2 turns (offline scan; +empirical only if the hash is computable)
EOB
}

resolve_stage() { # accept "30" or "30-responses"
    local want="$1" s
    for s in "${HEADLESS_STAGES[@]}" "${GUIDED_STAGES[@]}" "${FIXTURE_STAGES[@]}"; do
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
echo

FAILED=()
for s in "${STAGES[@]}"; do
    echo "==================== stage $s ===================="
    if ! bash "$HERE/stages/$s.sh"; then
        echo "stage $s FAILED (continuing -- stages fail independently)" >&2
        FAILED+=("$s")
    fi
    echo
done

echo "=================================================="
if [ "${#FAILED[@]}" -gt 0 ]; then
    echo "Stages with failures: ${FAILED[*]}"
    exit 1
fi
echo "All requested stages completed. Captures: ${CODEX_HOOKS_CAPTURE_DIR:-$HOME/.cache/forge-codex-hooks-probe}"
echo "Next: ./sanitize.sh, then review sanitized/ before promoting fixtures."
