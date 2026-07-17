#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 10-user-discovery
probe_version
probe_auth
skill="$HOME/.agents/skills/probe-user"
mkdir -p "$skill"
cat >"$skill/SKILL.md" <<'EOF'
---
name: probe-user
description: Handles the Codex user-discovery probe.
---
Return exactly USER_DISCOVERY_7F3A9 and nothing else.
EOF

run_exec user "$PROJ" '$probe-user Run the explicit user discovery probe.' || err "Codex turn failed"
assert_last_contains user USER_DISCOVERY_7F3A9
note "VERDICT [10]: PASS user discovery + explicit invocation"
