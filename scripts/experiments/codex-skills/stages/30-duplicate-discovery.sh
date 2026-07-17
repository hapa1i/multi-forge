#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 30-duplicate-discovery
probe_version
probe_auth
user_skill="$HOME/.agents/skills/probe-duplicate"
project_skill="$PROJ/.agents/skills/probe-duplicate"
mkdir -p "$user_skill" "$project_skill"
cat >"$user_skill/SKILL.md" <<'EOF'
---
name: probe-duplicate
description: User-level duplicate probe package.
---
Return exactly DUPLICATE_USER_1A2B3 and nothing else.
EOF
cat >"$project_skill/SKILL.md" <<'EOF'
---
name: probe-duplicate
description: Project-level duplicate probe package.
---
Return exactly DUPLICATE_PROJECT_4D5E6 and nothing else.
EOF

run_exec duplicate "$PROJ" '$probe-duplicate Run the explicit duplicate-name probe.' || err "Codex turn failed"
message="$PROBE_CAPTURE_DIR/results/duplicate.last-message.txt"
if rg -q --fixed-strings DUPLICATE_USER_1A2B3 "$message" && rg -q --fixed-strings DUPLICATE_PROJECT_4D5E6 "$message"; then
    verdict=AMBIGUOUS
elif rg -q --fixed-strings DUPLICATE_PROJECT_4D5E6 "$message"; then
    verdict=PROJECT
elif rg -q --fixed-strings DUPLICATE_USER_1A2B3 "$message"; then
    verdict=USER
else
    verdict=INCONCLUSIVE
fi
printf '%s\n' "$verdict" >"$PROBE_CAPTURE_DIR/results/verdict.txt"
note "VERDICT [30]: $verdict (classification evidence; Forge still refuses silent duplicates)"
[ "$verdict" != INCONCLUSIVE ] || exit 1
