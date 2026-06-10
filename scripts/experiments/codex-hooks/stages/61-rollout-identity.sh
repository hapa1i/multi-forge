#!/usr/bin/env bash
# Stage 61 -- rollout identity + stdin-prompt resume (Phase 2 bridge-CLI gates; 2 turns; hook-free).
# Pins two facts the bridge CLI builds on:
#   (a) the stream `thread_id` equals the rollout filename's `<session_id>` -- doc-asserted
#       (tests/fixtures/codex/README.md calls thread_id "the resume/session id") but never
#       binary-paired from one run. Gates hook-free rollout discovery into `confirmed`.
#   (b) `codex exec ... resume <thread_id>` accepts the prompt on STDIN. Probe 60 verified
#       resume with a POSITIONAL prompt, but the shipped invoker feeds prompts via
#       `proc.communicate(input=...)` (core/invoker/_lifecycle.py) -- the combination is
#       the one untested seam between probe 60 and `prepare_codex_request(resume_thread_id=...)`.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 61-rollout-identity
probe_version_check
probe_auth

extract_thread_id() { # from a captured stream
    python3 -c '
import json, sys
for line in open(sys.argv[1]):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "thread.started":
        print(ev.get("thread_id", ""))
        break
' "$1"
}

# ---- 61a: seed + rollout glob ---------------------------------------------------
run_exec 61a-seed read-only 'Remember the word PERSIMMON. Reply with the single word OK.'
TID="$(extract_thread_id "$PROBE_CAPTURE_DIR/streams/61a-seed.jsonl")"
[ -n "$TID" ] || err "no thread_id in the seed stream -- cannot probe rollout identity."
note "seed thread_id=$TID"
printf '%s\n' "$TID" >"$PROBE_CAPTURE_DIR/meta/seed-thread-id.txt"

# Rollout layout: $CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<session_id>.jsonl.
# The home is isolated, so the seed turn's rollout is the only candidate set.
shopt -s nullglob
ROLLOUTS=("$CODEX_HOME"/sessions/*/*/*/rollout-*-"$TID".jsonl)
ALL_ROLLOUTS=("$CODEX_HOME"/sessions/*/*/*/rollout-*.jsonl)
shopt -u nullglob
note "61a: rollouts matching thread_id: ${#ROLLOUTS[@]} (total rollouts in home: ${#ALL_ROLLOUTS[@]})"
{
    printf 'thread_id=%s\n' "$TID"
    printf 'match_count=%s\n' "${#ROLLOUTS[@]}"
    for f in "${ROLLOUTS[@]}"; do printf 'match=%s\n' "${f#"$CODEX_HOME"/}"; done
    for f in "${ALL_ROLLOUTS[@]}"; do printf 'rollout=%s\n' "${f#"$CODEX_HOME"/}"; done
} >"$PROBE_CAPTURE_DIR/meta/rollout-glob.txt"
if [ "${#ROLLOUTS[@]}" -eq 1 ]; then
    ROLLOUT_OK=1
    note "61a: rollout identity CONFIRMED (exactly one rollout-*-<thread_id>.jsonl)"
else
    ROLLOUT_OK=0
    note "61a: rollout identity NOT confirmed (matches=${#ROLLOUTS[@]}) -- inspect meta/rollout-glob.txt"
fi

# ---- 61b: stdin-prompt resume ----------------------------------------------------
# Deliberately NO positional prompt and NO </dev/null: the prompt is piped, mirroring
# the invoker's communicate(input=...). run_exec/resume_exec are not reused because
# both encode the positional-prompt contract.
STREAM="$PROBE_CAPTURE_DIR/streams/61b-stdin-resume.jsonl"
STDERR_F="$PROBE_CAPTURE_DIR/results/61b-stdin-resume.stderr.txt"
LM="$PROBE_CAPTURE_DIR/results/61b-stdin-resume.last-message.txt"
note "turn [61b] stdin-prompt: printf ... | codex exec --json ... resume $TID"
(cd "$PROJ" && printf '%s\n' 'Reply with only the word I asked you to remember.' |
    with_timeout codex exec --json --sandbox read-only -o "$LM" resume "$TID") \
    >"$STREAM" 2>"$STDERR_F"
RC=$?
printf '%s\n' "$RC" >"$PROBE_CAPTURE_DIR/results/61b-stdin-resume.exit"
note "turn [61b] exit=$RC last-message=$(head -c 80 "$LM" 2>/dev/null || echo '<none>')"
if grep -qi 'PERSIMMON' "$LM" 2>/dev/null; then
    STDIN_OK=1
    note "61b: stdin-prompt resume CONFIRMED (PERSIMMON recalled)"
else
    STDIN_OK=0
    note "61b: stdin-prompt resume NOT confirmed -- inspect stream/stderr (positional-prompt fallback needed in prepare_codex_request)"
fi
RESUMED_TID="$(extract_thread_id "$STREAM")"
note "61b: resumed stream thread_id=$RESUMED_TID (same as seed: $([ "$RESUMED_TID" = "$TID" ] && echo yes || echo NO))"

# Both facts gate independently: (a) gates rollout discovery, (b) gates the invoker's
# resume request shape. Either failure is a real Phase 2 design input, not noise.
EXIT_RC=0
VERDICT="ROLLOUT-IDENTITY=$([ "${ROLLOUT_OK:-0}" = "1" ] && echo confirmed || echo NOT-CONFIRMED)"
VERDICT="$VERDICT STDIN-RESUME=$([ "${STDIN_OK:-0}" = "1" ] && echo confirmed || echo NOT-CONFIRMED)"
[ "${ROLLOUT_OK:-0}" = "1" ] && [ "${STDIN_OK:-0}" = "1" ] || EXIT_RC=1
note "VERDICT [61]: $VERDICT"
printf '%s\n' "$VERDICT" >"$PROBE_CAPTURE_DIR/results/verdict.txt"
exit "$EXIT_RC"
