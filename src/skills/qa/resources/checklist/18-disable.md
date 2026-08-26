<!-- prereq: 0.3, 2.13 -->

## 18. Incremental Extension Disable

Test disabling individual scopes before removing every tracked installation.

### 18.1 Disable Local Scope Only

<!-- auto -->

<!-- destructive -->

```bash
cd $FORGE_TEST_REPO

# Uninstall only the local scope (-y: disable prompts for confirmation; non-interactive under docker exec)
forge extension disable --scope local -y

# Verify local removal (extensions install skills/, not a commands/ dir)
ls .claude/skills/   # Should be empty or removed
cat .claude/settings.local.json | jq '.statusLine'  # Should have no Forge status line

# Verify user scope STILL installed
ls ~/.claude/skills/  # Should still have Forge skills
cat ~/.claude/settings.json | jq '.hooks'  # Should still have Forge hooks

# Check tracking: the local:$FORGE_TEST_REPO key is removed; the user key remains.
# Other local:... keys from earlier worktree sections (5/6/10) may still be present.
cat ~/.forge/installed.json | jq '.installations | keys'
```

- [ ] Local skills removed
- [ ] Local status line removed from settings.local.json; runtime hooks were never owned by local scope
- [ ] User scope skills still present
- [ ] User scope hooks still present
- [ ] `local:$FORGE_TEST_REPO` removed from tracking; `user` key still present (other worktree-local keys may remain)

### 18.2 Verify Pre-Existing Settings Restored (Local)

<!-- auto -->

<!-- destructive -->

```bash
# CRITICAL: Check that user's original settings survived uninstall
cat .claude/settings.local.json | jq '.'

# Original permissions should still be there
cat .claude/settings.local.json | jq '.permissions.allow'
# Should show: ["Bash(npm test)", "Bash(uv run pytest*)"]

# Custom env var should still be there
cat .claude/settings.local.json | jq '.env.MY_CUSTOM_VAR'
# Should show: "should-survive-forge"
```

- [ ] Original `permissions.allow` entries preserved
- [ ] `env.MY_CUSTOM_VAR` still present
- [ ] Forge-added hooks removed; Forge-added permissions (Write, Edit) removed
- [ ] User-approved permissions (e.g., `Bash(forge workflow:*)`) may remain -- these are Claude Code auto-learned, not
  Forge-managed

### 18.3 Re-enable Local Scope

<!-- auto -->

<!-- destructive -->

```bash
# Re-install local scope so we can test complete uninstall
forge extension enable --scope local --runtime claude

# Verify user, local, and project scopes are installed
cat ~/.forge/installed.json | jq '.installations | keys'
# Should include: user, local:/workspace, project:/workspace
```

- [ ] Local scope re-installed
- [ ] User, local, and project installations are tracked

### 18.4 Remove and Restore One Project Runtime

<!-- auto -->

<!-- destructive -->

```bash
cd "$FORGE_TEST_REPO"
PROJECT_KEY="project:$(pwd -P)"

# Start from a dual-runtime project package set.
PATH="/tmp/forge-qa-runtime-bin:$PATH" forge extension enable --scope project --root "$FORGE_TEST_REPO" \
  --profile minimal --with skills --without commands --runtime all

# Remove only Codex. Claude packages and the project tracking row must survive.
forge extension disable --scope project --runtime codex --yes
! find .agents/skills -name SKILL.md -print -quit 2>/dev/null | grep -q .
test -f .claude/skills/review/SKILL.md
jq -e --arg key "$PROJECT_KEY" '
  .installations[$key] != null
  and ([.installations[$key].module_owners[].runtime] | unique == ["claude_code"])
' "$FORGE_HOME/installed.json"

# Sync must not resurrect the removed runtime.
forge extension sync --scope project
! find .agents/skills -name SKILL.md -print -quit 2>/dev/null | grep -q .

# Restore Codex while preserving Claude, so complete uninstall still covers both runtime surfaces.
PATH="/tmp/forge-qa-runtime-bin:$PATH" forge extension enable --scope project --root "$FORGE_TEST_REPO" \
  --profile minimal --with skills --without commands --runtime codex
forge extension status --scope project --root "$FORGE_TEST_REPO" --json \
  | jq -e '.schema_version == 3 and .unmanaged_skill_packages == []
      and .installations[0].managed_runtimes == ["claude_code", "codex"]
      and any(.installations[0].skill_packages[]; .runtime == "claude_code" and .state == "present")
      and any(.installations[0].skill_packages[]; .runtime == "codex" and .state == "present")'
```

- [ ] Runtime disable removes tracked project `.agents/skills` packages but retains the project row
- [ ] Project Claude packages remain present and tracked
- [ ] Sync does not resurrect Codex packages
- [ ] Re-enable restores healthy Claude and Codex project packages for complete-uninstall coverage

---
