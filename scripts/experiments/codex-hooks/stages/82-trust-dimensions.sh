#!/usr/bin/env bash
# Stage 82 -- trust dimensions (headless; requires the stage-80 fixture; run after
# 81). Three sub-probes, each isolated by a unique capture label so counts in the
# shared payloads dir stay unambiguous:
#
#   82e  40e -- mutate the REGISTERED COMMAND STRING of the sacrificial entry and
#        re-run headless. The primary SessionStart (unmutated) is the control:
#          moved fires + primary fires -> command string NOT in the hash
#          moved skipped + primary fires -> command string IS in a per-entry hash
#          neither fires               -> whole-file hashing OR config rejected
#        (40d only proved script-CONTENT changes survive; this is the string leg.)
#   82u  user-vs-project -- where the user-level hook's trust record landed (from
#        80's captured config) and whether it fires headless.
#   82w  worktree sensitivity -- trust keys embed the registering config's ABSOLUTE
#        path, so a `git worktree` checkout (new path) should NOT inherit the
#        project hook's trust, while the path-stable user-level hook should. The
#        asymmetry is the direct input to the Phase 6 installer scope decision
#        (user scope = one trust, path-stable; project scope = travels with git but
#        re-trust per worktree). Project trust_level is added first to DECONFOUND
#        (40b: trust_level is not sufficient, but its necessity alongside enrollment
#        was never disproved -- without it a no-fire is uninterpretable).
#
# NO --dangerously-bypass-hook-trust anywhere (trust is the variable under test).
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

fixture_init 82-trust-dimensions
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

fixture_tee_all

# =============================================================================
# 82e: 40e -- registration-string mutation of the sacrificial entry
# =============================================================================
# New wrapper at a DIFFERENT path, identical (tee) body, distinct capture label.
fixture_tee Sacrificial2 82e-sac-moved
# Control: re-stamp the primary SessionStart to a distinct label for this turn.
fixture_tee SessionStart 82e-primary
# Point the sacrificial project entry at the new command string (regenerates the
# whole project config; non-sacrificial entries keep byte-identical definitions).
fixture_register_project "$HOOKBIN/Sacrificial2.sh"
cp "$PROJ/.codex/config.toml" "$PROBE_CAPTURE_DIR/meta/project-config.40e-mutated.toml"
run_exec 82e-cmd-string read-only 'reply with the single word OK'
MOVED="$(fired_count 82e-sac-moved)"
PRIMARY="$(fired_count 82e-primary)"
if [ "$MOVED" -ge 1 ] && [ "$PRIMARY" -ge 1 ]; then
    oracle 82e-cmd-string "moved=$MOVED primary=$PRIMARY -> command string is NOT part of the trusted_hash (path swap still fired)"
elif [ "$MOVED" -eq 0 ] && [ "$PRIMARY" -ge 1 ]; then
    oracle 82e-cmd-string "moved=$MOVED primary=$PRIMARY -> command string IS in a PER-ENTRY hash (moved entry untrusted, others intact)"
else
    oracle 82e-cmd-string "moved=$MOVED primary=$PRIMARY -> neither fired: whole-file hashing OR config rejected; inspect results/82e-cmd-string.stderr.txt"
fi
# Restore the canonical (enrolled) sacrificial registration so 81/83 reruns see a
# pristine fixture; byte-identical to the original means the trust re-validates.
fixture_register_project
fixture_tee SessionStart

# =============================================================================
# 82u: user-level vs project-level trust
# =============================================================================
USER_CFG_AFTER="$CAPTURE_ROOT/80-enroll-fixture/meta/config-after-ceremony.toml"
USER_CFG_ABS="$(cd "$CODEX_HOME" && pwd -P)/config.toml"
{
    echo "# user-config abs path: $USER_CFG_ABS"
    echo "# project-config abs path: $(cd "$PROJ/.codex" 2>/dev/null && pwd -P)/config.toml"
    echo "# --- [hooks.state] keys from 80's captured post-ceremony user config ---"
    grep -nE '^\[hooks\.state\.|trust_level|^\[projects\.' "$USER_CFG_AFTER" 2>/dev/null ||
        echo "(80 capture missing: $USER_CFG_AFTER)"
} >"$PROBE_CAPTURE_DIR/meta/trust-locations.txt"
fixture_tee UserSessionStart 82u-user
fixture_tee SessionStart 82u-proj
run_exec 82u-user-vs-project read-only 'reply with the single word OK'
oracle 82u-user-vs-project "user-level fired=$(fired_count 82u-user) project-level fired=$(fired_count 82u-proj); trust-record locations -> meta/trust-locations.txt"
fixture_tee SessionStart
fixture_tee UserSessionStart

# =============================================================================
# 82w: worktree path sensitivity (avoid the registration confound)
# =============================================================================
# The project hook's registration must TRAVEL to the worktree, or "didn't fire"
# would prove "no hook" rather than "path-bound trust". So commit the project
# config (forced -- a global excludesfile may ignore .codex/), then add a worktree.
git -C "$PROJ" add -f .codex/config.toml >/dev/null 2>&1 || true
git -C "$PROJ" commit -q -m "probe: register codex hooks (82w)" >/dev/null 2>&1 || true
WT="$FIXTURE_ROOT/proj-codexwt" # sibling checkout (mirrors Forge's <repo>-<session>)
git -C "$PROJ" worktree remove --force "$WT" >/dev/null 2>&1 || true
rm -rf "$WT"
git -C "$PROJ" worktree prune >/dev/null 2>&1 || true
if ! git -C "$PROJ" worktree add --detach "$WT" >/dev/null 2>&1; then
    oracle 82w-worktree "SETUP-FAIL: git worktree add failed; cannot probe path sensitivity (inspect git state)."
else
    WT_REAL="$(cd "$WT" && pwd -P)"
    note "worktree at $WT_REAL (registration travelled: $([ -f "$WT/.codex/config.toml" ] && echo yes || echo NO))"
    # Idempotent CLEAN SLATE: the fixture config is PERSISTENT and a prior 82 run may
    # have left a worktree [projects."<WT>"] trust_level block behind. Strip any such
    # block FIRST so the no-trust_level base is genuinely clean -- otherwise 82w2
    # silently runs WITH leftover trust_level and the disambiguation is void (the bug
    # the first 82w2 run hit before this guard existed).
    python3 - "$CODEX_HOME/config.toml" "$WT_REAL" <<'PY'
import sys
path, wt = sys.argv[1], sys.argv[2]
text = open(path).read()
hdr = f'[projects."{wt}"]'
lines, out, i = text.splitlines(), [], 0
while i < len(lines):
    if lines[i].strip() == hdr:                 # drop this table header...
        if out and out[-1].strip() == "":
            out.pop()                           # ...and the blank line before it
        i += 1
        while i < len(lines) and not lines[i].lstrip().startswith("["):
            i += 1                              # ...and its body, until the next table
        continue
    out.append(lines[i])
    i += 1
open(path, "w").write("\n".join(out) + ("\n" if text.endswith("\n") else ""))
PY
    cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/user-config.no-wt-trustlevel.toml"
    # Self-protect against the confound class: the base MUST now lack the worktree
    # block, or any 82w2 result is meaningless.
    if grep -Fq "projects.\"$WT_REAL\"" "$PROBE_CAPTURE_DIR/meta/user-config.no-wt-trustlevel.toml" 2>/dev/null; then
        oracle 82w-worktree "INVALID: could not strip the worktree trust_level from the persistent config; 82w2 would be confounded. Inspect meta/user-config.no-wt-trustlevel.toml."
    else
        # 82w2 (run FIRST, from the clean base): WITHOUT worktree folder trust_level.
        # The project hook has neither a [hooks.state] record at the worktree path NOR
        # folder trust. If it STILL fires, enrollment SURVIVES the worktree (40b predicts
        # this). NOTE the scope limit: this is a `git worktree` of the SAME repo, so a
        # fire is consistent with EITHER a path-independent definition hash OR Codex
        # canonicalizing the worktree back to the enrolled checkout -- this probe does
        # not distinguish them, and proves nothing about an UNRELATED project reusing the
        # same command string (that needs a fresh-project probe). If it stops,
        # trust_level was load-bearing.
        fixture_tee SessionStart 82w2-proj
        fixture_tee UserSessionStart 82w2-user
        PROBE_EXEC_CWD="$WT" run_exec 82w2-no-trustlevel read-only 'reply with the single word OK'
        W2PROJ="$(fired_count 82w2-proj)"
        W2USER="$(fired_count 82w2-user)"
        note "82w2 (worktree, NO folder trust_level): proj=$W2PROJ user=$W2USER"

        # 82w: WITH worktree folder trust_level (the 40b deconfound).
        {
            echo ""
            echo "[projects.\"$WT_REAL\"]"
            echo 'trust_level = "trusted"'
        } >>"$CODEX_HOME/config.toml"
        cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/user-config.with-wt-trustlevel.toml"
        fixture_tee SessionStart 82w-proj
        fixture_tee UserSessionStart 82w-user
        PROBE_EXEC_CWD="$WT" run_exec 82w-in-worktree read-only 'reply with the single word OK'
        WPROJ="$(fired_count 82w-proj)"
        WUSER="$(fired_count 82w-user)"
        note "82w (worktree, WITH folder trust_level): proj=$WPROJ user=$WUSER"

        if [ "$W2PROJ" -ge 1 ]; then
            oracle 82w-worktree "fired WITHOUT worktree trust_level (w2=$W2PROJ user_w2=$W2USER; with-trustlevel w=$WPROJ) -> enrollment SURVIVES a git worktree of the enrolled project: no [hooks.state] record at the worktree path and no folder trust_level, yet the project hook fired (40b rules out folder trust, so this is a trusted_hash match). Mechanism not distinguished (path-independent definition hash vs worktree->checkout canonicalization); the broad 'any project with the same command string is trusted' claim is UNTESTED (needs a fresh-project probe). -> Phase 6: project-scope registration with a stable 'forge hook' command string survives worktrees (no per-worktree re-enrollment)."
        elif [ "$WPROJ" -ge 1 ]; then
            oracle 82w-worktree "fired ONLY WITH worktree trust_level (w=$WPROJ w2=$W2PROJ) -> folder trust_level is LOAD-BEARING for the worktree project hook. -> Phase 6: each worktree path needs folder trust (or register user-scope, path-stable)."
        else
            oracle 82w-worktree "did NOT fire in the worktree even with trust_level (w=$WPROJ w2=$W2PROJ user=$WUSER) -> ENROLLMENT IS PATH-BOUND; the path-stable user-level hook is the survivor. -> Phase 6: register Codex hooks at USER scope."
        fi
        # Restore the clean base (no worktree trust_level) -> pristine fixture.
        cp "$PROBE_CAPTURE_DIR/meta/user-config.no-wt-trustlevel.toml" "$CODEX_HOME/config.toml"
    fi
    # Leave the worktree dir for inspection; a re-run prunes + recreates it.
fi

fixture_tee_all
note "VERDICT [82]: TRUST-DIMENSIONS-CAPTURED (40e command-string + user-vs-project + worktree -> results/*.oracle.txt; worktree finding routes to the Phase 6 installer scope decision)."
