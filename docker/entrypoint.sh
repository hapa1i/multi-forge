#!/bin/bash
# Sidecar container entrypoint for Claude Forge.
#
# This script:
# 1. Optionally syncs project dependencies
# 2. Starts the proxy in background (bound to localhost)
# 3. Waits for proxy health check (FAILS HARD if never healthy)
# 4. Execs into Claude Code (becomes PID 1)
#
# Required environment variables:
#   FORGE_TEMPLATE - Proxy template name (e.g., "litellm-openai")
#
# Optional environment variables:
#   CLAUDE_CODE_AUTO_COMPACT_WINDOW - Compaction window limit (default: 200000)
#   FORGE_SESSION - Session name for hooks

set -e

# Sync project dependencies if pyproject.toml exists in workspace.
# Failures are surfaced (not silenced) so users see the actual error
# instead of confusing "module not found" from subsequent commands.
if [ -f /workspace/pyproject.toml ]; then
    cd /workspace && uv sync --quiet || {
        echo "WARNING: uv sync failed in /workspace (continuing without project deps)" >&2
    }
fi

# Validate required env vars
if [ -z "$FORGE_TEMPLATE" ]; then
    echo "ERROR: FORGE_TEMPLATE environment variable is required" >&2
    exit 1
fi

# Start proxy in background (bind to localhost only — minimal blast radius)
python -m forge.proxy.server \
  --template "$FORGE_TEMPLATE" \
  --host 127.0.0.1 --port 8085 \
  --log-level warning &

PROXY_PID=$!

# Wait for proxy health (FAIL HARD if never healthy)
PROXY_HEALTHY=false
echo "Waiting for proxy to become healthy..."
for i in {1..30}; do
  if curl -sf http://localhost:8085/ > /dev/null 2>&1; then
    PROXY_HEALTHY=true
    echo "Proxy healthy after $((i / 2)) seconds"
    break
  fi
  sleep 0.5
done

if [ "$PROXY_HEALTHY" != "true" ]; then
  echo "ERROR: Proxy failed to start within 15 seconds" >&2
  kill $PROXY_PID 2>/dev/null || true
  exit 1
fi

# Set env for Claude
export ANTHROPIC_BASE_URL=http://localhost:8085
export CLAUDE_CODE_AUTO_COMPACT_WINDOW="${CLAUDE_CODE_AUTO_COMPACT_WINDOW:-200000}"

# Configure Claude Code auth for container environment.
# Containers have no keychain/console login. apiKeyHelper calls a helper script
# to resolve the API key, and hasCompletedOnboarding skips the first-run screen.
# All files are in /root/.claude/ (container-local, ephemeral with --rm).
# See: github.com/anthropics/claude-code/issues/9699
mkdir -p /root/.claude
cat > /root/.claude/forge_api_key_helper.sh <<'HELPEREOF'
#!/bin/sh
printf '%s\n' "${ANTHROPIC_API_KEY:-forge-proxy-passthrough}"
HELPEREOF
chmod 700 /root/.claude/forge_api_key_helper.sh

cat > /root/.claude/settings.json <<'SETTINGSEOF'
{
  "apiKeyHelper": "/root/.claude/forge_api_key_helper.sh"
}
SETTINGSEOF
chmod 600 /root/.claude/settings.json

cat > /root/.claude.json <<'ONBOARDEOF'
{
  "hasCompletedOnboarding": true
}
ONBOARDEOF
chmod 600 /root/.claude.json

# Exec into Claude (becomes PID 1, replaces shell)
# Any arguments passed to the container are forwarded to Claude
exec claude "$@"
