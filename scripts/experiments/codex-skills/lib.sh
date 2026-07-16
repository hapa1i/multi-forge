#!/usr/bin/env bash
# Shared helpers for the Codex skills probe. Stages source this file.
set -euo pipefail

MIN_CODEX_VERSION="0.144.5"
PROBE_TURN_TIMEOUT="${PROBE_TURN_TIMEOUT:-240}"

err() {
    echo "ERROR: $*" >&2
    exit 1
}

note() { echo "[probe] $*"; }

version_ge() {
    gawk -v v="$1" -v m="$2" 'BEGIN {
        split(v, a, "."); split(m, b, ".");
        for (i = 1; i <= 3; i++) {
            ai = a[i] + 0; bi = b[i] + 0;
            if (ai > bi) exit 0;
            if (ai < bi) exit 1;
        }
        exit 0;
    }'
}

with_timeout() {
    if command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$PROBE_TURN_TIMEOUT" "$@"
    elif command -v timeout >/dev/null 2>&1; then
        timeout "$PROBE_TURN_TIMEOUT" "$@"
    else
        note "WARNING: no gtimeout/timeout found; running without an external timeout"
        "$@"
    fi
}

probe_init() {
    local stage="${1:?stage name}"
    command -v codex >/dev/null 2>&1 || err "codex is not on PATH"
    command -v rg >/dev/null 2>&1 || err "rg is not on PATH"

    LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
    export LIB_DIR
    REAL_HOME="${PROBE_REAL_HOME:-$HOME}"
    REAL_CODEX_HOME="${PROBE_REAL_CODEX_HOME:-${CODEX_HOME:-$REAL_HOME/.codex}}"
    CAPTURE_ROOT="${CODEX_SKILLS_CAPTURE_DIR:-$REAL_HOME/.cache/forge-codex-skills-probe}"
    PROBE_CAPTURE_DIR="$CAPTURE_ROOT/$stage"
    export REAL_HOME REAL_CODEX_HOME CAPTURE_ROOT PROBE_CAPTURE_DIR

    rm -rf "$PROBE_CAPTURE_DIR"
    mkdir -p "$PROBE_CAPTURE_DIR"/{meta,results,streams}

    PROBE_ROOT="$(mktemp -d)" || err "mktemp failed"
    export PROBE_ROOT
    # shellcheck disable=SC2064 -- expand this stage's path when installing the trap.
    trap "rm -rf '$PROBE_ROOT'" EXIT

    HOME="$PROBE_ROOT/home"
    CODEX_HOME="$PROBE_ROOT/codex-home"
    PROJ="$PROBE_ROOT/project"
    export HOME CODEX_HOME PROJ
    mkdir -p "$HOME/.agents/skills" "$CODEX_HOME" "$PROJ"
    chmod 700 "$HOME" "$CODEX_HOME"
    (
        cd "$PROJ" || exit 1
        git init -q
        git config user.email probe@example.invalid
        git config user.name probe
        touch README.md
        git add README.md
        git commit -qm init
    ) || err "could not initialize probe project"

    note "stage=$stage disposable=$PROBE_ROOT"
    note "captures=$PROBE_CAPTURE_DIR"
}

probe_version() {
    local version
    version="$(codex --version 2>/dev/null | gawk '$1 == "codex-cli" {print $2}')"
    [ -n "$version" ] || err "could not parse codex --version"
    version_ge "$version" "$MIN_CODEX_VERSION" || err "codex-cli $version is below $MIN_CODEX_VERSION"
    printf '%s\n' "$version" >"$PROBE_CAPTURE_DIR/meta/version.txt"
    if [ "$version" != "$MIN_CODEX_VERSION" ]; then
        note "WARNING: findings need review on codex-cli $version (research pin $MIN_CODEX_VERSION)"
    fi
    CODEX_VERSION="$version"
    export CODEX_VERSION
}

probe_auth() {
    [ -f "$REAL_CODEX_HOME/auth.json" ] || err "missing $REAL_CODEX_HOME/auth.json; run codex login first"
    install -m 600 "$REAL_CODEX_HOME/auth.json" "$CODEX_HOME/auth.json" || err "auth copy failed"
    local status
    status="$(codex login status 2>&1)"
    printf '%s\n' "$status" >"$PROBE_CAPTURE_DIR/meta/login-status.txt"
    printf '%s' "$status" | rg -qi 'logged in' || err "isolated Codex auth was not accepted"
}

run_exec() {
    local label="${1:?label}" cwd="${2:?cwd}" prompt="${3:?prompt}"
    local stream="$PROBE_CAPTURE_DIR/streams/$label.jsonl"
    local stderr_file="$PROBE_CAPTURE_DIR/results/$label.stderr.txt"
    local last_message="$PROBE_CAPTURE_DIR/results/$label.last-message.txt"
    note "turn=$label cwd=$cwd"
    set +e
    (
        cd "$cwd" || exit 1
        # The harness control variable contains the word SKILL; do not leak it
        # into the runtime-variable probe and mistake it for a Codex feature.
        with_timeout env -u CODEX_SKILLS_CAPTURE_DIR codex exec --ignore-user-config --ephemeral --json --sandbox read-only \
            -o "$last_message" "$prompt" </dev/null
    ) >"$stream" 2>"$stderr_file"
    local rc=$?
    set -e
    printf '%s\n' "$rc" >"$PROBE_CAPTURE_DIR/results/$label.exit"
    return "$rc"
}

assert_last_contains() {
    local label="${1:?label}" marker="${2:?marker}"
    rg -q --fixed-strings "$marker" "$PROBE_CAPTURE_DIR/results/$label.last-message.txt" ||
        err "$label last message did not contain $marker"
}
