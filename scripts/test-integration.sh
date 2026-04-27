#!/usr/bin/env bash
# Test runner for Docker-based integration tests
#
# Usage:
#   ./scripts/test-integration.sh                      # All integration tests
#   ./scripts/test-integration.sh -k test_proxy       # Filter by keyword
#   ./scripts/test-integration.sh tests/integration/  # Specific directory
#   ./scripts/test-integration.sh -v --tb=short       # With pytest flags

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
error() {
    echo -e "${RED}ERROR: $*${NC}" >&2
}

info() {
    echo -e "${GREEN}INFO: $*${NC}"
}

warn() {
    echo -e "${YELLOW}WARN: $*${NC}"
}

# Find repo root (directory containing pyproject.toml)
find_repo_root() {
    local dir="$PWD"
    while [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/pyproject.toml" ]]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    error "Could not find repo root (no pyproject.toml found)"
    exit 1
}

REPO_ROOT="$(find_repo_root)"
cd "$REPO_ROOT"

# Load environment variables (secrets only: API keys, workspace ID)
if [[ -f ".env" ]]; then
    # shellcheck disable=SC1091
    source .env
fi

# Detect Claude Code version from installed binary
if command -v claude &>/dev/null; then
    CLAUDE_VERSION="$(claude --version 2>/dev/null | awk '{print $1}')"
fi
CLAUDE_VERSION="${CLAUDE_VERSION:-latest}"
IMAGE_NAME="forge-claude-test:${CLAUDE_VERSION}"

get_forge_rev() {
    # Use git revision to detect stale test images (code is COPY'd at build time).
    # If repo is dirty, append -dirty so local changes trigger a rebuild.
    if command -v git &>/dev/null && git rev-parse --is-inside-work-tree &>/dev/null; then
        local rev
        rev="$(git rev-parse HEAD)"
        if [[ -n "$(git status --porcelain)" ]]; then
            echo "${rev}-dirty"
        else
            echo "${rev}"
        fi
        return 0
    fi
    echo "unknown"
}

FORGE_REV="$(get_forge_rev)"

# Validate Docker is available
if ! command -v docker &> /dev/null; then
    error "Docker command not found. Please install Docker."
    error "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null; then
    error "Docker daemon is not running. Please start Docker."
    exit 1
fi

info "Using Docker image: $IMAGE_NAME (Claude Code $CLAUDE_VERSION)"

# Check if image exists, build if missing or stale
needs_build=false
if ! docker image inspect "$IMAGE_NAME" &> /dev/null; then
    needs_build=true
else
    image_rev="$(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$IMAGE_NAME")" || {
        warn "Failed to read image revision label; forcing rebuild."
        image_rev=""
    }
    if [[ -z "${image_rev}" || "${image_rev}" != "${FORGE_REV}" ]]; then
        needs_build=true
        warn "Docker image is stale (image_rev=${image_rev:-<missing>}, repo_rev=${FORGE_REV}). Rebuilding..."
    fi
fi

if [[ "$needs_build" == "true" ]]; then

    DOCKERFILE="$REPO_ROOT/docker/Dockerfile.forge"
    if [[ ! -f "$DOCKERFILE" ]]; then
        error "Dockerfile not found at $DOCKERFILE"
        exit 1
    fi

    info "Building Docker image (this may take a few minutes)..."
    if ! docker build \
        -f "$DOCKERFILE" \
        --build-arg "CLAUDE_VERSION=$CLAUDE_VERSION" \
        --build-arg "FORGE_REV=$FORGE_REV" \
        -t "$IMAGE_NAME" \
        "$REPO_ROOT"; then
        error "Docker build failed"
        exit 1
    fi

    info "Build complete: $IMAGE_NAME"
else
    info "Using existing image: $IMAGE_NAME"
fi

# Ensure local LiteLLM is running (prerequisite for some integration tests)
# Uses port 4001 to avoid conflicts with local development LiteLLM (port 4000)
ensure_local_litellm() {
    local TEST_PORT=4001

    # Check if port 4001 is already listening
    if lsof -i :${TEST_PORT} -t &>/dev/null; then
        info "Local LiteLLM already running on port ${TEST_PORT}"
        return 0
    fi

    # Check if we have the required API key
    if [[ -z "${GEMINI_API_KEY:-}" ]]; then
        warn "GEMINI_API_KEY not set - local LiteLLM tests will fail"
        warn "Add to .env or ~/.forge/.env"
        return 0  # Don't block tests - let them fail with clear error
    fi

    # Ensure backend config exists
    if ! uv run forge backend create litellm 2>/dev/null; then
        # Config already exists or creation failed - either way, try to start
        :
    fi

    # Start local LiteLLM in background on test port 4001
    info "Starting local LiteLLM on port ${TEST_PORT} (test instance)..."
    if ! uv run forge backend start litellm --port ${TEST_PORT}; then
        warn "Failed to start local LiteLLM - tests requiring it will fail"
        return 0  # Don't block tests
    fi

    info "Local LiteLLM started successfully on port ${TEST_PORT}"
}

# Ensure local LiteLLM prerequisite (test template uses port 4001 for isolation)
ensure_local_litellm

# Run pytest on host - it will spawn Docker containers via fixtures
# Pass through all command-line arguments to pytest
info "Running integration tests (pytest will spawn Docker containers)..."

# Default to fast integration-marked tests if no args provided.
# This includes:
# - E2EIT: tests/integration/**
# - CIT: tests/src/**/test_*_integration.py
# Excludes:
# - @pytest.mark.slow network / real-Claude validation tests
# See TESTING_GUIDELINES.md: integration marking keeps unit suite fast.
if [[ $# -eq 0 ]]; then
    PYTEST_ARGS=("-m" "integration and not slow" "-v" "--reruns" "2" "--reruns-delay" "5")
else
    # Preserve expected semantics for this runner: only integration-marked tests.
    # If caller already provided a mark expression (-m/--markexpr/--markers), don't override it.
    # Explicit file paths still run slow integration tests unless the caller opts out.
    has_markexpr=false
    for arg in "$@"; do
        if [[ "$arg" == "-m" || "$arg" == "--markexpr" || "$arg" == "--markers" ]]; then
            has_markexpr=true
            break
        fi
    done

    if [[ "$has_markexpr" == "true" ]]; then
        PYTEST_ARGS=("$@")
    else
        PYTEST_ARGS=("-m" "integration" "$@")
    fi
fi

# Run pytest on host with uv
exec uv run pytest "${PYTEST_ARGS[@]}"
