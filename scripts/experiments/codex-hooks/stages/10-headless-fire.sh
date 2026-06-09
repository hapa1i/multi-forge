#!/usr/bin/env bash
# Stage 10 -- headless-fire (THE GATE; 1-2 model turns).
# Pins fact 5 (do hooks fire under `codex exec`?) plus partial facts 3 (which of
# the four registration surfaces deliver) and 4 (trust-skip behavior headless).
#
# One SessionStart tee per registration surface, distinct labels, single turn:
#   user TOML  $CODEX_HOME/config.toml      -> SessionStart-userToml
#   user JSON  $CODEX_HOME/hooks.json       -> SessionStart-userJson
#   proj TOML  $PROJ/.codex/config.toml     -> SessionStart-projToml
#   proj JSON  $PROJ/.codex/hooks.json      -> SessionStart-projJson
#
# Verdicts: [FIRES-HEADLESS] [FIRES-HEADLESS-TRUST-GATED] [INTERACTIVE-ONLY]
#           [NO-FIRE-UNCATEGORIZED]
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 10-headless-fire
probe_version_check
probe_auth

CMD_USER_TOML="$(make_hook_cmd SessionStart-userToml tee-hook.sh)"
CMD_USER_JSON="$(make_hook_cmd SessionStart-userJson tee-hook.sh)"
CMD_PROJ_TOML="$(make_hook_cmd SessionStart-projToml tee-hook.sh)"
CMD_PROJ_JSON="$(make_hook_cmd SessionStart-projJson tee-hook.sh)"

gen_hooks_config toml "SessionStart=$CMD_USER_TOML" >>"$CODEX_HOME/config.toml"
gen_hooks_config json "SessionStart=$CMD_USER_JSON" >"$CODEX_HOME/hooks.json"
mkdir -p "$PROJ/.codex"
gen_hooks_config toml "SessionStart=$CMD_PROJ_TOML" >"$PROJ/.codex/config.toml"
gen_hooks_config json "SessionStart=$CMD_PROJ_JSON" >"$PROJ/.codex/hooks.json"
cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/registered-user-config.toml"
cp "$CODEX_HOME/hooks.json" "$PROBE_CAPTURE_DIR/meta/registered-user-hooks.json"

note "-- turn 1: plain exec (no trust bypass) --"
run_exec t1-plain read-only 'reply with the single word OK'
FIRED_T1="$(fired_labels)"
note "fired after turn 1: ${FIRED_T1:-<none>}"

FIRED_T2=""
if [ -z "$FIRED_T1" ]; then
    note "-- turn 2: retry with --dangerously-bypass-hook-trust --"
    run_exec t2-bypass-trust read-only 'reply with the single word OK' --dangerously-bypass-hook-trust
    FIRED_T2="$(fired_labels)"
    note "fired after turn 2: ${FIRED_T2:-<none>}"
fi

{
    echo "turn1_fired: ${FIRED_T1:-none}"
    echo "turn2_bypass_fired: ${FIRED_T2:-none}"
} >"$PROBE_CAPTURE_DIR/results/fired-summary.txt"

if [ -n "$FIRED_T1" ]; then
    VERDICT="[FIRES-HEADLESS]"
elif [ -n "$FIRED_T2" ]; then
    VERDICT="[FIRES-HEADLESS-TRUST-GATED]"
else
    # Distinguish interactive-only from misregistration is stage 50's job; record
    # stderr for classification.
    VERDICT="[NO-FIRE-UNCATEGORIZED]"
fi
note "VERDICT [10]: $VERDICT (surfaces fired: t1=${FIRED_T1:-none} t2=${FIRED_T2:-none})"
printf '%s\n' "$VERDICT" >"$PROBE_CAPTURE_DIR/results/verdict.txt"
