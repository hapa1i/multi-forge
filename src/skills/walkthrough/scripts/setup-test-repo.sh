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
FORGE_TEST_REPO="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$FORGE_TEST_REPO")"

# CLAUDE_HOME is Forge's install/test override; Claude Code itself uses
# CLAUDE_CONFIG_DIR (or ~/.claude). Preserve that native store for auth and
# transcripts, while the launcher wrapper supplies sandbox hook settings.
if [ "${CLAUDE_CONFIG_DIR+set}" = "set" ]; then
    CLAUDE_CONFIG_DIR_WAS_SET=true
    NATIVE_CLAUDE_CONFIG_DIR="$CLAUDE_CONFIG_DIR"
else
    CLAUDE_CONFIG_DIR_WAS_SET=false
    NATIVE_CLAUDE_CONFIG_DIR="$HOME/.claude"
fi
NATIVE_CLAUDE_CONFIG_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$NATIVE_CLAUDE_CONFIG_DIR")"

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

# Both reset and initialization generate env.sh.
generate_env() {
    local wrapper_dir="$FORGE_TEST_REPO/.forge/walkthrough/bin"
    local wrapper_path="$wrapper_dir/claude"
    mkdir -p "$wrapper_dir" "$FORGE_TEST_REPO/.claude-user" "$FORGE_TEST_REPO/.codex-user"
    chmod 700 "$FORGE_TEST_REPO/.codex-user"
    if [ -L "$wrapper_path" ] || { [ -e "$wrapper_path" ] && [ ! -f "$wrapper_path" ]; }; then
        echo "ERROR: Walkthrough Claude wrapper target is not a regular file: $wrapper_path" >&2
        exit 1
    fi
    printf '%s\n' "$CLAUDE_WRAPPER_CONTENT" > "$wrapper_path"
    chmod 755 "$wrapper_path"
    if [ -L "$FORGE_TEST_REPO/.claude-user/settings.json" ]; then
        echo "ERROR: Sandboxed Claude settings must not be a symlink" >&2
        exit 1
    fi
    if [ ! -e "$FORGE_TEST_REPO/.claude-user/settings.json" ]; then
        printf '{}\n' > "$FORGE_TEST_REPO/.claude-user/settings.json"
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
    } > "$FORGE_TEST_REPO/.forge/walkthrough/env.sh"
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
    rm -rf "$FORGE_TEST_REPO/.forge/artifacts"
    rm -rf "$FORGE_TEST_REPO/.forge/search-index"
    rm -rf "$FORGE_TEST_REPO/.forge-home/logs"
    rm -f "$FORGE_TEST_REPO/.forge/walkthrough/progress.json"
    rm -f "$FORGE_TEST_REPO/.forge/walkthrough/real-system.json"
}

# Reset an existing walkthrough repository.
if [ "$RESET" = true ]; then
    if [ -d "$FORGE_TEST_REPO" ] && [ -f "$MARKER_FILE" ]; then
        if [ ! -f "$FORGE_TEST_REPO/src/main.py" ] || [ ! -f "$FORGE_TEST_REPO/CLAUDE.md" ]; then
            echo "ERROR: Expected structure not found (src/main.py, CLAUDE.md)." >&2
            echo "This does not look like a forge-walkthrough repo. Refusing --reset." >&2
            exit 1
        fi
        reset_sidecar_may_exist=false
        progress_file="$FORGE_TEST_REPO/.forge/walkthrough/progress.json"
        if [ -f "$progress_file" ]; then
            reset_sidecar_may_exist="$(python3 -c '
import json
import sys

try:
    state = json.load(open(sys.argv[1], encoding="utf-8"))
    value = state.get("vars", {}).get("SIDECAR_MAY_EXIST", "false")
    print("true" if value == "true" else "false")
except (OSError, ValueError, TypeError):
    print("false")
' "$progress_file")"
        fi
        if [ -e "$FORGE_TEST_REPO/.forge/sessions/walkthrough-sidecar" ]; then
            reset_sidecar_may_exist=true
        fi
        WALKTHROUGH_SIDECAR_MAY_EXIST="$reset_sidecar_may_exist" \
            FORGE_TEST_REPO="$FORGE_TEST_REPO" \
            bash "$SCRIPT_DIR/run-in-repo.sh" bash "$SCRIPT_DIR/cleanup-owned.sh" all
        echo "Resetting test repo: $FORGE_TEST_REPO" >&2
        cd "$FORGE_TEST_REPO"
        git clean -fdx -e .forge/walkthrough/ -e .forge-home/ -e .claude-user/ -e .codex-user/
        git checkout -- .
        mkdir -p .forge-home
        mkdir -p .forge/walkthrough
        scrub_volatile_state
        echo "forge-walkthrough-marker" > "$MARKER_FILE"
        generate_env
        prepare_codex_auth
        echo "Reset complete." >&2
        exit 0
    elif [ -d "$FORGE_TEST_REPO" ]; then
        echo "ERROR: Directory exists but has no walkthrough marker: $FORGE_TEST_REPO" >&2
        echo "Refusing --reset because ownership cannot be proven." >&2
        echo "Remove it manually or choose a different FORGE_TEST_REPO path." >&2
        exit 1
    fi
fi

# A fresh setup must not discard evidence or auth from an existing run.
if [ -d "$FORGE_TEST_REPO" ] && [ -f "$MARKER_FILE" ]; then
    FORGE_TEST_REPO="$FORGE_TEST_REPO" bash "$SCRIPT_DIR/run-in-repo.sh" true
    echo "ERROR: Walkthrough repository already exists: $FORGE_TEST_REPO" >&2
    echo "Use --reset to reclaim owned resources and create a fresh baseline." >&2
    exit 1
fi

# Do not initialize a directory that this script did not create.
if [ -d "$FORGE_TEST_REPO" ] && [ ! -f "$MARKER_FILE" ]; then
    echo "ERROR: Directory exists but has no marker: $FORGE_TEST_REPO" >&2
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
