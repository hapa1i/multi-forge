#!/usr/bin/env bash
# Native-resume cross-CWD relocation experiment.
#
# Hypothesis: Claude Code finds a `--resume` target only in the CWD-encoded
# project dir (~/.claude/projects/<encoded-cwd>/<uuid>.jsonl). The 2026-04-02
# negative result (Claude Code 2.1.90: cross-CWD --resume fails "No conversation
# found"; see ../../../src/forge/cli/session_fork.py and docs/design.md 3.9) only
# tried resuming from a foreign CWD -- it never RELOCATED the JSONL. This script
# tests whether COPYING the parent JSONL into the child CWD's encoded dir makes
# the session resumable across the boundary, and whether the tool-use
# continuation survives signed-thinking revalidation.
#
# Runs entirely under an isolated, disposable HOME so it never reads or writes
# the real ~/.claude store. Requires ANTHROPIC_API_KEY and Claude Code >= 2.1.90.
#
# Verdicts:
#   [PASS]           child resumed the relocated JSONL and completed a tool turn (signed block present)
#   [INCONCLUSIVE]   resumed, but the parent had no signed thinking block to revalidate
#   [DISCOVERY-FAIL] Claude could not find the relocated JSONL ("No conversation found")
#   [SIGNATURE-FAIL] found, but the continuation was rejected (signature/thinking)
#   [UNCATEGORIZED]  some other non-zero failure (see full output)
#
# NOTE: deliberately NOT `set -e` -- the control step is EXPECTED to fail, so
# errexit would abort the experiment before it runs.
set -uo pipefail

MIN_VERSION="2.1.90"
MODEL="${FORGE_RELOCATE_MODEL:-claude-opus-4-6}"

err() {
    echo "ERROR: $*" >&2
    exit 1
}

sha256() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        sha256sum "$1" | awk '{print $1}'
    fi
}

# ---- preconditions ---------------------------------------------------------
[ -n "${ANTHROPIC_API_KEY:-}" ] || err "ANTHROPIC_API_KEY is not set."
command -v claude >/dev/null 2>&1 || err "claude is not on PATH."

VERSION="$(claude --version 2>/dev/null | awk '{print $1}')"
[ -n "$VERSION" ] || err "could not parse 'claude --version'."
# Portable version >= compare (POSIX awk; avoids GNU-only `sort -V`, absent on BSD/macOS).
if ! awk -v v="$VERSION" -v m="$MIN_VERSION" 'BEGIN {
    split(v, a, "."); split(m, b, ".");
    for (i = 1; i <= 3; i++) { ai = a[i] + 0; bi = b[i] + 0;
        if (ai > bi) exit 0; if (ai < bi) exit 1 }
    exit 0 }'; then
    err "Claude Code $VERSION < required $MIN_VERSION (the version that governs the result)."
fi
echo "Claude Code version: $VERSION (>= $MIN_VERSION) OK"

# ---- isolated, disposable HOME ---------------------------------------------
_RUN_HOME="$(mktemp -d)" || err "mktemp -d failed."
export HOME="$_RUN_HOME"
trap 'rm -rf "$_RUN_HOME"' EXIT
mkdir -p "$HOME/.claude/projects"
printf '{}\n' >"$HOME/.claude.json"
echo "Isolated HOME: $HOME"

# Same-model pin + extended thinking so the parent transcript carries a SIGNED
# thinking block -- the thing cross-CWD resume must revalidate. Tier is derived
# from the model so ANTHROPIC_MODEL is the tier name Claude Code expects.
case "$MODEL" in
*opus*) TIER=opus ;;
*sonnet*) TIER=sonnet ;;
*haiku*) TIER=haiku ;;
*) TIER=opus ;;
esac
DEFAULT_ENV="ANTHROPIC_DEFAULT_$(printf '%s' "$TIER" | tr '[:lower:]' '[:upper:]')_MODEL"
export ANTHROPIC_MODEL="$TIER"
export "$DEFAULT_ENV=$MODEL"
export MAX_THINKING_TOKENS="${MAX_THINKING_TOKENS:-2048}"
echo "Model pin: ANTHROPIC_MODEL=$TIER  $DEFAULT_ENV=$MODEL  MAX_THINKING_TOKENS=$MAX_THINKING_TOKENS"

# ---- project dirs + encoded-dir helper -------------------------------------
DIR_A="$HOME/proj_a"
DIR_B="$HOME/proj_b"
mkdir -p "$DIR_A" "$DIR_B"
echo "PARENT_MARKER" >"$DIR_A/PARENT_FIXTURE.txt"
echo "CHILD_MARKER" >"$DIR_B/CHILD_FIXTURE.txt"

# Match encode_project_path(): resolve symlinks (pwd -P), then '/', '.', '_' -> '-'.
enc() { (cd "$1" && pwd -P | tr '/._' '-'); }
ENC_A="$(enc "$DIR_A")"
ENC_B="$(enc "$DIR_B")"
UUID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
# No --dangerously-skip-permissions: Claude rejects it under root, and read-only
# tools (Read) run in --print without it (matches the Docker contract posture).

# ---- parent run ------------------------------------------------------------
echo
echo "== Parent run in $DIR_A (uuid=$UUID) =="
(cd "$DIR_A" && claude --print --session-id "$UUID" \
    "Think step by step about which tool reads a file, then use the Read tool to read $DIR_A/PARENT_FIXTURE.txt and reply with exactly ACKNOWLEDGED.") \
    >"$HOME/parent.out" 2>"$HOME/parent.err"
PARENT_JSONL="$HOME/.claude/projects/$ENC_A/$UUID.jsonl"
[ -f "$PARENT_JSONL" ] || err "parent transcript not found at $PARENT_JSONL (parent run failed). See $HOME/parent.err"
if grep -q '"signature"' "$PARENT_JSONL"; then
    HAS_SIGNATURE=yes
    echo "parent transcript carries a signed thinking block: yes"
else
    HAS_SIGNATURE=no
    echo "WARNING: parent transcript has NO 'signature' -- result is INCONCLUSIVE for signature validation."
fi

run_child() { # combined stdout+stderr -> $HOME/child.out; echoes the exit code
    (cd "$DIR_B" && claude --print --resume "$UUID" --fork-session \
        "Use the Read tool to read $DIR_B/CHILD_FIXTURE.txt and reply with exactly CONTINUED.") \
        >"$HOME/child.out" 2>&1
    echo $?
}

# ---- control: resume from B WITHOUT relocating -----------------------------
echo
echo "== CONTROL: resume from $DIR_B WITHOUT relocating =="
CTRL_RC="$(run_child)"
echo "control exit=$CTRL_RC"
if grep -qi 'no conversation found' "$HOME/child.out"; then
    echo "control: reproduced 'No conversation found' (expected)"
else
    echo "control: did NOT reproduce the discovery failure (note this)"
fi

# ---- experiment: relocate A->B, then resume --------------------------------
echo
echo "== EXPERIMENT: relocate JSONL A->B, then resume =="
mkdir -p "$HOME/.claude/projects/$ENC_B"
RELOC_JSONL="$HOME/.claude/projects/$ENC_B/$UUID.jsonl"
cp "$PARENT_JSONL" "$RELOC_JSONL"
SHA_BEFORE="$(sha256 "$RELOC_JSONL")"
EXP_RC="$(run_child)"
SHA_AFTER="$(sha256 "$RELOC_JSONL")"
echo "experiment exit=$EXP_RC"

OUT="$(cat "$HOME/child.out")"
verdict="[UNCATEGORIZED]"
if [ "$EXP_RC" = "0" ]; then
    if [ "$HAS_SIGNATURE" = "yes" ]; then
        verdict="[PASS]"
    else
        # Resumed cleanly, but the parent had no signed block to revalidate --
        # the signature-survival hypothesis was never actually exercised.
        verdict="[INCONCLUSIVE]"
    fi
elif echo "$OUT" | grep -qi 'no conversation found'; then
    verdict="[DISCOVERY-FAIL]"
elif echo "$OUT" | grep -qiE 'signature|thinking|unmodified|invalid_request_error'; then
    verdict="[SIGNATURE-FAIL]"
fi

# --fork-session must not mutate the relocated parent copy.
if [ "$SHA_BEFORE" = "$SHA_AFTER" ]; then
    echo "relocated parent JSONL unchanged by resume: yes"
else
    echo "WARNING: relocated parent JSONL CHANGED during resume (product evidence)."
fi

echo
echo "================ VERDICT: $verdict  (Claude $VERSION) ================"
if [ "$verdict" != "[PASS]" ]; then
    echo "---- child output (tail) ----"
    echo "$OUT" | tail -n 30
fi
