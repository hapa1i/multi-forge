<!-- prereq: 0.3, 2.4, 18 -->

## 19. Complete Uninstallation (setup.sh --uninstall)

This tests the curl-installable uninstall that removes EVERYTHING.

### 19.1 Pre-Uninstall State Verification

<!-- auto -->

<!-- destructive -->

```bash
# Verify we have both installations
cat ~/.forge/installed.json | jq '.installations | keys'
# Should show: ["user", "local:$FORGE_TEST_REPO"]

# Verify artifacts exist
ls ~/.forge/             # Should exist
ls ~/.forge/bin/forge    # Should exist
ls ~/.claude/commands/   # Should have Forge commands
ls .claude/commands/     # Should have Forge commands (local)
```

- [ ] Both user and local installations tracked
- [ ] `~/.forge/` exists
- [ ] User scope has Forge files
- [ ] Local scope has Forge files

### 19.2 Run Complete Uninstall

<!-- auto -->

<!-- destructive -->

```bash
# Run the uninstall script using the local copy
~/.forge/repo/scripts/setup.sh --uninstall
```

The script attempts to remove extensions via Forge CLI:

- `forge extension disable --all --force` (remove tracked extensions)

Then it removes `~/.forge/` and other artifacts.

- [ ] Script runs without errors
- [ ] ALL scopes uninstalled (via `forge extension disable --all --force` or equivalent)
- [ ] Shows "Found N Forge installation(s)" summary (if forge available)
- [ ] `~/.forge/` removed
- [ ] `~/.forge/sessions/` removed (Forge session data)
- [ ] Docker images removed (claude-forge-\*)
- [ ] Shell profile cleaned (block markers removed)

### 19.3 Verify Complete Removal

<!-- auto -->

<!-- destructive -->

```bash
# Verify ~/.forge/ is gone
ls ~/.forge/ 2>/dev/null || echo "~/.forge/ removed"

# Verify forge not on PATH (need new terminal or source profile)
# source ~/.zshrc  # or restart terminal
# which forge      # Should fail or show nothing

# Verify no Forge hooks in global settings
cat ~/.claude/settings.json | jq '.hooks'
# Should be null or empty of Forge entries

# Verify user commands removed
ls ~/.claude/commands/ 2>/dev/null | grep -v "^$" || echo "User commands removed"
ls ~/.claude/agents/ 2>/dev/null | grep -v "^$" || echo "User agents removed"
ls ~/.claude/skills/ 2>/dev/null | grep -v "^$" || echo "User skills removed"
```

- [ ] `~/.forge/` directory removed
- [ ] Forge hooks removed from `~/.claude/settings.json`
- [ ] User commands/agents/skills removed

### 19.4 Verify Local Project Settings Preserved

<!-- auto -->

<!-- destructive -->

```bash
cd $FORGE_TEST_REPO

# CRITICAL: Local pre-existing settings should survive
cat .claude/settings.local.json | jq '.'

# Original permissions should still be there
cat .claude/settings.local.json | jq '.permissions.allow'
# Should show: ["Bash(npm test)", "Bash(uv run pytest*)"]

# Custom env var should still be there
cat .claude/settings.local.json | jq '.env.MY_CUSTOM_VAR'
# Should show: "should-survive-forge"
```

- [ ] `.claude/settings.local.json` still exists
- [ ] Original permissions preserved
- [ ] `env.MY_CUSTOM_VAR` preserved
- [ ] Forge-added entries (hooks, Write/Edit permissions, env) removed; user-approved permissions (e.g.,
  `Bash(forge workflow:*)`) may remain

### 19.5 Verify Shell Profile Cleaned

<!-- auto -->

<!-- destructive -->

```bash
# Check that block markers were removed from profile
grep -c "claude-forge" ~/.zshrc || echo "No claude-forge entries"
grep -c "~/.forge/bin" ~/.zshrc || echo "No forge bin entries"

# Check backup was created
ls ~/.zshrc.forge-uninstall-backup 2>/dev/null && echo "Backup exists"
```

- [ ] No `>>> claude-forge >>>` block in profile
- [ ] No `.forge/bin` in PATH
- [ ] Backup file created at `~/.zshrc.forge-uninstall-backup`

---
