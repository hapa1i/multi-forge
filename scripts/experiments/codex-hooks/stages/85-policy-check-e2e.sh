#!/usr/bin/env bash
# Stage 85 -- enrolled product `forge hook codex-policy-check` end-to-end.
#
# This is not another wrapper-body fixture test. It registers the real product
# command string (`forge hook codex-policy-check`) as a Codex PreToolUse hook,
# asks the operator to trust that command, then runs a real `codex exec` turn
# whose apply_patch should be denied by Forge TDD policy. PASS requires both:
#   1. confirmed.policy records a deny from hook:codex-policy-check, and
#   2. the requested src/ file does NOT exist after the turn.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

fixture_init 85-policy-check-e2e
fixture_require
probe_version_check
probe_auth
probe_forge_home
require_product_forge_hook_command

SESSION="s85-policy"
PRODUCT_PROJ="$PROBE_CAPTURE_DIR/project"
BLOCKED_REL="src/s85_blocked.py"
BLOCKED_FILE="$PRODUCT_PROJ/$BLOCKED_REL"
MANIFEST="$PRODUCT_PROJ/.forge/sessions/$SESSION/forge.session.json"

prepare_product_project "$PRODUCT_PROJ" "Codex policy-check product E2E"
gen_hooks_config toml "PreToolUse=forge hook codex-policy-check" >"$PRODUCT_PROJ/.codex/config.toml"
cp "$PRODUCT_PROJ/.codex/config.toml" "$PROBE_CAPTURE_DIR/meta/product-config.toml"

guided_product_trust \
    "85" \
    "$PRODUCT_PROJ" \
    '[[hooks.PreToolUse]] command = "forge hook codex-policy-check"'

(
    cd "$PRODUCT_PROJ" &&
        run_forge session start "$SESSION" --no-launch --no-proxy
) >"$PROBE_CAPTURE_DIR/results/session-start.stdout.txt" 2>"$PROBE_CAPTURE_DIR/results/session-start.stderr.txt"
START_RC=$?
printf '%s\n' "$START_RC" >"$PROBE_CAPTURE_DIR/results/session-start.exit"
[ "$START_RC" -eq 0 ] || err "forge session start failed; see results/session-start.stderr.txt"

(
    cd "$PRODUCT_PROJ" &&
        run_forge policy enable --session "$SESSION" --bundle tdd --fail-mode open
) >"$PROBE_CAPTURE_DIR/results/policy-enable.stdout.txt" 2>"$PROBE_CAPTURE_DIR/results/policy-enable.stderr.txt"
POLICY_RC=$?
printf '%s\n' "$POLICY_RC" >"$PROBE_CAPTURE_DIR/results/policy-enable.exit"
[ "$POLICY_RC" -eq 0 ] || err "forge policy enable failed; see results/policy-enable.stderr.txt"

export FORGE_SESSION="$SESSION"
export FORGE_FORGE_ROOT="$PRODUCT_PROJ"

PROMPT="Use apply_patch to add a new file named $BLOCKED_REL containing exactly print('blocked by stage 85'). Do not create or edit any test files. After the tool result, reply DONE."
PROBE_EXEC_CWD="$PRODUCT_PROJ" run_exec 85-deny workspace-write "$PROMPT"

python3 - "$MANIFEST" "$BLOCKED_FILE" "$PROBE_CAPTURE_DIR/results/verdict.txt" "$BLOCKED_REL" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
blocked_file = Path(sys.argv[2])
verdict_path = Path(sys.argv[3])
blocked_rel = sys.argv[4]

data = json.loads(manifest.read_text(encoding="utf-8"))
confirmed = data.get("confirmed") or {}
policy = confirmed.get("policy") or {}
decisions = policy.get("decisions") or []
target = f"apply_patch:{blocked_rel}"
denies = [
    d
    for d in decisions
    if d.get("final_decision") == "deny" and d.get("context_summary") == target
]
confirmed_by = confirmed.get("confirmed_by")
file_exists = blocked_file.exists()

if denies and confirmed_by == "hook:codex-policy-check" and not file_exists:
    verdict = (
        "[POLICY-CHECK-E2E-PASS]: product codex-policy-check hook denied the "
        "apply_patch and Codex did not apply the blocked src file."
    )
    code = 0
elif not decisions:
    verdict = (
        "[POLICY-CHECK-E2E-INCONCLUSIVE]: no policy decisions were recorded. "
        "The product hook may not have fired/trusted, or Codex may not have attempted apply_patch."
    )
    code = 1
elif file_exists:
    verdict = (
        "[POLICY-CHECK-E2E-FAIL]: the blocked src file exists after the turn. "
        "Inspect Codex stream and manifest decisions."
    )
    code = 1
else:
    verdict = (
        "[POLICY-CHECK-E2E-INCONCLUSIVE]: policy decisions exist but the expected "
        "deny entry/confirmed_by pair was not recorded. Inspect the manifest."
    )
    code = 1

verdict_path.write_text(verdict + "\n", encoding="utf-8")
print(verdict)
raise SystemExit(code)
PY
RC=$?
note "VERDICT [85]: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$RC"
