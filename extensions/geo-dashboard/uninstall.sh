#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="${HOME}/.claude/skills/geo-dashboard"
[ -d "${SKILL_DIR}" ] && rm -rf "${SKILL_DIR}" && echo "✓ Removed ${SKILL_DIR}"
echo "Note: flask/rich were installed via pip and are left in place — remove manually with 'pip uninstall flask rich' if desired."
