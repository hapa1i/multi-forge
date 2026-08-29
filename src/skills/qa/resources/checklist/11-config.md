<!-- prereq: 0.3 -->

## 11. Runtime Config + Claude Preset (`forge config`, `forge claude preset`)

### 11.1 Initialize Config

<!-- auto -->

```bash
# Config auto-creates with commented defaults on first access
forge config show

# Verify file created
cat ${FORGE_HOME:-$HOME/.forge}/config.yaml
```

- [ ] Config file created at `${FORGE_HOME:-$HOME/.forge}/config.yaml`
- [ ] Shows commented defaults (proxy_mode, sidecar_image, etc.)

### 11.2 Show Effective Config

<!-- auto -->

```bash
forge config show
```

- [ ] Shows all settings with current values
- [ ] Shows defaults when no overrides set

### 11.3 Set and Reset Values

<!-- auto -->

```bash
# Set a value
forge config set status_timeout=1.0

# Switch proxy mode default (host vs sidecar)
forge config set proxy_mode=sidecar

# Verify
forge config show | grep status_timeout
forge config show | grep proxy_mode

# Reset one key
forge config reset status_timeout

# Reset all (-y: reset-all prompts for confirmation; non-interactive under docker exec)
forge config reset -y
```

- [ ] `set` persists the value
- [ ] `reset` restores default
- [ ] Type validation works (rejects invalid values)

### 11.4 Migrate Downstream Retention

<!-- prereq: 4.2 -->

<!-- auto -->

Seed deprecated proxy-local values, prove preview is non-mutating, apply the migration, and prove the command is
rerunnable.

```bash
forge config reset telemetry -y 2>/dev/null || true
forge proxy set test-proxy-nostart audit.retention_days=21
forge proxy set test-proxy-nostart audit.max_total_mb=300

forge config migrate-retention --json >/tmp/forge-retention-preview.json
jq -e '
  .applied == false
  and .plan.write_global_policy == true
  and .plan.resolution.source == "legacy_consensus"
  and (.plan.targets | map(.proxy_id) | index("test-proxy-nostart") != null)
' /tmp/forge-retention-preview.json

forge config migrate-retention --yes --json >/tmp/forge-retention-apply.json
jq -e '
  .applied == true
  and .result.wrote_global_policy == true
  and (.result.migrated_proxy_ids | index("test-proxy-nostart") != null)
' /tmp/forge-retention-apply.json
forge config show --json | jq -e '
  .downstream_retention.source == "global"
  and .downstream_retention.effective.retention_days == 21
  and .downstream_retention.effective.max_total_mb == 300
'

/opt/forge-qa/bin/python - <<'PY'
import os
from pathlib import Path

import yaml

forge_home = Path(os.environ.get("FORGE_HOME", str(Path.home() / ".forge")))
data = yaml.safe_load((forge_home / "proxies" / "test-proxy-nostart" / "proxy.yaml").read_text())
for section_name in ("audit", "provider_trace"):
    section = data.get(section_name, {})
    assert "retention_days" not in section
    assert "max_total_mb" not in section
PY

forge config migrate-retention --yes --json | jq -e '
  .plan.has_changes == false
  and .result.wrote_global_policy == false
  and (.result.migrated_proxy_ids | length) == 0
'
```

- [ ] Deprecated `forge proxy set` keys print their exact `telemetry.downstream` replacements and migration command
- [ ] JSON preview reports `legacy_consensus` and the target proxy without changing either file
- [ ] Apply writes the global `21` day / `300` MB policy and removes only the deprecated proxy keys
- [ ] Reapplying the migration reports no changes

### 11.5 Edit in Editor

<!-- auto -->

```bash
EDITOR=true forge config edit
test -f "${FORGE_HOME:-$HOME/.forge}/config.yaml"
```

- [ ] `EDITOR=true` exercises the edit path and the config remains present

### 11.6 Show Claude Preset

<!-- auto -->

```bash
# Show current preset (raw JSON auto-creates on first access)
forge claude preset show --raw

# Verify file created and built-in keys present
/opt/forge-qa/bin/python - <<'PY'
import json
import os
from pathlib import Path

forge_home = Path(os.environ.get("FORGE_HOME", str(Path.home() / ".forge")))
path = forge_home / "claude.preset.json"
data = json.loads(path.read_text())
has_hooks = "hooks" in data
has_statusline = "statusLine" in data
print("PRESET_PATH=" + str(path))
print("HAS_HOOKS=" + str(has_hooks))
print("HAS_STATUSLINE=" + str(has_statusline))
PY
```

- [ ] Preset file created at `${FORGE_HOME:-$HOME/.forge}/claude.preset.json`
- [ ] Built-in preset includes `hooks` and `statusLine`

### 11.7 Reset Claude Preset

<!-- auto -->

```bash
# Add a disposable custom env var to the preset
/opt/forge-qa/bin/python - <<'PY'
import json
import os
from pathlib import Path

forge_home = Path(os.environ.get("FORGE_HOME", str(Path.home() / ".forge")))
path = forge_home / "claude.preset.json"
data = json.loads(path.read_text())
data.setdefault("env", {})["QA_TEMP_PRESET"] = "1"
path.write_text(json.dumps(data, indent=2) + "\n")
print("ADDED_QA_TEMP_PRESET=1")
PY

# Reset to built-in defaults without prompting
forge claude preset reset --yes

# Verify temporary key removed and built-in env preserved
/opt/forge-qa/bin/python - <<'PY'
import json
import os
from pathlib import Path

forge_home = Path(os.environ.get("FORGE_HOME", str(Path.home() / ".forge")))
path = forge_home / "claude.preset.json"
data = json.loads(path.read_text())
env = data.get("env", {})
has_qa_temp_preset = "QA_TEMP_PRESET" in env
print("HAS_QA_TEMP_PRESET=" + str(has_qa_temp_preset))
PY
```

- [ ] `reset --yes` restores the built-in preset non-interactively
- [ ] Custom preset additions are removed while built-in values remain

### 11.8 Edit Claude Preset in Editor

<!-- auto -->

```bash
EDITOR=true forge claude preset edit
test -f "${FORGE_HOME:-$HOME/.forge}/claude.preset.json"
```

- [ ] `EDITOR=true` exercises the preset edit path and the preset remains present

### 11.9 Per-Skill Invocation Mode

<!-- auto -->

```bash
set -euo pipefail

restore_review_invocation() {
  forge config reset skills >/dev/null 2>&1 || true
  forge extension sync --scope local >/dev/null 2>&1 || true
}
trap restore_review_invocation EXIT

forge config set skills.invocation.review=model
forge extension sync --scope local

/opt/forge-qa/bin/python - <<'PY'
import os
from pathlib import Path

import yaml

document = (Path(os.environ["FORGE_TEST_REPO"]) / ".claude" / "skills" / "review" / "SKILL.md").read_text()
frontmatter = yaml.safe_load(document.split("---", 2)[1])
assert frontmatter["disable-model-invocation"] is False
print("REVIEW_MODEL_INVOCATION=true")
PY

forge config reset skills
forge extension sync --scope local

/opt/forge-qa/bin/python - <<'PY'
import os
from pathlib import Path

import yaml

document = (Path(os.environ["FORGE_TEST_REPO"]) / ".claude" / "skills" / "review" / "SKILL.md").read_text()
frontmatter = yaml.safe_load(document.split("---", 2)[1])
assert frontmatter["disable-model-invocation"] is True
print("REVIEW_EXPLICIT_INVOCATION=true")
PY

trap - EXIT
```

- [ ] Config can opt one skill into model invocation without an extension-enable flag
- [ ] Local-scope sync materializes the changed policy in the installed package
- [ ] Removing the override restores human/explicit-only invocation

---
