#!/usr/bin/env bash
# Stage 30 -- response wire contracts (fact 2; ~8 model turns).
# One sub-probe per contract: fresh hook registration + one cheap turn + an
# observable oracle. The exec JSONL stream is ground truth for what actually ran.
#
#   30a PreToolUse deny (JSON)        -> command never runs; where does the reason surface?
#   30b PreToolUse deny (exit 2)      -> exit-code contract parity
#   30c PreToolUse allow+updatedInput -> which command actually ran (rewrite proof)
#   30d UserPromptSubmit block        -> the Forge %-command seam headless
#   30e SessionStart additionalContext-> magic token verifiably lands in model context
#   30f PermissionRequest deny        -> does the approval seam even fire headless?
#   30g Stop block-once               -> forces exactly one extra pass
#   30h PreToolUse malformed output   -> doc-claim: unsupported fields fail closed
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 30-responses
probe_version_check
probe_auth

RESPONSES="$LIB_DIR/responses"
BASE_CONFIG="$(cat "$CODEX_HOME/config.toml" 2>/dev/null || true)"

set_hooks() { # set_hooks HOOKSPEC...  (replaces the probe-owned hook block)
    {
        [ -n "$BASE_CONFIG" ] && printf '%s\n' "$BASE_CONFIG"
        gen_hooks_config toml "$@"
    } >"$CODEX_HOME/config.toml"
}

EXTRA=()
if need_trust_bypass; then EXTRA=(--dangerously-bypass-hook-trust); fi

oracle() { # oracle <label> <text...>  -- record + print a per-sub-probe finding
    local label="$1"
    shift
    printf '%s\n' "$*" >>"$PROBE_CAPTURE_DIR/results/$label.oracle.txt"
    note "oracle [$label]: $*"
}

stream_has() { grep -q "$2" "$PROBE_CAPTURE_DIR/streams/$1.jsonl" 2>/dev/null; }

# ---- 30a: PreToolUse deny via JSON response --------------------------------
set_hooks "PreToolUse=$(make_hook_cmd 30a-PreToolUse respond-hook.sh "$RESPONSES/pretooluse-deny.json")" \
    "PostToolUse=$(make_hook_cmd 30a-PostToolUse tee-hook.sh)"
run_exec 30a-deny-json read-only \
    'Run exactly this shell command: echo PROBE-30A. Then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}
if stream_has 30a-deny-json 'PROBE-30A'; then
    oracle 30a-deny-json "stream still references PROBE-30A -- inspect whether it EXECUTED or was denied"
else
    oracle 30a-deny-json "no PROBE-30A in stream"
fi
if stream_has 30a-deny-json 'PROBE-DENY-30A'; then
    oracle 30a-deny-json "deny reason surfaced in the stream"
fi

# ---- 30b: PreToolUse deny via exit 2 ----------------------------------------
set_hooks "PreToolUse=$(make_hook_cmd 30b-PreToolUse respond-hook.sh "$RESPONSES/pretooluse-deny-exit2.txt")"
run_exec 30b-deny-exit2 read-only \
    'Run exactly this shell command: echo PROBE-30B. Then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}
if stream_has 30b-deny-exit2 'PROBE-DENY-30B'; then
    oracle 30b-deny-exit2 "exit-2 stderr reason surfaced in the stream"
fi

# ---- 30c: PreToolUse allow + updatedInput (mutation) ------------------------
set_hooks "PreToolUse=$(make_hook_cmd 30c-PreToolUse respond-hook.sh "$RESPONSES/pretooluse-allow-updatedinput.json")" \
    "PostToolUse=$(make_hook_cmd 30c-PostToolUse tee-hook.sh)"
run_exec 30c-updatedinput read-only \
    'Run exactly this shell command: echo PROBE-ORIG. Then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}
if stream_has 30c-updatedinput 'PROBE-REWRITTEN'; then
    oracle 30c-updatedinput "REWRITTEN marker present -- updatedInput mutation took effect"
elif stream_has 30c-updatedinput 'PROBE-ORIG'; then
    oracle 30c-updatedinput "only ORIG marker present -- mutation did NOT take effect"
else
    oracle 30c-updatedinput "neither marker present -- inspect stream"
fi

# ---- 30d: UserPromptSubmit block (the %-command seam) ------------------------
set_hooks "UserPromptSubmit=$(make_hook_cmd 30d-UserPromptSubmit respond-hook.sh "$RESPONSES/userpromptsubmit-block.json")"
run_exec 30d-ups-block read-only '%status' ${EXTRA[@]+"${EXTRA[@]}"}
oracle 30d-ups-block "exit=$(cat "$PROBE_CAPTURE_DIR/results/30d-ups-block.exit") -- inspect stream for whether a model turn happened at all"

# ---- 30e: SessionStart additionalContext (magic-token echo) ------------------
set_hooks "SessionStart=$(make_hook_cmd 30e-SessionStart respond-hook.sh "$RESPONSES/sessionstart-additionalcontext.json")"
run_exec 30e-additionalcontext read-only \
    'If your context contains a token starting with MAGIC-CTX-, reply with that token exactly; otherwise reply NONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}
LM="$(cat "$PROBE_CAPTURE_DIR/results/30e-additionalcontext.last-message.txt" 2>/dev/null || true)"
if printf '%s' "$LM" | grep -q 'MAGIC-CTX-7F3A9'; then
    oracle 30e-additionalcontext "PASS: model echoed the injected token (additionalContext lands in context)"
else
    oracle 30e-additionalcontext "model did NOT echo the token (got: $(printf '%s' "$LM" | head -c 80))"
fi

# ---- 30f: PermissionRequest deny (does it fire headless?) --------------------
set_hooks "PermissionRequest=$(make_hook_cmd 30f-PermissionRequest respond-hook.sh "$RESPONSES/permissionrequest-deny.json")" \
    "PreToolUse=$(make_hook_cmd 30f-PreToolUse tee-hook.sh)" \
    "PostToolUse=$(make_hook_cmd 30f-PostToolUse tee-hook.sh)"
run_exec 30f-permreq read-only \
    'Create a file named blocked.txt containing X, then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}
if [ -n "$(find "$PROBE_CAPTURE_DIR/payloads" -name '30f-PermissionRequest-*' 2>/dev/null)" ]; then
    oracle 30f-permreq "PermissionRequest FIRED headless"
else
    oracle 30f-permreq "PermissionRequest did NOT fire headless (write under read-only sandbox)"
fi

# ---- 30g: Stop block-once (bounded continuation) -----------------------------
set_hooks "Stop=$(make_hook_cmd 30g-Stop respond-hook.sh "$RESPONSES/stop-block-once.json")"
run_exec 30g-stop-block read-only 'reply with the single word FIRST.' ${EXTRA[@]+"${EXTRA[@]}"}
LM="$(cat "$PROBE_CAPTURE_DIR/results/30g-stop-block.last-message.txt" 2>/dev/null || true)"
STOPS="$(find "$PROBE_CAPTURE_DIR/payloads" -name '30g-Stop-*.stdin.json' 2>/dev/null | wc -l | tr -d ' ')"
oracle 30g-stop-block "Stop fired ${STOPS}x; last message: $(printf '%s' "$LM" | head -c 40)"

# ---- 30h: PreToolUse malformed output (fail-closed doc-claim) ----------------
set_hooks "PreToolUse=$(make_hook_cmd 30h-PreToolUse respond-hook.sh "$RESPONSES/pretooluse-malformed.json")"
run_exec 30h-malformed read-only \
    'Run exactly this shell command: echo PROBE-30H. Then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}
if stream_has 30h-malformed 'PROBE-30H'; then
    oracle 30h-malformed "PROBE-30H referenced in stream -- inspect whether the malformed response failed open"
else
    oracle 30h-malformed "no PROBE-30H in stream -- consistent with fail-closed"
fi

note "VERDICT [30]: RESPONSES-CAPTURED (see results/*.oracle.txt; analysis happens in the decision record)"
