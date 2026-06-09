#!/usr/bin/env bash
# Stage 70 -- PreToolUse bypass paths (fact 8; 1 model turn here).
# 70a (simple shell) and 70b (apply_patch file write) reuse stage 20's captures
# -- do not re-spend turns on them. This stage adds:
#   70c compound shell: does PreToolUse fire once/twice/zero for `a && b | c`
#       (the doc-claimed unified_exec interception gap)?
#   70d MCP: NOT probed by default (set PROBE_MCP=1 once an MCP echo server is
#       wired); recorded as not-probed, never as bypassed.
# Ground truth for "executed" is the exec JSONL stream's command items.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 70-bypass
probe_version_check
probe_auth

gen_hooks_config toml \
    "PreToolUse=$(make_hook_cmd 70-PreToolUse tee-hook.sh)" \
    "PostToolUse=$(make_hook_cmd 70-PostToolUse tee-hook.sh)" \
    >>"$CODEX_HOME/config.toml"

EXTRA=()
if need_trust_bypass; then EXTRA=(--dangerously-bypass-hook-trust); fi

run_exec 70c-compound read-only \
    'Run exactly this shell command: echo A && echo B | tr a-z A-Z. Then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}

PRE_COUNT="$(find "$PROBE_CAPTURE_DIR/payloads" -name '70-PreToolUse-*.stdin.json' 2>/dev/null | wc -l | tr -d ' ')"
POST_COUNT="$(find "$PROBE_CAPTURE_DIR/payloads" -name '70-PostToolUse-*.stdin.json' 2>/dev/null | wc -l | tr -d ' ')"

{
    echo "# PreToolUse bypass matrix (fired counts; 'executed' = exec JSONL command items)"
    echo "70a simple shell (echo): see stage 20-payloads captures (PreToolUse vs t1 stream)"
    echo "70b apply_patch write:   see stage 20-payloads captures (PreToolUse vs t2 stream)"
    echo "70c compound shell:      PreToolUse=${PRE_COUNT}x PostToolUse=${POST_COUNT}x (stream: streams/70c-compound.jsonl)"
    echo "70d MCP:                 not-probed (PROBE_MCP gate not wired; record as not-probed, never bypassed)"
} >"$PROBE_CAPTURE_DIR/results/70-matrix.md"
cat "$PROBE_CAPTURE_DIR/results/70-matrix.md"

note "VERDICT [70]: BYPASS-MATRIX-CAPTURED (70c PreToolUse=${PRE_COUNT}x)"
