#!/usr/bin/env bash
# Create an isolated walkthrough workspace with separate Forge, Claude, and Codex settings homes.
#
# Usage:
#   setup-test-repo.sh                       # Create test repo (default location)
#   setup-test-repo.sh --reset               # Reset existing repo to clean baseline
#   setup-test-repo.sh --codex-auth <path>   # Copy auth into isolated CODEX_HOME
#
# Environment:
#   FORGE_TEST_REPO  Override test repo location (default: ~/.forge/manual-testing/walkthrough/test-repo)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CLAUDE_WRAPPER_SOURCE="$SCRIPT_DIR/claude-wrapper.sh"
if [ ! -f "$CLAUDE_WRAPPER_SOURCE" ]; then
    echo "ERROR: Packaged Claude walkthrough wrapper is missing: $CLAUDE_WRAPPER_SOURCE" >&2
    exit 1
fi
# Keep the bytes in memory because --reset disables the skill package that is
# currently executing before it regenerates the sandbox environment.
CLAUDE_WRAPPER_CONTENT="$(<"$CLAUDE_WRAPPER_SOURCE")"

RESET=false
CODEX_AUTH_SOURCE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --reset)
            if [ "$RESET" = true ]; then
                echo "ERROR: Duplicate argument: --reset" >&2
                exit 2
            fi
            RESET=true
            shift
            ;;
        --codex-auth)
            if [ -n "$CODEX_AUTH_SOURCE" ]; then
                echo "ERROR: Duplicate argument: --codex-auth" >&2
                exit 2
            fi
            if [ $# -lt 2 ] || [ -z "$2" ] || [[ "$2" == --* ]]; then
                echo "ERROR: --codex-auth requires a file path" >&2
                exit 2
            fi
            CODEX_AUTH_SOURCE="$2"
            shift 2
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if [ -n "$CODEX_AUTH_SOURCE" ]; then
    CODEX_AUTH_SOURCE="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$CODEX_AUTH_SOURCE")"
    if [ ! -f "$CODEX_AUTH_SOURCE" ]; then
        echo "ERROR: --codex-auth must resolve to one regular file" >&2
        exit 2
    fi
    CODEX_AUTH_MODE="explicit-file"
elif [ -n "${CODEX_API_KEY:-}" ] || [ -n "${CODEX_ACCESS_TOKEN:-}" ]; then
    CODEX_AUTH_MODE="environment"
else
    CODEX_AUTH_MODE="none"
fi

FORGE_TEST_REPO="${FORGE_TEST_REPO:-${FORGE_HOME:-$HOME/.forge}/manual-testing/walkthrough/test-repo}"
FORGE_TEST_REPO="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$FORGE_TEST_REPO")"

# CLAUDE_HOME is Forge's install/test override; Claude Code itself uses
# CLAUDE_CONFIG_DIR (or ~/.claude). Preserve that native store for auth and
# transcripts, while the launcher wrapper supplies sandbox hook settings.
if [ "${CLAUDE_CONFIG_DIR+set}" = "set" ]; then
    if [ -z "$CLAUDE_CONFIG_DIR" ]; then
        echo "ERROR: CLAUDE_CONFIG_DIR is explicitly set to empty. Refusing to proceed." >&2
        exit 2
    fi
    CLAUDE_CONFIG_DIR_WAS_SET=true
    NATIVE_CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR"
else
    CLAUDE_CONFIG_DIR_WAS_SET=false
    NATIVE_CLAUDE_CONFIG_DIR="$HOME/.claude"
fi
NATIVE_CLAUDE_CONFIG_DIR="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$NATIVE_CLAUDE_CONFIG_DIR")"

NATIVE_CLAUDE_BIN="${FORGE_WALKTHROUGH_CLAUDE_BIN:-}"
if [ -z "$NATIVE_CLAUDE_BIN" ]; then
    NATIVE_CLAUDE_BIN="$(command -v claude 2>/dev/null || true)"
fi
if [ -n "$NATIVE_CLAUDE_BIN" ]; then
    NATIVE_CLAUDE_BIN="$(python3 -c 'import os,sys; print(os.path.realpath(os.path.expanduser(sys.argv[1])))' "$NATIVE_CLAUDE_BIN")"
    if [ ! -x "$NATIVE_CLAUDE_BIN" ]; then
        echo "ERROR: Native Claude launcher is not executable: $NATIVE_CLAUDE_BIN" >&2
        exit 1
    fi
    case "$NATIVE_CLAUDE_BIN" in
        "$FORGE_TEST_REPO"/*)
            echo "ERROR: Native Claude launcher resolves inside the walkthrough sandbox: $NATIVE_CLAUDE_BIN" >&2
            echo "Rerun setup from a shell whose PATH resolves the installed Claude Code binary." >&2
            exit 1
            ;;
    esac
fi

MARKER_FILE="$FORGE_TEST_REPO/.forge-walkthrough-marker"

marker_is_canonical() {
    local marker_path="$1"
    if [ -L "$marker_path" ] || [ ! -f "$marker_path" ]; then
        return 1
    fi
    python3 - "$marker_path" <<'PY'
import os
import stat
import sys

try:
    descriptor = os.open(sys.argv[1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as marker:
        valid = stat.S_ISREG(os.fstat(marker.fileno()).st_mode) and marker.read() == b"forge-walkthrough-marker\n"
except OSError:
    valid = False
raise SystemExit(0 if valid else 1)
PY
}

# Refuse paths that are unsafe to replace.
check_safe_path() {
    local resolved
    resolved="$(realpath "$1" 2>/dev/null || echo "$1")"

    local -a denylist=("/" "$HOME" "/Users" "/tmp" "/var" "/etc" "/opt" "/usr")
    for bad in "${denylist[@]}"; do
        if [ "$resolved" = "$bad" ] || [ "$resolved" = "$(realpath "$bad" 2>/dev/null || echo "$bad")" ]; then
            echo "ERROR: Refusing to operate on '$resolved' (denylisted path)" >&2
            exit 1
        fi
    done
}

check_safe_path "$FORGE_TEST_REPO"

# Validate every preserved parent and leaf before setup writes generated code.
preflight_generated_environment_targets() {
    local wrapper_dir="$FORGE_TEST_REPO/.forge/walkthrough/bin"
    local wrapper_path="$wrapper_dir/claude"
    local env_path="$FORGE_TEST_REPO/.forge/walkthrough/env.sh"
    local forge_home="$FORGE_TEST_REPO/.forge-home"
    local claude_home="$FORGE_TEST_REPO/.claude-user"
    local codex_home="$FORGE_TEST_REPO/.codex-user"
    local claude_settings="$claude_home/settings.json"
    local directory
    local file

    for directory in \
        "$FORGE_TEST_REPO/.forge" \
        "$FORGE_TEST_REPO/.forge/walkthrough"; do
        if [ -L "$directory" ] || [ ! -d "$directory" ]; then
            echo "ERROR: Walkthrough environment parent is not a real directory: $directory" >&2
            exit 1
        fi
    done
    for directory in "$wrapper_dir" "$forge_home" "$claude_home" "$codex_home"; do
        if [ -L "$directory" ] || { [ -e "$directory" ] && [ ! -d "$directory" ]; }; then
            echo "ERROR: Walkthrough environment target is not a real directory: $directory" >&2
            exit 1
        fi
    done
    for file in "$wrapper_path" "$env_path" "$claude_settings"; do
        if [ -L "$file" ] || { [ -e "$file" ] && [ ! -f "$file" ]; }; then
            echo "ERROR: Walkthrough environment target is not a regular file: $file" >&2
            exit 1
        fi
    done
}

# Both reset and initialization generate env.sh.
generate_env() {
    local wrapper_dir="$FORGE_TEST_REPO/.forge/walkthrough/bin"
    local wrapper_path="$wrapper_dir/claude"
    local env_path="$FORGE_TEST_REPO/.forge/walkthrough/env.sh"
    local claude_home="$FORGE_TEST_REPO/.claude-user"
    local codex_home="$FORGE_TEST_REPO/.codex-user"
    local claude_settings="$claude_home/settings.json"

    preflight_generated_environment_targets

    mkdir -p "$wrapper_dir" "$FORGE_TEST_REPO/.claude-user" "$FORGE_TEST_REPO/.codex-user"
    chmod 700 "$FORGE_TEST_REPO/.codex-user"
    printf '%s\n' "$CLAUDE_WRAPPER_CONTENT" > "$wrapper_path"
    chmod 755 "$wrapper_path"
    if [ ! -e "$claude_settings" ]; then
        printf '{}\n' > "$claude_settings"
    fi
    {
        cat << 'ENVEOF'
# Generated by setup-test-repo.sh -- sandbox Forge state plus Claude/Codex settings.
# HOME stays real (Claude auth, native install, shell config all work).
ENVEOF
        printf 'export FORGE_TEST_REPO=%q\n' "$FORGE_TEST_REPO"
        printf 'export FORGE_HOME=%q\n' "$FORGE_TEST_REPO/.forge-home"
        printf 'export CLAUDE_HOME=%q\n' "$FORGE_TEST_REPO/.claude-user"
        printf 'export CODEX_HOME=%q\n' "$FORGE_TEST_REPO/.codex-user"
        printf 'export FORGE_WALKTHROUGH_CLAUDE_BIN=%q\n' "$NATIVE_CLAUDE_BIN"
        printf 'export FORGE_WALKTHROUGH_CLAUDE_CONFIG_DIR=%q\n' "$NATIVE_CLAUDE_CONFIG_DIR"
        if [ "$CLAUDE_CONFIG_DIR_WAS_SET" = true ]; then
            printf 'export CLAUDE_CONFIG_DIR=%q\n' "$NATIVE_CLAUDE_CONFIG_DIR"
        else
            printf 'unset CLAUDE_CONFIG_DIR\n'
        fi
        printf 'export PATH=%q:$PATH\n' "$wrapper_dir"
        printf 'export FORGE_DEBUG=%q\n' "1"
        printf 'export FORGE_WALKTHROUGH_CODEX_AUTH_MODE=%q\n' "$CODEX_AUTH_MODE"
        if [ "$CODEX_AUTH_MODE" = "explicit-file" ]; then
            cat << 'ENVEOF'
unset CODEX_API_KEY
unset CODEX_ACCESS_TOKEN
ENVEOF
        fi
        cat << 'ENVEOF'
echo "Forge walkthrough sandbox active:" >&2
echo "  FORGE_HOME = $FORGE_HOME (isolated)" >&2
echo "  CLAUDE_HOME = $CLAUDE_HOME (isolated)" >&2
echo "  CODEX_HOME = $CODEX_HOME (isolated)" >&2
echo "  HOME       = $HOME (unchanged)" >&2
echo "  Claude settings = sandbox overlay; native auth/store preserved" >&2
echo "  FORGE_DEBUG = $FORGE_DEBUG (sandbox debug logging)" >&2
echo "  Codex auth ingress = $FORGE_WALKTHROUGH_CODEX_AUTH_MODE" >&2
ENVEOF
    } > "$env_path"
}

prepare_codex_auth() {
    local destination="$FORGE_TEST_REPO/.codex-user/auth.json"
    rm -f "$destination"
    if [ "$CODEX_AUTH_MODE" = "explicit-file" ]; then
        install -m 600 "$CODEX_AUTH_SOURCE" "$destination"
    fi
}

# Remove walkthrough state that must not persist across runs.
scrub_volatile_state() {
    rm -rf "$FORGE_TEST_REPO/.forge-home/logs"
    rm -f "$FORGE_TEST_REPO/.forge/walkthrough/progress.json"
    rm -f "$FORGE_TEST_REPO/.forge/walkthrough/real-system.json"
}

# Reset an existing walkthrough repository.
if [ "$RESET" = true ]; then
    if [ -d "$FORGE_TEST_REPO" ]; then
        if ! marker_is_canonical "$MARKER_FILE"; then
            echo "ERROR: Directory has no canonical walkthrough marker: $FORGE_TEST_REPO" >&2
            echo "Refusing --reset because ownership cannot be proven." >&2
            echo "Remove it manually or choose a different FORGE_TEST_REPO path." >&2
            exit 1
        fi
        if [ ! -f "$FORGE_TEST_REPO/src/main.py" ] || [ ! -f "$FORGE_TEST_REPO/CLAUDE.md" ]; then
            echo "ERROR: Expected structure not found (src/main.py, CLAUDE.md)." >&2
            echo "This does not look like a forge-walkthrough repo. Refusing --reset." >&2
            exit 1
        fi
        preflight_generated_environment_targets
        reset_sidecar_may_exist=false
        progress_file="$FORGE_TEST_REPO/.forge/walkthrough/progress.json"
        if [ -e "$progress_file" ] || [ -L "$progress_file" ]; then
            if [ -L "$progress_file" ] || [ ! -f "$progress_file" ]; then
                echo "ERROR: Walkthrough progress is not a regular file; refusing --reset." >&2
                exit 1
            fi
            if ! reset_sidecar_may_exist="$(python3 -c '
import json
import sys

try:
    state = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, ValueError, TypeError):
    raise SystemExit(2)

if not isinstance(state, dict):
    raise SystemExit(2)

schema_version = state.get("schema_version")
if type(schema_version) is not int or schema_version not in {1, 2}:
    raise SystemExit(2)
if schema_version == 1:
    checklist_hash = state.get("checklist_hash")
    if (
        not isinstance(checklist_hash, str)
        or not checklist_hash.startswith("sha256:")
        or len(checklist_hash) != 71
        or any(character not in "0123456789abcdef" for character in checklist_hash[7:])
    ):
        raise SystemExit(2)

required_types = {
    "checklist_version": str,
    "mode": str,
    "started_at": str,
    "last_updated": str,
    "vars": dict,
    "steps": dict,
}
if any(key not in state or not isinstance(state[key], expected) for key, expected in required_types.items()):
    raise SystemExit(2)
if "current_step" not in state or not isinstance(state["current_step"], (str, type(None))):
    raise SystemExit(2)
if not all(isinstance(key, str) for key in state["vars"]):
    raise SystemExit(2)
if not all(isinstance(key, str) and isinstance(step, dict) for key, step in state["steps"].items()):
    raise SystemExit(2)
for step in state["steps"].values():
    results = step.get("results")
    if not isinstance(results, list) or any(
        not isinstance(result, str) or result not in {"pass", "fail", "skip"}
        for result in results
    ):
        raise SystemExit(2)
    if schema_version >= 2 and (
        "hash" not in step or not isinstance(step["hash"], (str, type(None)))
    ):
        raise SystemExit(2)
    if "scope" in step and not isinstance(step["scope"], str):
        raise SystemExit(2)

if "SIDECAR_MAY_EXIST" not in state["vars"]:
    value = "false"
else:
    value = state["vars"]["SIDECAR_MAY_EXIST"]
    if value not in {"true", "false"}:
        raise SystemExit(2)
print(value)
' "$progress_file")"; then
                echo "ERROR: Walkthrough progress is unreadable or malformed; refusing --reset." >&2
                exit 1
            fi
        fi
        if [ -e "$FORGE_TEST_REPO/.forge/sessions/walkthrough-sidecar" ]; then
            reset_sidecar_may_exist=true
        fi
        # These generated homes may be absent after an interrupted cleanup. Their
        # paths were proven to be missing or real directories above, so recreate
        # only the known sandbox leaves before invoking the gated cleanup.
        mkdir -p \
            "$FORGE_TEST_REPO/.forge-home" \
            "$FORGE_TEST_REPO/.claude-user" \
            "$FORGE_TEST_REPO/.codex-user"
        chmod 700 "$FORGE_TEST_REPO/.codex-user"
        WALKTHROUGH_SIDECAR_MAY_EXIST="$reset_sidecar_may_exist" \
            FORGE_TEST_REPO="$FORGE_TEST_REPO" \
            bash "$SCRIPT_DIR/run-in-repo.sh" bash "$SCRIPT_DIR/cleanup-owned.sh" all
        echo "Resetting test repo: $FORGE_TEST_REPO" >&2
        cd "$FORGE_TEST_REPO"
        git clean -fdx -e .forge/ -e .forge-home/ -e .claude-user/ -e .codex-user/
        git checkout -- .
        mkdir -p .forge-home
        mkdir -p .forge/walkthrough
        scrub_volatile_state
        echo "forge-walkthrough-marker" > "$MARKER_FILE"
        generate_env
        prepare_codex_auth
        echo "Reset complete." >&2
        exit 0
    fi
fi

# A fresh setup must not discard evidence or auth from an existing run.
if [ -d "$FORGE_TEST_REPO" ] && marker_is_canonical "$MARKER_FILE"; then
    echo "ERROR: Walkthrough repository already exists: $FORGE_TEST_REPO" >&2
    echo "Use --reset to reclaim owned resources and create a fresh baseline." >&2
    exit 1
fi

# Do not initialize a directory that this script did not create.
if [ -d "$FORGE_TEST_REPO" ]; then
    echo "ERROR: Directory exists but has no canonical marker: $FORGE_TEST_REPO" >&2
    echo "This was not created by setup-test-repo.sh. Refusing to initialize." >&2
    echo "Remove it manually or choose a different FORGE_TEST_REPO path." >&2
    exit 1
fi

# Initialize a new walkthrough repository.
echo "Creating test repo: $FORGE_TEST_REPO" >&2

mkdir -p "$FORGE_TEST_REPO"
cd "$FORGE_TEST_REPO"

mkdir -p .forge-home .claude-user .codex-user

mkdir -p .forge/walkthrough

mkdir -p src tests .claude

# Write fixture files.

cat > src/main.py << 'PYEOF'
def hello():
    return "world"
PYEOF

cat > tests/test_main.py << 'PYEOF'
from src.main import hello


def test_hello():
    assert hello() == "world"
PYEOF

cat > CLAUDE.md << 'PYEOF'
# forge-walkthrough

This is a test repo for the Forge walkthrough skill.
PYEOF

cat > README.md << 'PYEOF'
# forge-walkthrough

Test workspace for the Forge `/walkthrough` skill.
PYEOF

cat > .claude/settings.local.json << 'JSONEOF'
{
  "permissions": {
    "allow": [
      "Bash(npm test)",
      "Bash(uv run pytest*)"
    ]
  },
  "env": {
    "MY_CUSTOM_VAR": "should-survive-forge"
  }
}
JSONEOF

cat > .gitignore << 'GITEOF'
.DS_Store
.idea/
.env
.forge-home/
.claude-user/
.codex-user/
.forge/
__pycache__/
*.pyc
GITEOF

# Initialize the fixture repository.
git init -q
git config user.email "forge-test@localhost"
git config user.name "Forge Test"
git config commit.gpgsign false
git add -A
# Force-add paths excluded by Claude Code's global gitignore (~/.config/git/ignore):
#   **/.claude/settings.local.json, **/CLAUDE.local.md
for f in .claude/ CLAUDE.local.md; do
    [ -e "$f" ] && git add -f "$f"
done
git -c core.hooksPath=/dev/null commit -q -m "Initial test repo for forge walkthrough"

# Write the marker after the commit so git checkout preserves it.
echo "forge-walkthrough-marker" > "$MARKER_FILE"

generate_env
prepare_codex_auth

echo "Test repo created: $FORGE_TEST_REPO" >&2
echo "FORGE_HOME: $FORGE_TEST_REPO/.forge-home/" >&2
echo "CLAUDE_HOME: $FORGE_TEST_REPO/.claude-user/" >&2
echo "CODEX_HOME: $FORGE_TEST_REPO/.codex-user/" >&2
echo "Env file: $FORGE_TEST_REPO/.forge/walkthrough/env.sh" >&2
