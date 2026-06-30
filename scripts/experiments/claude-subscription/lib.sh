#!/usr/bin/env bash
# Shared library for the Claude-subscription billing probe harness (T0, Phase 0).
# Source from stages/*.sh. Read-only against Forge state: it reuses Forge's
# credential resolution (to PROVE no key is resolvable) but never writes ~/.forge.
#
# Environment contract (exported by probe_init):
#   PROBE_ROOT          disposable mktemp dir (removed on EXIT)
#   CAPTURE_ROOT        persistent capture dir (survives runs; manual cleanup)
#   PROBE_CAPTURE_DIR   stage-scoped capture subdir (cleared on init)
#   HELPERS             path to helpers/ (holds claude_probe.py)
#   REPO_ROOT           repo root (so `uv run` resolves the project venv)
#
# Privacy: no helper here ever prints or persists an API key or OAuth token. The
# Python helper emits deliberately shaped, metadata-only records; sanitize.sh is
# the scan-and-fail backstop. See README.md.

set -uo pipefail

# Per-turn wall-clock guard (seconds). A keyless OAuth turn can be slower than an
# API turn (first-call auth handshake), so the default is generous.
PROBE_TURN_TIMEOUT="${PROBE_TURN_TIMEOUT:-180}"

err() {
    echo "ERROR: $*" >&2
    exit 1
}

note() { echo "[probe] $*"; }

# Run a command under a wall-clock timeout, preferring GNU coreutils. On macOS
# (Homebrew) `timeout` ships as `gtimeout`; it may be absent entirely.
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

    CAPTURE_ROOT="${CLAUDE_SUB_CAPTURE_DIR:-$HOME/.cache/forge-claude-sub-probe}"
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

# run_probe <label> <subcommand> [args...]
# Invokes the Python helper via `uv run`; the helper writes results/<label>.record.json,
# results/verdict.txt, meta/run.json, and oracle lines under PROBE_CAPTURE_DIR.
run_probe() {
    local label="${1:?label required}" sub="${2:?subcommand required}"
    shift 2
    note "probe [$label] -> claude_probe.py $sub"
    (
        cd "$REPO_ROOT" &&
            with_timeout uv run python "$HELPERS/claude_probe.py" "$sub" \
                --capture-dir "$PROBE_CAPTURE_DIR" --label "$label" "$@"
    )
    local rc=$?
    printf '%s\n' "$rc" >"$PROBE_CAPTURE_DIR/results/$label.exit"
    return "$rc"
}
