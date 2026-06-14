#!/usr/bin/env bash
# Stage 80 -- build the PERSISTENT enrolled fixture + run the ONE operator trust
# ceremony (guided, needs a TTY). Everything in stages 81-83 then runs headless
# from this fixture. Re-running 80 rebuilds codex-home and requires a fresh
# ceremony -- deliberately NOT idempotent (81-83 are the repeatable consumers).
#
# Registering EVERYTHING before the single ceremony makes one grant yield many
# (registration -> trusted_hash) pairs for stage 83's preimage analysis AND
# answers the per-entry-vs-per-config prompt question:
#   - all 10 lifecycle events, project-level ($PROJ/.codex/config.toml, TOML)
#   - one extra PreToolUse WITH a matcher (exercises the matcher-idx key dimension)
#   - one user-level SessionStart ($CODEX_HOME/config.toml) -- user-vs-project trust
#   - one sacrificial SessionStart entry reserved for stage 82's 40e mutation
#
# Trust keys embed the registering config's ABSOLUTE path; the fixture paths are
# stable ($CAPTURE_ROOT/fixture/...), so one ceremony's trust holds across reruns
# of 81-83. The auth.json copy in the fixture home is removed on exit.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

fixture_init 80-enroll-fixture
fixture_build
probe_version_check
probe_auth

# ---- register everything via STABLE wrapper paths; all observe-only bodies -----
fixture_register_project
fixture_register_user
fixture_tee_all
cp "$PROJ/.codex/config.toml" "$PROBE_CAPTURE_DIR/meta/registered-project-config.toml"
cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/registered-user-config.before.toml"
snapshot_tree codex-home.before-ceremony "$CODEX_HOME"

if [ ! -t 0 ]; then
    err "stage 80 needs a TTY for the trust ceremony -- run it directly (not piped, not via './reproduce.sh all' in a non-interactive shell)."
fi

PROJ_REAL="$(cd "$PROJ" && pwd -P)"
cat <<EOI

  ================= OPERATOR STEP (80 -- trust ceremony, ~3 min) =================
  In ANOTHER terminal, run EXACTLY:

    cd "$PROJ_REAL" && CODEX_HOME="$CODEX_HOME" codex

  In the TUI:
    1. Accept the project/folder trust prompt if shown.
    2. When prompted about hooks, NOTE THE EXACT WORDING -- one grant for all
       entries, or one per entry? Does it show the command string, or a hash?
       Then ACCEPT each hook.
    3. Try the /hooks command; note what the review UI shows.
    4. /quit
  Then press ENTER here. (Type 's' + ENTER to skip -- leaves the fixture UNenrolled.)
  ===============================================================================
EOI
read -r REPLY
if [ "${REPLY:-}" = "s" ]; then
    note "ceremony SKIPPED by operator -- fixture left unenrolled; stages 81-83 will refuse to run."
    exit 1
fi

printf '\nRecord the observed TUI hook-trust wording (the one fact captures cannot hold).\n' >&2
printf 'Type it, then press Ctrl-D on a blank line:\n' >&2
cat >"$PROBE_CAPTURE_DIR/meta/operator-notes.txt" || true

# ---- harvest the trust delta (the 40c tree-diff pattern) -----------------------
snapshot_tree codex-home.after-ceremony "$CODEX_HOME"
diff "$PROBE_CAPTURE_DIR/trees/codex-home.before-ceremony.txt" \
    "$PROBE_CAPTURE_DIR/trees/codex-home.after-ceremony.txt" \
    >"$PROBE_CAPTURE_DIR/trees/ceremony-tree-diff.txt" 2>&1 || true
# Authoritative enrollment artifact: the user config AFTER the ceremony (carries
# the [hooks.state] records). stage 83's hash-preimage.py reads it + the project
# registration to rebuild (entry -> hash) pairs.
cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/config-after-ceremony.toml" 2>/dev/null || true
# Raw trust-key + hash lines for a quick human read (stage 83 does the full parse).
grep -nE '^\[hooks\.state\.|trusted_hash|trust_level|^\[projects\.' "$CODEX_HOME/config.toml" \
    >"$PROBE_CAPTURE_DIR/meta/trust-keys.txt" 2>/dev/null ||
    note "no [hooks.state]/trust lines found in user config -- ceremony may not have enrolled"
# Any sqlite stores that appeared (read-only inspection; round 2 found trust in
# config.toml, not sqlite -- this catches a version change).
find "$CODEX_HOME" \( -name '*.db' -o -name '*.sqlite*' \) 2>/dev/null \
    >"$PROBE_CAPTURE_DIR/meta/sqlite-candidates.txt"

# ---- headless verification: SessionStart must fire on two FRESH runs -----------
# (fresh `codex exec` process each -- the reproducibility assertion).
run_exec 80v1-verify read-only 'reply with the single word OK'
V1="$(find "$PROBE_CAPTURE_DIR/payloads" -name 'SessionStart-*.stdin.json' 2>/dev/null | wc -l | tr -d ' ')"
run_exec 80v2-verify read-only 'reply with the single word OK'
V2="$(find "$PROBE_CAPTURE_DIR/payloads" -name 'SessionStart-*.stdin.json' 2>/dev/null | wc -l | tr -d ' ')"
note "80: project SessionStart fired headless -- after run1=$V1, after run2=$V2 (expect 1 then 2)"

# Per-registration enrollment matrix: which registered wrappers produced a trust
# key, and which fired across the two verification turns.
ENROLLED_KEYS="$(grep -cE '^\[hooks\.state\.' "$CODEX_HOME/config.toml" 2>/dev/null || true)"
ENROLLED_KEYS="${ENROLLED_KEYS:-0}"
{
    echo "# stage 80 enrollment matrix (codex $CODEX_VERSION)"
    echo "# [hooks.state] keys written by the ceremony: $ENROLLED_KEYS"
    echo "# wrapper-key  fired_in_verification_turns"
    for k in $FIXTURE_WRAPPER_KEYS; do
        printf '%-20s %s\n' "$k" \
            "$(find "$PROBE_CAPTURE_DIR/payloads" -name "$k-*.stdin.json" 2>/dev/null | wc -l | tr -d ' ')"
    done
} >"$PROBE_CAPTURE_DIR/results/enrollment-matrix.txt"
fired_labels >"$PROBE_CAPTURE_DIR/results/fired-events.txt"
note "enrollment matrix -> results/enrollment-matrix.txt ($ENROLLED_KEYS trust keys)"

if [ "$V2" -ge 2 ]; then
    fixture_mark_enrolled "enrolled_keys=$ENROLLED_KEYS sessionstart_fired=$V2"
    note "VERDICT [80]: FIXTURE-ENROLLED (SessionStart fired headless in both runs; $ENROLLED_KEYS trust keys). 81-83 are now runnable."
else
    note "VERDICT [80]: ENROLLMENT-UNCONFIRMED (SessionStart fired ${V2}x, expected >=2)."
    note "Fixture NOT marked enrolled. If only some entries enrolled, inspect results/enrollment-matrix.txt + meta/trust-keys.txt and re-run stage 80 (fresh ceremony)."
    exit 1
fi
