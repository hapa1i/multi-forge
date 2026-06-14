#!/usr/bin/env bash
# Stage 84 -- cross-project trust (headless; requires the stage-80 fixture; run
# after 82). The fresh-project probe stage 82's 82w explicitly deferred: does ONE
# trust ceremony enroll a hook COMMAND STRING in an UNRELATED repo, or only in the
# enrolled project (+ its git worktrees)?
#
# 82w proved enrollment survives a `git worktree` of the enrolled project, but a
# worktree is the SAME git repo -- a fire is consistent with EITHER:
#   H1 (value/definition-based): trust matches the hook DEFINITION (command string
#       is in the trusted_hash, 40e), independent of the registering config path
#       -> a fresh UNRELATED repo with a byte-identical command string FIRES.
#   H2 (key/path-based): trust is looked up by <this-config-path>:event:mi:hi; the
#       worktree fired only via Codex canonicalizing it back to the enrolled
#       checkout -> a fresh UNRELATED repo does NOT fire.
# A fresh, unrelated `git init` repo cannot canonicalize back, so it separates them.
# (The trusted_hash preimage is NOT computable -- 0/13, stage 83 -- so a NO-FIRE
# cannot split H2 from "the path is in the hash" (H3); both collapse to the same
# installer conclusion, so the decision is unaffected. The verdict text must NOT
# claim the hash is path-INDEPENDENT on a fire -- only that lookup is not strictly
# path-scoped.)
#
# Two legs (mirrors 82w2/82w):
#   84a  fresh repo, NO folder trust_level -- the natural Day-1 state + the
#        self-enrollment detector. May be refused by a never-trusted folder; that
#        is data, not the verdict.
#   84b  fresh repo WITH folder trust_level (40b: folder trust alone does NOT fire
#        hooks, so a project-hook fire here is the definition hash; folder trust
#        just lets the turn run). DECISIVE. The path-stable user-level hook is the
#        positive control: it fires from any cwd iff the turn actually ran.
#
# NO --dangerously-bypass-hook-trust anywhere (trust is the variable under test;
# the 84b folder trust_level is the separate folder-trust axis, the 40b deconfound).
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

# Stage 84 writes fresh-project trust into the persistent fixture and the cleanup
# trap removes the fixture auth -- it must never target the real ~/.codex.
[ "${PROBE_USE_REAL_CODEX_HOME:-0}" = "1" ] &&
    err "stage 84 refuses PROBE_USE_REAL_CODEX_HOME=1: it mutates trust state and the cleanup trap would touch the real ~/.codex."

fixture_init 84-fresh-project
# Capture the FIXTURE codex-home BEFORE probe_auth (which could otherwise repoint
# CODEX_HOME); the cleanup trap cleans this path, never whatever CODEX_HOME becomes.
FIXTURE_CODEX_HOME="$CODEX_HOME"
fixture_require
probe_version_check
probe_auth

oracle() {
    local label="$1"
    shift
    printf '%s\n' "$*" >>"$PROBE_CAPTURE_DIR/results/$label.oracle.txt"
    note "oracle [$label]: $*"
}
fired_count() { find "$PROBE_CAPTURE_DIR/payloads" -name "$1-*.stdin.json" 2>/dev/null | wc -l | tr -d ' '; }
# Self-enrollment detector: a [hooks.state] record for the fresh path appearing
# under headless codex exec would refute the round-2 "headless cannot self-enroll".
fresh_self_enrolled() { grep -Fq "hooks.state.\"$FRESH" "$1" 2>/dev/null; }
# Single exit path: record the verdict, restore the pristine fixture (the EXIT trap
# restores too, but doing it here keeps a clean fixture even on exit 0), and exit.
# HOLDS/SCOPED are conclusive (code 0); INVALID/SELF-ENROLLED/INCONCLUSIVE are "no
# clean cross-project answer" (code 1, so reproduce.sh flags the stage).
finish_verdict() { # <verdict-string> <exit-code>
    oracle 84-cross-project "$1"
    printf '%s\n' "$1" >"$PROBE_CAPTURE_DIR/results/verdict.txt"
    cp "$BASE" "$CODEX_HOME/config.toml"
    fixture_tee_all
    note "VERDICT [84]: $1"
    exit "$2"
}

fixture_tee_all

# Pristine base snapshot -- the single source of truth for restore (trap + end).
BASE="$PROBE_CAPTURE_DIR/meta/user-config.base.toml"
cp "$CODEX_HOME/config.toml" "$BASE"

# =============================================================================
# Fresh, UNRELATED repo (not a worktree): a never-before-seen mktemp path with its
# own git history, registering a byte-identical primary-SessionStart definition.
# =============================================================================
TMPPARENT="$(mktemp -d)" || err "mktemp -d failed."
# Combined cleanup: restore the pristine fixture config (so a Ctrl+C / timeout after
# 84b's trust append leaves no fresh-project residue), drop the fixture auth, remove
# the mktemp tree. Overrides fixture_init's auth-only trap; FIXTURE_CODEX_HOME (not
# the live $CODEX_HOME) guarantees we never touch the real ~/.codex. Set now (BASE +
# FIXTURE_CODEX_HOME + TMPPARENT all known) so a git-init failure can't leak the tree.
# shellcheck disable=SC2064  # expand these vars NOW into the trap body
trap "[ -f '$BASE' ] && cp -f '$BASE' '$FIXTURE_CODEX_HOME/config.toml'; rm -f '$FIXTURE_CODEX_HOME/auth.json'; rm -rf '$TMPPARENT'" EXIT

FRESH="$TMPPARENT/freshrepo"
mkdir -p "$FRESH"
(cd "$FRESH" &&
    git init -q &&
    git config user.email probe@example.invalid &&
    git config user.name probe &&
    echo "# fresh unrelated probe project" >README.md &&
    git add README.md &&
    git commit -qm init) || err "fresh project git init failed."
# Canonicalize so the run cwd, the [projects."..."] block, and EVERY grep use the
# SAME spelling (macOS /var -> /private/var). run_exec cd's to the literal
# PROBE_EXEC_CWD, so a /var cwd vs a /private/var trust key would spuriously read
# SCOPED. After this, $FRESH is the realpath for all uses.
FRESH="$(cd "$FRESH" && pwd -P)"

mkdir -p "$FRESH/.codex"
# Single SessionStart entry -> index 0:0, no matcher, timeout 60: byte-identical to
# the enrolled primary proj SessionStart definition, only the registering config
# path differs. (NOT fixture_register_project, which emits 12 entries incl. a second
# SessionStart at 1:0 and a matcher'd PreToolUse -- that would muddy the test.)
gen_hooks_config toml "SessionStart=$HOOKBIN/SessionStart.sh" >"$FRESH/.codex/config.toml"
cp "$FRESH/.codex/config.toml" "$PROBE_CAPTURE_DIR/meta/fresh-project-config.toml"
{
    echo "# fresh (unrelated) project config: $FRESH/.codex/config.toml"
    echo "# enrolled project config:         $(cd "$PROJ/.codex" 2>/dev/null && pwd -P)/config.toml"
    echo "# user (path-stable) config:       $(cd "$CODEX_HOME" && pwd -P)/config.toml"
    echo "# hook command (stable, outside both trees): $HOOKBIN/SessionStart.sh"
} >"$PROBE_CAPTURE_DIR/meta/cross-project-locations.txt"

# =============================================================================
# 84a: fresh repo, NO folder trust_level (natural Day-1 state + self-enroll detector)
# =============================================================================
# Tripwire: the fresh mktemp path must have NO trust footprint before we run it, or
# any result is confounded (mirrors stage 82's INVALID self-guard).
if fresh_self_enrolled "$CODEX_HOME/config.toml" ||
    grep -Fq "[projects.\"$FRESH\"]" "$CODEX_HOME/config.toml" 2>/dev/null; then
    finish_verdict "[CROSS-PROJECT-INVALID] (pre-84a): the fresh path already carries a trust footprint in the base config -- confounded; inspect $BASE and re-run." 1
fi
fixture_tee SessionStart 84a-proj
fixture_tee UserSessionStart 84a-user
PROBE_EXEC_CWD="$FRESH" run_exec 84a-fresh-clean read-only 'reply with the single word OK'
cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/user-config.84a-after.toml"
A_PROJ="$(fired_count 84a-proj)"
A_USER="$(fired_count 84a-user)"
A_EXIT="$(cat "$PROBE_CAPTURE_DIR/results/84a-fresh-clean.exit" 2>/dev/null || echo '?')"
SELF_A=no
fresh_self_enrolled "$PROBE_CAPTURE_DIR/meta/user-config.84a-after.toml" && SELF_A=yes
note "84a (fresh, NO folder trust_level): proj=$A_PROJ user=$A_USER exit=$A_EXIT self_enroll=$SELF_A"
oracle 84-cross-project "84a (natural state, no folder trust): proj=$A_PROJ user=$A_USER exit=$A_EXIT self_enroll=$SELF_A"

# Short-circuit: 84a self-enrollment is already the MAJOR verdict -- settle it here
# rather than spend a 84b turn + churn more state (re-run for 84b data if investigating).
if [ "$SELF_A" = yes ]; then
    finish_verdict "[CROSS-PROJECT-SELF-ENROLLED] (MAJOR): a [hooks.state] record for the fresh UNRELATED path appeared after the 84a headless turn -- this refutes the round-2 premise that headless codex exec cannot self-enroll, so a project-hook fire is then NOT cross-project-trust evidence. Inspect meta/user-config.84a-after.toml before any installer conclusion." 1
fi

# =============================================================================
# 84b: fresh repo WITH folder trust_level (the 40b deconfound) -- DECISIVE
# =============================================================================
# Restore the pristine base, then add ONLY folder trust for the fresh path (40b:
# folder trust alone does not fire hooks, so a project-hook fire here is still the
# definition hash; folder trust just guarantees the turn runs).
cp "$BASE" "$CODEX_HOME/config.toml"
{
    echo ""
    echo "[projects.\"$FRESH\"]"
    echo 'trust_level = "trusted"'
} >>"$CODEX_HOME/config.toml"
cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/user-config.84b-with-trustlevel.toml"
# Self-guard: the intended folder-trust block landed. (No per-hook trust record can
# exist for the fresh path here: we restored from the pristine BASE -- which the
# pre-84a tripwire proved clean -- and 84a self-enrollment already short-circuited.)
if ! grep -Fq "[projects.\"$FRESH\"]" "$CODEX_HOME/config.toml" 2>/dev/null; then
    finish_verdict "[CROSS-PROJECT-INVALID] (pre-84b): the folder trust_level append did not land; inspect meta/user-config.84b-with-trustlevel.toml and re-run." 1
fi
fixture_tee SessionStart 84b-proj
fixture_tee UserSessionStart 84b-user
PROBE_EXEC_CWD="$FRESH" run_exec 84b-fresh-trustlevel read-only 'reply with the single word OK'
cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/user-config.84b-after.toml"
B_PROJ="$(fired_count 84b-proj)"
B_USER="$(fired_count 84b-user)"
B_EXIT="$(cat "$PROBE_CAPTURE_DIR/results/84b-fresh-trustlevel.exit" 2>/dev/null || echo '?')"
SELF_B=no
fresh_self_enrolled "$PROBE_CAPTURE_DIR/meta/user-config.84b-after.toml" && SELF_B=yes
note "84b (fresh, WITH folder trust_level): proj=$B_PROJ user=$B_USER exit=$B_EXIT self_enroll=$SELF_B"
oracle 84-cross-project "84b (decisive, folder trust added): proj=$B_PROJ user=$B_USER exit=$B_EXIT self_enroll=$SELF_B"

# =============================================================================
# Verdict (decisive on 84b; 84a self-enrollment already short-circuited above)
# =============================================================================
# A project-hook fire is itself proof the turn ran, so HOLDS does NOT need the
# positive control -- the user-level hook only gates a NO-fire (SCOPED vs the turn
# never running). A HOLDS with user=0 is unusual (the test hook fired but the
# path-stable control did not); it is flagged, but the project fire stands.
if [ "$SELF_B" = yes ]; then
    finish_verdict "[CROSS-PROJECT-SELF-ENROLLED] (MAJOR): a [hooks.state] record for the fresh UNRELATED path appeared after the 84b turn -- headless self-enrollment, refuting the round-2 premise, so a project-hook fire is then NOT cross-project-trust evidence. Inspect meta/user-config.84b-after.toml before any installer conclusion." 1
elif [ "$B_PROJ" -ge 1 ]; then
    HOLDS_FLAG=""
    [ "$B_USER" -eq 0 ] && HOLDS_FLAG=" (NOTE: the path-stable user-level positive control did NOT fire (user=0) though the project hook did -- unusual; inspect why the user hook was silent, but the project fire in a fresh unrelated repo is self-sufficient evidence the turn ran.)"
    finish_verdict "[CROSS-PROJECT-TRUST-HOLDS]: the fresh UNRELATED repo's project SessionStart fired (b_proj=$B_PROJ b_user=$B_USER) with a byte-identical command string and only folder trust_level (40b: folder trust alone does not fire hooks). Trust is NOT confined to the enrolled checkout -- lookup is not strictly path-scoped (do NOT claim the hash itself is path-independent; preimage uncomputable, stage 83). 82w worktree survival generalizes. -> Phase 6: ONE guided ceremony per CODEX_HOME + a path-stable 'forge hook' command string trusts it in every project.$HOLDS_FLAG" 0
elif [ "$B_USER" -ge 1 ]; then
    finish_verdict "[CROSS-PROJECT-TRUST-SCOPED]: the turn RAN (user-level positive control fired b_user=$B_USER) but the fresh repo's project hook did NOT fire (b_proj=$B_PROJ) despite a byte-identical command string + folder trust. Cross-project trust does NOT hold (key-path-scoping H2 OR preimage-path-binding H3 -- same installer conclusion). 82w worktree survival was git->checkout canonicalization, not a portable command-string trust. -> Phase 6: per-project enrollment OR register at USER scope (the path-stable user config -- the positive control proves user-scope hooks fire from any project)." 0
else
    finish_verdict "[CROSS-PROJECT-INCONCLUSIVE]: neither the project nor the user-level positive-control hook fired in 84b (b_proj=$B_PROJ b_user=$B_USER exit=$B_EXIT) -- the turn likely did not run, so 0 firings is not evidence (mirrors stage 10's NO-FIRE-INCONCLUSIVE). Inspect results/84b-fresh-trustlevel.stderr.txt + .exit. 84a was proj=$A_PROJ user=$A_USER exit=$A_EXIT." 1
fi
