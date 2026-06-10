#!/usr/bin/env bash
# Stage 50 -- interactive management facts (fact 6; 2 headless turns + one
# operator-guided interactive run).
#
#   50b headless controls: FORGE_SESSION visibility in hook env AND in the
#       model's shell (shell_environment_policy default filtering)
#   50c (operator, TTY) interactive run with hooks live -> initial-prompt arg,
#       hooks-fire-interactively, session/rollout file discovery via tree-diff
#   50d --ephemeral negative control (no session files expected)
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 50-interactive
probe_version_check
probe_auth

SS_CMD="$(make_hook_cmd 50-SessionStart tee-hook.sh)"
STOP_CMD="$(make_hook_cmd 50-Stop tee-hook.sh)"
gen_hooks_config toml "SessionStart=$SS_CMD" "Stop=$STOP_CMD" >>"$CODEX_HOME/config.toml"

EXTRA=()
if need_trust_bypass; then EXTRA=(--dangerously-bypass-hook-trust); fi

export FORGE_SESSION="probe-fs-xyz"

# ---- 50b: headless env-visibility controls -----------------------------------
snapshot_tree codex-home.before-50b "$CODEX_HOME"
# Single-quoted prompt: $FORGE_SESSION must reach the MODEL SHELL unexpanded.
# shellcheck disable=SC2016  # literal $FORGE_SESSION is the probe itself
run_exec 50b-env-visibility read-only \
    'Run exactly this shell command: echo FS=$FORGE_SESSION. Then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}
HOOK_ENV="$(grep -l 'FORGE_SESSION' "$PROBE_CAPTURE_DIR"/payloads/50-SessionStart-*.env 2>/dev/null | head -1 || true)"
if [ -n "$HOOK_ENV" ]; then
    note "50b: FORGE_SESSION visible in HOOK env: yes ($(grep '^FORGE_SESSION=' "$HOOK_ENV" || true))"
else
    note "50b: FORGE_SESSION visible in HOOK env: NO (or SessionStart never fired headless)"
fi
if grep -q 'FS=probe-fs-xyz' "$PROBE_CAPTURE_DIR/streams/50b-env-visibility.jsonl" 2>/dev/null; then
    note "50b: FORGE_SESSION visible in MODEL SHELL: yes"
else
    note "50b: FORGE_SESSION visible in MODEL SHELL: no (shell_environment_policy filtering?)"
fi
snapshot_tree codex-home.after-50b "$CODEX_HOME"
diff "$PROBE_CAPTURE_DIR/trees/codex-home.before-50b.txt" \
    "$PROBE_CAPTURE_DIR/trees/codex-home.after-50b.txt" \
    >"$PROBE_CAPTURE_DIR/trees/session-files-50b.txt" 2>&1 || true

# ---- 50d: --ephemeral negative control ---------------------------------------
snapshot_tree codex-home.before-50d "$CODEX_HOME"
run_exec 50d-ephemeral read-only 'reply with the single word OK' --ephemeral \
    ${EXTRA[@]+"${EXTRA[@]}"}
snapshot_tree codex-home.after-50d "$CODEX_HOME"
diff "$PROBE_CAPTURE_DIR/trees/codex-home.before-50d.txt" \
    "$PROBE_CAPTURE_DIR/trees/codex-home.after-50d.txt" \
    >"$PROBE_CAPTURE_DIR/trees/session-files-50d-ephemeral.txt" 2>&1 || true

# ---- 50c: operator-guided interactive run ------------------------------------
if [ -t 0 ]; then
    snapshot_tree codex-home.before-50c "$CODEX_HOME"
    cat <<EOI

  ================= OPERATOR STEP (50c) =================
  In ANOTHER terminal, run (note the POSITIONAL initial prompt):

    cd "$PROJ" && FORGE_SESSION=probe-fs-xyz CODEX_HOME="$CODEX_HOME" \\
        codex 'reply with the single word OK'

  Accept any trust prompts, let it answer, then exit (/quit).
  Press ENTER here when done (or 's' + ENTER to skip).
  =======================================================
EOI
    read -r REPLY
    if [ "${REPLY:-}" != "s" ]; then
        snapshot_tree codex-home.after-50c "$CODEX_HOME"
        diff "$PROBE_CAPTURE_DIR/trees/codex-home.before-50c.txt" \
            "$PROBE_CAPTURE_DIR/trees/codex-home.after-50c.txt" \
            >"$PROBE_CAPTURE_DIR/trees/session-files-50c-interactive.txt" 2>&1 || true
        INTERACTIVE_FIRED="$(find "$PROBE_CAPTURE_DIR/payloads" -name '50-SessionStart-*.stdin.json' | wc -l | tr -d ' ')"
        note "50c: SessionStart captures now total ${INTERACTIVE_FIRED} (headless + interactive)"
    else
        note "50c SKIPPED by operator"
    fi
else
    note "50c SKIPPED (no TTY) -- rerun stage 50 interactively for the interactive-fire + session-file facts"
fi

note "VERDICT [50]: INTERACTIVE-FACTS-CAPTURED (see trees/session-files-*.txt + payloads env captures)"
