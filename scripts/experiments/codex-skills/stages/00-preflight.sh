#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)/lib.sh"

probe_init 00-preflight
probe_version
probe_auth
codex exec --help >"$PROBE_CAPTURE_DIR/meta/exec-help.txt" 2>&1
note "VERDICT [00]: PASS codex-cli=$CODEX_VERSION isolated-home-auth"
