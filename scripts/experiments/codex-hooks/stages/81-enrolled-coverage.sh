#!/usr/bin/env bash
# Stage 81 -- post-enrollment event coverage + response contracts (headless;
# requires the stage-80 fixture). Three parts:
#   81.0  re-validate 40d: a wrapper-BODY swap must not break trust (the whole
#         arm/tee design rests on this -- if it fails, fall back to per-change
#         ceremonies and record it as a MAJOR finding).
#   81.1  stage-20 rerun: tee every event, two turns -> per-event fired matrix
#         POST-enrollment (round 2 only confirmed SessionStart firing).
#   81.2  stage-30 rerun (30a-30h): response wire contracts, one subprobe at a
#         time with arm/tee activation discipline. PreToolUse deny/updatedInput
#         verdicts gate Phase 3 + the registry pretool_policy value; the 30e
#         additionalContext oracle gates Phase 4.
#
# NO --dangerously-bypass-hook-trust ANYWHERE: trust enrollment is the variable
# under test (need_trust_bypass is the pre-enrollment crutch; calling it here
# would defeat the measurement). All hooks are already enrolled, so EVERY armed
# body fires every turn -- hence the strict tee-back-between-subprobes discipline.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

fixture_init 81-enrolled-coverage
fixture_require
probe_version_check
probe_auth

RESPONSES="$LIB_DIR/responses"

oracle() { # oracle <label> <text...> -- record + print a per-sub-probe finding
    local label="$1"
    shift
    printf '%s\n' "$*" >>"$PROBE_CAPTURE_DIR/results/$label.oracle.txt"
    note "oracle [$label]: $*"
}
stream_has() { grep -q "$2" "$PROBE_CAPTURE_DIR/streams/$1.jsonl" 2>/dev/null; }
fired_count() { find "$PROBE_CAPTURE_DIR/payloads" -name "$1-*.stdin.json" 2>/dev/null | wc -l | tr -d ' '; }

# ---- 81.0: re-validate the 40d body-swap foundation --------------------------
# fixture_tee_all just rewrote every wrapper body (a content change), re-stamped to
# THIS stage's capture dir. If trust held, the project SessionStart fires this turn.
fixture_tee_all
run_exec 81-revalidate read-only 'reply with the single word OK'
if [ "$(fired_count SessionStart)" -ge 1 ]; then
    oracle 81-revalidate "PASS: SessionStart fired after a body swap -- 40d holds on this fixture/version; the arm/tee design is valid."
else
    oracle 81-revalidate "FAIL (MAJOR): SessionStart did NOT fire after a body swap -- 40d does NOT hold here. arm/tee swaps are unreliable; 81.1/81.2 results are SUSPECT. Fallback: per-change ceremonies."
fi

# ---- 81.1: stage-20 rerun -- per-event fired/not-fired matrix -----------------
fixture_tee_all
run_exec 81-matrix-readonly read-only \
    'Run exactly this shell command: echo PROBE-RT-1. Then reply DONE.'
run_exec 81-matrix-write workspace-write \
    'Create a file named probe.txt containing exactly PROBE-WR-1, then reply DONE.'
{
    echo "# post-enrollment fired/not-fired matrix (codex $CODEX_VERSION, enrolled, no bypass)"
    echo "# two turns: read-only shell + workspace-write file creation"
    echo "# wrapper-key          fired_count"
    for k in $FIXTURE_WRAPPER_KEYS; do
        printf '%-20s %s\n' "$k" "$(fired_count "$k")"
    done
} >"$PROBE_CAPTURE_DIR/results/event-matrix.txt"
note "event matrix:"
cat "$PROBE_CAPTURE_DIR/results/event-matrix.txt"

# ---- 81.2: stage-30 rerun -- response contracts, one subprobe at a time -------
# Discipline per subprobe: default tee everywhere; ARM exactly the hook(s) under
# test with the stage-30 capture label; run one turn; TEE them back (clears
# block-once guards) before the next. Registrations are NEVER touched (trust holds).
fixture_tee_all

# 30a: PreToolUse deny via JSON response
fixture_arm PreToolUse respond-hook.sh "$RESPONSES/pretooluse-deny.json" 30a-PreToolUse
fixture_tee PostToolUse 30a-PostToolUse
run_exec 30a-deny-json read-only 'Run exactly this shell command: echo PROBE-30A. Then reply DONE.'
if stream_has 30a-deny-json 'PROBE-30A'; then
    oracle 30a-deny-json "stream references PROBE-30A -- inspect whether it EXECUTED or was denied"
else
    oracle 30a-deny-json "no PROBE-30A in stream"
fi
stream_has 30a-deny-json 'PROBE-DENY-30A' && oracle 30a-deny-json "deny reason surfaced in the stream"
oracle 30a-deny-json "PreToolUse fired $(fired_count 30a-PreToolUse)x (gates Phase 3 + registry pretool_policy)"
fixture_tee PreToolUse
fixture_tee PostToolUse

# 30b: PreToolUse deny via exit 2
fixture_arm PreToolUse respond-hook.sh "$RESPONSES/pretooluse-deny-exit2.txt" 30b-PreToolUse
run_exec 30b-deny-exit2 read-only 'Run exactly this shell command: echo PROBE-30B. Then reply DONE.'
stream_has 30b-deny-exit2 'PROBE-DENY-30B' &&
    oracle 30b-deny-exit2 "exit-2 stderr reason surfaced in the stream"
stream_has 30b-deny-exit2 'PROBE-30B' &&
    oracle 30b-deny-exit2 "PROBE-30B referenced in stream -- inspect executed-vs-denied"
fixture_tee PreToolUse

# 30c: PreToolUse allow + updatedInput (mutation proof)
fixture_arm PreToolUse respond-hook.sh "$RESPONSES/pretooluse-allow-updatedinput.json" 30c-PreToolUse
fixture_tee PostToolUse 30c-PostToolUse
run_exec 30c-updatedinput read-only 'Run exactly this shell command: echo PROBE-ORIG. Then reply DONE.'
if stream_has 30c-updatedinput 'PROBE-REWRITTEN'; then
    oracle 30c-updatedinput "REWRITTEN marker present -- updatedInput mutation took effect (gates Phase 3 mutation support)"
elif stream_has 30c-updatedinput 'PROBE-ORIG'; then
    oracle 30c-updatedinput "only ORIG marker present -- mutation did NOT take effect"
else
    oracle 30c-updatedinput "neither marker present -- inspect stream"
fi
fixture_tee PreToolUse
fixture_tee PostToolUse

# 30d: UserPromptSubmit block (the Forge %-command seam headless)
fixture_arm UserPromptSubmit respond-hook.sh "$RESPONSES/userpromptsubmit-block.json" 30d-UserPromptSubmit
run_exec 30d-ups-block read-only '%status'
oracle 30d-ups-block "exit=$(cat "$PROBE_CAPTURE_DIR/results/30d-ups-block.exit" 2>/dev/null) ups-fired=$(fired_count 30d-UserPromptSubmit) -- inspect stream for whether a model turn happened"
stream_has 30d-ups-block 'PROBE-BLOCKED-BY-HOOK' &&
    oracle 30d-ups-block "block reason surfaced in the stream"
fixture_tee UserPromptSubmit

# 30e: SessionStart additionalContext (magic-token echo) -- GATES PHASE 4
fixture_arm SessionStart respond-hook.sh "$RESPONSES/sessionstart-additionalcontext.json" 30e-SessionStart
run_exec 30e-additionalcontext read-only \
    'If your context contains a token starting with MAGIC-CTX-, reply with that token exactly; otherwise reply NONE.'
LM="$(cat "$PROBE_CAPTURE_DIR/results/30e-additionalcontext.last-message.txt" 2>/dev/null || true)"
if printf '%s' "$LM" | grep -q 'MAGIC-CTX-7F3A9'; then
    oracle 30e-additionalcontext "PASS: model echoed the injected token -- additionalContext lands in context headless (Phase 4 SessionStart transfer delivery is VIABLE)"
else
    oracle 30e-additionalcontext "FAIL: model did NOT echo the token (got: $(printf '%s' "$LM" | head -c 80)) -- Phase 4 hook-delivery NOT viable; initial-message stays the only path"
fi
fixture_tee SessionStart

# 30f: PermissionRequest deny (does the approval seam fire headless when enrolled?)
fixture_arm PermissionRequest respond-hook.sh "$RESPONSES/permissionrequest-deny.json" 30f-PermissionRequest
fixture_tee PreToolUse 30f-PreToolUse
fixture_tee PostToolUse 30f-PostToolUse
run_exec 30f-permreq read-only 'Create a file named blocked.txt containing X, then reply DONE.'
if [ "$(fired_count 30f-PermissionRequest)" -ge 1 ]; then
    oracle 30f-permreq "PermissionRequest FIRED headless (enrolled) -- approval seam available"
else
    oracle 30f-permreq "PermissionRequest did NOT fire headless even enrolled (write under read-only sandbox)"
fi
fixture_tee PermissionRequest
fixture_tee PreToolUse
fixture_tee PostToolUse

# 30g: Stop block-once (bounded continuation)
fixture_arm Stop respond-hook.sh "$RESPONSES/stop-block-once.json" 30g-Stop
run_exec 30g-stop-block read-only 'reply with the single word FIRST.'
LM="$(cat "$PROBE_CAPTURE_DIR/results/30g-stop-block.last-message.txt" 2>/dev/null || true)"
oracle 30g-stop-block "Stop fired $(fired_count 30g-Stop)x; last message: $(printf '%s' "$LM" | head -c 40)"
fixture_tee Stop

# 30h: PreToolUse malformed output (doc-claim: unsupported fields fail closed)
fixture_arm PreToolUse respond-hook.sh "$RESPONSES/pretooluse-malformed.json" 30h-PreToolUse
run_exec 30h-malformed read-only 'Run exactly this shell command: echo PROBE-30H. Then reply DONE.'
if stream_has 30h-malformed 'PROBE-30H'; then
    oracle 30h-malformed "PROBE-30H referenced in stream -- inspect whether the malformed response failed OPEN"
else
    oracle 30h-malformed "no PROBE-30H in stream -- consistent with fail-closed"
fi
fixture_tee PreToolUse

# Leave the fixture in the all-tee default so a later stage starts clean.
fixture_tee_all
note "VERDICT [81]: COVERAGE-CAPTURED (matrix -> results/event-matrix.txt; contracts -> results/*.oracle.txt; 30e + PreToolUse verdicts gate Phases 4/3)."
