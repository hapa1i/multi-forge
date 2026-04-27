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

# Reset all
forge config reset
```

- [ ] `set` persists the value
- [ ] `reset` restores default
- [ ] Type validation works (rejects invalid values)

### 11.4 Edit in Editor

<!-- human:guided -->

In the **container shell**, run `forge config edit`. Verify `$EDITOR` opens `${FORGE_HOME:-$HOME/.forge}/config.yaml`.

```
forge config edit
```

- [ ] Opens `${FORGE_HOME:-$HOME/.forge}/config.yaml` in `$EDITOR`

### 11.5 Show Claude Preset

<!-- auto -->

```bash
# Show current preset (raw JSON auto-creates on first access)
forge claude preset show --raw

# Verify file created and built-in keys present
python3 - <<'PY'
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

### 11.6 Reset Claude Preset

<!-- auto -->

```bash
# Add a disposable custom env var to the preset
python3 - <<'PY'
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
forge claude preset reset --force

# Verify temporary key removed and built-in env preserved
python3 - <<'PY'
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

- [ ] `reset --force` restores the built-in preset non-interactively
- [ ] Custom preset additions are removed while built-in values remain

### 11.7 Edit Claude Preset in Editor

<!-- human:guided -->

In the **container shell**, run `forge claude preset edit`. Verify `$EDITOR` opens
`${FORGE_HOME:-$HOME/.forge}/claude.preset.json`.

```
forge claude preset edit
```

- [ ] Opens `${FORGE_HOME:-$HOME/.forge}/claude.preset.json` in `$EDITOR`

---
