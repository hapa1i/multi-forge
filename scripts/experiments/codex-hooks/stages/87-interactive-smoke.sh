#!/usr/bin/env bash
# Stage 87 -- Forge-managed interactive Codex behavioral smoke.
#
# Drives the real foreground TUI paths shipped in Phase 5. Several assertions are
# inherently operator-observed (hold instructions, live reattach memory, active
# gate while another TUI is open, and sandbox behavior), so this stage records
# explicit yes/no answers alongside manifest facts.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

fixture_init 87-interactive-smoke
fixture_require
probe_version_check
probe_auth
probe_forge_home
require_product_forge_hook_command
FORGE_BIN="$(command -v forge)"
export FORGE_BIN

if [ ! -t 0 ]; then
    err "stage 87 needs a TTY; it launches foreground Codex TUIs and asks operator questions."
fi

PARENT="s87-parent"
BARE="s87a-bare"
POSITIONAL="s87b-positional"
HOOKED="s87c-hook"
SANDBOXED="s87d-sandbox"
MAGIC="MAGIC-CTX-S87-3C41"
REATTACH_TOKEN="S87-REATTACH-PAPAYA"
PRODUCT_PROJ="$PROBE_CAPTURE_DIR/project"
TRANSCRIPT="$PRODUCT_PROJ/s87-parent.transcript.jsonl"
PARENT_MANIFEST="$PRODUCT_PROJ/.forge/sessions/$PARENT/forge.session.json"
ANSWERS="$PROBE_CAPTURE_DIR/results/operator-answers.txt"
: >"$ANSWERS"

operator_confirm() { # operator_confirm <key> <question>
    local key="${1:?key}" question="${2:?question}" reply
    printf '\n%s [y/N] ' "$question" >&2
    read -r reply
    case "$reply" in
    y | Y | yes | YES)
        printf '%s=yes\n' "$key" >>"$ANSWERS"
        return 0
        ;;
    *)
        printf '%s=no\n' "$key" >>"$ANSWERS"
        return 1
        ;;
    esac
}

run_interactive_step() { # run_interactive_step <label> <args...>
    local label="${1:?label}"
    shift
    printf 'cd %s && forge %s\n' "$PRODUCT_PROJ" "$*" >"$PROBE_CAPTURE_DIR/results/$label.command.txt"
    # The Codex TUI requires a real terminal on stdout/stderr. Do not redirect
    # these foreground launches; capture only the command and exit code.
    (
        cd "$PRODUCT_PROJ" &&
            run_forge "$@"
    )
    local rc=$?
    printf '%s\n' "$rc" >"$PROBE_CAPTURE_DIR/results/$label.exit"
    note "$label exit=$rc"
    return "$rc"
}

session_has_codex_thread() { # session_has_codex_thread <session-name>
    local session="${1:?session name}"
    python3 - "$PRODUCT_PROJ/.forge/sessions/$session/forge.session.json" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
if not manifest.exists():
    raise SystemExit(1)
data = json.loads(manifest.read_text(encoding="utf-8"))
codex = (data.get("confirmed") or {}).get("codex") or {}
raise SystemExit(0 if codex.get("thread_id") else 1)
PY
}

record_active_gate_result() {
    local exit_f="$PROBE_CAPTURE_DIR/results/active-gate.exit"
    local stdout_f="$PROBE_CAPTURE_DIR/results/active-gate.stdout.txt"
    local stderr_f="$PROBE_CAPTURE_DIR/results/active-gate.stderr.txt"
    local combined="$PROBE_CAPTURE_DIR/results/active-gate.combined.txt"
    cat "$stdout_f" "$stderr_f" >"$combined" 2>/dev/null || true
    if [ -f "$exit_f" ] &&
        [ "$(cat "$exit_f" 2>/dev/null)" != "0" ] &&
        grep -Eiq 'cannot reconnect|still be active|appears to still be active|live session' "$combined"; then
        printf 'active_gate_refused_second_tui=yes\n' >>"$ANSWERS"
        note "active gate refused the second TUI"
    else
        printf 'active_gate_refused_second_tui=no\n' >>"$ANSWERS"
        note "active gate was not confirmed; see results/active-gate.*"
    fi
}

prepare_product_project "$PRODUCT_PROJ" "Codex interactive product smoke"
gen_hooks_config toml "SessionStart=forge hook codex-session-start" >"$PRODUCT_PROJ/.codex/config.toml"
cp "$PRODUCT_PROJ/.codex/config.toml" "$PROBE_CAPTURE_DIR/meta/product-config.toml"

guided_product_trust \
    "87" \
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
    "Stage 87 interactive bridge payload. "
    + "This repeated context makes the positional and hook bridge bodies realistic in size. " * 120
    + f" The oracle token is {magic}. "
    + "The model should not edit files until the operator gives a follow-up instruction."
)
lines = [
    {
        "requestId": "s87-1",
        "timestamp": "2026-06-12T00:00:00Z",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "Plan the interactive Codex smoke."}],
        },
    },
    {
        "requestId": "s87-1",
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

cat <<EOI

  ================= STAGE 87A: bare interactive start =================
  The next command launches a foreground Codex TUI for session $BARE.

  In the TUI:
    1. Type a NORMAL MESSAGE, not a slash command:

       Remember this exact token for this conversation: $REATTACH_TOKEN

    2. Wait for an acknowledgement.
    3. /quit
  =====================================================================
EOI
run_interactive_step 87a-bare session start "$BARE" --runtime codex --sandbox read-only
operator_confirm "bare_token_planted" "Did the bare TUI acknowledge the reattach token?"
if ! session_has_codex_thread "$BARE"; then
    err "87A did not record a Codex thread_id. A slash command such as /status does not create a model turn; rerun 87 and send the normal token-memory message before /quit."
fi

cat <<EOI

  ================= STAGE 87A-R: live reattach =================
  The next command reattaches with 'forge session resume $BARE'.

  In the TUI:
    1. Ask what token you told it to remember.
    2. Confirm it answers: $REATTACH_TOKEN
    3. Before quitting, run this in ANOTHER terminal to pin the active gate:

       cd "$PRODUCT_PROJ" && CODEX_HOME="$CODEX_HOME" FORGE_HOME="$FORGE_HOME" "$FORGE_BIN" session resume "$BARE" >"$PROBE_CAPTURE_DIR/results/active-gate.stdout.txt" 2>"$PROBE_CAPTURE_DIR/results/active-gate.stderr.txt"; echo \$? >"$PROBE_CAPTURE_DIR/results/active-gate.exit"

    4. /quit
  =====================================================================
EOI
run_interactive_step 87a-reattach session resume "$BARE"
operator_confirm "reattach_memory_visible" "Did the reattached TUI recall $REATTACH_TOKEN?"
record_active_gate_result

# These status snapshots catch obvious edits, but the positional leg runs under
# read-only sandbox. The load-bearing oracle is the operator's first-turn
# observation: acknowledge context, wait, and use no tools.
git -C "$PRODUCT_PROJ" status --short >"$PROBE_CAPTURE_DIR/results/git-status.before-positional.txt"
cat <<EOI

  ================= STAGE 87B: positional bridge hold =================
  The next command launches an interactive bridge with transfer delivered as the
  positional initial prompt. That prompt starts a real model turn, so the hold
  instructions are load-bearing.

  In the TUI, observe the FIRST model turn before typing anything:
    - It should acknowledge the context and wait.
    - It should NOT run commands.
    - It should NOT edit files.
  Then /quit.
  =====================================================================
EOI
run_interactive_step 87b-positional session start "$POSITIONAL" --runtime codex --resume-from "$PARENT" --strategy full --sandbox read-only
git -C "$PRODUCT_PROJ" status --short >"$PROBE_CAPTURE_DIR/results/git-status.after-positional.txt"
operator_confirm "positional_hold_held" "Did the positional bridge hold instructions hold with no pre-input tools or edits?"

cat <<EOI

  ================= STAGE 87C: hook-delivered bridge =================
  The next command launches an interactive bridge with --context-delivery hook.
  The SessionStart hook should deliver context passively via additionalContext.

  In the TUI:
    1. Confirm there is no synthetic first turn from a positional prompt.
    2. Ask whether the context contains $MAGIC.
    3. Observe whether Codex visibly renders the SessionStart hook context
       block in the transcript.
    4. Confirm Codex can answer with that token.
    5. /quit
  =====================================================================
EOI
run_interactive_step 87c-hook session start "$HOOKED" --runtime codex --resume-from "$PARENT" --strategy full --sandbox read-only --context-delivery hook
operator_confirm "hook_delivery_context_visible" "Did the hook-delivered TUI see $MAGIC without a synthetic positional first turn?"
operator_confirm "hook_delivery_context_rendered" "Did the TUI visibly print the SessionStart hook context/additionalContext block?"

SANDBOX_FILE="$PRODUCT_PROJ/sandbox_should_not_exist.txt"
rm -f "$SANDBOX_FILE"
cat <<EOI

  ================= STAGE 87D: read-only sandbox behavior =================
  The next command launches a bare read-only-sandbox TUI for session $SANDBOXED.

  In the TUI:
    1. Ask Codex to create sandbox_should_not_exist.txt in the project root.
    2. If it asks for write approval, decline it.
    3. Confirm the runtime refuses or cannot write because the sandbox is read-only.
    4. /quit
  =====================================================================
EOI
run_interactive_step 87d-sandbox session start "$SANDBOXED" --runtime codex --sandbox read-only
if [ -e "$SANDBOX_FILE" ]; then
    printf 'sandbox_file_absent=no\n' >>"$ANSWERS"
else
    printf 'sandbox_file_absent=yes\n' >>"$ANSWERS"
fi
operator_confirm "sandbox_refused_write" "Did the TUI visibly honor read-only sandbox behavior?"

python3 - "$PRODUCT_PROJ" "$ANSWERS" "$PROBE_CAPTURE_DIR/results/verdict.txt" "$BARE" "$POSITIONAL" "$HOOKED" "$SANDBOXED" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

project = Path(sys.argv[1])
answers_path = Path(sys.argv[2])
verdict_path = Path(sys.argv[3])
sessions = sys.argv[4:]

answers: dict[str, str] = {}
for line in answers_path.read_text(encoding="utf-8").splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        answers[k] = v

def codex(session: str) -> dict:
    manifest = project / ".forge" / "sessions" / session / "forge.session.json"
    if not manifest.exists():
        return {}
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return ((data.get("confirmed") or {}).get("codex") or {})

bare, positional, hooked, sandboxed = (codex(s) for s in sessions)
facts = {
    "bare_thread": bool(bare.get("thread_id")),
    "bare_no_delivery": bare.get("context_delivery") is None,
    "positional_thread": bool(positional.get("thread_id")),
    "positional_delivery": positional.get("context_delivery") == "initial_message",
    "hook_thread": bool(hooked.get("thread_id")),
    "hook_delivery": hooked.get("context_delivery") == "session_start_hook",
    "sandbox_thread": bool(sandboxed.get("thread_id")),
}
required_answers = [
    "bare_token_planted",
    "reattach_memory_visible",
    "active_gate_refused_second_tui",
    "positional_hold_held",
    "hook_delivery_context_visible",
    "sandbox_file_absent",
    "sandbox_refused_write",
]
answers_ok = all(answers.get(k) == "yes" for k in required_answers)
facts_ok = all(facts.values())
observations = {
    "hook_context_rendered_in_tui": answers.get("hook_delivery_context_rendered", "unknown"),
}
observation_text = "\n".join(f"{key}={value}" for key, value in observations.items()) + "\n"
(verdict_path.parent / "observations.txt").write_text(observation_text, encoding="utf-8")

non_sandbox_required = [
    "bare_token_planted",
    "reattach_memory_visible",
    "active_gate_refused_second_tui",
    "positional_hold_held",
    "hook_delivery_context_visible",
]
non_sandbox_answers_ok = all(answers.get(k) == "yes" for k in non_sandbox_required)
sandbox_file_absent = answers.get("sandbox_file_absent") == "yes"
sandbox_refused = answers.get("sandbox_refused_write") == "yes"

if answers_ok and facts_ok:
    verdict = (
        "[INTERACTIVE-SMOKE-PASS]: bare start, live reattach, active gate, "
        "positional hold behavior, hook delivery, and read-only sandbox behavior "
        "were all operator-confirmed with matching manifest facts."
    )
    code = 0
elif facts_ok and non_sandbox_answers_ok and not sandbox_file_absent:
    verdict = (
        "[INTERACTIVE-SMOKE-SANDBOX-FAIL]: bare start, live reattach, active gate, "
        "positional hold behavior, and hook delivery passed, but the read-only "
        f"sandbox write landed. answers={answers} facts={facts}"
    )
    code = 1
elif facts_ok and non_sandbox_answers_ok and not sandbox_refused:
    verdict = (
        "[INTERACTIVE-SMOKE-SANDBOX-INCONCLUSIVE]: main interactive checks passed, "
        f"but the sandbox refusal was not operator-confirmed. answers={answers} facts={facts}"
    )
    code = 1
else:
    verdict = (
        "[INTERACTIVE-SMOKE-INCOMPLETE]: one or more operator confirmations or "
        f"manifest facts failed. answers={answers} facts={facts}"
    )
    code = 1

verdict_path.write_text(verdict + "\n", encoding="utf-8")
print(verdict)
raise SystemExit(code)
PY
RC=$?
note "VERDICT [87]: $(cat "$PROBE_CAPTURE_DIR/results/verdict.txt")"
exit "$RC"
