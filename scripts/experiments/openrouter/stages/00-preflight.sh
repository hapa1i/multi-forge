#!/usr/bin/env bash
# Stage 00 -- preflight. Resolve OPENROUTER_API_KEY via Forge (read-only),
# stamp base_url + key provenance (NEVER the key), and check required tools.
# This is the operator gate: every other stage assumes a resolvable key.
set -uo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"
probe_init "00-preflight"

command -v uv >/dev/null 2>&1 || err "uv not on PATH (needed for 'uv run python')"
command -v python3 >/dev/null 2>&1 || err "python3 not on PATH"

if run_probe "creds" creds; then
    note "base_url      = $(cat "$PROBE_CAPTURE_DIR/meta/base-url.txt" 2>/dev/null)"
    note "key provenance= $(cat "$PROBE_CAPTURE_DIR/meta/key-provenance.txt" 2>/dev/null)"
    verdict "[PREFLIGHT-OK]"
    exit 0
else
    verdict "[PREFLIGHT-NO-KEY]"
    err "OPENROUTER_API_KEY not resolvable by Forge. Set the env var or run 'forge auth login -c openrouter'."
fi
