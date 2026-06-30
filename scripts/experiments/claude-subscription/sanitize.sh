#!/usr/bin/env bash
# Scan probe captures for residual secrets and host paths, redact to placeholders,
# and FAIL LOUDLY on any secret hit. Scan-and-fail, never a silent scrub: the
# operator must fix the offending file (or a sed/scan rule) and re-run before any
# excerpt is promoted into a committed results doc.
#
# Run AFTER reproduce.sh, BEFORE copying anything out of the cache. This harness
# probes the OAuth/subscription path, so the scan targets Anthropic keys
# (sk-ant-...) AND OAuth/access tokens (the ~/.claude credential store contents),
# not just generic API keys.
set -euo pipefail

CAPTURE_ROOT="${CLAUDE_SUB_CAPTURE_DIR:-$HOME/.cache/forge-claude-sub-probe}"
OUT="$CAPTURE_ROOT/sanitized"
[ -d "$CAPTURE_ROOT" ] || {
    echo "ERROR: no captures at $CAPTURE_ROOT (run ./reproduce.sh first)" >&2
    exit 1
}

# GNU sed/grep REQUIRED. BSD/macOS sed/grep silently no-op the \b word boundary in
# the redaction + scan patterns below; on a Mac without Homebrew GNU tools that would
# turn this secret scanner into a false "OK". A hard failure beats a silent miss.
# Prefer the g-prefixed Homebrew tool; else accept a base tool that IS GNU (Linux).
# (macOS grep --version says "GNU compatible", so match the exact "GNU sed"/"GNU grep"
# marker, not a bare "GNU".)
_require_gnu() {
    local name="$1" marker="$2" g="g$1"
    if command -v "$g" >/dev/null 2>&1; then
        printf '%s\n' "$g"
        return 0
    fi
    if command -v "$name" >/dev/null 2>&1 && "$name" --version 2>/dev/null | grep -qF "$marker"; then
        printf '%s\n' "$name"
        return 0
    fi
    return 1
}
SED="$(_require_gnu sed 'GNU sed')" || {
    echo "ERROR: sanitize.sh needs GNU sed (gsed) -- BSD sed ignores word boundaries. Install: brew install gnu-sed" >&2
    exit 1
}
GREP="$(_require_gnu grep 'GNU grep')" || {
    echo "ERROR: sanitize.sh needs GNU grep (ggrep) -- BSD grep ignores word boundaries. Install: brew install grep" >&2
    exit 1
}

rm -rf "$OUT"
mkdir -p "$OUT"

USER_NAME="$(whoami)"

# Redact host-identifying paths/names to placeholders. `|` is the sed delimiter,
# and none of these values contain `|`, so no escaping is needed.
find "$CAPTURE_ROOT" -type f -not -path "$OUT/*" | while IFS= read -r f; do
    rel="${f#"$CAPTURE_ROOT"/}"
    dest="$OUT/$rel"
    mkdir -p "$(dirname "$dest")"
    "$SED" -E \
        -e "s|/tmp/tmp[A-Za-z0-9._-]*|<PROBE_ROOT>|g" \
        -e "s|/tmp/claude-sub-probe-[A-Za-z0-9._-]*|<PROBE_ROOT>|g" \
        -e "s|/private/var/folders/[A-Za-z0-9._/-]*|<PROBE_ROOT>|g" \
        -e "s|$HOME|<HOME>|g" \
        -e "s|\\b$USER_NAME\\b|<USER>|g" \
        "$f" >"$dest"
done

echo "Scanning for residual secrets..."
HITS=0
scan() {
    local label="$1"
    shift
    local found
    found="$("$GREP" -RIlE "$@" "$OUT" 2>/dev/null || true)"
    if [ -n "$found" ]; then
        echo "HIT [$label]:" >&2
        echo "$found" >&2
        HITS=1
    fi
}

scan "anthropic-key" '\bsk-ant-[A-Za-z0-9_-]{16,}'
scan "openai-style-key" '\bsk-[A-Za-z0-9_-]{16,}'
scan "bearer-token" 'Bearer [A-Za-z0-9._-]{8,}'
scan "jwt-ish" 'eyJ[A-Za-z0-9_-]{10,}'
scan "oauth-access" '(access_token|refresh_token)["[:space:]:=]+[A-Za-z0-9._-]{8,}'
scan "api-key-assign" '(ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|CLAUDE_CODE_OAUTH_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN)=[^<]'

[ "$HITS" -eq 0 ] || {
    echo "FAIL: residual secrets found under $OUT" >&2
    exit 1
}
echo "OK: sanitized captures at $OUT"
