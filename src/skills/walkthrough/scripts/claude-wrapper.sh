#!/usr/bin/env bash
# Launch native Claude with only sandbox project/local settings plus the
# walkthrough's isolated user-hook settings. Authentication and transcripts
# stay in Claude's pre-existing native configuration store.

set -euo pipefail

fail() {
    echo "ERROR: $1" >&2
    exit 1
}

test -n "${FORGE_TEST_REPO:-}" || fail "FORGE_TEST_REPO is not set"
test -f "$FORGE_TEST_REPO/.forge-walkthrough-marker" || fail "walkthrough marker is missing"

expected_claude_home="$FORGE_TEST_REPO/.claude-user"
test "${CLAUDE_HOME:-}" = "$expected_claude_home" || fail "CLAUDE_HOME is outside the walkthrough sandbox"

settings="$CLAUDE_HOME/settings.json"
test -f "$settings" || fail "sandbox Claude settings are missing; rerun /walkthrough --reset"
test ! -L "$settings" || fail "sandbox Claude settings must not be a symlink"

native_claude="${FORGE_WALKTHROUGH_CLAUDE_BIN:-}"
case "$native_claude" in
    /*) ;;
    *) fail "native Claude launcher is unavailable; install Claude Code and rerun /walkthrough --reset" ;;
esac
test -x "$native_claude" || fail "recorded native Claude launcher is not executable: $native_claude"

wrapper_path="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$0")"
native_path="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$native_claude")"
test "$native_path" != "$wrapper_path" || fail "native Claude launcher resolves back to the walkthrough wrapper"

exec "$native_path" \
    --setting-sources project,local \
    --settings "$settings" \
    "$@"
