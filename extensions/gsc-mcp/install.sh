#!/usr/bin/env bash
# Claude SEO x GEO — optional Google Search Console MCP extension installer.
#
# This is an OAuth-free ALTERNATIVE to the native GSC path already provided
# by skills/seo-google (scripts/gsc_query.py, scripts/gsc_inspect.py). It is
# for operators who want live GSC data without setting up a GCP OAuth app.
# No core skill depends on this extension.
set -euo pipefail

main() {
    SKILL_DIR="${HOME}/.claude/skills"
    SETTINGS_JSON="${HOME}/.claude/settings.json"

    echo "════════════════════════════════════════"
    echo "║   Claude SEO x GEO — GSC-MCP extension   ║"
    echo "════════════════════════════════════════"
    echo "This wires a Google Search Console MCP server as an OAuth-free"
    echo "alternative to the native seo-google GSC integration."
    echo

    command -v node >/dev/null 2>&1 || { echo "✗ Node.js required for the MCP server."; exit 1; }
    [ ! -d "${SKILL_DIR}/seo" ] && { echo "✗ claude-seo base not installed."; exit 1; }
    command -v claude >/dev/null 2>&1 || { echo "✗ Claude Code CLI required (for 'claude mcp add')."; exit 1; }

    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

    read -rp "Path to your Google Search Console MCP server package (npm package name or local path): " GSC_MCP_PACKAGE
    [ -z "${GSC_MCP_PACKAGE}" ] && { echo "✗ No package specified."; exit 1; }

    claude mcp add gsc-mcp -- npx -y "${GSC_MCP_PACKAGE}"

    mkdir -p "${SKILL_DIR}/seo-gsc-mcp"
    cp "${SOURCE_DIR}/skills/seo-gsc-mcp/SKILL.md" "${SKILL_DIR}/seo-gsc-mcp/SKILL.md"

    echo "Done. This extension does not replace seo-google's native GSC path —"
    echo "it is documented as an alternative. Try: /seo gsc-mcp sites"
}
main "$@"
