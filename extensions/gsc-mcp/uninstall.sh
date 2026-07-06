#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="${HOME}/.claude/skills/seo-gsc-mcp"
[ -d "${SKILL_DIR}" ] && rm -rf "${SKILL_DIR}" && echo "✓ Removed ${SKILL_DIR}"
command -v claude >/dev/null 2>&1 && claude mcp remove gsc-mcp 2>/dev/null && echo "✓ Removed gsc-mcp MCP server registration" || true
