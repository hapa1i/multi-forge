#!/usr/bin/env bash
# Safety wrapper for Forge walkthrough commands.
# Sources env.sh, verifies isolation through 6 gates, cd's to test repo, runs the command.
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
# Check for explicitly-set empty value before applying default
if [ "${FORGE_TEST_REPO+set}" = "set" ] && [ -z "$FORGE_TEST_REPO" ]; then
    echo "ERROR: FORGE_TEST_REPO is explicitly set to empty. Refusing to proceed." >&2
    exit 1
fi
FORGE_TEST_REPO="${FORGE_TEST_REPO:-${FORGE_HOME:-$HOME/.forge}/manual-testing/walkthrough/test-repo}"
FORGE_TEST_REPO="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$FORGE_TEST_REPO")"

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

check_safe_path "$FORGE_TEST_REPO"

# --- Gate 1: env.sh exists ---
ENV_FILE="$FORGE_TEST_REPO/.forge/walkthrough/env.sh"
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

# shellcheck source=/dev/null
source "$ENV_FILE"

# --- Gate 2: marker file exists ---
MARKER_FILE="$FORGE_TEST_REPO/.forge-walkthrough-marker"
if [ ! -f "$MARKER_FILE" ]; then
    echo "ERROR: Marker file missing at: $MARKER_FILE" >&2
    echo "  This directory was not created by setup-test-repo.sh." >&2
    echo "  Refusing to run commands -- your real system may be at risk." >&2
    exit 1
fi

# --- Gate 3: FORGE_HOME isolation ---
EXPECTED_FORGE_HOME="$FORGE_TEST_REPO/.forge-home"
if [ "${FORGE_HOME:-}" != "$EXPECTED_FORGE_HOME" ]; then
    echo "ERROR: FORGE_HOME is not redirected to the test sandbox." >&2
    echo "  Expected: $EXPECTED_FORGE_HOME" >&2
    echo "  Actual:   ${FORGE_HOME:-<unset>}" >&2
    echo "  Did you source env.sh?" >&2
    exit 1
fi

# --- Gate 4: CLAUDE_HOME isolation ---
EXPECTED_CLAUDE_HOME="$FORGE_TEST_REPO/.claude-user"
if [ "${CLAUDE_HOME:-}" != "$EXPECTED_CLAUDE_HOME" ]; then
    echo "ERROR: CLAUDE_HOME is not redirected to the test sandbox." >&2
    echo "  Expected: $EXPECTED_CLAUDE_HOME" >&2
    echo "  Actual:   ${CLAUDE_HOME:-<unset>}" >&2
    echo "  Did you source env.sh?" >&2
    exit 1
fi

# --- Gate 5: CODEX_HOME isolation ---
EXPECTED_CODEX_HOME="$FORGE_TEST_REPO/.codex-user"
if [ "${CODEX_HOME:-}" != "$EXPECTED_CODEX_HOME" ]; then
    echo "ERROR: CODEX_HOME is not redirected to the test sandbox." >&2
    echo "  Expected: $EXPECTED_CODEX_HOME" >&2
    echo "  Actual:   ${CODEX_HOME:-<unset>}" >&2
    echo "  Did you source env.sh?" >&2
    exit 1
fi

# --- Gate 6: structure check ---
if [ ! -d "$FORGE_TEST_REPO/.forge/walkthrough" ]; then
    echo "ERROR: Expected directory missing: $FORGE_TEST_REPO/.forge/walkthrough/" >&2
    echo "  The test repo structure is incomplete. Run setup-test-repo.sh." >&2
    exit 1
fi

if [ ! -f "$FORGE_TEST_REPO/CLAUDE.md" ]; then
    echo "ERROR: Expected file missing: $FORGE_TEST_REPO/CLAUDE.md" >&2
    echo "  This doesn't look like a forge walkthrough test repo." >&2
    exit 1
fi

# --- cd to test repo (unless --no-cd) ---
if [ "$NO_CD" = false ]; then
    cd "$FORGE_TEST_REPO" || {
        echo "ERROR: Cannot cd to test repo: $FORGE_TEST_REPO" >&2
        exit 1
    }
fi

# --- Execute the command ---
exec "$@"
