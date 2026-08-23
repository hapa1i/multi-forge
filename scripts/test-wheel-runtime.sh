#!/usr/bin/env bash
set -euo pipefail

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
    if [[ "$SMOKE_STARTED" == "true" && -x "${SMOKE_VENV}/bin/forge" ]]; then
        FORGE_HOME="$SMOKE_FORGE_HOME" \
            "${SMOKE_VENV}/bin/forge" model backend stop "litellm-${SMOKE_PORT}" >/dev/null 2>&1 || true
    fi

    case "$SMOKE_ROOT" in
        "${SMOKE_TEMP_BASE}"/multi-forge-wheel-smoke.*)
            rm -rf -- "$SMOKE_ROOT"
            ;;
    esac
}
trap cleanup EXIT

mkdir -p "$SMOKE_DIST"
uv build --wheel --out-dir "$SMOKE_DIST"
uv venv --python "$SMOKE_PYTHON" "$SMOKE_VENV"

SMOKE_WHEELS=("$SMOKE_DIST"/multi_forge-*.whl)
if [[ "${#SMOKE_WHEELS[@]}" -ne 1 || ! -f "${SMOKE_WHEELS[0]}" ]]; then
    echo "Expected exactly one multi-forge wheel in $SMOKE_DIST" >&2
    exit 1
fi

uv pip install --python "${SMOKE_VENV}/bin/python" "${SMOKE_WHEELS[0]}"
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
