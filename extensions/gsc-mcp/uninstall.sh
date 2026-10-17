#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="${HOME}/.claude/skills/seo-gsc-mcp"
[ -d "${SKILL_DIR}" ] && rm -rf "${SKILL_DIR}" && echo "✓ Removed ${SKILL_DIR}"
# Installs since ZYRA v3.1 register the server at user scope; earlier ones used
# the default local scope of whatever directory the installer ran in.
if command -v claude >/dev/null 2>&1; then
    claude mcp remove --scope user gsc-mcp 2>/dev/null && echo "✓ Removed gsc-mcp MCP server registration (user scope)" || true
    claude mcp remove --scope local gsc-mcp 2>/dev/null && echo "✓ Removed gsc-mcp MCP server registration (local scope)" || true
fi
