#!/usr/bin/env bash
# Shared library for the OpenRouter provider-trace probe harness (Phase 0).
# Source from stages/*.sh. Read-only against Forge state: it reuses Forge
# credential resolution but never writes ~/.forge.
#
# Environment contract (exported by probe_init):
#   PROBE_ROOT          disposable mktemp dir (removed on EXIT)
#   CAPTURE_ROOT        persistent capture dir (survives runs; manual cleanup)
#   PROBE_CAPTURE_DIR   stage-scoped capture subdir (cleared on init)
#   HELPERS             path to helpers/ (holds or_probe.py)
#   REPO_ROOT           repo root (so `uv run` resolves the project venv)
#
# Privacy: no helper here ever prints or persists an API key. The Python
# helper emits deliberately shaped records; sanitize.sh is the scan-and-fail
# backstop. See README.md.

set -uo pipefail

# Per-turn wall-clock guard (seconds). An OpenRouter turn should be quick.
PROBE_TURN_TIMEOUT="${PROBE_TURN_TIMEOUT:-240}"

err() {
    echo "ERROR: $*" >&2
    exit 1
}

note() { echo "[probe] $*"; }

# Portable major.minor.patch compare: `version_ge A B` exits 0 iff A >= B.
# Avoids GNU `sort -V` (not on BSD/macOS by default).
version_ge() {
    awk -v v="$1" -v m="$2" 'BEGIN {
        split(v, a, "."); split(m, b, ".");
        for (i = 1; i <= 3; i++) {
            ai = a[i] + 0; bi = b[i] + 0;
            if (ai > bi) exit 0;
            if (ai < bi) exit 1;
        }
        exit 0
    }'
}

# Run a command under a wall-clock timeout, preferring GNU coreutils.
with_timeout() {
    if command -v timeout >/dev/null 2>&1; then
        timeout "$PROBE_TURN_TIMEOUT" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$PROBE_TURN_TIMEOUT" "$@"
    else
        note "WARNING: no timeout/gtimeout found; running unbounded"
        "$@"
    fi
}

# probe_init <stage-name>
# Sets up the capture dir (cleared) and a disposable scratch root.
probe_init() {
    local stage="${1:?stage name required}"

    LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
    export LIB_DIR
    HELPERS="$LIB_DIR/helpers"
    export HELPERS
    REPO_ROOT="$(cd "$LIB_DIR/../../.." && pwd -P)"
    export REPO_ROOT

    CAPTURE_ROOT="${OPENROUTER_CAPTURE_DIR:-$HOME/.cache/forge-openrouter-probe}"
    export CAPTURE_ROOT
    PROBE_CAPTURE_DIR="$CAPTURE_ROOT/$stage"
    export PROBE_CAPTURE_DIR

    # Clear stale captures so a previous run's records cannot read as this run's.
    rm -rf "$PROBE_CAPTURE_DIR"
    mkdir -p "$PROBE_CAPTURE_DIR/results" "$PROBE_CAPTURE_DIR/meta"
    chmod 700 "$PROBE_CAPTURE_DIR"

    PROBE_ROOT="$(mktemp -d)" || err "mktemp -d failed"
    export PROBE_ROOT
    # shellcheck disable=SC2064  # expand PROBE_ROOT now, not at trap time
    trap "rm -rf '$PROBE_ROOT'" EXIT

    note "stage=$stage  captures -> $PROBE_CAPTURE_DIR"
}

# verdict <bracketed-string>  -> single-line results/verdict.txt
verdict() {
    printf '%s\n' "$1" >"$PROBE_CAPTURE_DIR/results/verdict.txt"
    note "verdict: $1"
}

# oracle <label> <line>  -> append a natural-language finding to results/<label>.oracle.txt
oracle() {
    printf '%s\n' "$2" >>"$PROBE_CAPTURE_DIR/results/$1.oracle.txt"
}

# run_probe <label> <subcommand> [args...]
# Invokes the Python helper via `uv run`; the helper writes results/<label>.record.json,
# results/verdict.txt, meta/run.json, and oracle lines under PROBE_CAPTURE_DIR.
run_probe() {
    local label="${1:?label required}" sub="${2:?subcommand required}"
    shift 2
    note "probe [$label] -> or_probe.py $sub"
    (
        cd "$REPO_ROOT" &&
            with_timeout uv run python "$HELPERS/or_probe.py" "$sub" \
                --capture-dir "$PROBE_CAPTURE_DIR" --label "$label" "$@"
    )
    local rc=$?
    printf '%s\n' "$rc" >"$PROBE_CAPTURE_DIR/results/$label.exit"
    return "$rc"
}
