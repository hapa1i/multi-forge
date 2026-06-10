#!/usr/bin/env bash
# Sanitize raw probe captures into fixture candidates.
#
#   raw:        ${CODEX_HOOKS_CAPTURE_DIR:-~/.cache/forge-codex-hooks-probe}/<stage>/...
#   sanitized:  .../sanitized/<stage>/...   (review by hand before promoting)
#
# Policy (mirrors tests/fixtures/codex/README.md): replace $HOME/$USER/probe
# paths with placeholders, then SCAN for residual secrets and FAIL LOUDLY listing
# files (scan-and-fail, never silent scrub). codex-home dirs (which may hold an
# auth.json copy) are never copied; a lingering auth.json anywhere fails the run.
set -euo pipefail

CAPTURE_ROOT="${CODEX_HOOKS_CAPTURE_DIR:-$HOME/.cache/forge-codex-hooks-probe}"
OUT="$CAPTURE_ROOT/sanitized"
[ -d "$CAPTURE_ROOT" ] || {
    echo "ERROR: no captures at $CAPTURE_ROOT" >&2
    exit 1
}

# Gate 0: no auth material may exist outside a codex-home dir; none may be copied.
AUTH_STRAYS="$(find "$CAPTURE_ROOT" -name 'auth.json' -not -path '*/codex-home/*' 2>/dev/null || true)"
if [ -n "$AUTH_STRAYS" ]; then
    echo "ERROR: auth.json outside codex-home -- remove before sanitizing:" >&2
    printf '%s\n' "$AUTH_STRAYS" >&2
    exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT"

USER_NAME="$(whoami)"

# macOS ships BSD sed/grep, which do not support `\b` word boundaries (CLAUDE.md
# mandates GNU tools on Darwin). Prefer gsed/ggrep; fall back to sed/grep (already
# GNU on Linux). Without this the `\b$USER_NAME\b` rule below silently no-ops on BSD
# sed, leaving the real username in "sanitized" output.
SED="$(command -v gsed || command -v sed)"
GREP="$(command -v ggrep || command -v grep)"

find "$CAPTURE_ROOT" -type f \
    -not -path "$OUT/*" \
    -not -path '*/codex-home/*' \
    -not -name '*.guard' -not -path '*/guards/*' | while IFS= read -r f; do
    rel="${f#"$CAPTURE_ROOT"/}"
    dest="$OUT/$rel"
    mkdir -p "$(dirname "$dest")"
    "$SED" -E \
        -e "s|/private/var/folders/[A-Za-z0-9/_.+-]*|<PROBE_ROOT>|g" \
        -e "s|/var/folders/[A-Za-z0-9/_.+-]*|<PROBE_ROOT>|g" \
        -e "s|/tmp/tmp[A-Za-z0-9._-]*|<PROBE_ROOT>|g" \
        -e "s|$HOME|<HOME>|g" \
        -e "s|\b$USER_NAME\b|<USER>|g" \
        "$f" >"$dest"
done

# Scan-and-fail: list any file still carrying secret-shaped content.
echo "Scanning sanitized output for residual secrets..."
HITS=0
scan() { # scan <label> <grep-args...>
    local label="$1"
    shift
    local found
    found="$("$GREP" -RIl "$@" "$OUT" 2>/dev/null || true)"
    if [ -n "$found" ]; then
        echo "SECRET-SCAN HIT [$label]:" >&2
        printf '%s\n' "$found" >&2
        HITS=1
    fi
}
# Anchor at a word boundary + require key length: real sk- keys appear at token
# boundaries (after a quote/space/=) and are long. Without \b the pattern matched
# mid-word filename fragments in codex-home's plugin clone (e.g. "task-creation",
# "task-abstraction-...") that show up in trees/ path listings.
scan "openai-style key" -E '\bsk-[A-Za-z0-9_-]{16,}'
scan "bearer token" -E 'Bearer [A-Za-z0-9._-]{8,}'
scan "jwt-ish blob" -E 'eyJ[A-Za-z0-9_-]{10,}'
scan "home path" -F "$HOME"
scan "username" -E "\b$USER_NAME\b"
scan "api key var with value" -E '(API_KEY|ACCESS_TOKEN)=[^<]'

if [ "$HITS" -ne 0 ]; then
    echo "FAIL: sanitization incomplete -- fix the listed files (or the sed rules) and rerun." >&2
    exit 1
fi
echo "OK: sanitized captures at $OUT -- review before the build card promotes any to tests/fixtures/codex/hooks/."
