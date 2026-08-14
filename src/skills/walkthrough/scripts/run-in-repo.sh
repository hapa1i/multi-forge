#!/usr/bin/env bash
# Safety wrapper for Forge walkthrough commands.
# Resolves and validates the target before sourcing env.sh, verifies isolation through 6 gates,
# cd's to the test repo, and runs the command.
#
# Usage:
#   bash run-in-repo.sh forge session list           # cd's to test repo automatically
#   bash run-in-repo.sh jq '.' .claude/settings.json # relative paths work
#   bash run-in-repo.sh --no-cd docker info           # skip cd (maintainer-only)
#
# Exit codes:
#   Command's exit code on success
#   1 on any gate failure

set -euo pipefail

# --- Parse --no-cd flag (maintainer-only: only for commands with no path arguments) ---
NO_CD=false
if [ "${1:-}" = "--no-cd" ]; then
    NO_CD=true
    shift
fi

if [ $# -eq 0 ]; then
    echo "ERROR: No command specified." >&2
    echo "Usage: bash run-in-repo.sh [--no-cd] <command...>" >&2
    exit 1
fi

# --- Resolve FORGE_TEST_REPO ---
resolve_path() {
    python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$1"
}

matches_expected_path() {
    local actual="$1"
    local expected="$2"
    case "$actual" in
        /*) [ "$(resolve_path "$actual")" = "$(resolve_path "$expected")" ] ;;
        *) return 1 ;;
    esac
}

# Check for explicitly-set empty value before applying default
if [ "${FORGE_TEST_REPO+set}" = "set" ] && [ -z "$FORGE_TEST_REPO" ]; then
    echo "ERROR: FORGE_TEST_REPO is explicitly set to empty. Refusing to proceed." >&2
    exit 1
fi
FORGE_TEST_REPO="${FORGE_TEST_REPO:-${FORGE_HOME:-$HOME/.forge}/manual-testing/walkthrough/test-repo}"
FORGE_TEST_REPO="$(resolve_path "$FORGE_TEST_REPO")"
readonly WALKTHROUGH_ROOT="$FORGE_TEST_REPO"

# --- Denylist: refuse obviously dangerous values ---
check_safe_path() {
    local resolved="$1"

    if [ -z "$resolved" ]; then
        echo "ERROR: FORGE_TEST_REPO is empty. Refusing to proceed." >&2
        exit 1
    fi

    local -a denylist=("/" "$HOME" "/Users" "/tmp" "/var" "/etc" "/opt" "/usr")
    for bad in "${denylist[@]}"; do
        local bad_resolved
        bad_resolved="$(realpath "$bad" 2>/dev/null || echo "$bad")"
        if [ "$resolved" = "$bad" ] || [ "$resolved" = "$bad_resolved" ]; then
            echo "ERROR: FORGE_TEST_REPO='$resolved' is a denylisted path. Refusing to proceed." >&2
            echo "  Set FORGE_TEST_REPO to a safe test directory (not $bad)." >&2
            exit 1
        fi
    done
}

check_safe_path "$WALKTHROUGH_ROOT"

# --- Gate 1: env.sh exists ---
ENV_FILE="$WALKTHROUGH_ROOT/.forge/walkthrough/env.sh"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: env.sh not found at: $ENV_FILE" >&2
    echo "" >&2
    echo "  The test environment is missing. Likely causes:" >&2
    echo "    - Test repo was deleted (rm -rf $FORGE_TEST_REPO)" >&2
    echo "    - setup-test-repo.sh has not been run" >&2
    echo "" >&2
    echo "  Fix: Run setup-test-repo.sh to recreate the test environment." >&2
    exit 1
fi

# --- Gate 2: marker file exists ---
MARKER_FILE="$WALKTHROUGH_ROOT/.forge-walkthrough-marker"
if [ ! -f "$MARKER_FILE" ]; then
    echo "ERROR: Marker file missing at: $MARKER_FILE" >&2
    echo "  This directory was not created by setup-test-repo.sh." >&2
    echo "  Refusing to run commands -- your real system may be at risk." >&2
    exit 1
fi

# --- Gate 6: structure check ---
if [ ! -d "$WALKTHROUGH_ROOT/.forge/walkthrough" ]; then
    echo "ERROR: Expected directory missing: $WALKTHROUGH_ROOT/.forge/walkthrough/" >&2
    echo "  The test repo structure is incomplete. Run setup-test-repo.sh." >&2
    exit 1
fi

if [ ! -f "$WALKTHROUGH_ROOT/CLAUDE.md" ]; then
    echo "ERROR: Expected file missing: $WALKTHROUGH_ROOT/CLAUDE.md" >&2
    echo "  This doesn't look like a forge walkthrough test repo." >&2
    exit 1
fi

# Source target-controlled code only after proving the walkthrough marker and structure.
# shellcheck source=/dev/null
source "$ENV_FILE"

# env.sh is generated inside the validated target, but it is still sourced shell code.
# Keep the root used by every later gate immutable so a stale or edited env file cannot
# redirect the command after the denylist and provenance checks have already passed.
if [ -z "${FORGE_TEST_REPO:-}" ]; then
    echo "ERROR: env.sh unset FORGE_TEST_REPO after it was validated. Refusing to proceed." >&2
    exit 1
fi
SOURCED_FORGE_TEST_REPO="$(resolve_path "$FORGE_TEST_REPO")"
if [ "$SOURCED_FORGE_TEST_REPO" != "$WALKTHROUGH_ROOT" ]; then
    echo "ERROR: env.sh changed FORGE_TEST_REPO after validation. Refusing to proceed." >&2
    echo "  Expected: $WALKTHROUGH_ROOT" >&2
    echo "  Actual:   $SOURCED_FORGE_TEST_REPO" >&2
    exit 1
fi
export FORGE_TEST_REPO="$WALKTHROUGH_ROOT"

# --- Gate 3: FORGE_HOME isolation ---
EXPECTED_FORGE_HOME="$WALKTHROUGH_ROOT/.forge-home"
if ! matches_expected_path "${FORGE_HOME:-}" "$EXPECTED_FORGE_HOME"; then
    echo "ERROR: FORGE_HOME is not redirected to the test sandbox." >&2
    echo "  Expected: $EXPECTED_FORGE_HOME" >&2
    echo "  Actual:   ${FORGE_HOME:-<unset>}" >&2
    echo "  Did you source env.sh?" >&2
    exit 1
fi

# --- Gate 4: CLAUDE_HOME isolation ---
EXPECTED_CLAUDE_HOME="$WALKTHROUGH_ROOT/.claude-user"
if ! matches_expected_path "${CLAUDE_HOME:-}" "$EXPECTED_CLAUDE_HOME"; then
    echo "ERROR: CLAUDE_HOME is not redirected to the test sandbox." >&2
    echo "  Expected: $EXPECTED_CLAUDE_HOME" >&2
    echo "  Actual:   ${CLAUDE_HOME:-<unset>}" >&2
    echo "  Did you source env.sh?" >&2
    exit 1
fi

# --- Gate 5: CODEX_HOME isolation ---
EXPECTED_CODEX_HOME="$WALKTHROUGH_ROOT/.codex-user"
if ! matches_expected_path "${CODEX_HOME:-}" "$EXPECTED_CODEX_HOME"; then
    echo "ERROR: CODEX_HOME is not redirected to the test sandbox." >&2
    echo "  Expected: $EXPECTED_CODEX_HOME" >&2
    echo "  Actual:   ${CODEX_HOME:-<unset>}" >&2
    echo "  Did you source env.sh?" >&2
    exit 1
fi

# --- cd to test repo (unless --no-cd) ---
if [ "$NO_CD" = false ]; then
    cd "$WALKTHROUGH_ROOT" || {
        echo "ERROR: Cannot cd to test repo: $WALKTHROUGH_ROOT" >&2
        exit 1
    }
fi

# --- Execute the command ---
exec "$@"
