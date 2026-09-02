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

resolve_forge_python() {
    local forge_launcher
    local forge_real
    local candidate
    if ! forge_launcher="$(command -v forge 2>/dev/null)"; then
        echo "ERROR: Could not resolve the Forge launcher for registry validation" >&2
        return 1
    fi
    forge_real="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$forge_launcher")"
    for candidate in "$(dirname "$forge_real")/python" "$(dirname "$forge_real")/python3"; do
        if [ -x "$candidate" ] && "$candidate" -c 'from forge.install.tracking import TrackingStore' 2>/dev/null; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    echo "ERROR: Could not resolve the Python environment used by Forge: $forge_real" >&2
    return 1
}

check_extension_registry() {
    local expectation="$1"
    local registry="$FORGE_HOME/installed.json"
    if [ ! -e "$registry" ] && [ ! -L "$registry" ]; then
        return 0
    fi
    if [ -L "$registry" ] || [ ! -f "$registry" ]; then
        echo "ERROR: Sandboxed Forge installation registry is not a regular file: $registry" >&2
        return 2
    fi
    local forge_python
    if ! forge_python="$(resolve_forge_python)"; then
        return 2
    fi
    "$forge_python" - "$registry" "$expectation" "$FORGE_TEST_REPO" "$CLAUDE_HOME" <<'PY'
import sys
from pathlib import Path

from forge.install.exceptions import TrackingCorruptedError, TrackingUnreadableError
from forge.install.tracking import TrackingStore

registry = Path(sys.argv[1])
expectation = sys.argv[2]
walkthrough_root = sys.argv[3]
claude_home = Path(sys.argv[4])

try:
    rows = TrackingStore(tracking_path=registry).read().installations
except (OSError, UnicodeError, ValueError, TypeError, TrackingCorruptedError, TrackingUnreadableError):
    print("ERROR: Sandboxed Forge installation registry is unreadable or malformed", file=sys.stderr)
    raise SystemExit(2)

def target_is_within(raw_path: str, boundary: Path) -> bool:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        return False
    try:
        # Resolve the parent while retaining the leaf so a target symlink is
        # validated by its owned location, matching Forge's removal policy.
        location = candidate.parent.resolve(strict=False) / candidate.name
        return location.is_relative_to(boundary.resolve(strict=False))
    except (OSError, RuntimeError):
        return False


def ownership_violation(key, row):
    expected_local_id = f"local:{walkthrough_root}"
    if key == "user" and row.scope == "user" and row.project_path in (None, ""):
        boundary = claude_home
    elif key == expected_local_id and row.scope == "local" and row.project_path == walkthrough_root:
        boundary = Path(walkthrough_root) / ".claude"
    else:
        return "installation id is outside walkthrough ownership"

    if row.mode != "copy" or any(record.mode != "copy" for record in row.files):
        return "installation uses a non-copy mode"
    if any(owner.runtime != "claude_code" for owner in row.module_owners):
        return "installation contains non-Claude runtime ownership"
    if any(package.runtime != "claude_code" for package in row.skill_packages):
        return "installation contains a non-Claude skill package"
    if row.codex_config_path is not None or row.codex_commands:
        return "installation contains Codex configuration ownership"

    tracked_targets = [record.target_path for record in row.files]
    for package in row.skill_packages:
        tracked_targets.append(package.target_dir)
        tracked_targets.extend(package.file_paths)
    if row.settings_backup_path is not None:
        tracked_targets.append(row.settings_backup_path)
    if any(not target_is_within(target, boundary) for target in tracked_targets):
        return "installation records a target outside its walkthrough boundary"
    return None


if expectation == "owned-only":
    unexpected = {
        key: (row, violation)
        for key, row in rows.items()
        if (violation := ownership_violation(key, row)) is not None
    }
    heading = "Sandboxed Forge registry contains installations outside walkthrough ownership"
elif expectation == "empty":
    unexpected = {key: (row, "installation remains after cleanup") for key, row in rows.items()}
    heading = "Sandboxed Forge registry still contains installations after cleanup"
else:
    print(f"ERROR: Unknown registry expectation: {expectation}", file=sys.stderr)
    raise SystemExit(2)

if not unexpected:
    raise SystemExit(0)

print(f"ERROR: {heading}:", file=sys.stderr)
for key in sorted(unexpected):
    row, violation = unexpected[key]
    print(
        f"  - id={key!r} (scope={row.scope!r}, project_path={row.project_path!r}, reason={violation})",
        file=sys.stderr,
    )
raise SystemExit(1)
PY
}

require_registry_state() {
    local expectation="$1"
    if check_extension_registry "$expectation"; then
        return 0
    else
        local registry_status=$?
        if [ "$registry_status" -eq 1 ]; then
            echo "ERROR: Refusing cleanup because another target is tracked by the sandbox registry." >&2
            echo "Do not delete installed.json; reconcile the listed row from its recorded project with:" >&2
            echo "  FORGE_HOME=$FORGE_HOME forge extension disable --scope <scope> --yes" >&2
            echo "Then restore that project from a normal, non-walkthrough Forge environment and retry --reset." >&2
        else
            echo "ERROR: Could not prove the sandbox extension registry is safe for cleanup." >&2
        fi
        return 1
    fi
}

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
            case "$session_name" in
                walkthrough-demo|walkthrough-continuation)
                    # Claude Code writes native transcripts under its own
                    # CLAUDE_CONFIG_DIR, while Forge-owned settings remain in
                    # the sandbox CLAUDE_HOME. Point deletion at the native
                    # store only for these two fixed, walkthrough-created ids.
                    CLAUDE_HOME="$FORGE_WALKTHROUGH_CLAUDE_CONFIG_DIR" \
                        forge session delete "$session_name" --yes --force
                    ;;
                *)
                    forge session delete "$session_name" --yes --force
                    ;;
            esac
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
    require_registry_state empty
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

if [[ "$PHASE" == "extensions" || "$PHASE" == "all" ]]; then
    # Validate the entire isolated registry before runtime cleanup can remove
    # evidence. Status queries are CWD-scoped and cannot expose foreign rows.
    require_registry_state owned-only
fi
if [[ "$PHASE" == "runtime" || "$PHASE" == "all" ]]; then
    cleanup_runtime
fi
if [[ "$PHASE" == "extensions" || "$PHASE" == "all" ]]; then
    cleanup_extensions
fi

echo "Walkthrough-owned $PHASE cleanup complete."
