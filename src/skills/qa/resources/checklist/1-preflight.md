<!-- prereq: 0.3 -->

## 1. Pre-Flight for Extension Tests

### 1.1 Pre-Flight Checks

<!-- auto -->

```bash
# Navigate to test repo
cd $FORGE_TEST_REPO

# IMPORTANT: Verify pre-existing user settings exist
cat .claude/settings.local.json | jq '.'
# Should include permissions.allow ["Bash(npm test)", "Bash(uv run pytest*)"] and env.MY_CUSTOM_VAR="should-survive-forge".

# Optional: verify project settings file exists too
ls -la .claude/settings.json 2>/dev/null || true
```

- [ ] Test repo has `.claude/settings.local.json` with pre-existing settings
- [ ] Note the original content for later verification

---
