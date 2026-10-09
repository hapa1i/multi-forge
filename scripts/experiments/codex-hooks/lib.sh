#!/usr/bin/env bash
# Shared library for the codex-hooks probe stages. Source from stages/*.sh.
#
# Environment contract:
#   PROBE_ROOT    disposable mktemp project and hookbin -- removed on EXIT
#   CAPTURE_ROOT  persistent capture dir OUTSIDE the repo (survives stages; rm -rf when done)
#   CODEX_HOME    independently logged-in persistent probe home (never ~/.codex)
#   PROJ          hermetic git-inited temp project inside PROBE_ROOT
#   PROBE_CAPTURE_DIR  stage-scoped capture dir (exported; hook scripts write here)
#
# Deliberately NOT `set -e`: several probes measure failure. Stages set -uo pipefail.

MIN_CODEX_VERSION="0.137.0"
PROBE_TURN_TIMEOUT="${PROBE_TURN_TIMEOUT:-240}"

err() {
    echo "ERROR: $*" >&2
    exit 1
}

note() { echo "[probe] $*"; }

# Portable version >= compare (mirrors scripts/experiments/native-resume/reproduce.sh).
version_ge() { # version_ge ACTUAL FLOOR -> exit 0 when ACTUAL >= FLOOR
    awk -v v="$1" -v m="$2" 'BEGIN {
        split(v, a, "."); split(m, b, ".");
        for (i = 1; i <= 3; i++) { ai = a[i] + 0; bi = b[i] + 0;
            if (ai > bi) exit 0; if (ai < bi) exit 1 }
        exit 0 }'
}

# A separate round owner must also sweep detached descendants (see probe-runtime.py).
with_timeout() {
    if command -v timeout >/dev/null 2>&1; then
        timeout --kill-after="${PROBE_KILL_GRACE:-5}s" "$PROBE_TURN_TIMEOUT" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then
        gtimeout --kill-after="${PROBE_KILL_GRACE:-5}s" "$PROBE_TURN_TIMEOUT" "$@"
    else
        err "GNU timeout/gtimeout is required; refusing an unbounded probe."
    fi
}

probe_home() {
    CODEX_HOME="${PROBE_CODEX_HOME:-$CAPTURE_ROOT/login/codex-home}"
    export CODEX_HOME
    python3 "$LIB_DIR/probe-home.py" "$CODEX_HOME" || err "unsafe Codex probe home"
}

prepare_capture() {
    if [ -d "$PROBE_CAPTURE_DIR" ]; then
        mkdir -p "$CAPTURE_ROOT/archive"
        local stamp
        stamp="$(python3 -c 'import time; print(time.time_ns())')"
        mv "$PROBE_CAPTURE_DIR" "$CAPTURE_ROOT/archive/$(basename "$PROBE_CAPTURE_DIR")-$stamp"
    fi
    mkdir -p "$PROBE_CAPTURE_DIR"/{payloads,results,streams,trees,meta,env,guards}
    if [ -n "${PROBE_CONTROL:-}" ]; then
        python3 - "$PROBE_CONTROL" "$PROBE_CAPTURE_DIR" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"capture": sys.argv[2], "mode": "observe", "reviewer": "fast"}))
PY
    fi
}

probe_init() { # probe_init <stage-name> [--persistent-home]
    local stage="${1:?stage name}"

    command -v codex >/dev/null 2>&1 || err "codex is not on PATH."
    command -v python3 >/dev/null 2>&1 || err "python3 is not on PATH."

    LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
    export LIB_DIR
    REPO_ROOT="$(cd "$LIB_DIR/../../.." && pwd -P)"
    export REPO_ROOT

    CAPTURE_ROOT="${CODEX_HOOKS_CAPTURE_DIR:-$HOME/.cache/forge-codex-hooks-probe}"
    export CAPTURE_ROOT
    PROBE_CAPTURE_DIR="$CAPTURE_ROOT/$stage"
    export PROBE_CAPTURE_DIR
    # Archive prior attempts so neither stale payloads nor lost failures affect results.
    prepare_capture

    PROBE_ROOT="$(mktemp -d)" || err "mktemp -d failed."
    export PROBE_ROOT
    # shellcheck disable=SC2064  # expand PROBE_ROOT now: the trap must remove THIS tree
    trap "rm -rf '$PROBE_ROOT'" EXIT

    # Credentials survive project teardown and refresh in one place. Callers run
    # baseline/config probes before enrollment, or use another independent login.
    probe_home

    PROJ="$PROBE_ROOT/proj"
    export PROJ
    mkdir -p "$PROJ"
    (cd "$PROJ" &&
        git init -q &&
        git config user.email probe@example.invalid &&
        git config user.name probe &&
        git config commit.gpgsign false &&
        echo "# probe project" >README.md &&
        git add README.md &&
        git commit -qm init) || err "temp project git init failed."

    HOOKBIN="$PROBE_ROOT/hookbin"
    export HOOKBIN
    mkdir -p "$HOOKBIN"

    note "stage=$stage PROBE_ROOT=$PROBE_ROOT"
    note "CODEX_HOME=$CODEX_HOME"
    note "captures -> $PROBE_CAPTURE_DIR"
}

probe_version_check() {
    local version
    version="$(codex --version 2>/dev/null | awk '/^codex-cli /{print $2}')"
    [ -n "$version" ] || err "could not parse 'codex --version' (expected 'codex-cli <ver>')."
    version_ge "$version" "$MIN_CODEX_VERSION" ||
        err "codex-cli $version < required $MIN_CODEX_VERSION."
    if [ "$version" != "$MIN_CODEX_VERSION" ]; then
        note "WARNING: codex-cli $version is newer than the $MIN_CODEX_VERSION research pin -- findings re-pin to $version"
    fi
    printf '%s\n' "$version" >"$PROBE_CAPTURE_DIR/meta/version.txt"
    CODEX_VERSION="$version"
    export CODEX_VERSION
    note "codex-cli $version OK (floor $MIN_CODEX_VERSION)"
}

# Never duplicate a refreshing login. The operator logs this persistent home in.
probe_auth() {
    if [ "${PROBE_USE_REAL_CODEX_HOME:-0}" = "1" ]; then
        err "PROBE_USE_REAL_CODEX_HOME is no longer supported; use an independent fixture login."
    fi
    python3 "$LIB_DIR/probe-home.py" "$CODEX_HOME" || err "unsafe Codex probe home"
    [ -f "$CODEX_HOME/auth.json" ] || err "Log in separately: CODEX_HOME='$CODEX_HOME' codex -c 'cli_auth_credentials_store=\"file\"' login"
    local status
    local status_rc=0
    status="$(codex login status 2>&1)" || status_rc=$?
    printf '%s\n' "$status" >"$PROBE_CAPTURE_DIR/meta/login-status.txt"
    if [ "$status_rc" -eq 0 ] && printf '%s' "$status" | grep -q '^Logged in using ChatGPT'; then
        note "isolated CODEX_HOME auth OK: $status"
    else
        err "codex does not report logged-in under the independent fixture home ('$status'). Stop; no auth fallback."
    fi
}

# make_hook_cmd <label> <handler-basename> [template-path] -> echoes wrapper path.
# A per-label wrapper script bakes the args in, so registration never depends on
# whether codex shell-splits the `command` string (itself an open question).
make_hook_cmd() {
    local label="${1:?label}" handler="${2:?handler}" template="${3:-}"
    local wrapper="$HOOKBIN/$label.sh"
    {
        echo '#!/usr/bin/env bash'
        echo "export PROBE_CAPTURE_DIR='$PROBE_CAPTURE_DIR'"
        if [ -n "$template" ]; then
            echo "exec '$LIB_DIR/hooks/$handler' '$label' '$template'"
        else
            echo "exec '$LIB_DIR/hooks/$handler' '$label'"
        fi
    } >"$wrapper"
    chmod +x "$wrapper"
    printf '%s\n' "$wrapper"
}

# gen_hooks_config <json|toml> HOOKSPEC... -> emits config text on stdout.
# HOOKSPEC := EVENT[:MATCHER]=COMMAND
gen_hooks_config() {
    local format="${1:?format}"
    shift
    python3 "$LIB_DIR/hooks/gen-config.py" --format "$format" "$@"
}

# run_exec <label> <sandbox> <prompt> [extra codex-exec args...]
# Runs one `codex exec --json` turn from $PROJ; captures stream/stderr/exit/last-message.
run_exec() {
    local label="${1:?label}" sandbox="${2:?sandbox}" prompt="${3:?prompt}"
    shift 3
    local stream="$PROBE_CAPTURE_DIR/streams/$label.jsonl"
    local stderr_f="$PROBE_CAPTURE_DIR/results/$label.stderr.txt"
    local lm="$PROBE_CAPTURE_DIR/results/$label.last-message.txt"
    local cwd="${PROBE_EXEC_CWD:-$PROJ}"
    note "turn [$label] sandbox=$sandbox cwd=$cwd"
    # </dev/null: the prompt is positional; an ambient pipe would otherwise be
    # read as an appended <stdin> block ("Reading additional input from stdin...").
    # PROBE_EXEC_CWD overrides the project dir for one turn (stage 82 runs from a
    # git worktree to test whether trust survives a changed project-config path).
    (cd "$cwd" && with_timeout codex exec --json --sandbox "$sandbox" -o "$lm" "$@" "$prompt" </dev/null) \
        >"$stream" 2>"$stderr_f"
    local rc=$?
    printf '%s\n' "$rc" >"$PROBE_CAPTURE_DIR/results/$label.exit"
    note "turn [$label] exit=$rc last-message=$(head -c 120 "$lm" 2>/dev/null || echo '<none>')"
    return "$rc"
}

# fired_labels -> lists hook labels that produced payload captures in this stage.
fired_labels() {
    find "$PROBE_CAPTURE_DIR/payloads" -name '*.stdin.json' 2>/dev/null |
        sed -E 's|.*/([^/]+)-[0-9]+\.stdin\.json|\1|' | sort -u
}

snapshot_tree() { # snapshot_tree <name> <dir>
    find "$2" -type f 2>/dev/null | sort >"$PROBE_CAPTURE_DIR/trees/$1.txt"
}

# Should hook turns add --dangerously-bypass-hook-trust? Auto mode reads stage
# 10's verdict; PROBE_BYPASS_TRUST=1/0 forces.
need_trust_bypass() {
    case "${PROBE_BYPASS_TRUST:-auto}" in
    1) return 0 ;;
    0) return 1 ;;
    esac
    grep -q 'TRUST-GATED' "$CAPTURE_ROOT/10-headless-fire/results/verdict.txt" 2>/dev/null
}

# =============================================================================
# Fixture mode (stages 80-83): a PERSISTENT enrolled CODEX_HOME + project +
# hookbin under $CAPTURE_ROOT/fixture, so ONE operator trust ceremony (stage 80)
# serves many headless probe turns (81-83). Round 2 settled that hooks fire
# headless once trust-enrolled but headless cannot self-enroll; this mode makes
# the enrolled state reusable.
#
# Contract vs probe_init:
#   - No mktemp tree, no EXIT-trap tree removal: the fixture survives across runs.
#   - Prior attempts are archived before creating a per-stage $PROBE_CAPTURE_DIR.
#   - The independent login lives outside fixture/project teardown and retains
#     refreshed auth across stages. It is never copied or restored from a seed.
#   - Registered hook COMMAND STRINGS (wrapper paths) are STABLE so the trust key
#     never changes; wrapper BODIES are rewritten per stage (make_hook_cmd bakes
#     the stage's PROBE_CAPTURE_DIR -- a stale body silently misattributes
#     captures). 40d proved trust survives a body change; stage 81 re-validates it.
# =============================================================================

# Codex events registered in the fixture, mapped to STABLE wrapper keys (the
# wrapper file stem, also the default capture label). PreToolUse appears twice
# (plain + matcher) to exercise the matcher-idx trust-key dimension; SessionStart
# appears three times (primary project, a Sacrificial entry reserved for stage
# 82's 40e registration-string mutation, and a UserSessionStart entry for the
# user-vs-project trust-location question).
FIXTURE_WRAPPER_KEYS="SessionStart SubagentStart PreToolUse PreToolUseMatched PermissionRequest PostToolUse PreCompact PostCompact UserPromptSubmit SubagentStop Stop Sacrificial UserSessionStart"

fixture_init() { # fixture_init <stage-name>  -- shared setup for stages 80-83
    local stage="${1:?stage name}"
    command -v codex >/dev/null 2>&1 || err "codex is not on PATH."
    command -v python3 >/dev/null 2>&1 || err "python3 is not on PATH."

    LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
    export LIB_DIR
    REPO_ROOT="$(cd "$LIB_DIR/../../.." && pwd -P)"
    export REPO_ROOT

    CAPTURE_ROOT="${CODEX_HOOKS_CAPTURE_DIR:-$HOME/.cache/forge-codex-hooks-probe}"
    export CAPTURE_ROOT
    PROBE_CAPTURE_DIR="$CAPTURE_ROOT/$stage"
    export PROBE_CAPTURE_DIR
    prepare_capture

    FIXTURE_ROOT="$CAPTURE_ROOT/fixture"
    export FIXTURE_ROOT
    PROJ="$FIXTURE_ROOT/proj"
    HOOKBIN="$FIXTURE_ROOT/hookbin"
    export PROJ HOOKBIN
    probe_home

    note "stage=$stage (fixture mode)"
    note "FIXTURE_ROOT=$FIXTURE_ROOT"
    note "CODEX_HOME=$CODEX_HOME captures -> $PROBE_CAPTURE_DIR"
}

probe_forge_home() {
    FORGE_HOME="${PROBE_FORGE_HOME:-$PROBE_CAPTURE_DIR/forge-home}"
    export FORGE_HOME
    mkdir -p "$FORGE_HOME"
    chmod 700 "$FORGE_HOME"
    note "FORGE_HOME=$FORGE_HOME"
}

run_forge() {
    if command -v forge >/dev/null 2>&1; then
        forge "$@"
        return $?
    fi
    if command -v uv >/dev/null 2>&1 && [ -f "$REPO_ROOT/pyproject.toml" ]; then
        uv run --project "$REPO_ROOT" forge "$@"
        return $?
    fi
    err "forge is not on PATH and uv run forge is unavailable from $REPO_ROOT."
}

require_product_forge_hook_command() {
    command -v forge >/dev/null 2>&1 ||
        err "product-hook stages register command=\"forge hook ...\" in Codex config, so 'forge' must be on PATH. Run ./scripts/setup.sh --local or otherwise install Forge before this probe."
}

prepare_product_project() { # prepare_product_project <path> <title>
    local dir="${1:?project path}" title="${2:-Codex product probe project}"
    rm -rf "$dir"
    mkdir -p "$dir"/{.forge,.claude,.codex,src,tests}
    (
        cd "$dir" &&
            git init -q &&
            git config user.email probe@example.invalid &&
            git config user.name probe &&
            git config commit.gpgsign false &&
            printf '# %s\n' "$title" >README.md &&
            git add README.md &&
            git commit -qm init
    ) || err "product project git init failed: $dir"
}

guided_product_trust() { # guided_product_trust <stage> <project-path> <hook-summary>
    local stage="${1:?stage}" project="${2:?project}" hook_summary="${3:?hook summary}"
    if [ ! -t 0 ]; then
        err "stage $stage needs a TTY for the product-hook trust ceremony."
    fi
    local project_real
    project_real="$(cd "$project" && pwd -P)"
    cat <<EOI

  ================= OPERATOR STEP ($stage -- product hook trust) =================
  This stage registered:

    $hook_summary

  In ANOTHER terminal, run EXACTLY:

    cd "$project_real" && FORGE_DEV="$REPO_ROOT" CODEX_HOME="$CODEX_HOME" FORGE_HOME="$FORGE_HOME" "$(command -v codex)"

  In the TUI:
    1. Accept project/folder trust if shown.
    2. Accept the hook trust prompt(s) for the product Forge hook command(s).
    3. /quit

  If no trust prompt appears, the stable project path may already be enrolled; /quit.
  Then press ENTER here. (Type 's' + ENTER to skip -- the stage will stop.)
  ===============================================================================
EOI
    local reply
    read -r reply
    if [ "${reply:-}" = "s" ]; then
        err "operator skipped the $stage trust ceremony."
    fi
}

# Stage 80 rebuilds projects and hook registrations, preserving its independent login.
fixture_build() {
    [ -n "${FIXTURE_ROOT:-}" ] || err "fixture_build: call fixture_init first."
    case "$CODEX_HOME/" in "$FIXTURE_ROOT/"*) err "login home must be outside fixture teardown" ;; esac
    rm -rf "$FIXTURE_ROOT"
    mkdir -p "$CODEX_HOME" "$HOOKBIN"
    chmod 700 "$CODEX_HOME"
    printf 'cli_auth_credentials_store = "file"\n[features]\nhooks = true\n' >"$CODEX_HOME/config.toml"
    mkdir -p "$PROJ"
    (cd "$PROJ" &&
        git init -q &&
        git config user.email probe@example.invalid &&
        git config user.name probe &&
        git config commit.gpgsign false &&
        echo "# probe fixture project" >README.md &&
        git add README.md &&
        git commit -qm init) || err "fixture project git init failed."
    note "fixture built: $FIXTURE_ROOT"
}

# fixture_mark_enrolled <summary...> -- write the enrollment sentinel (stage 80).
fixture_mark_enrolled() {
    {
        echo "enrolled_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo "codex_version=${CODEX_VERSION:-unknown}"
        echo "$*"
    } >"$FIXTURE_ROOT/ENROLLED"
}

# fixture_require -- (stages 81-83) refuse to run without an enrolled fixture.
fixture_require() {
    [ -n "${FIXTURE_ROOT:-}" ] || err "fixture_require: call fixture_init first."
    if [ ! -f "$FIXTURE_ROOT/ENROLLED" ] || [ ! -f "$CODEX_HOME/config.toml" ]; then
        err "no enrolled fixture at $FIXTURE_ROOT -- run stage 80 (operator trust ceremony) first."
    fi
    note "fixture present: $(tr '\n' ' ' <"$FIXTURE_ROOT/ENROLLED")"
}

# _fixture_write_wrapper <wrapper-key> <handler> <capture-label> [template]
# Rewrites the STABLE wrapper $HOOKBIN/<wrapper-key>.sh body to invoke <handler>
# with <capture-label> as argv[1], stamped with the CURRENT $PROBE_CAPTURE_DIR.
# Touches only the body (40d: trust survives this); the registered command string
# never changes. Clears stale block-once guards for the label so a prior *-once
# responder cannot leak across subprobes (respond-hook.sh keys guards on the label).
_fixture_write_wrapper() {
    local key="${1:?wrapper key}" handler="${2:?handler}" label="${3:?label}" template="${4:-}"
    local wrapper="$HOOKBIN/$key.sh"
    {
        echo '#!/usr/bin/env bash'
        echo "export PROBE_CAPTURE_DIR='$PROBE_CAPTURE_DIR'"
        if [ -n "$template" ]; then
            echo "exec '$LIB_DIR/hooks/$handler' '$label' '$template'"
        else
            echo "exec '$LIB_DIR/hooks/$handler' '$label'"
        fi
    } >"$wrapper"
    chmod +x "$wrapper"
    rm -f "$PROBE_CAPTURE_DIR"/guards/"$label"-*.fired 2>/dev/null || true
}

# fixture_tee <wrapper-key> [capture-label] -- observe-only body (the default).
fixture_tee() {
    _fixture_write_wrapper "${1:?wrapper key}" tee-hook.sh "${2:-$1}"
}

# fixture_arm <wrapper-key> <handler> <template> [capture-label] -- active responder.
fixture_arm() {
    local key="${1:?wrapper key}" handler="${2:?handler}" template="${3:?template}"
    _fixture_write_wrapper "$key" "$handler" "${4:-$key}" "$template"
}

# fixture_tee_all -- reset EVERY registered wrapper to its observe-only default,
# re-stamped to the current stage capture dir. Call at stage start and between
# subprobes so no armed deny/block body leaks into the next turn.
fixture_tee_all() {
    local k
    for k in $FIXTURE_WRAPPER_KEYS; do fixture_tee "$k"; done
}

# fixture_project_specs [sacrificial-command] -- emit project-level HOOKSPEC lines
# (EVENT[:MATCHER]=COMMAND) for gen_hooks_config, via STABLE wrapper paths so trust
# keys are reproducible. $1 overrides the sacrificial entry's command (stage 82's
# 40e registration-string mutation); empty/unset uses the stable sacrificial path.
# The matcher on the extra PreToolUse exists to exercise the matcher-idx key + the
# matcher field in the hashed definition; whether it actually matches a tool (so
# fires) is incidental to that purpose.
fixture_project_specs() {
    local sac="${1:-$HOOKBIN/Sacrificial.sh}"
    printf '%s\n' \
        "SessionStart=$HOOKBIN/SessionStart.sh" \
        "SubagentStart=$HOOKBIN/SubagentStart.sh" \
        "PreToolUse=$HOOKBIN/PreToolUse.sh" \
        "PreToolUse:shell=$HOOKBIN/PreToolUseMatched.sh" \
        "PermissionRequest=$HOOKBIN/PermissionRequest.sh" \
        "PostToolUse=$HOOKBIN/PostToolUse.sh" \
        "PreCompact=$HOOKBIN/PreCompact.sh" \
        "PostCompact=$HOOKBIN/PostCompact.sh" \
        "UserPromptSubmit=$HOOKBIN/UserPromptSubmit.sh" \
        "SubagentStop=$HOOKBIN/SubagentStop.sh" \
        "Stop=$HOOKBIN/Stop.sh" \
        "SessionStart=$sac"
}

# fixture_register_project [sacrificial-command] -- write $PROJ/.codex/config.toml.
fixture_register_project() {
    mkdir -p "$PROJ/.codex"
    local specs=() line
    # Process substitution (not a pipe) so the array fills in THIS shell. bash 3.2 OK.
    while IFS= read -r line; do
        [ -n "$line" ] && specs+=("$line")
    done < <(fixture_project_specs "${1:-}")
    gen_hooks_config toml "${specs[@]}" >"$PROJ/.codex/config.toml"
}

# fixture_register_user -- append the user-level SessionStart registration.
fixture_register_user() {
    gen_hooks_config toml "SessionStart=$HOOKBIN/UserSessionStart.sh" >>"$CODEX_HOME/config.toml"
}
