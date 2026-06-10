#!/usr/bin/env bash
# Stage 00 -- preflight (0 model turns).
# Pins: codex version (+drift stamp), hooks feature enablement, CODEX_HOME
# isolation for auth, and read-only --help captures for later stages.
set -uo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 00-preflight
probe_version_check

# --help captures (free; leads for stages 50/60 and the decision record).
codex --help >"$PROBE_CAPTURE_DIR/meta/help-codex.txt" 2>&1
codex exec --help >"$PROBE_CAPTURE_DIR/meta/help-exec.txt" 2>&1
codex exec resume --help >"$PROBE_CAPTURE_DIR/meta/help-exec-resume.txt" 2>&1 || true
codex app-server --help >"$PROBE_CAPTURE_DIR/meta/help-app-server.txt" 2>&1 || true
# No `codex hooks` subcommand exists on 0.138.0 (falls through to top-level help)
# -- capture the fall-through as the evidence.
codex hooks --help >"$PROBE_CAPTURE_DIR/meta/help-hooks-fallthrough.txt" 2>&1 || true

# Feature enablement: parse by first token == hooks, last token == bool
# (stability column can be multi-word, e.g. "under development").
codex features list >"$PROBE_CAPTURE_DIR/meta/features-list.txt" 2>&1
HOOKS_ENABLED="$(awk '$1 == "hooks" {print $NF}' "$PROBE_CAPTURE_DIR/meta/features-list.txt")"
note "features: hooks=$HOOKS_ENABLED"
[ "$HOOKS_ENABLED" = "true" ] || err "hooks feature is not enabled ('$HOOKS_ENABLED') -- hook stages would no-op."

# Auth under the isolated home (verifies the isolation assumption itself).
probe_auth
snapshot_tree codex-home.before "$CODEX_HOME"

note "VERDICT [00]: PREFLIGHT-OK codex-cli=$CODEX_VERSION hooks=enabled auth=isolated-home"
