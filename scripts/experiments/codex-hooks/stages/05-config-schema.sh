#!/usr/bin/env bash
# Stage 05 -- hook-registration schema validation depth (0 real model turns).
# Uses `codex exec --strict-config` with a deliberately-bogus model: a config
# error aborts BEFORE any model call; a schema-valid config reaches the provider
# "model not supported" rejection (no completion, no usage billed).
#
# Pins (fact 3 refinement): which parts of the [[hooks.<Event>]] registration
# the binary actually validates -- and which misregistrations stay SILENT.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 05-config-schema
probe_version_check
probe_auth

DUMMY="$HOOKBIN/dummy.sh"
printf '#!/bin/sh\nexit 0\n' >"$DUMMY"
chmod +x "$DUMMY"
FINDINGS="$PROBE_CAPTURE_DIR/results/schema-findings.txt"
: >"$FINDINGS"

# probe_cfg <case-id> <config-text> -- classify: CONFIG-ERROR vs LOADED.
probe_cfg() {
    local case_id="$1" cfg="$2" out rc
    printf '%s\n' "$cfg" >"$CODEX_HOME/config.toml"
    out="$( (cd "$PROJ" && with_timeout codex exec --strict-config -m bogus-model-zzz 'x' </dev/null) 2>&1)"
    rc=$?
    printf '%s\n' "$out" >"$PROBE_CAPTURE_DIR/results/$case_id.out.txt"
    if printf '%s' "$out" | grep -q 'Error loading config.toml'; then
        local detail
        detail="$(printf '%s' "$out" | grep -E 'missing field|unknown configuration field|invalid' | head -1)"
        echo "$case_id: CONFIG-ERROR ($detail)" >>"$FINDINGS"
    elif printf '%s' "$out" | grep -q 'model is not supported'; then
        echo "$case_id: LOADED (schema-accepted; reached provider model rejection)" >>"$FINDINGS"
    else
        echo "$case_id: UNCATEGORIZED rc=$rc (see $case_id.out.txt)" >>"$FINDINGS"
    fi
}

VALID="[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = \"command\"
command = \"$DUMMY\"
timeout = 60"

probe_cfg valid-shape "$VALID"

probe_cfg missing-command "[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = \"command\"
comand = \"$DUMMY\"
timeout = 60"

probe_cfg toplevel-bogus-key "definitely_not_a_real_key = 1"

probe_cfg inner-bogus-field "[[hooks.SessionStart]]
[[hooks.SessionStart.hooks]]
type = \"command\"
command = \"$DUMMY\"
bogus_zzz = 1"

probe_cfg outer-bogus-field "[[hooks.SessionStart]]
bogus_zzz = 1
[[hooks.SessionStart.hooks]]
type = \"command\"
command = \"$DUMMY\""

probe_cfg bogus-event-name "[[hooks.NotARealEvent]]
[[hooks.NotARealEvent.hooks]]
type = \"command\"
command = \"$DUMMY\""

echo "---- schema findings ----"
cat "$FINDINGS"
note "VERDICT [05]: SCHEMA-DEPTH-CAPTURED (see results/schema-findings.txt)"
