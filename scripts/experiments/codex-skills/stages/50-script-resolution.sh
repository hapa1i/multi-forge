#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 50-script-resolution
probe_version
probe_auth
skill="$HOME/.agents/skills/probe-script"
mkdir -p "$skill/resources" "$skill/scripts" "$PROJ/a/b"
cat >"$skill/resources/marker.md" <<'EOF'
RESOURCE_ROOT_2D1E0
EOF
cat >"$skill/scripts/marker.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo SCRIPT_ROOT_5B4C3
EOF
chmod +x "$skill/scripts/marker.sh"

cat >"$skill/SKILL.md" <<'EOF'
---
name: probe-script
description: Probes packaged script resolution from an unrelated working directory.
---
Execute `bash scripts/marker.sh` verbatim. Then report its output and any environment variable whose name contains
`SKILL`. Do not search for the script.
EOF
run_exec literal "$PROJ/a/b" '$probe-script Run the literal packaged-script probe.' || true
if rg -q --fixed-strings SCRIPT_ROOT_5B4C3 "$PROBE_CAPTURE_DIR/results/literal.last-message.txt"; then
    err "literal relative script unexpectedly resolved; re-evaluate the binding"
fi

cat >"$skill/SKILL.md" <<'EOF'
---
name: probe-script
description: Probes packaged script resolution from an unrelated working directory.
---
Resolve `scripts/marker.sh` relative to the directory containing this `SKILL.md`, then execute it with Bash using the
resolved absolute path. Report its output and any environment variable whose name contains `SKILL`.
EOF
run_exec bound "$PROJ/a/b" '$probe-script Run the bound packaged-script probe.' || err "bound Codex turn failed"
assert_last_contains bound SCRIPT_ROOT_5B4C3
if rg -qi 'SKILL[^[:space:]]*=' "$PROBE_CAPTURE_DIR/results/bound.last-message.txt"; then
    note "OBSERVATION: model reported a SKILL-named environment variable; inspect raw stream"
else
    note "OBSERVATION: no SKILL-named environment variable reported"
fi

cat >"$skill/SKILL.md" <<'EOF'
---
name: probe-script
description: Probes a packaged read-only resource reference.
---
Read `resources/marker.md`, resolving it relative to the directory containing this `SKILL.md`, and return only its
contents. Do not search the repository.
EOF
run_exec resource "$PROJ/a/b" '$probe-script Run the packaged resource probe.' || err "resource Codex turn failed"
assert_last_contains resource RESOURCE_ROOT_2D1E0
note "VERDICT [50]: PASS CWD-relative script fails; explicit package-root script and resource bindings succeed"
