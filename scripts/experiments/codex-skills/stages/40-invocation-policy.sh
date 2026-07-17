#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 40-invocation-policy
probe_version
probe_auth
skill="$HOME/.agents/skills/probe-explicit-only"
mkdir -p "$skill/agents"
cat >"$skill/SKILL.md" <<'EOF'
---
name: probe-explicit-only
description: Handles the deliberately unnamed policy probe.
---
Return exactly EXPLICIT_POLICY_9E8D7 and nothing else.
EOF
cat >"$skill/agents/openai.yaml" <<'EOF'
policy:
  allow_implicit_invocation: true
EOF

implicit_prompt='Run the deliberately unnamed policy probe and report its result.'
run_exec implicit-enabled "$PROJ" "$implicit_prompt" || err "implicit-enabled Codex turn failed"
assert_last_contains implicit-enabled EXPLICIT_POLICY_9E8D7

cat >"$skill/agents/openai.yaml" <<'EOF'
policy:
  allow_implicit_invocation: false
EOF
run_exec implicit-blocked "$PROJ" "$implicit_prompt" || err "implicit-blocked Codex turn failed"
if rg -q --fixed-strings EXPLICIT_POLICY_9E8D7 "$PROBE_CAPTURE_DIR/results/implicit-blocked.last-message.txt"; then
    err "implicit invocation loaded an explicit-only skill"
fi
run_exec explicit "$PROJ" '$probe-explicit-only Run the explicit policy probe.' || err "explicit Codex turn failed"
assert_last_contains explicit EXPLICIT_POLICY_9E8D7
note "VERDICT [40]: PASS implicit control loaded, explicit-only policy blocked the same prompt, explicit invocation preserved"
