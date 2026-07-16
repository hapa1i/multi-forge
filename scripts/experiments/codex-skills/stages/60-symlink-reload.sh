#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 60-symlink-reload
probe_version
probe_auth
source_skill="$PROBE_ROOT/source/probe-symlink"
mkdir -p "$source_skill"
cat >"$source_skill/SKILL.md" <<'EOF'
---
name: probe-symlink
description: Handles the symlink and reload probe.
---
Return exactly SYMLINK_VERSION_A_3C2D1 and nothing else.
EOF
ln -s "$source_skill" "$HOME/.agents/skills/probe-symlink"

run_exec version-a "$PROJ" '$probe-symlink Report the symlink marker.' || err "first Codex turn failed"
assert_last_contains version-a SYMLINK_VERSION_A_3C2D1
cat >"$source_skill/SKILL.md" <<'EOF'
---
name: probe-symlink
description: Handles the symlink and reload probe.
---
Return exactly SYMLINK_VERSION_B_8A7B6 and nothing else.
EOF
run_exec version-b "$PROJ" '$probe-symlink Report the updated symlink marker.' || err "second Codex turn failed"
assert_last_contains version-b SYMLINK_VERSION_B_8A7B6
note "VERDICT [60]: PASS symlink package discovered and fresh exec reloaded changed source"
