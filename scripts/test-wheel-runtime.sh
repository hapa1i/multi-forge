#!/usr/bin/env bash
set -euo pipefail

SMOKE_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_UNCONSTRAINED=false
if [[ "${1:-}" == "--unconstrained" && "$#" -eq 1 ]]; then
    SMOKE_UNCONSTRAINED=true
elif [[ "$#" -ne 0 ]]; then
    echo "Usage: $0 [--unconstrained]" >&2
    exit 2
fi

SMOKE_TEMP_BASE="${TMPDIR:-/tmp}"
SMOKE_TEMP_BASE="${SMOKE_TEMP_BASE%/}"
SMOKE_ROOT="$(mktemp -d "${SMOKE_TEMP_BASE}/multi-forge-wheel-smoke.XXXXXX")"
SMOKE_DIST="${SMOKE_ROOT}/dist"
SMOKE_VENV="${SMOKE_ROOT}/venv"
SMOKE_FORGE_HOME="${SMOKE_ROOT}/forge-home"
SMOKE_PORT="${FORGE_WHEEL_SMOKE_PORT:-49176}"
SMOKE_PYTHON="${FORGE_WHEEL_SMOKE_PYTHON:->=3.11,<3.14}"
SMOKE_STARTED=false

cleanup() {
    local smoke_exit_status=$?
    local smoke_cleanup_status=0
    local smoke_backend_log="${SMOKE_FORGE_HOME}/logs/backend/litellm-${SMOKE_PORT}.log"
    if [[ "$smoke_exit_status" -ne 0 && -f "$smoke_backend_log" ]]; then
        echo "LiteLLM backend log before cleanup:" >&2
        tail -n 200 "$smoke_backend_log" >&2 || true
    fi

    if [[ "$SMOKE_STARTED" == "true" ]]; then
        if FORGE_HOME="$SMOKE_FORGE_HOME" \
            "${SMOKE_VENV}/bin/python" -B "${SMOKE_REPO_ROOT}/scripts/wheel-smoke-cleanup.py" \
            "$SMOKE_FORGE_HOME" "${SMOKE_VENV}/bin/forge" "$SMOKE_PORT"; then
            :
        else
            smoke_cleanup_status=$?
        fi
    fi

    if [[ "$smoke_cleanup_status" -eq 0 ]]; then
        case "$SMOKE_ROOT" in
            "${SMOKE_TEMP_BASE}"/multi-forge-wheel-smoke.*)
                rm -rf -- "$SMOKE_ROOT" || smoke_cleanup_status=$?
                ;;
        esac
    fi
    if [[ "$smoke_cleanup_status" -ne 0 ]]; then
        echo "Wheel smoke cleanup incomplete; retained evidence at $SMOKE_ROOT" >&2
        if [[ "$smoke_exit_status" -eq 0 && -f "$smoke_backend_log" ]]; then
            tail -n 200 "$smoke_backend_log" >&2 || true
        fi
    fi
    if [[ "$smoke_exit_status" -ne 0 ]]; then
        exit "$smoke_exit_status"
    fi
    exit "$smoke_cleanup_status"
}
trap cleanup EXIT

mkdir -p "$SMOKE_DIST"
uv build "$SMOKE_REPO_ROOT" --wheel --out-dir "$SMOKE_DIST" \
    --build-constraints "$SMOKE_REPO_ROOT/requirements/build.txt" --require-hashes
uv venv --python "$SMOKE_PYTHON" "$SMOKE_VENV"

SMOKE_WHEELS=("$SMOKE_DIST"/multi_forge-*.whl)
if [[ "${#SMOKE_WHEELS[@]}" -ne 1 || ! -f "${SMOKE_WHEELS[0]}" ]]; then
    echo "Expected exactly one multi-forge wheel in $SMOKE_DIST" >&2
    exit 1
fi

if [[ "$SMOKE_UNCONSTRAINED" == "true" ]]; then
    # Consumer resolution must not inherit this checkout's reviewed constraints.
    env -u UV_BUILD_CONSTRAINT -u UV_CONSTRAINT -u UV_OVERRIDE -u UV_EXCLUDE \
        -u UV_EXCLUDE_NEWER -u UV_CONFIG_FILE \
        uv pip install --no-config --python "${SMOKE_VENV}/bin/python" "${SMOKE_WHEELS[0]}"
else
    uv export --project "$SMOKE_REPO_ROOT" --locked --no-dev --no-emit-project \
        --output-file "$SMOKE_ROOT/runtime.txt" >/dev/null
    uv pip install --no-config --python "${SMOKE_VENV}/bin/python" --require-hashes --no-build -r "$SMOKE_ROOT/runtime.txt"
    uv pip install --python "${SMOKE_VENV}/bin/python" --no-deps "${SMOKE_WHEELS[0]}"
fi
uv pip check --python "${SMOKE_VENV}/bin/python"
"${SMOKE_VENV}/bin/python" -c '
from forge.cli.statusline.registry import SEGMENTS
from forge.core.models.model_practices import load_model_practices
from forge.core.ops.session_model import SessionModelReport

catalog = load_model_practices(force_reload=True)
assert catalog.schema_version == 1
assert catalog.models == {}
assert SessionModelReport({"schema_version": 1}).to_dict() == {"schema_version": 1}
assert any(segment.name == "marking" for segment in SEGMENTS)
'

export FORGE_HOME="$SMOKE_FORGE_HOME"
export LITELLM_LOCAL_MODEL_COST_MAP=true
"${SMOKE_VENV}/bin/forge" model backend create litellm
SMOKE_STARTED=true
"${SMOKE_VENV}/bin/forge" model backend start litellm --port "$SMOKE_PORT"

SMOKE_HEALTH_OK=false
for _ in {1..40}; do
    if curl -fsS "http://127.0.0.1:${SMOKE_PORT}/health/liveliness" >/dev/null; then
        SMOKE_HEALTH_OK=true
        break
    fi
    sleep 0.25
done

if [[ "$SMOKE_HEALTH_OK" != "true" ]]; then
    echo "Packaged LiteLLM backend did not become healthy on port $SMOKE_PORT" >&2
    exit 1
fi

echo "Clean wheel install and LiteLLM start/health smoke passed."
