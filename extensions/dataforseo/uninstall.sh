#!/usr/bin/env bash
set -euo pipefail

main() {
    echo "→ Uninstalling DataForSEO extension..."

    # Remove skill
    rm -rf "${HOME}/.claude/skills/seo-dataforseo"

    # Remove agent
    rm -f "${HOME}/.claude/agents/seo-dataforseo.md"

    # Remove field config
    rm -f "${HOME}/.claude/skills/seo/dataforseo-field-config.json"

    # Remove the MCP server entry from ~/.claude.json (where Claude Code reads
    # MCP servers), and the stale copy older releases wrote to
    # ~/.claude/settings.json. The helper rewrites a file atomically and never
    # touches one that does not parse.
    CLEANUP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/mcp_config_cleanup.py"
    if [ -f "${CLEANUP}" ]; then
        python3 "${CLEANUP}" dataforseo --file "${HOME}/.claude.json" \
            || echo "  ⚠  Could not auto-remove MCP config. Remove 'dataforseo' from ~/.claude.json manually."
        python3 "${CLEANUP}" dataforseo || true
    else
        echo "  ⚠  Remove 'dataforseo' from mcpServers in ~/.claude.json manually."
    fi

    echo "✓ DataForSEO extension uninstalled."
}

main "$@"
