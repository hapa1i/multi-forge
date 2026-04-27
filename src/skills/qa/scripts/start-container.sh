#!/usr/bin/env bash
# Start or reuse a Docker container for full QA mode.
#
# Usage:
#   bash start-container.sh           # Start or reuse container
#   bash start-container.sh --reset  # Kill container, remove image, rebuild and start
#   bash start-container.sh --stop    # Stop and remove container
#   bash start-container.sh --status  # Check container status
#
# Outputs container name to stdout on success.
# Exit codes: 0=ready, 1=no docker, 2=build failed, 3=start failed

set -euo pipefail

CONTAINER_NAME="forge-qa"

# --- Resolve repo root and image tag ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd -P)"

# Detect Claude Code version from installed binary
if command -v claude &>/dev/null; then
    CLAUDE_VERSION="$(claude --version 2>/dev/null | awk '{print $1}')"
fi
CLAUDE_VERSION="${CLAUDE_VERSION:-latest}"
IMAGE_NAME="forge-claude-test:${CLAUDE_VERSION}"

# --- Helper functions ---
error() { echo "ERROR: $*" >&2; }
info()  { echo "INFO: $*" >&2; }

# --- Host state dir (mounted into container) ---
HOST_STATE_DIR_RAW="${FORGE_HOME:-$HOME/.forge}/manual-testing/qa"
HOST_STATE_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(os.path.expandvars(sys.argv[1]))))' "$HOST_STATE_DIR_RAW")"
mkdir -p "$HOST_STATE_DIR"

# --- Docker availability check ---
if ! command -v docker &> /dev/null; then
    error "Docker command not found. Install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null; then
    error "Docker daemon is not running. Start Docker Desktop and try again."
    exit 1
fi

# --- Handle --reset (kill container + remove image, then fall through to rebuild) ---
if [[ "${1:-}" == "--reset" ]]; then
    info "Rebuild: removing container and image..."
    docker stop "$CONTAINER_NAME" > /dev/null 2>&1 || true
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
    docker rmi "$IMAGE_NAME" > /dev/null 2>&1 || true
    info "Cleaned up. Rebuilding from scratch..."
    shift  # consume --reset so the rest of the script runs normally
fi

# --- Handle --stop ---
if [[ "${1:-}" == "--stop" ]]; then
    if docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
        info "Stopping and removing container: $CONTAINER_NAME"
        docker stop "$CONTAINER_NAME" > /dev/null 2>&1 || true
        docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
        info "Container removed."
    else
        info "No running container named $CONTAINER_NAME."
        docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
    fi
    exit 0
fi

# --- Handle --status ---
if [[ "${1:-}" == "--status" ]]; then
    if docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
        info "Container $CONTAINER_NAME is running."
        forge_ver="$(docker exec "$CONTAINER_NAME" bash -lc 'cd /forge && uv run python -c "import forge; print(getattr(forge, \"__version__\", \"unknown\"))"' 2>/dev/null || echo "unknown")"
        info "Forge: $forge_ver"
        exit 0
    elif docker ps -aq -f "name=^${CONTAINER_NAME}$" | grep -q .; then
        info "Container $CONTAINER_NAME exists but is stopped."
        exit 1
    else
        info "No container named $CONTAINER_NAME."
        exit 1
    fi
fi

# --- Reuse if already running ---
if docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
    info "Reusing running container: $CONTAINER_NAME"
    echo "$CONTAINER_NAME"
    exit 0
fi

# --- Remove stopped container with same name ---
if docker ps -aq -f "name=^${CONTAINER_NAME}$" | grep -q .; then
    info "Removing stopped container: $CONTAINER_NAME"
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
fi

DOCKERFILE="$REPO_ROOT/docker/Dockerfile.forge"

# --- Image staleness detection (reuse pattern from scripts/test-integration.sh) ---
get_forge_rev() {
    if command -v git &>/dev/null && git -C "$REPO_ROOT" rev-parse --is-inside-work-tree &>/dev/null; then
        local rev
        rev="$(git -C "$REPO_ROOT" rev-parse HEAD)"
        if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
            echo "${rev}-dirty"
        else
            echo "${rev}"
        fi
        return 0
    fi
    echo "unknown"
}

FORGE_REV="$(get_forge_rev)"

needs_build=false
if ! docker image inspect "$IMAGE_NAME" &> /dev/null; then
    needs_build=true
    info "Image $IMAGE_NAME not found. Building..."
else
    image_rev="$(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE_NAME")" || {
        info "Failed to read image revision label; forcing rebuild."
        image_rev=""
    }
    if [[ -z "${image_rev}" || "${image_rev}" != "${FORGE_REV}" ]]; then
        needs_build=true
        info "Image stale (image=${image_rev:-<missing>}, repo=${FORGE_REV}). Rebuilding..."
    fi
fi

if [[ "$needs_build" == "true" ]]; then
    if [[ ! -f "$DOCKERFILE" ]]; then
        if docker image inspect "$IMAGE_NAME" &> /dev/null; then
            info "Source repo not available ($DOCKERFILE missing). Using existing image: $IMAGE_NAME"
            needs_build=false
        else
            error "Dockerfile not found at $DOCKERFILE"
            error "Source repo is required to build the QA image."
            error "Fix: run from the Forge source repo or install it so docker/Dockerfile.forge is available."
            exit 2
        fi
    fi

    if [[ "$needs_build" == "true" ]]; then
        info "Building Docker image (this may take a few minutes)..."
        if ! docker build \
            -f "$DOCKERFILE" \
            --build-arg "CLAUDE_VERSION=$CLAUDE_VERSION" \
            --build-arg "FORGE_REV=$FORGE_REV" \
            -t "$IMAGE_NAME" \
            "$REPO_ROOT"; then
            error "Docker build failed."
            exit 2
        fi
        info "Build complete: $IMAGE_NAME"
    fi
fi

# --- Start container ---
info "Starting container: $CONTAINER_NAME"
if ! docker run -d \
    --name "$CONTAINER_NAME" \
    -v "$HOST_STATE_DIR:/workspace/.forge/qa" \
    -w /workspace \
    "$IMAGE_NAME" \
    tail -f /dev/null > /dev/null; then
    error "Failed to start container."
    exit 3
fi

# --- Remove leaked .env before any forge imports ---
# load_dotenv() in cli/main.py:16 fires at import time. If /forge/.env survived
# from a stale image (built before .dockerignore excluded it), it contaminates
# all forge commands. Remove before the "Forge importable" preflight check.
docker exec "$CONTAINER_NAME" bash -c 'rm -f /forge/.env /forge/.env.*'

# --- Preflight inside container ---
info "Running preflight checks..."

# Install jq (many checklist items use it)
docker exec "$CONTAINER_NAME" bash -c 'apt-get update -qq && apt-get install -y -qq jq > /dev/null 2>&1' || {
    error "Failed to install jq in container."
    exit 3
}

# Set a profile to ensure bash -lc has forge, env vars, and API keys
{
    echo 'export PATH="/forge/.venv/bin:$PATH"'
    echo 'export FORGE_HOME="/root/.forge"'
    echo 'export CLAUDE_HOME="/root/.claude"'
    echo 'export FORGE_TEST_REPO="/workspace"'
    # QA defaults to debug logging so every Forge command leaves evidence.
    echo 'export FORGE_DEBUG="1"'
    # Pass API keys and infra URLs from host env or .env file
    for var in GEMINI_API_KEY ANTHROPIC_API_KEY LITELLM_API_KEY LITELLM_BASE_URL OPENAI_API_KEY; do
        # Fall back to .env if the variable isn't in the host environment
        if [[ -z "${!var:-}" && -f "$REPO_ROOT/.env" ]]; then
            _val="$(grep "^${var}=" "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2- || true)"
            _val="${_val%\"}" ; _val="${_val#\"}"
            _val="${_val%\'}" ; _val="${_val#\'}"
            if [[ -n "$_val" ]]; then
                declare -x "$var=$_val"
            fi
        fi
        if [[ -n "${!var:-}" ]]; then
            printf 'export %s=%q\n' "$var" "${!var}"
        fi
    done
} | docker exec -i "$CONTAINER_NAME" bash -c 'cat > /etc/profile.d/forge-qa.sh && chmod 600 /etc/profile.d/forge-qa.sh' || {
    error "Failed to write /etc/profile.d/forge-qa.sh"
    exit 3
}

docker exec "$CONTAINER_NAME" bash -lc 'test -x /forge/.venv/bin/forge' || {
    error "forge not found at /forge/.venv/bin/forge"
    exit 3
}

# Configure Claude Code auth for container environment.
# ANTHROPIC_API_KEY from the env profile (set above) is the sole auth mechanism.
# hasCompletedOnboarding skips the first-run screen.
# settings.json starts empty; `forge extension enable` (section 2) merges hooks into it.
# See: github.com/anthropics/claude-code/issues/9699
docker exec "$CONTAINER_NAME" bash -c 'mkdir -p /root/.claude'

docker exec -i "$CONTAINER_NAME" bash -c 'cat > /root/.claude/settings.json && chmod 600 /root/.claude/settings.json' <<'SETTINGSEOF'
{}
SETTINGSEOF

docker exec -i "$CONTAINER_NAME" bash -c 'cat > /root/.claude.json && chmod 600 /root/.claude.json' <<'ONBOARDEOF'
{"hasCompletedOnboarding":true}
ONBOARDEOF

# Verify Forge is importable
docker exec "$CONTAINER_NAME" bash -lc 'cd /forge && uv run python -c "import forge.cli.main"' || {
    error "Forge is not importable in container."
    exit 3
}

# --- Initialize workspace ---
docker exec "$CONTAINER_NAME" bash -c '
    mkdir -p /workspace/src /workspace/tests /workspace/.claude /workspace/.forge/qa /workspace/.forge/qa/logs
    cd /workspace

    cat > src/main.py << "PYEOF"
def hello():
    return "world"
PYEOF

    cat > tests/test_main.py << "PYEOF"
from src.main import hello

def test_hello():
    assert hello() == "world"
PYEOF

    cat > CLAUDE.md << "PYEOF"
# forge-walkthrough
This is a test repo for the Forge walkthrough skill.
PYEOF

    cat > README.md << "PYEOF"
# forge-walkthrough
Test workspace for the Forge walkthrough skill.
PYEOF

    cat > .claude/settings.local.json << "JSONEOF"
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

    cat > .gitignore << "GITEOF"
.DS_Store
.idea/
.env
.test-home/
.forge/
__pycache__/
*.pyc
GITEOF

    git init -q -b main
    git config user.email "forge-qa@localhost"
    git config user.name "Forge QA"
    git config commit.gpgsign false
    git add -A
    git commit -q -m "Initial test repo for forge walkthrough --full"
' || {
    error "Failed to initialize workspace in container."
    exit 3
}

info "Container ready: $CONTAINER_NAME (image: $IMAGE_NAME)"
echo "$CONTAINER_NAME"
