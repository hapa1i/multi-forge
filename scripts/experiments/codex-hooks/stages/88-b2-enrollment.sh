#!/usr/bin/env bash
# B2 enrollment: two positive-control turns plus Forge's empirical user-hook check.
# An optional capture name keeps a later revalidation separate from the original round.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

CAPTURE_NAME="${1:-88-b2-enrollment}"
case "$CAPTURE_NAME" in 88-*) ;; *) err "capture name must start with 88-" ;; esac
case "$CAPTURE_NAME" in *[!a-zA-Z0-9_-]*) err "capture name may contain only letters, digits, underscores and hyphens" ;; esac
fixture_init "$CAPTURE_NAME"
probe_version_check
probe_auth
fixture_tee_all
python3 - "$PROBE_CONTROL" "$PROBE_CAPTURE_DIR" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"capture": sys.argv[2], "mode": "observe", "reviewer": "fast"}))
PY
run_exec 88v1 read-only 'Reply with only OK.'
FIRST="$(find "$PROBE_CAPTURE_DIR/payloads" -name 'SessionStart-*.stdin.json' | wc -l | tr -d ' ')"
run_exec 88v2 read-only 'Reply with only OK.'
SECOND="$(find "$PROBE_CAPTURE_DIR/payloads" -name 'SessionStart-*.stdin.json' | wc -l | tr -d ' ')"
[ "$FIRST" -ge 1 ] && [ "$SECOND" -gt "$FIRST" ] || err "enrollment not confirmed by both completed turns"
fixture_mark_enrolled "project_sessionstart=$SECOND; independent login; B2 current dispatcher also registered"

"$FORGE_DEV/.venv/bin/forge" runtime preflight codex --json >"$PROBE_CAPTURE_DIR/results/preflight.json"
"$FORGE_DEV/.venv/bin/forge" extension doctor --json >"$PROBE_CAPTURE_DIR/results/forge-doctor.json"
"$FORGE_DEV/.venv/bin/forge" runtime preflight codex --verify-enrollment --json >"$PROBE_CAPTURE_DIR/results/enrollment.json"
python3 - "$PROBE_CAPTURE_DIR" <<'PY'
import json, sys
from pathlib import Path
capture=Path(sys.argv[1])
preflight=json.loads((capture/'results/preflight.json').read_text())
assert preflight['ready'] and preflight['auth_method']=='chatgpt_tokens'
assert preflight['auth_source']=='codex_store' and preflight['billing_mode']=='subscription_quota'
doctor=json.loads((capture/'results/forge-doctor.json').read_text())
assert doctor['hook_dispatcher']['dev_override']['effective'] is True
enrollment=json.loads((capture/'results/enrollment.json').read_text())
assert enrollment['attempted'] and enrollment['codex_succeeded'] and enrollment['enrolled']
assert list(capture.glob('*-observation-receipt.json')), 'retain the receipt before temporary probe teardown'
assert (capture/'hook-launchers.jsonl').is_file(), 'retain hook-side checkout provenance'
(capture/'results/verdict.txt').write_text('PASS: completed enrolled controls, Forge preflight, receipt, checkout dispatch\n')
PY
note "B2 enrollment and provenance PASS"
