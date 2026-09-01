<!-- prereq: 0.3 -->

## 17. System Info

### 17.1 `forge info`

<!-- auto -->

```bash
forge info
```

- [ ] Shows Forge version
- [ ] Shows installation status
- [ ] Shows configured proxy registry entries
- [ ] Shows recent sessions (if any)

### 17.2 Debug Logging and `forge logs`

<!-- auto -->

Run a Forge command with debug logging enabled, then use `forge logs show` to inspect and clean up log files.

```bash
set -euo pipefail

ZOMBIE_PARENT_PID=
ZOMBIE_PID_FILE=$(mktemp /tmp/forge-qa-zombie-pid.XXXXXX)
ZOMBIE_SCRIPT=$(mktemp /tmp/forge-qa-zombie-parent.XXXXXX)
cleanup_zombie_fixture() {
  if test -n "$ZOMBIE_PARENT_PID"; then
    kill -TERM "$ZOMBIE_PARENT_PID" 2>/dev/null || true
    wait "$ZOMBIE_PARENT_PID" 2>/dev/null || true
  fi
  rm -f "$ZOMBIE_PID_FILE" "$ZOMBIE_SCRIPT"
}
trap cleanup_zombie_fixture EXIT

# Keep a child defunct long enough to prove kill(pid, 0) is not Forge's only
# liveness signal. Containers without an init may otherwise retain these logs forever.
cat >"$ZOMBIE_SCRIPT" <<'PY'
import os
from pathlib import Path
import signal
import sys
import time

child = os.fork()
if child == 0:
    os._exit(0)

Path(sys.argv[1]).write_text(str(child), encoding="utf-8")

def reap_and_exit(_signum, _frame):
    os.waitpid(child, 0)
    raise SystemExit(0)

signal.signal(signal.SIGTERM, reap_and_exit)
while True:
    time.sleep(1)
PY
/opt/forge-qa/bin/python "$ZOMBIE_SCRIPT" "$ZOMBIE_PID_FILE" &
ZOMBIE_PARENT_PID=$!
ZOMBIE_STATE=
for _attempt in $(seq 1 100); do
  if test -s "$ZOMBIE_PID_FILE"; then
    ZOMBIE_PID=$(cat "$ZOMBIE_PID_FILE")
    ZOMBIE_STATE=$(awk '{print $3}' "/proc/$ZOMBIE_PID/stat" 2>/dev/null || true)
    test "$ZOMBIE_STATE" = Z && break
  fi
  sleep 0.05
done
test "$ZOMBIE_STATE" = Z
ZOMBIE_LOG="$HOME/.forge/logs/proxy/proxy.$ZOMBIE_PID.log"
mkdir -p "$(dirname "$ZOMBIE_LOG")"
printf '%s\n' 'defunct processes cannot append to this shard' >"$ZOMBIE_LOG"

# Run a command with debug logging
FORGE_DEBUG=1 forge info

# Show log locations and file counts
forge logs show

# Verify logs were written
forge logs show
# Expected: shows log directory path and file count > 0

# Clean up logs
forge logs clean --yes
test ! -e "$ZOMBIE_LOG"
echo "ZOMBIE_LOG_REMOVED"
cleanup_zombie_fixture
trap - EXIT

# Verify cleanup
forge logs show
# Expected: reports 0 log files when no Forge processes are running.
# If QA proxies are still running, active proxy logs may be retained.
```

- [ ] `FORGE_DEBUG=1` enables debug logging (no crash, no error)
- [ ] `forge logs show` shows log directory location and file counts
- [ ] Log files were actually written (count > 0 after debug run)
- [ ] `forge logs clean --yes` removes stale log files
- [ ] After cleanup, `ZOMBIE_LOG_REMOVED` is printed and `forge logs show` reports 0 files, or only logs for currently
  running Forge proxy processes

### 17.3 `forge runtime list`

<!-- auto -->

```bash
# Capability matrix: which agent runtimes Forge knows, install state, and capabilities
forge runtime list

# Machine-readable
forge runtime list --json
```

- [ ] A `claude_code` row is present in the capability matrix
- [ ] `--json` emits a valid JSON array (one object per runtime, each with `id` and `installed`)
- [ ] A `codex` row is present with honest hook/pretool capability values

### 17.4 Runtime Skill Package Health

<!-- auto -->

```bash
cd "$FORGE_TEST_REPO"

forge extension status --scope project --root "$FORGE_TEST_REPO" | tee /tmp/forge-project-status.txt
rg -q 'Skill packages:' /tmp/forge-project-status.txt
test "$(rg -c 'present[[:space:]]+codex[[:space:]]+' /tmp/forge-project-status.txt)" -eq 9

forge extension status --scope project --root "$FORGE_TEST_REPO" --json \
  | tee /tmp/forge-project-status.json \
  | jq -e '.schema_version == 3 and (.installations | length == 1)
      and .unmanaged_skill_packages == [] and .installations[0].scope == "project"
      and (.installations[0].skill_packages | length == 9)
      and all(.installations[0].skill_packages[];
        . as $package
        | $package.runtime == "codex" and ($package.skill | length > 0)
        and ($package.target_dir | endswith("/.agents/skills/" + $package.skill))
        and ($package.file_paths | length > 0)
        and all($package.file_paths[]; startswith($package.target_dir + "/"))
        and $package.state == "present" and $package.target_present == true
        and $package.missing_file_paths == [] and $package.duplicate_dirs == [] and $package.recovery == null)'
```

- [ ] Human status shows a runtime-package table with the nine project Codex packages in `present` state
- [ ] JSON status reports one project installation and nine healthy Codex package records
- [ ] Every JSON package record names its skill/runtime/target/files and has no missing files, duplicates, or recovery
  action

---
