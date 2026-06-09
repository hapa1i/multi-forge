#!/usr/bin/env bash
# Stage 60 -- `codex exec resume` semantics (fact 7; 4 model turns; hook-free).
# Pins: resume id (= thread_id from thread.started), --json composition + flag
# position, cross-cwd behavior ("cwd-aware since 0.135.0" claim), --last.
# Feeds the bridge-CLI go/no-go directly.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 60-exec-resume
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

# resume_exec <label> <cwd> <resume-args...> -- two argv shapes tried in order:
#   A (per `codex exec [OPTIONS] <COMMAND>` usage): options BEFORE the subcommand
#   B: options AFTER the subcommand
resume_exec() {
    local label="$1" cwd="$2"
    shift 2
    local stream="$PROBE_CAPTURE_DIR/streams/$label.jsonl"
    local stderr_f="$PROBE_CAPTURE_DIR/results/$label.stderr.txt"
    local lm="$PROBE_CAPTURE_DIR/results/$label.last-message.txt"
    note "turn [$label] form A: codex exec --json ... resume $*"
    (cd "$cwd" && with_timeout codex exec --json --sandbox read-only -o "$lm" resume "$@") \
        >"$stream" 2>"$stderr_f"
    local rc=$?
    printf 'A %s\n' "$rc" >"$PROBE_CAPTURE_DIR/results/$label.exit"
    if [ "$rc" -eq 2 ] && grep -qiE 'usage|unexpected|invalid' "$stderr_f"; then
        note "turn [$label] form A rejected (usage error) -- trying form B"
        (cd "$cwd" && with_timeout codex exec resume "$@" --json --sandbox read-only -o "$lm") \
            >"$stream" 2>"$stderr_f"
        rc=$?
        printf 'B %s\n' "$rc" >>"$PROBE_CAPTURE_DIR/results/$label.exit"
    fi
    note "turn [$label] exit=$rc last-message=$(head -c 80 "$lm" 2>/dev/null || echo '<none>')"
    return "$rc"
}

# ---- 60a: seed ----------------------------------------------------------------
run_exec 60a-seed read-only 'Remember the word AUBERGINE. Reply with the single word OK.'
TID="$(extract_thread_id "$PROBE_CAPTURE_DIR/streams/60a-seed.jsonl")"
[ -n "$TID" ] || err "no thread_id in the seed stream -- cannot probe resume."
note "seed thread_id=$TID"
printf '%s\n' "$TID" >"$PROBE_CAPTURE_DIR/meta/seed-thread-id.txt"

# ---- 60b: same-cwd resume by id -----------------------------------------------
resume_exec 60b-same-cwd "$PROJ" "$TID" 'Reply with only the word I asked you to remember.'
if grep -qi 'AUBERGINE' "$PROBE_CAPTURE_DIR/results/60b-same-cwd.last-message.txt" 2>/dev/null; then
    note "60b: continuity CONFIRMED (AUBERGINE recalled)"
else
    note "60b: continuity NOT confirmed -- inspect stream/stderr"
fi
RESUMED_TID="$(extract_thread_id "$PROBE_CAPTURE_DIR/streams/60b-same-cwd.jsonl")"
note "60b: resumed stream thread_id=$RESUMED_TID (same as seed: $([ "$RESUMED_TID" = "$TID" ] && echo yes || echo NO))"

# ---- 60c: cross-cwd resume ------------------------------------------------------
PROJ2="$PROBE_ROOT/proj2"
mkdir -p "$PROJ2"
(cd "$PROJ2" && git init -q && git config user.email p@e.invalid && git config user.name p &&
    echo x >f && git add f && git commit -qm init)
resume_exec 60c-cross-cwd "$PROJ2" "$TID" 'Reply with only the word I asked you to remember.'
if grep -qi 'AUBERGINE' "$PROBE_CAPTURE_DIR/results/60c-cross-cwd.last-message.txt" 2>/dev/null; then
    note "60c: cross-cwd resume WORKED (found + recalled)"
else
    note "60c: cross-cwd resume did not recall -- inspect (refused? rebound? not found?)"
fi

# ---- 60d: --last ---------------------------------------------------------------
resume_exec 60d-last "$PROJ" --last 'Reply with only the word I asked you to remember.'
note "60d: --last exit=$(tail -1 "$PROBE_CAPTURE_DIR/results/60d-last.exit")"

note "VERDICT [60]: RESUME-CAPTURED (id=thread_id; see results/*.exit for accepted argv forms)"
