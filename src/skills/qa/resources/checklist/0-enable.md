## 0. Verify Release Artifact (New User Flow)

This verifies the exact wheel installed by the release-QA harness before any Forge-owned user or project state exists.

### 0.1 Pre-requisites Check

<!-- auto -->

```bash
# Check you have the required tools
/opt/forge-qa/bin/python --version   # Need 3.11+
uv --version        # Need uv package manager
git --version       # Need git
```

- [ ] Python 3.11+ installed
- [ ] uv installed
- [ ] git installed

### 0.2 Verify Clean State

<!-- auto -->

```bash
set -euo pipefail

# Runtime preflight may create a cache, but no extension/proxy ownership may predate the run.
test ! -f "$FORGE_HOME/installed.json"
test ! -d "$FORGE_HOME/proxies"
which forge                # Must be the isolated release-wheel entry point
test "$(readlink -f "$(command -v forge)")" = /opt/forge-qa/bin/forge \
  || { echo "ERROR: forge does not resolve to the isolated wheel launcher" >&2; exit 1; }
test ! -d "$HOME/.agents/skills" || test -z "$(find "$HOME/.agents/skills" -mindepth 1 -maxdepth 1 -print -quit)"

# Check Claude settings have no Forge hooks
cat ~/.claude/settings.json | jq '.hooks' 2>/dev/null || true
cat ~/.claude/settings.local.json | jq '.hooks' 2>/dev/null || true
```

- [ ] `$FORGE_HOME` has no pre-existing extension tracking or proxy state
- [ ] `forge` resolves through the container launcher to `/opt/forge-qa/bin/forge`
- [ ] `$HOME/.agents/skills` has no pre-existing Codex skill packages
- [ ] No Forge hooks in user or project-local Claude settings

### 0.3 Verify Exact Wheel Installation

<!-- auto -->

```bash
cd "$FORGE_TEST_REPO"
test -n "$FORGE_QA_WHEEL_FILENAME"
test -n "$FORGE_QA_WHEEL_SHA256"
/opt/forge-qa/bin/python -I - <<'PY'
import importlib.metadata as metadata
import importlib.resources as resources
import os
from pathlib import Path

import forge
from forge.install.installer import get_extensions_root

prefix = Path("/opt/forge-qa")
assert metadata.version("multi-forge") == os.environ["FORGE_QA_FORGE_VERSION"]
assert forge.__version__ == os.environ["FORGE_QA_FORGE_VERSION"]
assert Path(forge.__file__).is_relative_to(prefix)
assert Path(str(resources.files("forge"))).is_relative_to(prefix)
extensions = get_extensions_root()
assert extensions.is_relative_to(prefix)
for relative in (
    "skills/qa/SKILL.md",
    "skills/qa/resources/checklist.md",
    "skills/qa/resources/coverage-map.md",
    "skills/qa/resources/execution-budget.json",
    "skills/qa/resources/report-template.md",
    "skills/qa/resources/runtime-matrix.json",
    "skills/qa/scripts/qa-artifact.py",
    "skills/qa/scripts/qa-run-metrics.py",
    "skills/qa/scripts/qa-selection.py",
    "skills/qa/scripts/start-container.sh",
    "skills/qa/scripts/walkthrough-state.py",
):
    assert (extensions / relative).is_file(), relative
assert len(list((extensions / "skills/qa/resources/checklist").glob("*.md"))) == 21
PY
```

- [ ] Distribution metadata and `forge.__version__` match the recorded artifact version
- [ ] Forge imports resolve under `/opt/forge-qa`, not the editable checkout
- [ ] Packaged resources resolve under `/opt/forge-qa`
- [ ] The index, all 21 fragments, report contract, identity resources, and runner scripts are present in the wheel
- [ ] The harness supplied a wheel filename and SHA-256 identity

### 0.4 Verify CLI and Release Identity

<!-- auto -->

```bash
# Verify the installed entry point and extension surface
command -v forge
forge --version
forge extension enable --help | rg -- '--runtime'

# Print the immutable inputs that must appear in the report
printf 'wheel=%s\nsha256=%s\nversion=%s\nmode=%s\ntrack=%s\n' \
  "$FORGE_QA_WHEEL_FILENAME" \
  "$FORGE_QA_WHEEL_SHA256" \
  "$FORGE_QA_FORGE_VERSION" \
  "$FORGE_QA_ARTIFACT_MODE" \
  "$FORGE_QA_RUNTIME_TRACK"
```

- [ ] `forge` command is the isolated wheel entry point on `PATH`
- [ ] `forge --version` matches the recorded wheel version
- [ ] Extension help documents repeatable `--runtime` selection (`claude`, `codex`, or `all`)
- [ ] Wheel filename, SHA-256, artifact mode, and runtime track are printable for the report

---
