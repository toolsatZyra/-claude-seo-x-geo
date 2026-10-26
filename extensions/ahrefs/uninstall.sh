#!/usr/bin/env bash
# Claude SEO: clean up the retired Ahrefs extension.
#
# Removes the seo-ahrefs skill and the extension's old MCP entry. An "ahrefs"
# entry that is not the old local @ahrefs/mcp package (for example Ahrefs'
# hosted connector, added by the user with `claude mcp add`) is kept.
set -euo pipefail

SKILL_DIR="${HOME}/.claude/skills/seo-ahrefs"
MCP_CONFIG_JSON="${HOME}/.claude.json"
CLEANUP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/mcp_config_cleanup.py"

if [ -d "${SKILL_DIR}" ]; then
    rm -rf "${SKILL_DIR}"
    echo "✓ Removed ${SKILL_DIR}"
fi

# Which kind of mcpServers.ahrefs entry is in ~/.claude.json: legacy, other or none.
# A file that does not parse is reported as none and never touched.
ENTRY="$(python3 - "${MCP_CONFIG_JSON}" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        server = json.load(fh).get("mcpServers", {}).get("ahrefs")
except (OSError, ValueError, AttributeError):
    server = None
if not isinstance(server, dict):
    print("none")
elif any("@ahrefs/mcp" in str(arg) for arg in server.get("args") or []):
    print("legacy")
else:
    print("other")
PY
)"

case "${ENTRY}" in
    legacy)
        if [ -f "${CLEANUP}" ]; then
            python3 "${CLEANUP}" ahrefs --file "${MCP_CONFIG_JSON}" \
                || echo "  ⚠  Could not update ${MCP_CONFIG_JSON}; remove mcpServers.ahrefs manually."
        else
            echo "  ⚠  Remove mcpServers.ahrefs from ${MCP_CONFIG_JSON} manually."
        fi
        ;;
    other)
        echo "✓ Kept mcpServers.ahrefs in ${MCP_CONFIG_JSON}: it is not this extension's old local server."
        ;;
esac

# Older releases also wrote this server, with its credential, to
# ~/.claude/settings.json, which Claude Code never reads for MCP servers.
[ -f "${CLEANUP}" ] && python3 "${CLEANUP}" ahrefs || true

echo "Done."
