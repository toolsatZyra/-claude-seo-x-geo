#!/usr/bin/env bash
# Claude SEO: Ahrefs extension uninstaller.
set -euo pipefail

SKILL_DIR="${HOME}/.claude/skills/seo-ahrefs"
MCP_CONFIG_JSON="${HOME}/.claude.json"

if [ -d "${SKILL_DIR}" ]; then
    rm -rf "${SKILL_DIR}"
    echo "✓ Removed ${SKILL_DIR}"
fi

# Remove mcpServers.ahrefs from ~/.claude.json (where Claude Code reads MCP
# servers), and the stale copy older releases wrote to ~/.claude/settings.json.
# The helper rewrites a file atomically and never touches one that does not parse.
CLEANUP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/mcp_config_cleanup.py"
if [ -f "${CLEANUP}" ]; then
    python3 "${CLEANUP}" ahrefs --file "${MCP_CONFIG_JSON}" \
        || echo "  ⚠  Could not update ${MCP_CONFIG_JSON}; remove mcpServers.ahrefs manually."
    python3 "${CLEANUP}" ahrefs || true
else
    echo "  ⚠  Remove mcpServers.ahrefs from ${MCP_CONFIG_JSON} manually."
fi

echo "Done."
