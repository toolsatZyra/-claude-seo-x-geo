#!/usr/bin/env bash
# Claude SEO: Ahrefs extension (retired 2026-10-26).
#
# This extension is retired and installs nothing. It never worked: it saved
# the key as AHREFS_API_TOKEN while the archived local package reads API_KEY,
# and Ahrefs archived that package on 2026-02-24. Ahrefs' hosted replacement
# needs a paid plan. See extensions/ahrefs/docs/AHREFS-SETUP.md.
set -euo pipefail

cat <<'EOF'
The Claude SEO Ahrefs extension is retired. Nothing was installed or changed.

Why: Ahrefs archived the local @ahrefs/mcp package this extension used
(2026-02-24), and the extension never passed its key to that package.

Instead:
  - Backlink data: DataForSEO (./extensions/dataforseo/install.sh) or Moz's
    free tier (/seo backlinks setup).
  - Ahrefs data you already have: export a CSV from Ahrefs and give it to
    /seo links (it runs link_sources.py import --format ahrefs) or to
    /seo keywords.
  - Ahrefs' own hosted connector (paid Lite plan or higher; not supported by
    this plugin): https://docs.ahrefs.com/mcp/docs/claude-code.md

To remove an earlier install of this extension, run:
  ./extensions/ahrefs/uninstall.sh
EOF
