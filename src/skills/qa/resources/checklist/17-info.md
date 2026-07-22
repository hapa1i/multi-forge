<!-- prereq: 0.3 -->

## 17. System Info

### 17.1 `forge info`

<!-- auto -->

```bash
forge info
```

- [ ] Shows Forge version
- [ ] Shows installation status
- [ ] Shows proxy status
- [ ] Shows active session (if any)

### 17.2 Debug Logging and `forge logs`

<!-- human:confirm -->

Run a Forge command with debug logging enabled, then use `forge logs show` to inspect and clean up log files.

```bash
# Run a command with debug logging
FORGE_DEBUG=1 forge info

# Show log locations and file counts
forge logs show

# Verify logs were written
forge logs show
# Expected: shows log directory path and file count > 0

# Clean up logs
forge logs clean --yes

# Verify cleanup
forge logs show
# Expected: reports 0 log files when no Forge processes are running.
# If QA proxies are still running, active proxy logs may be retained.
```

- [ ] `FORGE_DEBUG=1` enables debug logging (no crash, no error)
- [ ] `forge logs show` shows log directory location and file counts
- [ ] Log files were actually written (count > 0 after debug run)
- [ ] `forge logs clean --yes` removes stale log files
- [ ] After cleanup, `forge logs show` reports 0 files, or only logs for currently running Forge proxy processes

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
test "$(rg -c 'present[[:space:]]+codex[[:space:]]+' /tmp/forge-project-status.txt)" -eq 5

forge extension status --scope project --root "$FORGE_TEST_REPO" --json \
  | tee /tmp/forge-project-status.json \
  | jq -e '.schema_version == 2 and (.installations | length == 1)
      and .unmanaged_skill_packages == [] and .installations[0].scope == "project"
      and (.installations[0].skill_packages | length == 5)
      and all(.installations[0].skill_packages[];
        . as $package
        | $package.runtime == "codex" and ($package.skill | length > 0)
        and ($package.target_dir | endswith("/.agents/skills/" + $package.skill))
        and ($package.file_paths | length > 0)
        and all($package.file_paths[]; startswith($package.target_dir + "/"))
        and $package.state == "present" and $package.target_present == true
        and $package.missing_file_paths == [] and $package.duplicate_dirs == [] and $package.recovery == null)'
```

- [ ] Human status shows a runtime-package table with the five project Codex packages in `present` state
- [ ] JSON status reports one project installation and five healthy Codex package records
- [ ] Every JSON package record names its skill/runtime/target/files and has no missing files, duplicates, or recovery
  action

---
