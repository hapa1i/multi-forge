#!/usr/bin/env bash
# Remove only resources with fixed walkthrough ownership. Invoke through run-in-repo.sh.

set -euo pipefail

PHASE="${1:-all}"
if [[ "$PHASE" != "runtime" && "$PHASE" != "extensions" && "$PHASE" != "all" ]]; then
    echo "ERROR: cleanup phase must be runtime, extensions, or all" >&2
    exit 2
fi

test -f .forge-walkthrough-marker
test "$PWD" = "$FORGE_TEST_REPO"

session_is_listed() {
    local session_name="$1"
    local rows
    if ! rows="$(forge session list --scope all --include-incognito --json)"; then
        echo "ERROR: Could not inspect the session index before cleanup" >&2
        return 2
    fi
    printf '%s\n' "$rows" | python3 -c '
import json
import sys

name = sys.argv[1]
try:
    rows = json.load(sys.stdin)
except (json.JSONDecodeError, OSError):
    raise SystemExit(2)
if not isinstance(rows, list):
    raise SystemExit(2)
if any(not isinstance(row, dict) for row in rows):
    raise SystemExit(2)
raise SystemExit(0 if any(row.get("name", row.get("session_name")) == name for row in rows) else 1)
' "$session_name"
}

owned_proxy_status() {
    local rows
    if ! rows="$(forge proxy list --json)"; then
        echo "ERROR: Could not inspect the proxy registry before cleanup" >&2
        return 2
    fi
    printf '%s\n' "$rows" | python3 -c '
import json
import sys

try:
    rows = json.load(sys.stdin)
except (json.JSONDecodeError, OSError):
    raise SystemExit(2)
if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
    raise SystemExit(2)
matches = [row for row in rows if row.get("proxy_id") == "walkthrough-sidecar-proxy"]
if not matches:
    raise SystemExit(1)
if len(matches) != 1 or matches[0].get("template") != "openrouter-anthropic":
    raise SystemExit(3)
raise SystemExit(0)
'
}

cleanup_runtime() {
    local session_name
    for session_name in \
        walkthrough-codex \
        walkthrough-sidecar \
        walkthrough-continuation \
        walkthrough-incognito \
        walkthrough-demo; do
        if session_is_listed "$session_name"; then
            forge session delete "$session_name" --yes --force
        else
            local lookup_status=$?
            if [ "$lookup_status" -ne 1 ]; then
                echo "ERROR: Could not prove whether $session_name is walkthrough-owned index state" >&2
                exit 1
            fi
            if [ -e ".forge/sessions/$session_name" ] || [ -L ".forge/sessions/$session_name" ]; then
                echo "ERROR: $session_name has on-disk state but is absent from the session index; refusing cleanup" >&2
                exit 1
            fi
        fi
    done

    local proxy_dir="$FORGE_HOME/proxies/walkthrough-sidecar-proxy"
    if owned_proxy_status; then
        if [ -L "$proxy_dir" ]; then
            echo "ERROR: Walkthrough sidecar proxy directory is a symlink; refusing cleanup" >&2
            exit 1
        fi
        forge proxy delete walkthrough-sidecar-proxy --yes
    else
        local proxy_status=$?
        if [ "$proxy_status" -eq 2 ]; then
            exit 1
        fi
        if [ "$proxy_status" -eq 3 ]; then
            echo "ERROR: Proxy walkthrough-sidecar-proxy has unexpected identity; refusing cleanup" >&2
            exit 1
        fi
        if [ -e "$proxy_dir" ] || [ -L "$proxy_dir" ]; then
            if [ -L "$proxy_dir" ]; then
                echo "ERROR: Walkthrough sidecar proxy directory is a symlink; refusing cleanup" >&2
                exit 1
            fi
            forge proxy delete walkthrough-sidecar-proxy --yes
        fi
    fi

    if [ "${WALKTHROUGH_SIDECAR_MAY_EXIST:-false}" = "true" ]; then
        if ! command -v docker >/dev/null 2>&1; then
            echo "ERROR: sidecar cleanup was selected but Docker is unavailable" >&2
            exit 1
        fi
        local container_names
        if ! container_names="$(docker ps -a --format '{{.Names}}')"; then
            echo "ERROR: Could not inspect Docker containers before sidecar cleanup" >&2
            exit 1
        fi
        if printf '%s\n' "$container_names" | grep -Fxq forge-walkthrough-sidecar; then
            local project_mount
            if ! project_mount="$(docker inspect \
                --format '{{range .Mounts}}{{if eq .Destination "/workspace"}}{{.Source}}{{end}}{{end}}' \
                forge-walkthrough-sidecar)"; then
                echo "ERROR: Could not inspect the walkthrough sidecar mount before cleanup" >&2
                exit 1
            fi
            project_mount="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$project_mount")"
            if [ "$project_mount" != "$FORGE_TEST_REPO" ]; then
                echo "ERROR: Container forge-walkthrough-sidecar is not mounted from this walkthrough; refusing cleanup" >&2
                exit 1
            fi
            docker rm -f forge-walkthrough-sidecar
        fi
    fi

    rm -rf \
        .forge/artifacts \
        .forge/search-index \
        .forge/prev_sessions/walkthrough-demo \
        .forge/walkthrough/noop-bin
}

scope_is_installed() {
    local scope="$1"
    local status
    if ! status="$(forge extension status --scope "$scope" --json)"; then
        echo "ERROR: Could not inspect the $scope extension installation before cleanup" >&2
        return 2
    fi
    printf '%s\n' "$status" | python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, OSError):
    raise SystemExit(2)
if not isinstance(payload, dict) or not isinstance(payload.get("installations", []), list):
    raise SystemExit(2)
rows = payload.get("installations", [])
raise SystemExit(0 if rows else 1)
'
}

cleanup_extensions() {
    if scope_is_installed local; then
        forge extension disable --scope local --yes
    elif [ "$?" -ne 1 ]; then
        exit 1
    fi
    if scope_is_installed user; then
        forge extension disable --scope user --runtime claude --yes
    elif [ "$?" -ne 1 ]; then
        exit 1
    fi
    git rm --cached --ignore-unmatch -q -- src/greeting.py
    if [ -e src/greeting.py ] || [ -L src/greeting.py ]; then
        if [ ! -f src/greeting.py ] && [ ! -L src/greeting.py ]; then
            echo "ERROR: Walkthrough-owned src/greeting.py is not a file; refusing cleanup" >&2
            exit 1
        fi
        rm -f src/greeting.py
    fi
    rm -rf .codex-user
    mkdir -p .codex-user
    chmod 700 .codex-user
}

if [[ "$PHASE" == "runtime" || "$PHASE" == "all" ]]; then
    cleanup_runtime
fi
if [[ "$PHASE" == "extensions" || "$PHASE" == "all" ]]; then
    cleanup_extensions
fi

echo "Walkthrough-owned $PHASE cleanup complete."
