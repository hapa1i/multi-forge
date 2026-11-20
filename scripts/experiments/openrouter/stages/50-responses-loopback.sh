#!/usr/bin/env bash
# Run only against the local synthetic Responses server. Takes no provider credentials.
set -euo pipefail
umask 077

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
binaries="${OPENROUTER_RESPONSES_BINARIES:?Set OPENROUTER_RESPONSES_BINARIES to the version-to-executable JSON file}"
root="${OPENROUTER_CAPTURE_DIR:?Set OPENROUTER_CAPTURE_DIR to a private capture directory for this run}"
mkdir -p "$root"
exec python3 "$here/helpers/codex_matrix.py" --binaries "$binaries" --output "$root/50-loopback" \
    --workers "${OPENROUTER_RESPONSES_WORKERS:-4}"
