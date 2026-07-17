#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
STAGES=(
    00-preflight
    10-user-discovery
    20-project-discovery
    30-duplicate-discovery
    40-invocation-policy
    50-script-resolution
    60-symlink-reload
)

resolve_stage() {
    local wanted="$1" stage
    for stage in "${STAGES[@]}"; do
        case "$stage" in "$wanted" | "$wanted"-*)
            printf '%s\n' "$stage"
            return 0
            ;;
        esac
    done
    echo "ERROR: unknown stage '$wanted'" >&2
    return 1
}

selected=()
if [ "$#" -eq 0 ]; then
    selected=("${STAGES[@]}")
else
    for arg in "$@"; do
        stage="$(resolve_stage "$arg")" || exit 1
        selected+=("$stage")
    done
fi

failed=()
for stage in "${selected[@]}"; do
    echo "==================== $stage ===================="
    if ! bash "$HERE/stages/$stage.sh"; then
        failed+=("$stage")
    fi
done

if [ "${#failed[@]}" -gt 0 ]; then
    echo "Failed stages: ${failed[*]}" >&2
    exit 1
fi
echo "All requested stages passed. Captures: ${CODEX_SKILLS_CAPTURE_DIR:-$HOME/.cache/forge-codex-skills-probe}"
