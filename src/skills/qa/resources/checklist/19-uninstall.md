<!-- prereq: 0.3, 2.13, 18.4 -->

## 19. Complete Extension Removal

This removes every tracked extension installation while keeping the exact wheel environment available for final
verification. Package-manager removal is outside the container's extension-ownership contract.

### 19.1 Pre-Uninstall State Verification

<!-- auto -->

<!-- destructive -->

```bash
set -euo pipefail

# Verify user, local, and project installations
cat ~/.forge/installed.json | jq '.installations | keys'
# Should include: user, local:$FORGE_TEST_REPO, project:$FORGE_TEST_REPO

# Verify artifacts exist
ls ~/.forge/             # Should exist
test "$(readlink -f "$(command -v forge)")" = /opt/forge-qa/bin/forge \
  || { echo "ERROR: forge does not resolve to the isolated wheel launcher" >&2; exit 1; }
test -f ~/.claude/skills/qa/SKILL.md
jq -e '.hooks != null and .statusLine != null' .claude/settings.local.json
ls .agents/skills/       # Should have nine portable Codex project skills
```

- [ ] User, local, and project installations tracked
- [ ] Forge tracking state exists
- [ ] User scope has Forge files
- [ ] Local scope has Forge files
- [ ] Project scope has nine portable Codex packages under `.agents/skills`

### 19.2 Disable Every Tracked Installation

<!-- auto -->

<!-- destructive -->

```bash
# Remove every tracked user, local, and project extension installation.
forge extension disable --all --yes
```

- [ ] Command runs without errors
- [ ] All tracked scopes are processed
- [ ] Output reports the full-disable summary
- [ ] User Claude commands, agents, skills, and runtime hooks are removed
- [ ] Local Claude commands, agents, skills, and status-line ownership are removed
- [ ] Project Codex skill packages are removed
- [ ] Session and telemetry data remain available for report preservation

### 19.3 Verify Complete Removal

<!-- auto -->

<!-- destructive -->

```bash
# Verify tracking contains no installation rows (the file may be retained).
if [ -f "$FORGE_HOME/installed.json" ]; then
  jq -e '(.installations // {}) == {}' "$FORGE_HOME/installed.json"
fi

# Verify no Forge hooks in global settings
cat ~/.claude/settings.json | jq '.hooks'
# Should be null or empty of Forge entries

# Verify user commands removed
ls ~/.claude/commands/ 2>/dev/null | grep -v "^$" || echo "User commands removed"
ls ~/.claude/agents/ 2>/dev/null | grep -v "^$" || echo "User agents removed"
ls ~/.claude/skills/ 2>/dev/null | grep -v "^$" || echo "User skills removed"
! find "$HOME/.agents/skills" -name SKILL.md -print -quit 2>/dev/null | grep -q .
! find "$FORGE_TEST_REPO/.agents/skills" -name SKILL.md -print -quit 2>/dev/null | grep -q .
```

- [ ] No tracked extension installation remains
- [ ] Forge hooks removed from `~/.claude/settings.json`
- [ ] User commands/agents/skills removed
- [ ] No tracked Codex package remains under user or project `.agents/skills`

### 19.4 Verify Local Project Settings Preserved

<!-- human:confirm -->

<!-- destructive -->

Run the deterministic preservation checks below, then review the surviving settings as the one final uninstall
checkpoint. The filesystem assertions decide pass/fail; the human review catches unexpected but syntactically valid
settings drift before cleanup removes the remaining QA fixtures.

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

### 19.5 Verify Wheel Environment Preserved

<!-- auto -->

<!-- destructive -->

```bash
test "$(readlink -f "$(command -v forge)")" = /opt/forge-qa/bin/forge \
  || { echo "ERROR: forge does not resolve to the isolated wheel launcher" >&2; exit 1; }
test "$(forge --version | awk '{print $NF}')" = "$FORGE_QA_FORGE_VERSION"
/opt/forge-qa/bin/python -I - <<'PY'
import importlib.metadata as metadata
from pathlib import Path

import forge

assert metadata.version("multi-forge") == forge.__version__
assert Path(forge.__file__).is_relative_to("/opt/forge-qa")
PY
```

- [ ] `forge` remains available only from the isolated wheel environment
- [ ] CLI and distribution versions still match the recorded wheel
- [ ] Removing extensions did not remove or redirect the installed Python package

---
