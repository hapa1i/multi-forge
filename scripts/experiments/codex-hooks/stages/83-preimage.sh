#!/usr/bin/env bash
# Stage 83 -- trusted_hash preimage + programmatic pre-enrollment (mostly offline;
# 1-2 validation turns if the hash is computable). Requires the stage-80 fixture.
#
#   83.1  offline: hash-preimage.py reverse-engineers the trusted_hash algorithm
#         from the LIVE fixture's harvested (registration -> hash) pairs.
#   83.2  decisive empirical test (only if 83.1 found the algorithm): in a FRESH
#         throwaway home, write a registration + a FORGED [hooks.state] record +
#         project trust_level, run one headless turn -> if the hook fires with NO
#         ceremony, programmatic pre-enrollment is proven end-to-end.
#   83.3  necessity control: remove the trust_level record, re-run -> answers from
#         the other side whether project trust is *necessary* alongside enrollment
#         (the stage-82 confound).
#
# Outcome feeds the pre-enrollment posture Open Decision: computable -> the
# installer MAY write [hooks.state] (explicit, documented; precedent: Forge writes
# Claude's settings.json with consent); not computable -> guided one-time ceremony.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

fixture_init 83-preimage
fixture_require
probe_version_check

PREIMAGE="$LIB_DIR/hooks/hash-preimage.py"
REPORT="$PROBE_CAPTURE_DIR/meta/preimage-report.txt"

# Round-2 reference vector (registration not captured -> untestable, printed only).
KNOWN=""
R2="$CAPTURE_ROOT/40-trust/meta/config-after-40c.toml"
[ -f "$R2" ] && KNOWN="$(grep -oE 'sha256:[0-9a-f]+' "$R2" 2>/dev/null | head -1)"

# ---- 83.1: offline preimage scan over the LIVE fixture configs ----------------
note "scanning candidate preimages (report -> meta/preimage-report.txt)"
python3 "$PREIMAGE" \
    --user-config "$CODEX_HOME/config.toml" \
    --project-config "$PROJ/.codex/config.toml" \
    ${KNOWN:+--known-hash "$KNOWN"} >"$REPORT" 2>&1
PRE_RC=$?
cat "$REPORT"

if [ "$PRE_RC" -ne 0 ] || ! grep -q '^PREIMAGE FOUND' "$REPORT"; then
    note "VERDICT [83]: PREIMAGE-NOT-COMPUTABLE -> posture = GUIDED one-time ceremony (not a failure)."
    note "Optional next step: source-dive openai/codex (Rust hooks/trust hashing) at $CODEX_VERSION, add a CANDIDATES entry to hash-preimage.py, re-run stage 83."
    exit 0
fi
note "preimage computable -- proceeding to the empirical pre-enrollment test."

# ---- 83.2: decisive empirical test (fresh home, FORGED trust record) ----------
probe_auth # populates the fixture home's auth.json (source for the throwaway copy)
EMP_ROOT="$(mktemp -d)" || err "mktemp -d failed."
# Replace fixture_init's auth-only trap: also remove the throwaway tree. Expand now.
# shellcheck disable=SC2064
trap "rm -f '$CODEX_HOME/auth.json'; rm -rf '$EMP_ROOT'" EXIT

EMP_HOME="$EMP_ROOT/codex-home"
EMP_PROJ="$EMP_ROOT/proj"
EMP_BIN="$EMP_ROOT/hookbin"
mkdir -p "$EMP_HOME" "$EMP_BIN" "$EMP_PROJ/.codex"
chmod 700 "$EMP_HOME"
(cd "$EMP_PROJ" &&
    git init -q &&
    git config user.email probe@example.invalid &&
    git config user.name probe &&
    echo "# empirical" >README.md &&
    git add README.md &&
    git commit -qm init) || err "empirical project git init failed."

# Throwaway wrapper tees to THIS stage's capture dir (label 83-empirical).
EMP_WRAP="$EMP_BIN/Empirical.sh"
{
    echo '#!/usr/bin/env bash'
    echo "export PROBE_CAPTURE_DIR='$PROBE_CAPTURE_DIR'"
    echo "exec '$LIB_DIR/hooks/tee-hook.sh' '83-empirical'"
} >"$EMP_WRAP"
chmod +x "$EMP_WRAP"

# Project-level registration (mirrors the fixture's primary SessionStart shape).
gen_hooks_config toml "SessionStart=$EMP_WRAP" >"$EMP_PROJ/.codex/config.toml"
EMP_PROJ_CFG_ABS="$(cd "$EMP_PROJ/.codex" && pwd -P)/config.toml"
EMP_PROJ_ABS="$(cd "$EMP_PROJ" && pwd -P)"

# Forge the [hooks.state] record for this registration via the discovered algorithm.
STATE_BLOCK="$(python3 "$PREIMAGE" \
    --user-config "$CODEX_HOME/config.toml" \
    --project-config "$PROJ/.codex/config.toml" \
    --emit-state --state-config-path "$EMP_PROJ_CFG_ABS" \
    --state-command "$EMP_WRAP" --state-event SessionStart \
    2>"$PROBE_CAPTURE_DIR/meta/emit-state.err")" || err "hash-preimage.py --emit-state failed (see meta/emit-state.err)."

# User config: forged trust record + project trust_level (the two-record state the
# ceremony actually leaves behind).
write_user_config() { # write_user_config <include-trust-level: 1|0>
    {
        printf '%s\n' "$STATE_BLOCK"
        if [ "$1" = "1" ]; then
            echo "[projects.\"$EMP_PROJ_ABS\"]"
            echo 'trust_level = "trusted"'
        fi
    } >"$EMP_HOME/config.toml"
}
install -m 600 "$CODEX_HOME/auth.json" "$EMP_HOME/auth.json" || err "empirical auth copy failed."

write_user_config 1
cp "$EMP_PROJ/.codex/config.toml" "$PROBE_CAPTURE_DIR/meta/empirical-project-config.toml"
cp "$EMP_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/empirical-user-config.with-trustlevel.toml"
CODEX_HOME="$EMP_HOME" PROBE_EXEC_CWD="$EMP_PROJ" run_exec 83-empirical read-only 'reply with the single word OK'
EMP_FIRED="$(find "$PROBE_CAPTURE_DIR/payloads" -name '83-empirical-*.stdin.json' 2>/dev/null | wc -l | tr -d ' ')"
if [ "$EMP_FIRED" -ge 1 ]; then
    note "83.2: PROGRAMMATIC PRE-ENROLLMENT PROVEN -- the forged hook fired with NO ceremony (fired=$EMP_FIRED)."
else
    note "83.2: forged record did NOT fire (fired=$EMP_FIRED) -- preimage may be wrong despite matching, OR enrollment needs more than [hooks.state]+trust_level. Inspect results/83-empirical.stderr.txt."
fi

# ---- 83.3: necessity control -- drop trust_level, keep the forged record ------
write_user_config 0
cp "$EMP_HOME/config.toml" "$PROBE_CAPTURE_DIR/meta/empirical-user-config.no-trustlevel.toml"
CODEX_HOME="$EMP_HOME" PROBE_EXEC_CWD="$EMP_PROJ" run_exec 83-empirical-no-trustlevel read-only 'reply with the single word OK'
EMP2_FIRED="$(find "$PROBE_CAPTURE_DIR/payloads" -name '83-empirical-*.stdin.json' 2>/dev/null | wc -l | tr -d ' ')"
DELTA=$((EMP2_FIRED - EMP_FIRED))
if [ "$DELTA" -ge 1 ]; then
    note "83.3: still fired WITHOUT trust_level (delta=$DELTA) -- project trust_level is NOT necessary; the forged [hooks.state] suffices."
else
    note "83.3: did NOT fire without trust_level (delta=$DELTA) -- project trust_level IS necessary alongside enrollment."
fi

{
    echo "preimage_found=yes"
    echo "empirical_fired_with_trustlevel=$EMP_FIRED"
    echo "empirical_fired_without_trustlevel_delta=$DELTA"
} >"$PROBE_CAPTURE_DIR/results/preimage-verdict.txt"
note "VERDICT [83]: PREIMAGE-COMPUTABLE + empirical pre-enrollment $([ "$EMP_FIRED" -ge 1 ] && echo PROVEN || echo UNCONFIRMED). -> posture decision input recorded (results/preimage-verdict.txt)."
