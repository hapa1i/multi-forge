#!/usr/bin/env bash
# Forge smoke test -- read-only installation verification.
# Runs a fixed whitelist of probes and asserts no filesystem side effects.
#
# Usage:
#   FORGE_SKILL_RUNTIME=claude_code bash smoke-test.sh
#   FORGE_SKILL_RUNTIME=codex bash smoke-test.sh
#
# Exit codes:
#   0  All checks passed
#   1  One or more checks failed
#   2  Unsupported runtime selection

set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found on PATH. Smoke test requires python3 for mtime snapshots." >&2
    exit 1
fi

RUNTIME="${FORGE_SKILL_RUNTIME:-claude_code}"
FORGE_STATE_HOME="${FORGE_HOME:-$HOME/.forge}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PACKAGE_DIR=$(dirname "$SCRIPT_DIR")
SKILLS_DIR=$(dirname "$PACKAGE_DIR")
RUNTIME_ROOT=$(dirname "$SKILLS_DIR")
case "$RUNTIME" in
    claude_code)
        RUNTIME_FLAG="claude"
        ;;
    codex)
        RUNTIME_FLAG="codex"
        ;;
    *)
        echo "ERROR: unsupported FORGE_SKILL_RUNTIME '$RUNTIME' (expected claude_code or codex)." >&2
        exit 2
        ;;
esac

PASS=0
FAIL=0
RESULTS=()

# --- Snapshot "must not change" paths ---
snapshot_mtime() {
    if [ -e "$1" ]; then
        python3 -c 'import os,sys; print(int(os.path.getmtime(sys.argv[1])))' "$1"
    else
        echo "absent"
    fi
}

SNAP_FORGE=$(snapshot_mtime "$FORGE_STATE_HOME")
SNAP_INSTALLED=$(snapshot_mtime "$FORGE_STATE_HOME/installed.json")

case "$RUNTIME" in
    claude_code)
        SNAP_SETTINGS=$(snapshot_mtime "$RUNTIME_ROOT/settings.json")
        SNAP_LOCAL=$(snapshot_mtime "$RUNTIME_ROOT/settings.local.json")
        SNAP_COMMANDS=$(snapshot_mtime "$RUNTIME_ROOT/commands")
        SNAP_AGENTS=$(snapshot_mtime "$RUNTIME_ROOT/agents")
        SNAP_SKILLS=$(snapshot_mtime "$SKILLS_DIR")
        ;;
    codex)
        CODEX_CONFIG_HOME="${CODEX_HOME:-$HOME/.codex}"
        SNAP_CODEX_SKILLS=$(snapshot_mtime "$SKILLS_DIR")
        SNAP_CODEX_CONFIG=$(snapshot_mtime "$CODEX_CONFIG_HOME/config.toml")
        ;;
esac

# --- Probe helpers ---
check() {
    local name="$1"
    shift
    if output=$("$@" 2>&1); then
        PASS=$((PASS + 1))
        local short="${output:0:60}"
        RESULTS+=("$(printf '  %-28s [PASS]  %s' "$name" "$short")")
    else
        FAIL=$((FAIL + 1))
        local short="${output:0:60}"
        RESULTS+=("$(printf '  %-28s [FAIL]  %s' "$name" "$short")")
    fi
}

check_file() {
    local name="$1"
    local path="$2"
    local desc="$3"
    if [ -f "$path" ]; then
        PASS=$((PASS + 1))
        RESULTS+=("$(printf '  %-28s [PASS]  %s' "$name" "$desc")")
    else
        FAIL=$((FAIL + 1))
        RESULTS+=("$(printf '  %-28s [FAIL]  not found' "$name")")
    fi
}

# --- Run probes (read-only only -- no forge subcommands that trigger pending-work queue) ---
check "forge on PATH" command -v forge
check "forge --version" forge --version
check_file "installed.json" "$FORGE_STATE_HOME/installed.json" "exists"

# Direct file read -- no Forge CLI invocation, no startup side effects
if [ -f "$FORGE_STATE_HOME/installed.json" ] && command -v jq >/dev/null 2>&1; then
    check "tracking version" jq -r '.version // "unknown"' "$FORGE_STATE_HOME/installed.json"
fi

# --- Assert no side effects ---
assert_unchanged() {
    local name="$1"
    local path="$2"
    local before="$3"
    local after
    after=$(snapshot_mtime "$path")
    if [ "$before" = "$after" ]; then
        PASS=$((PASS + 1))
        RESULTS+=("$(printf '  %-28s [PASS]  unchanged' "$name")")
    else
        FAIL=$((FAIL + 1))
        RESULTS+=("$(printf '  %-28s [FAIL]  MODIFIED (%s -> %s)' "$name" "$before" "$after")")
    fi
}

case "$RUNTIME" in
    claude_code)
        assert_unchanged "settings.json intact" "$RUNTIME_ROOT/settings.json" "$SNAP_SETTINGS"
        assert_unchanged "settings.local intact" "$RUNTIME_ROOT/settings.local.json" "$SNAP_LOCAL"
        assert_unchanged "commands dir intact" "$RUNTIME_ROOT/commands" "$SNAP_COMMANDS"
        assert_unchanged "agents dir intact" "$RUNTIME_ROOT/agents" "$SNAP_AGENTS"
        assert_unchanged "skills dir intact" "$SKILLS_DIR" "$SNAP_SKILLS"
        ;;
    codex)
        assert_unchanged "Codex skills dir intact" "$SKILLS_DIR" "$SNAP_CODEX_SKILLS"
        assert_unchanged "Codex config intact" "$CODEX_CONFIG_HOME/config.toml" "$SNAP_CODEX_CONFIG"
        ;;
esac
assert_unchanged "Forge state intact" "$FORGE_STATE_HOME" "$SNAP_FORGE"
assert_unchanged "installed.json intact" "$FORGE_STATE_HOME/installed.json" "$SNAP_INSTALLED"

# --- Print results ---
TOTAL=$((PASS + FAIL))
echo ""
echo "Forge Smoke Test ($RUNTIME)"
echo "------------------------------------"
for line in "${RESULTS[@]}"; do
    echo "$line"
done
echo "------------------------------------"
echo "  $PASS/$TOTAL passed"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "  Some checks failed for $RUNTIME. Run 'forge extension enable --runtime $RUNTIME_FLAG' for the intended scope."
    exit 1
fi
exit 0
