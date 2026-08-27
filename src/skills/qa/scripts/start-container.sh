#!/usr/bin/env bash
# Start or reuse a Docker container for full QA mode.
#
# Usage:
#   bash start-container.sh                                      # Build one wheel, then start or reuse
#   bash start-container.sh --wheel dist/multi_forge-1.0.0-*.whl # Run one prebuilt release candidate
#   bash start-container.sh --runtime-track latest               # Non-blocking compatibility lane
#   bash start-container.sh --provider-profile remote-litellm    # Use legacy remote LiteLLM QA profile
#   bash start-container.sh --reset                              # Remove this release image and rebuild
#   bash start-container.sh --stop                               # Stop and remove container
#   bash start-container.sh --status                             # Check container status
#
# Outputs container name to stdout on success.
# Exit codes: 0=ready, 1=no docker, 2=build failed, 3=start failed

set -euo pipefail

CONTAINER_NAME="forge-qa"
PROVIDER_PROFILE="openrouter"
RUNTIME_TRACK="pinned"
WHEEL_PATH=""
CODEX_AUTH_FILE=""
RESET=false
ACTION="start"
PROVIDER_PROFILE_SEEN=false
RUNTIME_TRACK_SEEN=false
WHEEL_PATH_SEEN=false
CODEX_AUTH_SEEN=false
RESET_SEEN=false
ACTION_SEEN=false
RELEASE_BUILD_CONTEXT=""

# Resolve the repository root and image tag.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd -P)"
RUNTIME_MATRIX="$REPO_ROOT/src/skills/qa/resources/runtime-matrix.json"
ARTIFACT_HELPER="$SCRIPT_DIR/qa-artifact.py"
QA_DOCKERFILE="$REPO_ROOT/docker/Dockerfile.qa"
BASE_DOCKERFILE="$REPO_ROOT/docker/Dockerfile.forge"

# Helpers
error() { echo "ERROR: $*" >&2; }
info()  { echo "INFO: $*" >&2; }

cleanup_release_build_context() {
    if [[ -n "$RELEASE_BUILD_CONTEXT" && -d "$RELEASE_BUILD_CONTEXT" ]]; then
        rm -rf "$RELEASE_BUILD_CONTEXT"
    fi
    RELEASE_BUILD_CONTEXT=""
}

trap cleanup_release_build_context EXIT

# Repo revision baked into built images (org.opencontainers.image.revision).
# A trailing -dirty marks an uncommitted working tree so any local change forces
# a rebuild instead of a stale reuse. Defined here (not just before the build) so
# the running-container reuse path can revision-check before reusing.
get_forge_rev() {
    if command -v git &>/dev/null && git -C "$REPO_ROOT" rev-parse --is-inside-work-tree &>/dev/null; then
        local rev
        rev="$(git -C "$REPO_ROOT" rev-parse HEAD)"
        if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
            local dirty_digest
            dirty_digest="$(python3 - "$REPO_ROOT" <<'PY'
import hashlib
import os
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
digest = hashlib.sha256()
digest.update(subprocess.check_output(["git", "-C", str(root), "diff", "--binary", "HEAD", "--"]))
untracked = subprocess.check_output(
    ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"]
)
for raw_path in sorted(path for path in untracked.split(b"\0") if path):
    path = root / os.fsdecode(raw_path)
    digest.update(raw_path + b"\0")
    if path.is_symlink():
        digest.update(os.fsencode(os.readlink(path)))
    elif path.is_file():
        digest.update(path.read_bytes())
print(digest.hexdigest()[:12])
PY
)"
            echo "${rev}-dirty-${dirty_digest}"
        else
            echo "${rev}"
        fi
        return 0
    fi
    echo "unknown"
}

usage() {
    cat >&2 <<'EOF'
Usage: start-container.sh [--wheel PATH] [--runtime-track pinned|latest]
                          [--codex-auth PATH]
                          [--provider-profile openrouter|remote-litellm]
                          [--reset|--stop|--status]

Release sign-off requires --wheel with the exact prebuilt release-candidate wheel.
Without --wheel, the script builds one development wheel and reports its path.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --provider-profile)
            if [[ "$PROVIDER_PROFILE_SEEN" == "true" ]]; then
                error "--provider-profile may be specified only once"
                exit 1
            fi
            if [[ -z "${2:-}" ]]; then
                error "--provider-profile requires a value: openrouter or remote-litellm"
                usage
                exit 1
            fi
            PROVIDER_PROFILE="$2"
            PROVIDER_PROFILE_SEEN=true
            shift 2
            ;;
        --provider-profile=*)
            PROVIDER_PROFILE="${1#--provider-profile=}"
            if [[ "$PROVIDER_PROFILE_SEEN" == "true" || -z "$PROVIDER_PROFILE" ]]; then
                error "--provider-profile requires exactly one value"
                exit 1
            fi
            PROVIDER_PROFILE_SEEN=true
            shift
            ;;
        --wheel)
            if [[ "$WHEEL_PATH_SEEN" == "true" ]]; then
                error "--wheel may be specified only once"
                exit 1
            fi
            if [[ -z "${2:-}" ]]; then
                error "--wheel requires a path"
                usage
                exit 1
            fi
            WHEEL_PATH="$2"
            WHEEL_PATH_SEEN=true
            shift 2
            ;;
        --wheel=*)
            WHEEL_PATH="${1#--wheel=}"
            if [[ "$WHEEL_PATH_SEEN" == "true" || -z "$WHEEL_PATH" ]]; then
                error "--wheel requires exactly one path"
                exit 1
            fi
            WHEEL_PATH_SEEN=true
            shift
            ;;
        --runtime-track)
            if [[ "$RUNTIME_TRACK_SEEN" == "true" ]]; then
                error "--runtime-track may be specified only once"
                exit 1
            fi
            if [[ -z "${2:-}" ]]; then
                error "--runtime-track requires pinned or latest"
                usage
                exit 1
            fi
            RUNTIME_TRACK="$2"
            RUNTIME_TRACK_SEEN=true
            shift 2
            ;;
        --runtime-track=*)
            RUNTIME_TRACK="${1#--runtime-track=}"
            if [[ "$RUNTIME_TRACK_SEEN" == "true" || -z "$RUNTIME_TRACK" ]]; then
                error "--runtime-track requires exactly one value"
                exit 1
            fi
            RUNTIME_TRACK_SEEN=true
            shift
            ;;
        --codex-auth)
            if [[ "$CODEX_AUTH_SEEN" == "true" ]]; then
                error "--codex-auth may be specified only once"
                exit 1
            fi
            if [[ -z "${2:-}" ]]; then
                error "--codex-auth requires an auth.json path"
                usage
                exit 1
            fi
            CODEX_AUTH_FILE="$2"
            CODEX_AUTH_SEEN=true
            shift 2
            ;;
        --codex-auth=*)
            CODEX_AUTH_FILE="${1#--codex-auth=}"
            if [[ "$CODEX_AUTH_SEEN" == "true" || -z "$CODEX_AUTH_FILE" ]]; then
                error "--codex-auth requires exactly one path"
                exit 1
            fi
            CODEX_AUTH_SEEN=true
            shift
            ;;
        --reset)
            if [[ "$RESET_SEEN" == "true" ]]; then
                error "--reset may be specified only once"
                exit 1
            fi
            RESET=true
            RESET_SEEN=true
            shift
            ;;
        --stop)
            if [[ "$ACTION_SEEN" == "true" ]]; then
                error "--stop and --status are mutually exclusive and may be specified only once"
                exit 1
            fi
            ACTION="stop"
            ACTION_SEEN=true
            shift
            ;;
        --status)
            if [[ "$ACTION_SEEN" == "true" ]]; then
                error "--stop and --status are mutually exclusive and may be specified only once"
                exit 1
            fi
            ACTION="status"
            ACTION_SEEN=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            error "Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ "$ACTION" != "start" && ( "$WHEEL_PATH_SEEN" == "true" || "$CODEX_AUTH_SEEN" == "true" || "$RUNTIME_TRACK_SEEN" == "true" || "$PROVIDER_PROFILE_SEEN" == "true" || "$RESET" == "true" ) ]]; then
    error "--wheel, --codex-auth, --runtime-track, --provider-profile, and --reset apply only when starting QA"
    exit 1
fi

case "$PROVIDER_PROFILE" in
    openrouter)
        FORGE_QA_OPENAI_TEMPLATE="openrouter-openai"
        FORGE_QA_GEMINI_TEMPLATE="openrouter-gemini"
        FORGE_QA_ANTHROPIC_TEMPLATE="openrouter-anthropic"
        : "${FORGE_QA_WORKFLOW_MODELS:=deepseek-v4-pro,minimax-m3}"
        : "${FORGE_QA_WORKFLOW_MODEL_A:=deepseek-v4-pro}"
        : "${FORGE_QA_WORKFLOW_MODEL_B:=minimax-m3}"
        FORGE_QA_DEEPSEEK_TEMPLATE="openrouter-deepseek"
        FORGE_QA_MINIMAX_TEMPLATE="openrouter-minimax"
        ;;
    remote-litellm)
        FORGE_QA_OPENAI_TEMPLATE="litellm-openai"
        FORGE_QA_GEMINI_TEMPLATE="litellm-gemini"
        FORGE_QA_ANTHROPIC_TEMPLATE="litellm-anthropic"
        : "${FORGE_QA_WORKFLOW_MODELS:=gpt-5.6-sol,gemini-3.1-pro-preview}"
        : "${FORGE_QA_WORKFLOW_MODEL_A:=gpt-5.6-sol}"
        : "${FORGE_QA_WORKFLOW_MODEL_B:=gemini-3.1-pro-preview}"
        FORGE_QA_DEEPSEEK_TEMPLATE=""
        FORGE_QA_MINIMAX_TEMPLATE=""
        ;;
    *)
        error "Invalid --provider-profile '$PROVIDER_PROFILE' (expected: openrouter or remote-litellm)"
        exit 1
        ;;
esac

FORGE_QA_PROVIDER_PROFILE="$PROVIDER_PROFILE"
FORGE_QA_OPENAI_PROXY="qa-openai"
FORGE_QA_GEMINI_PROXY="qa-gemini"
FORGE_QA_ANTHROPIC_PROXY="qa-anthropic"

load_env_var() {
    local var="$1"
    if [[ -z "${!var:-}" && -f "$REPO_ROOT/.env" ]]; then
        local val
        val="$(grep "^${var}=" "$REPO_ROOT/.env" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
        val="${val%\"}" ; val="${val#\"}"
        val="${val%\'}" ; val="${val#\'}"
        if [[ -n "$val" ]]; then
            printf -v "$var" '%s' "$val"
            export "$var"
        fi
    fi
}

load_qa_env() {
    local var
    for var in \
        GEMINI_API_KEY \
        ANTHROPIC_API_KEY \
        CODEX_API_KEY \
        LITELLM_API_KEY \
        LITELLM_BASE_URL \
        OPENAI_API_KEY \
        OPENROUTER_API_KEY \
        OPENROUTER_BASE_URL; do
        load_env_var "$var"
    done
}

validate_provider_profile() {
    load_qa_env

    case "$PROVIDER_PROFILE" in
        openrouter)
            if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
                error "QA provider profile 'openrouter' requires OPENROUTER_API_KEY."
                error "Set it in your environment or repo .env, or use --provider-profile remote-litellm."
                exit 1
            fi
            ;;
        remote-litellm)
            if [[ -z "${LITELLM_API_KEY:-}" || -z "${LITELLM_BASE_URL:-}" ]]; then
                error "QA provider profile 'remote-litellm' requires LITELLM_API_KEY and LITELLM_BASE_URL."
                error "Set both in your environment or repo .env, or use the default OpenRouter profile."
                exit 1
            fi
            ;;
    esac
}

validate_running_container_profile() {
    case "$PROVIDER_PROFILE" in
        openrouter)
            if ! docker exec "$CONTAINER_NAME" sh -c 'test -n "${OPENROUTER_API_KEY:-}"' >/dev/null 2>&1; then
                error "Running QA container for profile 'openrouter' is missing OPENROUTER_API_KEY."
                error "Run 'bash start-container.sh --stop' and restart it with OPENROUTER_API_KEY set."
                exit 3
            fi
            ;;
        remote-litellm)
            if ! docker exec "$CONTAINER_NAME" sh -c \
                'test -n "${LITELLM_API_KEY:-}" && test -n "${LITELLM_BASE_URL:-}"' >/dev/null 2>&1; then
                error "Running QA container for profile 'remote-litellm' is missing LITELLM_API_KEY or LITELLM_BASE_URL."
                error "Run 'bash start-container.sh --stop' and restart it with both variables set."
                exit 3
            fi
            ;;
    esac
}

docker_env_args() {
    local args=(
        -e "PATH=/opt/forge-qa/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        -e "PYTHONNOUSERSITE=1"
        -e "FORGE_HOME=/root/.forge"
        -e "CLAUDE_HOME=/root/.claude"
        -e "CODEX_HOME=/root/.codex"
        -e "FORGE_TEST_REPO=/workspace"
        -e "FORGE_DEBUG=1"
        -e "FORGE_QA_WHEEL_PATH=$WHEEL_PATH"
        -e "FORGE_QA_WHEEL_FILENAME=$WHEEL_FILENAME"
        -e "FORGE_QA_WHEEL_SHA256=$WHEEL_SHA256"
        -e "FORGE_QA_FORGE_VERSION=$FORGE_VERSION"
        -e "FORGE_QA_ARTIFACT_MODE=$ARTIFACT_MODE"
        -e "FORGE_QA_RUNTIME_TRACK=$RUNTIME_TRACK"
        -e "FORGE_QA_RUNTIME_TRACK_BLOCKING=$RUNTIME_TRACK_BLOCKING"
        -e "FORGE_QA_CLAUDE_VERSION=$CLAUDE_VERSION"
        -e "FORGE_QA_CODEX_VERSION=$CODEX_VERSION"
        -e "FORGE_QA_CODEX_AUTH_MODE=$CODEX_AUTH_MODE"
        -e "FORGE_QA_PROVIDER_PROFILE=$FORGE_QA_PROVIDER_PROFILE"
        -e "FORGE_QA_OPENAI_TEMPLATE=$FORGE_QA_OPENAI_TEMPLATE"
        -e "FORGE_QA_GEMINI_TEMPLATE=$FORGE_QA_GEMINI_TEMPLATE"
        -e "FORGE_QA_ANTHROPIC_TEMPLATE=$FORGE_QA_ANTHROPIC_TEMPLATE"
        -e "FORGE_QA_OPENAI_PROXY=$FORGE_QA_OPENAI_PROXY"
        -e "FORGE_QA_GEMINI_PROXY=$FORGE_QA_GEMINI_PROXY"
        -e "FORGE_QA_ANTHROPIC_PROXY=$FORGE_QA_ANTHROPIC_PROXY"
        -e "FORGE_QA_WORKFLOW_MODELS=$FORGE_QA_WORKFLOW_MODELS"
        -e "FORGE_QA_WORKFLOW_MODEL_A=$FORGE_QA_WORKFLOW_MODEL_A"
        -e "FORGE_QA_WORKFLOW_MODEL_B=$FORGE_QA_WORKFLOW_MODEL_B"
        -e "FORGE_QA_DEEPSEEK_TEMPLATE=${FORGE_QA_DEEPSEEK_TEMPLATE:-}"
        -e "FORGE_QA_MINIMAX_TEMPLATE=${FORGE_QA_MINIMAX_TEMPLATE:-}"
    )

    local var
    for var in \
        GEMINI_API_KEY \
        ANTHROPIC_API_KEY \
        CODEX_API_KEY \
        LITELLM_API_KEY \
        LITELLM_BASE_URL \
        OPENAI_API_KEY \
        OPENROUTER_API_KEY \
        OPENROUTER_BASE_URL; do
        if [[ "$var" == "CODEX_API_KEY" && "$CODEX_AUTH_MODE" == "explicit-file" ]]; then
            continue
        fi
        if [[ -n "${!var:-}" ]]; then
            args+=(-e "$var=${!var}")
        fi
    done

    DOCKER_ENV=("${args[@]}")
}

json_field() {
    python3 -c 'import json,sys; value=json.loads(sys.argv[1])[sys.argv[2]]; print(str(value).lower() if isinstance(value, bool) else value)' "$1" "$2"
}

prepare_artifact() {
    if [[ ! -f "$RUNTIME_MATRIX" ]]; then
        error "Runtime matrix not found: $RUNTIME_MATRIX"
        exit 2
    fi
    if [[ ! -x "$ARTIFACT_HELPER" ]]; then
        error "Artifact validator not found or not executable: $ARTIFACT_HELPER"
        exit 2
    fi

    if [[ -z "$WHEEL_PATH" ]]; then
        ARTIFACT_MODE="development-build"
        if ! command -v uv &>/dev/null; then
            error "uv is required to build the default QA wheel; pass --wheel with a prebuilt artifact instead"
            exit 2
        fi
        local artifact_build_dir
        artifact_build_dir="$(mktemp -d "$HOST_STATE_DIR/artifacts/build.XXXXXX")"
        info "Building one development QA wheel in $artifact_build_dir ..."
        if ! (cd "$REPO_ROOT" && uv build --wheel --out-dir "$artifact_build_dir"); then
            error "Wheel build failed."
            exit 2
        fi
        local built_wheels=()
        shopt -s nullglob
        built_wheels=("$artifact_build_dir"/*.whl)
        shopt -u nullglob
        if [[ "${#built_wheels[@]}" -ne 1 ]]; then
            error "Wheel build must produce exactly one artifact; found ${#built_wheels[@]} in $artifact_build_dir"
            exit 2
        fi
        WHEEL_PATH="${built_wheels[0]}"
        info "Development artifact retained at $WHEEL_PATH"
    else
        ARTIFACT_MODE="prebuilt"
    fi

    local artifact_json
    if ! artifact_json="$(python3 "$ARTIFACT_HELPER" \
        --wheel "$WHEEL_PATH" \
        --matrix "$RUNTIME_MATRIX" \
        --runtime-track "$RUNTIME_TRACK")"; then
        exit 2
    fi

    WHEEL_PATH="$(json_field "$artifact_json" wheel_path)"
    WHEEL_FILENAME="$(json_field "$artifact_json" wheel_filename)"
    WHEEL_SHA256="$(json_field "$artifact_json" sha256)"
    FORGE_VERSION="$(json_field "$artifact_json" forge_version)"
    RUNTIME_TRACK_BLOCKING="$(json_field "$artifact_json" runtime_track_blocking)"
    CLAUDE_VERSION="$(json_field "$artifact_json" claude_version)"
    CODEX_VERSION="$(json_field "$artifact_json" codex_version)"
    BASE_IMAGE_NAME="$(json_field "$artifact_json" base_image)"
    IMAGE_NAME="$(json_field "$artifact_json" release_image)"

    if [[ -n "$CODEX_AUTH_FILE" ]]; then
        if [[ ! -f "$CODEX_AUTH_FILE" ]]; then
            error "Codex auth source is not a regular file: $CODEX_AUTH_FILE"
            exit 2
        fi
        CODEX_AUTH_FILE="$(python3 -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).expanduser().resolve(strict=True))' "$CODEX_AUTH_FILE")"
    fi
}

runtime_output_matches_pin() {
    local observed="$1"
    local expected="$2"
    python3 -c 'import re,sys; raise SystemExit(0 if re.search(r"(?<![0-9.])" + re.escape(sys.argv[2]) + r"(?![0-9.])", sys.argv[1]) else 1)' \
        "$observed" "$expected"
}

record_artifact_identity() {
    local claude_observed codex_observed
    claude_observed="$(docker exec "$CONTAINER_NAME" claude --version 2>&1 | head -n 1)" || {
        error "Claude version probe failed in release-QA container."
        exit 3
    }
    codex_observed="$(docker exec "$CONTAINER_NAME" codex --version 2>&1 | head -n 1)" || {
        error "Codex version probe failed in release-QA container."
        exit 3
    }

    if [[ "$RUNTIME_TRACK" == "pinned" ]]; then
        if ! runtime_output_matches_pin "$claude_observed" "$CLAUDE_VERSION"; then
            error "Claude runtime mismatch: expected $CLAUDE_VERSION, observed '$claude_observed'."
            exit 3
        fi
        if ! runtime_output_matches_pin "$codex_observed" "$CODEX_VERSION"; then
            error "Codex runtime mismatch: expected $CODEX_VERSION, observed '$codex_observed'."
            exit 3
        fi
    fi

    python3 - \
        "$HOST_STATE_DIR/artifact.json" \
        "$WHEEL_PATH" \
        "$WHEEL_FILENAME" \
        "$WHEEL_SHA256" \
        "$FORGE_VERSION" \
        "$ARTIFACT_MODE" \
        "$BASE_IMAGE_NAME" \
        "$IMAGE_NAME" \
        "$FORGE_REV" \
        "$RUNTIME_TRACK" \
        "$RUNTIME_TRACK_BLOCKING" \
        "$CLAUDE_VERSION" \
        "$claude_observed" \
        "$CODEX_VERSION" \
        "$codex_observed" \
        "$CODEX_AUTH_MODE" \
        "$FORGE_QA_PROVIDER_PROFILE" \
        "$CONTAINER_NAME" <<'PY'
import json
import sys
from pathlib import Path

(
    output,
    wheel_path,
    wheel_filename,
    wheel_sha256,
    forge_version,
    artifact_mode,
    base_image,
    release_image,
    forge_revision,
    runtime_track,
    runtime_track_blocking,
    claude_pin,
    claude_observed,
    codex_pin,
    codex_observed,
    codex_auth_mode,
    provider_profile,
    container,
) = sys.argv[1:]
payload = {
    "schema_version": 1,
    "artifact": {
        "path": wheel_path,
        "filename": wheel_filename,
        "sha256": wheel_sha256,
        "forge_version": forge_version,
        "mode": artifact_mode,
    },
    "image": {
        "base": base_image,
        "release": release_image,
        "forge_revision": forge_revision,
    },
    "runtime": {
        "track": runtime_track,
        "blocking": runtime_track_blocking == "true",
        "claude": {"pin": claude_pin, "observed": claude_observed},
        "codex": {"pin": codex_pin, "observed": codex_observed},
        "codex_auth_mode": codex_auth_mode,
    },
    "provider_profile": provider_profile,
    "container": container,
}
path = Path(output)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

install_codex_auth() {
    docker exec "$CONTAINER_NAME" bash -c 'mkdir -p /root/.codex && chmod 700 /root/.codex'
    if [[ "$CODEX_AUTH_MODE" == "explicit-file" ]]; then
        if ! docker cp "$CODEX_AUTH_FILE" "$CONTAINER_NAME:/root/.codex/auth.json" >/dev/null; then
            error "Failed to copy the selected Codex auth file."
            exit 3
        fi
        docker exec "$CONTAINER_NAME" chmod 600 /root/.codex/auth.json
    else
        docker exec "$CONTAINER_NAME" rm -f /root/.codex/auth.json
    fi
}

# Mount the host QA state in the container.
HOST_STATE_DIR_RAW="${FORGE_HOME:-$HOME/.forge}/manual-testing/qa"
HOST_STATE_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(os.path.expandvars(sys.argv[1]))))' "$HOST_STATE_DIR_RAW")"
mkdir -p "$HOST_STATE_DIR/artifacts"

# Require a running Docker daemon.
if ! command -v docker &> /dev/null; then
    error "Docker command not found. Install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null; then
    error "Docker daemon is not running. Start Docker Desktop and try again."
    exit 1
fi

# Stop and remove the container.
if [[ "$ACTION" == "stop" ]]; then
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

# Report container status.
if [[ "$ACTION" == "status" ]]; then
    if docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
        info "Container $CONTAINER_NAME is running."
        forge_ver="$(docker exec "$CONTAINER_NAME" /opt/forge-qa/bin/forge --version 2>/dev/null || echo "unknown")"
        info "Forge: $forge_ver"
        status_label() {
            local label_key="$1"
            local value
            value="$(docker inspect -f "{{ index .Config.Labels \"$label_key\" }}" "$CONTAINER_NAME" 2>/dev/null || true)"
            printf '%s' "${value:-unknown}"
        }
        info "Repository revision: $(status_label "org.opencontainers.image.revision")"
        info "Wheel path: $(status_label "io.multi-forge.qa.wheel-path")"
        info "Wheel SHA-256: $(status_label "io.multi-forge.qa.wheel-sha256")"
        info "Artifact mode: $(status_label "io.multi-forge.qa.artifact-mode")"
        info "Runtime track: $(status_label "io.multi-forge.qa.runtime-track")"
        info "Claude version: $(status_label "io.multi-forge.qa.claude-version")"
        info "Codex version: $(status_label "io.multi-forge.qa.codex-version")"
        info "Codex auth mode: $(status_label "io.multi-forge.qa.codex-auth-mode")"
        info "QA provider profile: $(status_label "io.multi-forge.qa.provider-profile")"
        info "Image: $(docker inspect -f '{{ .Config.Image }}' "$CONTAINER_NAME" 2>/dev/null || echo "unknown")"
        exit 0
    elif docker ps -aq -f "name=^${CONTAINER_NAME}$" | grep -q .; then
        info "Container $CONTAINER_NAME exists but is stopped."
        exit 1
    else
        info "No container named $CONTAINER_NAME."
        exit 1
    fi
fi

# Use the repository revision to detect stale containers and images.
FORGE_REV="$(get_forge_rev)"
prepare_artifact
load_qa_env
if [[ -n "$CODEX_AUTH_FILE" ]]; then
    CODEX_AUTH_MODE="explicit-file"
elif [[ -n "${CODEX_API_KEY:-}" ]]; then
    CODEX_AUTH_MODE="api-key"
else
    CODEX_AUTH_MODE="none"
fi

require_container_label() {
    local label_key="$1"
    local expected="$2"
    local label_name="$3"
    local actual
    actual="$(docker inspect -f "{{ index .Config.Labels \"$label_key\" }}" "$CONTAINER_NAME" 2>/dev/null || true)"
    if [[ -z "$actual" || "$actual" != "$expected" ]]; then
        error "Running container '$CONTAINER_NAME' has stale $label_name (${actual:-<missing>}); expected $expected."
        if [[ "$label_key" == "io.multi-forge.qa.artifact-mode" ]] && \
            [[ "$actual" == "development-build" || "$expected" == "development-build" ]]; then
            error "Development QA runs are single-invocation; only runs started with --wheel are resumable."
        fi
        error "Rerun QA with --reset to rebuild, or 'bash start-container.sh --stop' to remove it."
        exit 3
    fi
}

# Reuse a current running container.
if [[ "$RESET" != "true" && "$RUNTIME_TRACK" == "latest" ]] \
    && docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
    error "The latest compatibility track does not reuse a running QA container."
    error "Rerun with --reset so client packages are resolved again, or stop the existing container first."
    exit 3
fi

if [[ "$RESET" != "true" ]] && docker ps -q -f "name=^${CONTAINER_NAME}$" | grep -q .; then
    # Refuse reuse unless every input that defines release evidence is equal.
    # Matching a checkout revision alone is insufficient: two wheel digests or
    # runtime tracks can intentionally share that revision.
    require_container_label "org.opencontainers.image.revision" "$FORGE_REV" "repository revision"
    require_container_label "io.multi-forge.qa.wheel-sha256" "$WHEEL_SHA256" "wheel SHA-256"
    require_container_label "io.multi-forge.qa.forge-version" "$FORGE_VERSION" "Forge version"
    require_container_label "io.multi-forge.qa.runtime-track" "$RUNTIME_TRACK" "runtime track"
    require_container_label "io.multi-forge.qa.claude-version" "$CLAUDE_VERSION" "Claude version"
    require_container_label "io.multi-forge.qa.codex-version" "$CODEX_VERSION" "Codex version"
    require_container_label "io.multi-forge.qa.provider-profile" "$FORGE_QA_PROVIDER_PROFILE" "provider profile"
    require_container_label "io.multi-forge.qa.artifact-mode" "$ARTIFACT_MODE" "artifact mode"
    require_container_label "io.multi-forge.qa.wheel-path" "$WHEEL_PATH" "wheel path"
    require_container_label "io.multi-forge.qa.codex-auth-mode" "$CODEX_AUTH_MODE" "Codex auth mode"
    running_image="$(docker inspect -f '{{ .Config.Image }}' "$CONTAINER_NAME" 2>/dev/null || true)"
    if [[ "$running_image" != "$IMAGE_NAME" ]]; then
        error "Running container '$CONTAINER_NAME' uses ${running_image:-<unknown>}, expected $IMAGE_NAME."
        error "Rerun QA with --reset or stop the existing container."
        exit 3
    fi
    existing_profile="$(docker exec "$CONTAINER_NAME" sh -c 'printf "%s" "${FORGE_QA_PROVIDER_PROFILE:-}"' 2>/dev/null || true)"
    if [[ "$existing_profile" != "$FORGE_QA_PROVIDER_PROFILE" ]]; then
        error "Running container '$CONTAINER_NAME' was created with provider profile '${existing_profile:-unknown}', not '$FORGE_QA_PROVIDER_PROFILE'."
        error "Run 'bash start-container.sh --stop' or rerun QA with --reset before switching provider profiles."
        exit 3
    fi
    for wf_var in FORGE_QA_WORKFLOW_MODELS FORGE_QA_WORKFLOW_MODEL_A FORGE_QA_WORKFLOW_MODEL_B; do
        wf_expected="${!wf_var}"
        wf_actual="$(docker exec "$CONTAINER_NAME" sh -c "printf '%s' \"\${${wf_var}:-}\"" 2>/dev/null || true)"
        if [[ "$wf_actual" != "$wf_expected" ]]; then
            error "Running container '$CONTAINER_NAME' has $wf_var='${wf_actual:-<unset>}', expected '$wf_expected'."
            error "Run 'bash start-container.sh --stop' then restart, or rerun QA with --reset."
            exit 3
        fi
    done
    validate_running_container_profile
    install_codex_auth
    record_artifact_identity
    info "Reusing running container: $CONTAINER_NAME"
    echo "$CONTAINER_NAME"
    exit 0
fi

validate_provider_profile

# Reset the wheel-backed release layer while retaining the separately keyed runtime base.
if [[ "$RESET" == "true" ]]; then
    info "Rebuild: removing container and wheel-backed release image..."
    docker stop "$CONTAINER_NAME" > /dev/null 2>&1 || true
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
    docker rmi "$IMAGE_NAME" > /dev/null 2>&1 || true
    info "Release layer removed. Rebuilding against the selected runtime base..."
fi

# Remove a stopped container that uses the target name.
if docker ps -aq -f "name=^${CONTAINER_NAME}$" | grep -q .; then
    info "Removing stopped container: $CONTAINER_NAME"
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1 || true
fi

if [[ ! -f "$BASE_DOCKERFILE" || ! -f "$QA_DOCKERFILE" ]]; then
    error "Release QA requires $BASE_DOCKERFILE and $QA_DOCKERFILE"
    error "Run the harness from a Forge source checkout."
    exit 2
fi

# Keep the editable base shared with integration runners, but install the exact
# wheel into a separately named release image.
base_needs_build=false
if [[ "$RUNTIME_TRACK" == "latest" ]] || ! docker image inspect "$BASE_IMAGE_NAME" &>/dev/null; then
    base_needs_build=true
else
    base_rev="$(docker image inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$BASE_IMAGE_NAME" 2>/dev/null || true)"
    if [[ "$base_rev" != "$FORGE_REV" ]]; then
        base_needs_build=true
    fi
fi
if [[ "$base_needs_build" == "true" ]]; then
    info "Building $RUNTIME_TRACK runtime base: $BASE_IMAGE_NAME"
    base_build_args=(
        -f "$BASE_DOCKERFILE"
        --build-arg "CLAUDE_VERSION=$CLAUDE_VERSION"
        --build-arg "CODEX_VERSION=$CODEX_VERSION"
        --build-arg "FORGE_REV=$FORGE_REV"
        -t "$BASE_IMAGE_NAME"
        "$REPO_ROOT"
    )
    if [[ "$RUNTIME_TRACK" == "latest" ]]; then
        base_build_args=(--pull --no-cache "${base_build_args[@]}")
    fi
    if ! docker build "${base_build_args[@]}"; then
        error "Pinned runtime base build failed."
        exit 2
    fi
fi

release_needs_build=false
if [[ "$RUNTIME_TRACK" == "latest" ]] || ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    release_needs_build=true
else
    for image_contract in \
        "org.opencontainers.image.revision=$FORGE_REV" \
        "io.multi-forge.qa.wheel-sha256=$WHEEL_SHA256" \
        "io.multi-forge.qa.forge-version=$FORGE_VERSION" \
        "io.multi-forge.qa.runtime-track=$RUNTIME_TRACK" \
        "io.multi-forge.qa.claude-version=$CLAUDE_VERSION" \
        "io.multi-forge.qa.codex-version=$CODEX_VERSION"; do
        image_label_key="${image_contract%%=*}"
        image_label_expected="${image_contract#*=}"
        image_label_actual="$(docker image inspect -f "{{ index .Config.Labels \"$image_label_key\" }}" "$IMAGE_NAME" 2>/dev/null || true)"
        if [[ "$image_label_actual" != "$image_label_expected" ]]; then
            release_needs_build=true
            break
        fi
    done
fi
if [[ "$release_needs_build" == "true" ]]; then
    info "Installing exact wheel into release QA image: $IMAGE_NAME"
    RELEASE_BUILD_CONTEXT="$(mktemp -d "$HOST_STATE_DIR/artifacts/docker-context.XXXXXX")"
    if ! cp "$WHEEL_PATH" "$RELEASE_BUILD_CONTEXT/$WHEEL_FILENAME"; then
        error "Could not stage the release wheel in its isolated Docker build context."
        exit 2
    fi
    release_build_args=(
        -f "$QA_DOCKERFILE"
        --build-arg "BASE_IMAGE=$BASE_IMAGE_NAME"
        --build-arg "FORGE_WHEEL_NAME=$WHEEL_FILENAME"
        --build-arg "FORGE_WHEEL_SHA256=$WHEEL_SHA256"
        --build-arg "FORGE_VERSION=$FORGE_VERSION"
        --build-arg "FORGE_REV=$FORGE_REV"
        --build-arg "RUNTIME_TRACK=$RUNTIME_TRACK"
        --build-arg "CLAUDE_VERSION=$CLAUDE_VERSION"
        --build-arg "CODEX_VERSION=$CODEX_VERSION"
        -t "$IMAGE_NAME"
        "$RELEASE_BUILD_CONTEXT"
    )
    if [[ "$RUNTIME_TRACK" == "latest" ]]; then
        release_build_args=(--no-cache "${release_build_args[@]}")
    fi
    if ! docker build "${release_build_args[@]}"; then
        error "Release QA image build failed."
        exit 2
    fi
    cleanup_release_build_context
fi

# Start the container.
info "Starting container: $CONTAINER_NAME"
DOCKER_ENV=()
docker_env_args
if ! docker run -d \
    --name "$CONTAINER_NAME" \
    --label "io.multi-forge.qa.provider-profile=$FORGE_QA_PROVIDER_PROFILE" \
    --label "io.multi-forge.qa.artifact-mode=$ARTIFACT_MODE" \
    --label "io.multi-forge.qa.wheel-path=$WHEEL_PATH" \
    --label "io.multi-forge.qa.codex-auth-mode=$CODEX_AUTH_MODE" \
    "${DOCKER_ENV[@]}" \
    -v "$HOST_STATE_DIR:/workspace/.forge/qa" \
    -w /workspace \
    "$IMAGE_NAME" \
    tail -f /dev/null > /dev/null; then
    error "Failed to start container."
    exit 3
fi

# Remove leaked .env files before importing Forge. A stale image can contain files
# excluded by current .dockerignore rules, and load_dotenv() would import their values.
docker exec "$CONTAINER_NAME" bash -c 'rm -f /forge/.env /forge/.env.*'

# Codex auth ingress is deliberately narrow: an environment key or one
# explicitly selected auth.json. Never mount or copy the rest of host CODEX_HOME.
install_codex_auth

# Run the container preflight.
info "Running preflight checks..."

# Set a profile for interactive debugging shells. Checklist execution relies on
# docker run -e above so plain docker exec calls see the same values.
{
    echo 'export PATH="/opt/forge-qa/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"'
    echo 'export PYTHONNOUSERSITE="1"'
    echo 'export FORGE_HOME="/root/.forge"'
    echo 'export CLAUDE_HOME="/root/.claude"'
    echo 'export CODEX_HOME="/root/.codex"'
    echo 'export FORGE_TEST_REPO="/workspace"'
    # QA defaults to debug logging so every Forge command leaves evidence.
    echo 'export FORGE_DEBUG="1"'
    for var in \
        FORGE_QA_PROVIDER_PROFILE \
        FORGE_QA_OPENAI_TEMPLATE \
        FORGE_QA_GEMINI_TEMPLATE \
        FORGE_QA_ANTHROPIC_TEMPLATE \
        FORGE_QA_OPENAI_PROXY \
        FORGE_QA_GEMINI_PROXY \
        FORGE_QA_ANTHROPIC_PROXY \
        FORGE_QA_WORKFLOW_MODELS \
        FORGE_QA_WORKFLOW_MODEL_A \
        FORGE_QA_WORKFLOW_MODEL_B \
        FORGE_QA_DEEPSEEK_TEMPLATE \
        FORGE_QA_MINIMAX_TEMPLATE \
        FORGE_QA_WHEEL_PATH \
        FORGE_QA_WHEEL_FILENAME \
        FORGE_QA_WHEEL_SHA256 \
        FORGE_QA_FORGE_VERSION \
        FORGE_QA_ARTIFACT_MODE \
        FORGE_QA_RUNTIME_TRACK \
        FORGE_QA_RUNTIME_TRACK_BLOCKING \
        FORGE_QA_CLAUDE_VERSION \
        FORGE_QA_CODEX_VERSION \
        FORGE_QA_CODEX_AUTH_MODE \
        GEMINI_API_KEY \
        ANTHROPIC_API_KEY \
        CODEX_API_KEY \
        LITELLM_API_KEY \
        LITELLM_BASE_URL \
        OPENAI_API_KEY \
        OPENROUTER_API_KEY \
        OPENROUTER_BASE_URL; do
        if [[ "$var" == "CODEX_API_KEY" && "$CODEX_AUTH_MODE" == "explicit-file" ]]; then
            continue
        fi
        if [[ -n "${!var:-}" ]]; then
            printf 'export %s=%q\n' "$var" "${!var}"
        fi
    done
} | docker exec -i "$CONTAINER_NAME" bash -c 'cat > /etc/profile.d/forge-qa.sh && chmod 600 /etc/profile.d/forge-qa.sh' || {
    error "Failed to write /etc/profile.d/forge-qa.sh"
    exit 3
}

docker exec "$CONTAINER_NAME" bash -lc 'test "$(command -v forge)" = /opt/forge-qa/bin/forge' || {
    error "forge does not resolve to the isolated wheel environment"
    exit 3
}

# Use ANTHROPIC_API_KEY as the only Claude Code authentication mechanism.
# Mark onboarding complete to bypass the first-run screen. Section 2 runs
# `forge extension enable`, which adds hooks to the initially empty settings.json.
# See: github.com/anthropics/claude-code/issues/9699
docker exec "$CONTAINER_NAME" bash -c 'mkdir -p /root/.claude'

docker exec -i "$CONTAINER_NAME" bash -c 'cat > /root/.claude/settings.json && chmod 600 /root/.claude/settings.json' <<'SETTINGSEOF'
{}
SETTINGSEOF

docker exec -i "$CONTAINER_NAME" bash -c 'cat > /root/.claude.json && chmod 600 /root/.claude.json' <<'ONBOARDEOF'
{"hasCompletedOnboarding":true}
ONBOARDEOF

docker exec "$CONTAINER_NAME" bash -lc 'cd /workspace && /opt/forge-qa/bin/python -I -c '\''
import importlib.metadata as metadata
import importlib.resources as resources
import os
import pathlib
import sys
import forge
from forge.install.installer import get_extensions_root

prefix = pathlib.Path("/opt/forge-qa")
assert metadata.version("multi-forge") == os.environ["FORGE_QA_FORGE_VERSION"]
assert forge.__version__ == os.environ["FORGE_QA_FORGE_VERSION"]
assert pathlib.Path(forge.__file__).is_relative_to(prefix)
assert pathlib.Path(str(resources.files("forge"))).is_relative_to(prefix)
extensions = get_extensions_root()
assert extensions.is_relative_to(prefix)
assert (extensions / "skills" / "qa" / "SKILL.md").is_file()
qa = extensions / "skills" / "qa"
for relative in (
    "resources/checklist.md",
    "resources/coverage-map.md",
    "resources/execution-budget.json",
    "resources/report-template.md",
    "resources/runtime-matrix.json",
    "scripts/qa-artifact.py",
    "scripts/qa-run-metrics.py",
    "scripts/qa-selection.py",
    "scripts/start-container.sh",
    "scripts/walkthrough-state.py",
):
    assert (qa / relative).is_file(), relative
assert len(list((qa / "resources/checklist").glob("*.md"))) == 21
assert all(not pathlib.Path(entry or ".").resolve().is_relative_to("/forge") for entry in sys.path)
'\''' || {
    error "Forge provenance preflight did not resolve exclusively from the exact wheel."
    exit 3
}

record_artifact_identity

# Initialize the workspace.
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
