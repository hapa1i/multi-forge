<!-- prereq: 0.3, 2.4 -->

## 18. Uninstallation (Incremental)

Test uninstalling individual scopes before the complete uninstall.

### 18.1 Uninstall Local Scope Only

<!-- auto -->

<!-- destructive -->

```bash
cd $FORGE_TEST_REPO

# Uninstall only the local scope (-y: disable prompts for confirmation; non-interactive under docker exec)
forge extension disable --scope local -y

# Verify local removal (extensions install skills/, not a commands/ dir)
ls .claude/skills/   # Should be empty or removed
cat .claude/settings.local.json | jq '.hooks'  # Should have no Forge hooks

# Verify user scope STILL installed
ls ~/.claude/skills/  # Should still have Forge skills
cat ~/.claude/settings.json | jq '.hooks'  # Should still have Forge hooks

# Check tracking: the local:$FORGE_TEST_REPO key is removed; the user key remains.
# Other local:... keys from earlier worktree sections (5/6/10) may still be present.
cat ~/.forge/installed.json | jq '.installations | keys'
```

- [ ] Local skills removed
- [ ] Local hooks removed from settings.local.json
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

### 18.3 Re-install Local for Complete Test

<!-- auto -->

<!-- destructive -->

```bash
# Re-install local scope so we can test complete uninstall
forge extension enable --scope local

# Verify both scopes installed again
cat ~/.forge/installed.json | jq '.installations | keys'
# Should show: ["user", "local:/Users/..."]
```

- [ ] Local scope re-installed
- [ ] Both installations tracked

---
