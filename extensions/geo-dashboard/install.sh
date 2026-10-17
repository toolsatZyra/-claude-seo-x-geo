#!/usr/bin/env bash
# Claude SEO x GEO — optional CRM/report dashboard extension installer.
#
# Installs the Rich-based CLI dashboard for viewing GEO prospect/audit data.
# This is the ONLY place flask/rich are used in this plugin — never a core
# dependency of any skill.
set -euo pipefail

main() {
    SKILL_DIR="${HOME}/.claude/skills"

    echo "════════════════════════════════════════"
    echo "║  Claude SEO x GEO — Dashboard extension ║"
    echo "════════════════════════════════════════"

    command -v python3 >/dev/null 2>&1 || { echo "✗ Python 3 required."; exit 1; }
    [ ! -d "${SKILL_DIR}/seo" ] && { echo "✗ claude-seo base not installed."; exit 1; }

    SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"

    # flask>=3.1.3 matches requirements.txt's security floor.
    python3 -m pip install "flask>=3.1.3,<4.0.0" "rich>=13.0.0,<14.0.0"

    mkdir -p "${SKILL_DIR}/geo-dashboard"
    cp "${SOURCE_DIR}/skills/geo-dashboard/SKILL.md" "${SKILL_DIR}/geo-dashboard/SKILL.md"
    # Copy directory contents (not the directory itself) so a reinstall
    # updates files in place instead of nesting scripts/scripts.
    mkdir -p "${SKILL_DIR}/geo-dashboard/scripts" "${SKILL_DIR}/geo-dashboard/templates"
    cp -R "${SOURCE_DIR}/scripts/." "${SKILL_DIR}/geo-dashboard/scripts/"
    cp -R "${SOURCE_DIR}/templates/." "${SKILL_DIR}/geo-dashboard/templates/"

    echo "Done. Try: python3 ${SKILL_DIR}/geo-dashboard/scripts/crm_dashboard.py"
}
main "$@"
