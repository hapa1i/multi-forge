<!-- prereq: 0.3, 2.1, 5.1 -->

## 9. Direct Commands (% commands)

### 9.1 Test %help

<!-- auto -->

```bash
# Simulate UserPromptSubmit with %help
echo '{"prompt": "%help"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] Returns help text listing available commands

### 9.2 Test %session list

<!-- auto -->

```bash
echo '{"prompt": "%session list"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] Returns session list (similar to CLI)

### 9.3 Test %proxy list

<!-- auto -->

```bash
echo '{"prompt": "%proxy list"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] Returns proxy list (read-only)

### 9.4 Test %policy commands

<!-- auto -->

```bash
# Policy status
echo '{"prompt": "%policy status"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit

# Policy enable
echo '{"prompt": "%policy enable --bundle tdd"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit

# Policy disable
echo '{"prompt": "%policy disable"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] `%policy status` returns policy state
- [ ] `%policy enable` enables TDD enforcement
- [ ] `%policy disable` disables all policy

### 9.5 Test %policy check (Phase 18)

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Create a test file to generate a diff
echo 'def hello(): pass' > src/test_policy_check.py
git add src/test_policy_check.py && git commit -m "placeholder"
echo 'def hello(): return "world"' > src/test_policy_check.py

# Check unstaged changes against TDD bundle (should deny: impl without tests)
echo '{"prompt": "%policy check --bundle tdd"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit

# Check staged changes
git add src/test_policy_check.py
echo '{"prompt": "%policy check --bundle tdd --staged"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit

# With explicit bundle override
echo '{"prompt": "%policy check --bundle coding_standards"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit

# Clean up the test file (revert the commit + remove the file)
git reset --hard HEAD~1
rm -f src/test_policy_check.py

# Ensure no unstaged changes remain (Forge may have modified settings.local.json etc.)
git checkout -- . 2>/dev/null || true

# Now verify "no changes" path
echo '{"prompt": "%policy check --bundle tdd"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] `%policy check` returns JSON with `passed`, `files_checked`, `bundles` fields
- [ ] Impl-only file denied by TDD bundle (`passed: false`)
- [ ] `--staged` flag evaluates staged changes instead of unstaged
- [ ] `--bundle` override selects specific bundle
- [ ] No changes returns `"No unstaged changes to check."`

### 9.6 Test %config

<!-- auto -->

```bash
echo '{"prompt": "%config"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] Returns effective runtime config (read-only)

### 9.7 Test %session list --no-incognito

<!-- auto -->

```bash
echo '{"prompt": "%session list --no-incognito"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] Returns a session list that excludes incognito sessions

### 9.8 Test %proxy show

<!-- auto -->

<!-- prereq: 4.2 -->

```bash
echo '{"prompt": "%proxy show test-proxy-nostart"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit
```

- [ ] Returns proxy details (template, base_url, status) for the requested proxy id

### 9.9 Test %cancel-verification

<!-- auto -->

```bash
cd $FORGE_TEST_REPO

# Configure verification (completion promise) on the session
forge session set verification '{"type":"completion_promise","promise":"FORGE_COMPLETED"}' --session test-session-1

# Enable bypass via direct command escape hatch
echo '{"prompt": "%cancel-verification"}' | FORGE_SESSION=test-session-1 forge hook user-prompt-submit

# Verify override set
cat .forge/sessions/test-session-1/forge.session.json | jq '.overrides.verification.bypass'
```

- [ ] `%cancel-verification` returns "bypass enabled" message
- [ ] Session overrides include `verification.bypass: true`

---
