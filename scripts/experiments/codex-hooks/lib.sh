#!/usr/bin/env bash
# Shared library for the codex-hooks probe stages. Source from stages/*.sh.
#
# Environment contract:
#   PROBE_ROOT    disposable mktemp tree (CODEX_HOME, project, hookbin) -- removed on EXIT
#   CAPTURE_ROOT  persistent capture dir OUTSIDE the repo (survives stages; rm -rf when done)
#   CODEX_HOME    isolated codex home inside PROBE_ROOT (never the real ~/.codex)
#   PROJ          hermetic git-inited temp project inside PROBE_ROOT
#   PROBE_CAPTURE_DIR  stage-scoped capture dir (exported; hook scripts write here)
#
# Deliberately NOT `set -e`: several probes measure failure. Stages set -uo pipefail.

MIN_CODEX_VERSION="0.137.0"
PROBE_TURN_TIMEOUT="${PROBE_TURN_TIMEOUT:-240}"

err() {
    echo "ERROR: $*" >&2
    exit 1
}

note() { echo "[probe] $*"; }

# Portable version >= compare (mirrors scripts/experiments/native-resume/reproduce.sh).
version_ge() { # version_ge ACTUAL FLOOR -> exit 0 when ACTUAL >= FLOOR
    awk -v v="$1" -v m="$2" 'BEGIN {
        split(v, a, "."); split(m, b, ".");
        for (i = 1; i <= 3; i++) { ai = a[i] + 0; bi = b[i] + 0;
            if (ai > bi) exit 0; if (ai < bi) exit 1 }
        exit 0 }'
}

# Prefer coreutils timeout; macOS homebrew ships gtimeout (5a reproduce.sh precedent).
with_timeout() {
    if command -v timeout >/dev/null 2>&1; then
        timeout "$PROBE_TURN_TIMEOUT" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$PROBE_TURN_TIMEOUT" "$@"
    else
        note "WARNING: no timeout/gtimeout on PATH -- running unbounded"
        "$@"
    fi
}

probe_init() { # probe_init <stage-name> [--persistent-home]
    local stage="${1:?stage name}"
    local home_mode="${2:-}"

    command -v codex >/dev/null 2>&1 || err "codex is not on PATH."
    command -v python3 >/dev/null 2>&1 || err "python3 is not on PATH."

    LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
    export LIB_DIR

    CAPTURE_ROOT="${CODEX_HOOKS_CAPTURE_DIR:-$HOME/.cache/forge-codex-hooks-probe}"
    export CAPTURE_ROOT
    PROBE_CAPTURE_DIR="$CAPTURE_ROOT/$stage"
    export PROBE_CAPTURE_DIR
    mkdir -p "$PROBE_CAPTURE_DIR"/{payloads,results,streams,trees,meta,env,guards}

    PROBE_ROOT="$(mktemp -d)" || err "mktemp -d failed."
    export PROBE_ROOT
    # shellcheck disable=SC2064  # expand PROBE_ROOT now: the trap must remove THIS tree
    trap "rm -rf '$PROBE_ROOT'" EXIT

    # Isolated CODEX_HOME. Stage 40 needs trust state to persist across sub-steps,
    # so --persistent-home keeps it under the capture root (still never ~/.codex).
    if [ "$home_mode" = "--persistent-home" ]; then
        CODEX_HOME="$CAPTURE_ROOT/$stage/codex-home"
    else
        CODEX_HOME="$PROBE_ROOT/codex-home"
    fi
    export CODEX_HOME
    mkdir -p "$CODEX_HOME"
    chmod 700 "$CODEX_HOME"

    PROJ="$PROBE_ROOT/proj"
    export PROJ
    mkdir -p "$PROJ"
    (cd "$PROJ" &&
        git init -q &&
        git config user.email probe@example.invalid &&
        git config user.name probe &&
        echo "# probe project" >README.md &&
        git add README.md &&
        git commit -qm init) || err "temp project git init failed."

    HOOKBIN="$PROBE_ROOT/hookbin"
    export HOOKBIN
    mkdir -p "$HOOKBIN"

    note "stage=$stage PROBE_ROOT=$PROBE_ROOT"
    note "CODEX_HOME=$CODEX_HOME"
    note "captures -> $PROBE_CAPTURE_DIR"
}

probe_version_check() {
    local version
    version="$(codex --version 2>/dev/null | awk '/^codex-cli /{print $2}')"
    [ -n "$version" ] || err "could not parse 'codex --version' (expected 'codex-cli <ver>')."
    version_ge "$version" "$MIN_CODEX_VERSION" ||
        err "codex-cli $version < required $MIN_CODEX_VERSION."
    if [ "$version" != "$MIN_CODEX_VERSION" ]; then
        note "WARNING: codex-cli $version is newer than the $MIN_CODEX_VERSION research pin -- findings re-pin to $version"
    fi
    printf '%s\n' "$version" >"$PROBE_CAPTURE_DIR/meta/version.txt"
    CODEX_VERSION="$version"
    export CODEX_VERSION
    note "codex-cli $version OK (floor $MIN_CODEX_VERSION)"
}

# Copy real auth into the isolated home (0600, dies with PROBE_ROOT unless
# --persistent-home, where it dies with the capture-root cleanup). Escape hatch:
# PROBE_USE_REAL_CODEX_HOME=1 keeps the real ~/.codex (WARNING: trust probes then
# mutate real trust state).
probe_auth() {
    if [ "${PROBE_USE_REAL_CODEX_HOME:-0}" = "1" ]; then
        CODEX_HOME="$HOME/.codex"
        export CODEX_HOME
        note "WARNING: using REAL ~/.codex (PROBE_USE_REAL_CODEX_HOME=1) -- trust probes will mutate real state"
        return 0
    fi
    [ -f "$HOME/.codex/auth.json" ] || err "no ~/.codex/auth.json to copy -- run 'codex login' first (or set PROBE_USE_REAL_CODEX_HOME=1)."
    if [ ! -f "$CODEX_HOME/auth.json" ]; then
        install -m 600 "$HOME/.codex/auth.json" "$CODEX_HOME/auth.json" || err "auth copy failed."
    fi
    local status
    status="$(codex login status 2>&1)"
    printf '%s\n' "$status" >"$PROBE_CAPTURE_DIR/meta/login-status.txt"
    if printf '%s' "$status" | grep -qi 'logged in'; then
        note "isolated CODEX_HOME auth OK: $status"
    else
        err "codex does not report logged-in under isolated CODEX_HOME ('$status'). The CODEX_HOME-isolation assumption failed -- record this finding; rerun with PROBE_USE_REAL_CODEX_HOME=1 only with explicit consent."
    fi
}

# make_hook_cmd <label> <handler-basename> [template-path] -> echoes wrapper path.
# A per-label wrapper script bakes the args in, so registration never depends on
# whether codex shell-splits the `command` string (itself an open question).
make_hook_cmd() {
    local label="${1:?label}" handler="${2:?handler}" template="${3:-}"
    local wrapper="$HOOKBIN/$label.sh"
    {
        echo '#!/usr/bin/env bash'
        echo "export PROBE_CAPTURE_DIR='$PROBE_CAPTURE_DIR'"
        if [ -n "$template" ]; then
            echo "exec '$LIB_DIR/hooks/$handler' '$label' '$template'"
        else
            echo "exec '$LIB_DIR/hooks/$handler' '$label'"
        fi
    } >"$wrapper"
    chmod +x "$wrapper"
    printf '%s\n' "$wrapper"
}

# gen_hooks_config <json|toml> HOOKSPEC... -> emits config text on stdout.
# HOOKSPEC := EVENT[:MATCHER]=COMMAND
gen_hooks_config() {
    local format="${1:?format}"
    shift
    python3 "$LIB_DIR/hooks/gen-config.py" --format "$format" "$@"
}

# run_exec <label> <sandbox> <prompt> [extra codex-exec args...]
# Runs one `codex exec --json` turn from $PROJ; captures stream/stderr/exit/last-message.
run_exec() {
    local label="${1:?label}" sandbox="${2:?sandbox}" prompt="${3:?prompt}"
    shift 3
    local stream="$PROBE_CAPTURE_DIR/streams/$label.jsonl"
    local stderr_f="$PROBE_CAPTURE_DIR/results/$label.stderr.txt"
    local lm="$PROBE_CAPTURE_DIR/results/$label.last-message.txt"
    note "turn [$label] sandbox=$sandbox"
    # </dev/null: the prompt is positional; an ambient pipe would otherwise be
    # read as an appended <stdin> block ("Reading additional input from stdin...").
    (cd "$PROJ" && with_timeout codex exec --json --sandbox "$sandbox" -o "$lm" "$@" "$prompt" </dev/null) \
        >"$stream" 2>"$stderr_f"
    local rc=$?
    printf '%s\n' "$rc" >"$PROBE_CAPTURE_DIR/results/$label.exit"
    note "turn [$label] exit=$rc last-message=$(head -c 120 "$lm" 2>/dev/null || echo '<none>')"
    return "$rc"
}

# fired_labels -> lists hook labels that produced payload captures in this stage.
fired_labels() {
    find "$PROBE_CAPTURE_DIR/payloads" -name '*.stdin.json' 2>/dev/null |
        sed -E 's|.*/([^/]+)-[0-9]+\.stdin\.json|\1|' | sort -u
}

snapshot_tree() { # snapshot_tree <name> <dir>
    find "$2" -type f 2>/dev/null | sort >"$PROBE_CAPTURE_DIR/trees/$1.txt"
}

# Should hook turns add --dangerously-bypass-hook-trust? Auto mode reads stage
# 10's verdict; PROBE_BYPASS_TRUST=1/0 forces.
need_trust_bypass() {
    case "${PROBE_BYPASS_TRUST:-auto}" in
    1) return 0 ;;
    0) return 1 ;;
    esac
    grep -q 'TRUST-GATED' "$CAPTURE_ROOT/10-headless-fire/results/verdict.txt" 2>/dev/null
}
