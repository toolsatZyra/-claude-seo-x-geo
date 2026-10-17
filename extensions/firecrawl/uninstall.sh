#!/usr/bin/env bash
set -euo pipefail

echo "Removing Firecrawl extension..."

# Remove skill directory
rm -rf "${HOME}/.claude/skills/seo-firecrawl"
echo "v Removed skill files"

# Remove the MCP entry from ~/.claude.json (where Claude Code reads MCP
# servers), and the stale copy older releases wrote to ~/.claude/settings.json.
# The helper rewrites a file atomically and never touches one that does not parse.
CLEANUP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/mcp_config_cleanup.py"
if [ -f "${CLEANUP}" ]; then
    python3 "${CLEANUP}" firecrawl-mcp --file "${HOME}/.claude.json" \
        || echo "  Warning: Could not update ~/.claude.json automatically."
    python3 "${CLEANUP}" firecrawl-mcp || true
else
    echo "  Warning: remove 'firecrawl-mcp' from mcpServers in ~/.claude.json manually."
fi

echo ""
echo "v Firecrawl extension uninstalled."
echo "  Core Claude SEO skills are unchanged."
