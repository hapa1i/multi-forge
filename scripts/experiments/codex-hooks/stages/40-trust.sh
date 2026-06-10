#!/usr/bin/env bash
# Stage 40 -- trust mechanics (fact 4; 3 headless turns + one operator-guided
# interactive step). Sub-steps share ONE persistent CODEX_HOME (under the capture
# root, never ~/.codex) because 40c's trust grant must be visible to 40d.
#
#   40a untrusted project-local hook -> fired? silent skip or warning?
#   40b projects."<proj>".trust_level = "trusted" -> does config-level project
#       trust alone deliver, or is per-hook-hash trust additionally required?
#   40c (operator, TTY) interactive trust flow; tree-diff finds WHERE trust lives
#   40d after trust: change the hook script content -> skipped again? (hash-keyed?)
#
# The auth.json copy inside the persistent home is removed on exit.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 40-trust --persistent-home
rm -rf "$CODEX_HOME" && mkdir -p "$CODEX_HOME" && chmod 700 "$CODEX_HOME" # deterministic restart
probe_version_check
probe_auth
# shellcheck disable=SC2064  # expand now; PROBE_ROOT trap is replaced on purpose
trap "rm -f '$CODEX_HOME/auth.json'; rm -rf '$PROBE_ROOT'" EXIT

count_fired() { find "$PROBE_CAPTURE_DIR/payloads" -name "$1-*.stdin.json" 2>/dev/null | wc -l | tr -d ' '; }

# ---- 40a: untrusted project-local hook (NO user hooks, NO trust) -------------
PROJ_HOOK="$(make_hook_cmd 40-ProjHook tee-hook.sh)"
mkdir -p "$PROJ/.codex"
gen_hooks_config toml "SessionStart=$PROJ_HOOK" >"$PROJ/.codex/config.toml"
run_exec 40a-untrusted read-only 'reply with the single word OK'
A_FIRED="$(count_fired 40-ProjHook)"
note "40a: project hook fired ${A_FIRED}x (untrusted project; expect 0 if skipped)"
grep -i 'hook\|trust' "$PROBE_CAPTURE_DIR/results/40a-untrusted.stderr.txt" \
    >"$PROBE_CAPTURE_DIR/results/40a-warning-lines.txt" 2>/dev/null || true

# ---- 40b: project trust_level in user config ---------------------------------
PROJ_REAL="$(cd "$PROJ" && pwd -P)"
{
    echo "[projects.\"$PROJ_REAL\"]"
    echo 'trust_level = "trusted"'
} >>"$CODEX_HOME/config.toml"
run_exec 40b-trust-level read-only 'reply with the single word OK'
B_FIRED="$(count_fired 40-ProjHook)"
note "40b: project hook fired ${B_FIRED}x total (delta vs 40a = $((B_FIRED - A_FIRED)))"

# ---- 40c: operator-guided interactive trust ----------------------------------
snapshot_tree codex-home.before-40c "$CODEX_HOME"
cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/config-before-40c.toml" 2>/dev/null || true
if [ -t 0 ]; then
    cat <<EOI

  ================= OPERATOR STEP (40c) =================
  In ANOTHER terminal, run:

    cd "$PROJ_REAL" && CODEX_HOME="$CODEX_HOME" codex

  Inside the TUI: if prompted about project/hook trust, ACCEPT/trust; try the
  /hooks command if available to review the SessionStart hook; then exit (/quit).
  Press ENTER here when done (or 's' + ENTER to skip).
  =======================================================
EOI
    read -r REPLY
    if [ "${REPLY:-}" != "s" ]; then
        snapshot_tree codex-home.after-40c "$CODEX_HOME"
        diff "$PROBE_CAPTURE_DIR/trees/codex-home.before-40c.txt" \
            "$PROBE_CAPTURE_DIR/trees/codex-home.after-40c.txt" \
            >"$PROBE_CAPTURE_DIR/trees/trust-diff.txt" 2>&1 || true
        cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/config-after-40c.toml" 2>/dev/null || true
        # Trust-store candidates: any sqlite DBs that appeared (read-only inspection).
        find "$CODEX_HOME" \( -name '*.db' -o -name '*.sqlite*' \) 2>/dev/null \
            >"$PROBE_CAPTURE_DIR/meta/sqlite-candidates.txt"
        if command -v sqlite3 >/dev/null 2>&1; then
            while IFS= read -r db; do
                [ -n "$db" ] || continue
                {
                    echo "== $db =="
                    sqlite3 "file:$db?mode=ro" .tables 2>&1
                } >>"$PROBE_CAPTURE_DIR/meta/sqlite-tables.txt"
            done <"$PROBE_CAPTURE_DIR/meta/sqlite-candidates.txt"
        fi
        # 40c2: THE ENABLEMENT TEST -- headless re-run in the SAME home right
        # after interactive review/trust, hook content UNchanged. If this fires
        # where 40a/40b did not, "enabled" is a per-hook state granted by the
        # interactive review flow and headless-only environments can never
        # self-enable (the unifying hypothesis for stage 10/20's zero firings).
        run_exec 40c2-posttrust read-only 'reply with the single word OK'
        C2_FIRED="$(count_fired 40-ProjHook)"
        note "40c2: project hook fired ${C2_FIRED}x total (delta vs 40b = $((C2_FIRED - B_FIRED)))"

        # 40d: hash-keying -- change the hook script CONTENT, re-run headless. This
        # covers the content-hash dimension only; changing the registered command
        # PATH/string is a separate trust dimension not exercised here (deferred to
        # the interactive build-card probe -- docs/board/proposed/codex_frontend/card.md).
        echo "# content change to break the hook hash" >>"$PROJ_HOOK"
        run_exec 40d-hash-change read-only 'reply with the single word OK'
        D_FIRED="$(count_fired 40-ProjHook)"
        note "40d: project hook fired ${D_FIRED}x total (delta vs 40c2 = $((D_FIRED - C2_FIRED)))"
    else
        note "40c/40d SKIPPED by operator"
    fi
else
    note "40c/40d SKIPPED (no TTY) -- rerun stage 40 interactively for the trust-store discovery"
fi

note "VERDICT [40]: TRUST-CAPTURED (40a=${A_FIRED} 40b-delta=$((B_FIRED - A_FIRED)); see trees/trust-diff.txt)"
