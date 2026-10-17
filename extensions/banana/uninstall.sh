#!/usr/bin/env bash
set -euo pipefail

main() {
    echo "→ Uninstalling Banana Image Generation extension..."

    # Remove skill (includes copied scripts and references)
    rm -rf "${HOME}/.claude/skills/seo-image-gen"

    # Remove agent
    rm -f "${HOME}/.claude/agents/seo-image-gen.md"

    # Ask before removing MCP server (user may use standalone banana skill)
    MCP_CONFIG_FILE="${HOME}/.claude.json"
    if [ -d "${HOME}/.claude/skills/banana" ]; then
        echo "  ℹ  Standalone banana skill detected at ~/.claude/skills/banana/"
        echo "  ℹ  Keeping nanobanana-mcp in ~/.claude.json (used by standalone skill)"
    else
        # No standalone skill, safe to remove MCP: from ~/.claude.json (where
        # Claude Code reads MCP servers) and the stale copy older releases
        # wrote to ~/.claude/settings.json. The helper rewrites a file
        # atomically and never touches one that does not parse.
        CLEANUP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/mcp_config_cleanup.py"
        if [ -f "${CLEANUP}" ]; then
            python3 "${CLEANUP}" nanobanana-mcp --file "${MCP_CONFIG_FILE}" \
                || echo "  ⚠  Could not auto-remove MCP config. Remove 'nanobanana-mcp' from ~/.claude.json manually."
            python3 "${CLEANUP}" nanobanana-mcp || true
        else
            echo "  ⚠  Remove 'nanobanana-mcp' from mcpServers in ~/.claude.json manually."
        fi
    fi

    echo "✓ Banana Image Generation extension uninstalled."
}

main "$@"
