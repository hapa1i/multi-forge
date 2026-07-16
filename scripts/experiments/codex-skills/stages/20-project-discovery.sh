#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 20-project-discovery
probe_version
probe_auth
skill="$PROJ/.agents/skills/probe-project"
mkdir -p "$skill" "$PROJ/a/b"
cat >"$skill/SKILL.md" <<'EOF'
---
name: probe-project
description: Handles the nested project-discovery probe.
---
Return exactly PROJECT_DISCOVERY_6C2B8 and nothing else.
EOF

run_exec project "$PROJ/a/b" '$probe-project Run the explicit project discovery probe.' || err "Codex turn failed"
assert_last_contains project PROJECT_DISCOVERY_6C2B8
note "VERDICT [20]: PASS repository-root discovery from nested CWD"
