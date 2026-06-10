#!/usr/bin/env bash
# Stage 20 -- payload shapes (facts 1 + 3; 2 model turns).
# Tee hooks on all ten doc-claimed lifecycle events; one read-only shell turn and
# one workspace-write (apply_patch-flavored) turn. Pins per event: exact field
# names (snake_case vs camelCase), tool_input shape per tool, session/turn/cwd
# fields. PreToolUse/PostToolUse captures double as stage 70's 70a/70b evidence.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 20-payloads
probe_version_check
probe_auth

EVENTS=(SessionStart SubagentStart PreToolUse PermissionRequest PostToolUse
    PreCompact PostCompact UserPromptSubmit SubagentStop Stop)
SPECS=()
for ev in "${EVENTS[@]}"; do
    cmd="$(make_hook_cmd "$ev" tee-hook.sh)"
    SPECS+=("$ev=$cmd")
done
gen_hooks_config toml "${SPECS[@]}" >>"$CODEX_HOME/config.toml"
cp "$CODEX_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/registered-config.toml"

EXTRA=()
if need_trust_bypass; then EXTRA=(--dangerously-bypass-hook-trust); fi

note "-- turn 1: read-only shell --"
run_exec t1-readonly-shell read-only \
    'Run exactly this shell command: echo PROBE-RT-1. Then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}

note "-- turn 2: workspace-write file creation --"
run_exec t2-write-file workspace-write \
    'Create a file named probe.txt containing exactly PROBE-WR-1, then reply DONE.' \
    ${EXTRA[@]+"${EXTRA[@]}"}

note "fired events: $(fired_labels | tr '\n' ' ')"
fired_labels >"$PROBE_CAPTURE_DIR/results/fired-events.txt"
note "VERDICT [20]: PAYLOADS-CAPTURED ($(fired_labels | wc -l | tr -d ' ') distinct events)"
