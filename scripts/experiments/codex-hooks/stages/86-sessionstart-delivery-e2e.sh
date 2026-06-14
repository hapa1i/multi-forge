#!/usr/bin/env bash
# Stage 86 -- enrolled product `forge hook codex-session-start` delivery E2E.
#
# Registers the real product SessionStart hook command, trusts it, then runs the
# shipped one-command bridge with `--context-delivery hook`. The parent transcript
# is synthetic but realistic-sized and uses `--strategy full`, so this probes the
# real staging -> additionalContext -> receipt -> confirmed.codex reconciliation
# loop without depending on a curation LLM call.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

fixture_init 86-sessionstart-delivery-e2e
fixture_require
probe_version_check
probe_auth
probe_forge_home
require_product_forge_hook_command

PARENT="s86-parent"
CHILD="s86-child"
MAGIC="MAGIC-CTX-S86-7B6D"
PRODUCT_PROJ="$PROBE_CAPTURE_DIR/project"
TRANSCRIPT="$PRODUCT_PROJ/s86-parent.transcript.jsonl"
PARENT_MANIFEST="$PRODUCT_PROJ/.forge/sessions/$PARENT/forge.session.json"
CHILD_MANIFEST="$PRODUCT_PROJ/.forge/sessions/$CHILD/forge.session.json"
CHILD_TRANSFER="$PRODUCT_PROJ/.forge/prev_sessions/$PARENT/children/$CHILD.md"

prepare_product_project "$PRODUCT_PROJ" "Codex SessionStart delivery product E2E"
gen_hooks_config toml "SessionStart=forge hook codex-session-start" >"$PRODUCT_PROJ/.codex/config.toml"
cp "$PRODUCT_PROJ/.codex/config.toml" "$PROBE_CAPTURE_DIR/meta/product-config.toml"

guided_product_trust \
    "86" \
    "$PRODUCT_PROJ" \
    '[[hooks.SessionStart]] command = "forge hook codex-session-start"'

(
    cd "$PRODUCT_PROJ" &&
        run_forge session start "$PARENT" --no-launch --no-proxy
) >"$PROBE_CAPTURE_DIR/results/parent-start.stdout.txt" 2>"$PROBE_CAPTURE_DIR/results/parent-start.stderr.txt"
PARENT_RC=$?
printf '%s\n' "$PARENT_RC" >"$PROBE_CAPTURE_DIR/results/parent-start.exit"
[ "$PARENT_RC" -eq 0 ] || err "parent session start failed; see results/parent-start.stderr.txt"

python3 - "$TRANSCRIPT" "$PARENT_MANIFEST" "$MAGIC" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

transcript = Path(sys.argv[1])
manifest = Path(sys.argv[2])
magic = sys.argv[3]

large_context = (
    "Stage 86 realistic transfer payload. "
    + "This sentence intentionally repeats to push the transfer body beyond several kilobytes. " * 120
    + f" The delivery oracle token is {magic}. "
    + "The child should echo only the oracle token when asked."
)
lines = [
    {
        "requestId": "s86-1",
        "timestamp": "2026-06-12T00:00:00Z",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "Plan a Codex hook-delivery probe."}],
        },
    },
    {
        "requestId": "s86-1",
        "timestamp": "2026-06-12T00:00:01Z",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": large_context}],
        },
    },
]
transcript.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

data = json.loads(manifest.read_text(encoding="utf-8"))
data.setdefault("confirmed", {})["transcript_path"] = str(transcript)
manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

TASK="If your session context contains the token $MAGIC, reply with exactly $MAGIC and no other text. If not, reply NONE. Do not edit files or run commands."
(
    cd "$PRODUCT_PROJ" &&
        run_forge session start "$CHILD" \
            --runtime codex \
            --resume-from "$PARENT" \
            --task "$TASK" \
            --strategy full \
            --sandbox read-only \
            --context-delivery hook
) >"$PROBE_CAPTURE_DIR/results/codex-start.stdout.txt" 2>"$PROBE_CAPTURE_DIR/results/codex-start.stderr.txt"
START_RC=$?
printf '%s\n' "$START_RC" >"$PROBE_CAPTURE_DIR/results/codex-start.exit"

python3 - "$CHILD_MANIFEST" "$CHILD_TRANSFER" "$PROBE_CAPTURE_DIR/results/codex-start.stdout.txt" "$PROBE_CAPTURE_DIR/results/codex-start.stderr.txt" "$MAGIC" "$START_RC" "$PROBE_CAPTURE_DIR/results/verdict.txt" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
transfer = Path(sys.argv[2])
stdout = Path(sys.argv[3]).read_text(encoding="utf-8", errors="replace")
stderr = Path(sys.argv[4]).read_text(encoding="utf-8", errors="replace")
magic = sys.argv[5]
start_rc = int(sys.argv[6])
verdict_path = Path(sys.argv[7])

data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
codex = ((data.get("confirmed") or {}).get("codex") or {})
delivery = codex.get("context_delivery")
rollout_source = codex.get("rollout_source")
thread_id = codex.get("thread_id")
transfer_size = transfer.stat().st_size if transfer.exists() else 0
echoed = magic in (stdout + "\n" + stderr)

if (
    start_rc == 0
    and echoed
    and delivery == "session_start_hook"
    and rollout_source == "session_start_hook"
    and thread_id
    and transfer_size >= 4096
):
    verdict = (
        "[SESSIONSTART-DELIVERY-E2E-PASS]: product codex-session-start delivered "
        f"a {transfer_size}-byte transfer via additionalContext; model echoed the token; "
        "confirmed.codex records session_start_hook."
    )
    code = 0
elif delivery == "hook_undelivered":
    verdict = (
        "[SESSIONSTART-DELIVERY-E2E-FAIL]: hook mode ran but no delivery receipt was "
        "reconciled (context_delivery=hook_undelivered). Inspect trust/enrollment and stderr."
    )
    code = 1
else:
    verdict = (
        "[SESSIONSTART-DELIVERY-E2E-INCONCLUSIVE]: expected echo/manifest facts were not "
        f"all present (rc={start_rc}, echoed={echoed}, delivery={delivery!r}, "
        f"rollout_source={rollout_source!r}, thread_id={bool(thread_id)}, "
        f"transfer_size={transfer_size})."
    )
    code = 1

verdict_path.write_text(verdict + "\n", encoding="utf-8")
print(verdict)
raise SystemExit(code)
PY
RC=$?
note "VERDICT [86]: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$RC"
