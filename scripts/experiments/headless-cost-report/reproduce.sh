#!/usr/bin/env bash
# Headless cost/usage reporter spike (metric-evidence Phase 5a, HARD GATE).
#
# Question: does `claude -p --output-format json` expose per-run cost
# (`total_cost_usd`) and token `usage` Forge can record, across the auth modes
# and flag combos Forge actually builds? The card's rule: present -> record with
# provenance `reported`; absent -> `unavailable` (NEVER estimate from a table).
#
# This runs the auth-mode x flag-combo matrix for the CURRENT auth mode (detected
# from the env) and prints a verdict per combo. Run it once per auth mode:
#   - direct API key:  ANTHROPIC_API_KEY=... ./reproduce.sh
#   - OAuth/subscription:  (unset ANTHROPIC_API_KEY; have OAuth creds) ./reproduce.sh
#   - proxied:  ANTHROPIC_BASE_URL=http://localhost:<port> ./reproduce.sh
#
# KEY EMPIRICAL FINDING (Claude Code 2.1.165): `--output-format json` emits a
# JSON ARRAY of events [system, assistant, result] -- the cost/usage live in the
# LAST element whose type=="result", NOT a single top-level object. The parser
# Forge ships (parse_headless_envelope) handles BOTH shapes; this harness does too.
#
# Verdicts (per combo):
#   [COST-REPORTED]    result.total_cost_usd is a number
#   [COST-ABSENT]      result element present but total_cost_usd null/absent (honest "unavailable")
#   [USAGE-REPORTED]   result.usage carries input/output tokens
#   [JSON-INCOMPATIBLE] combo errored or stdout was not valid JSON (must NOT request JSON for it)
#   [NO-RESULT]        valid JSON but no type=="result" element
#
# Requires Claude Code on PATH. Does NOT require isolated HOME (so OAuth creds in
# the real ~/.claude still resolve); it runs each probe in a disposable temp CWD,
# so transcripts land under ~/.claude/projects/<encoded-temp> and are harmless.
#
# NOTE: deliberately NOT `set -e` -- some combos may legitimately fail on older
# CLIs (that is a recorded verdict, not a script abort).
set -uo pipefail

MODEL_TIER="${FORGE_SPIKE_TIER:-opus}"

err() { echo "ERROR: $*" >&2; exit 1; }

command -v claude >/dev/null 2>&1 || err "claude is not on PATH."
command -v python3 >/dev/null 2>&1 || err "python3 is not on PATH."
VERSION="$(claude --version 2>/dev/null | awk '{print $1}')"
[ -n "$VERSION" ] || err "could not parse 'claude --version'."

# Per-probe wall-clock guard. GNU coreutils ships `timeout` as `gtimeout` on macOS
# (Homebrew) and it may be absent entirely; detect once and fall back to no guard
# with a warning rather than failing every probe with "command not found".
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT=(timeout 120)
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT=(gtimeout 120)
else
    echo "WARNING: no 'timeout'/'gtimeout' on PATH -- probes run without a wall-clock guard." >&2
    TIMEOUT=()
fi

# Auth-mode detection (recorded, not enforced).
if [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
    AUTH_MODE="proxied ($ANTHROPIC_BASE_URL)"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    AUTH_MODE="direct API key"
else
    AUTH_MODE="OAuth/subscription (no ANTHROPIC_API_KEY)"
fi

echo "Claude Code version: $VERSION"
echo "Auth mode:           $AUTH_MODE"
echo "Model tier:          $MODEL_TIER"
echo

WORK="$(mktemp -d)" || err "mktemp -d failed."
trap 'rm -rf "$WORK"' EXIT

# Extract (valid_json, has_result, total_cost_usd, has_usage, is_error) from a
# captured JSON file, handling BOTH the array shape (take last result element)
# and the single-object shape. Prints a one-line verdict.
verdict() { # $1=label  $2=rc  $3=json_file  $4=err_file
    python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, sys
label, rc, jf, ef = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
raw = open(jf).read() if jf else ""
try:
    d = json.loads(raw); valid = True
except Exception:
    d = None; valid = False
res = None
if valid:
    if isinstance(d, list):
        rs = [x for x in d if isinstance(x, dict) and x.get("type") == "result"]
        res = rs[-1] if rs else None
    elif isinstance(d, dict):
        res = d if d.get("type") == "result" else None
tags = []
if not valid:
    tags.append("[JSON-INCOMPATIBLE]")
    detail = open(ef).read()[:160].replace("\n", " ") if ef else ""
elif res is None:
    tags.append("[NO-RESULT]")
    detail = "no type==result element"
else:
    cost = res.get("total_cost_usd")
    usage = res.get("usage")
    tags.append("[COST-REPORTED]" if isinstance(cost, (int, float)) else "[COST-ABSENT]")
    tags.append("[USAGE-REPORTED]" if isinstance(usage, dict) and usage.get("input_tokens") is not None else "[USAGE-ABSENT]")
    detail = f"cost={cost!r} is_error={res.get('is_error')!r} subtype={res.get('subtype')!r}"
print(f"  {label:<22} rc={rc} {' '.join(tags):<32} {detail}")
PY
}

probe() { # $1=label, rest=claude args  (sets PROBE_SID from the result element)
    local label="$1"; shift
    # ${TIMEOUT[@]+"${TIMEOUT[@]}"}: expands to nothing when TIMEOUT is empty WITHOUT
    # tripping `set -u` on bash 3.2 (macOS default), else the quoted `timeout 120`.
    ( cd "$WORK" && ${TIMEOUT[@]+"${TIMEOUT[@]}"} claude -p "$@" --output-format json < /dev/null ) > "$WORK/out.json" 2> "$WORK/out.err"
    local rc=$?
    verdict "$label" "$rc" "$WORK/out.json" "$WORK/out.err"
    PROBE_SID="$(python3 -c 'import json,sys
try: d=json.loads(open(sys.argv[1]).read())
except Exception: sys.exit()
rs=[x for x in d if isinstance(x,dict) and x.get("type")=="result"] if isinstance(d,list) else ([d] if isinstance(d,dict) and d.get("type")=="result" else [])
print(rs[-1].get("session_id","") if rs else "")' "$WORK/out.json" 2>/dev/null)"
}

echo "== flag-combo matrix (auth mode: $AUTH_MODE) =="
probe "plain"            "Reply with exactly: a"
PARENT_SID="$PROBE_SID"
probe "model"            "Reply with exactly: b" --model "$MODEL_TIER"
if [ -n "$PARENT_SID" ]; then
    probe "resume+fork"  "Reply with exactly: c" --resume "$PARENT_SID" --fork-session
fi
# --bare disables OAuth (requires a real key); only meaningful with a key present.
if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ -z "${ANTHROPIC_BASE_URL:-}" ]; then
    probe "bare"                 "Reply with exactly: d" --bare
    if [ -n "$PARENT_SID" ]; then
        probe "bare+resume+fork+model" "Reply with exactly: e" --bare --resume "$PARENT_SID" --fork-session --model "$MODEL_TIER"
    fi
else
    echo "  bare*                  SKIP (--bare needs ANTHROPIC_API_KEY and no proxy; not this auth mode)"
fi

echo
echo "== stream-json terminal event =="
( cd "$WORK" && timeout 120 claude -p "Reply with exactly: f" --output-format stream-json --verbose < /dev/null ) > "$WORK/stream.out" 2> "$WORK/stream.err"
SRC=$?
tail -n 1 "$WORK/stream.out" > "$WORK/stream.last"
python3 - "$SRC" "$WORK/stream.last" <<'PY'
import json, sys
rc, lf = sys.argv[1], sys.argv[2]
raw = open(lf).read().strip()
try:
    d = json.loads(raw)
except Exception as e:
    print(f"  stream-json          rc={rc} [JSON-INCOMPATIBLE] last line not JSON: {str(e)[:80]}")
    raise SystemExit
print(f"  stream-json          rc={rc} last_type={d.get('type')!r} total_cost_usd={d.get('total_cost_usd')!r}")
PY

echo
echo "================ Record these rows in README.md for auth mode: $AUTH_MODE ================"
echo "Envelope shape: array=[system,assistant,result] (cost/usage in the LAST result element)."
