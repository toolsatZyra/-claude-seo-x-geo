# Claude SEO: Ahrefs extension (retired 2026-10-26).
# Mirrors extensions/ahrefs/install.sh: installs nothing and changes no settings.
# The extension never worked (it saved the key as AHREFS_API_TOKEN while the
# archived local package reads API_KEY), and Ahrefs archived that package on
# 2026-02-24. See extensions/ahrefs/docs/AHREFS-SETUP.md.

Write-Host @"
The Claude SEO Ahrefs extension is retired. Nothing was installed or changed.

Why: Ahrefs archived the local @ahrefs/mcp package this extension used
(2026-02-24), and the extension never passed its key to that package.

Instead:
  - Backlink data: DataForSEO (.\extensions\dataforseo\install.ps1) or Moz's
    free tier (/seo backlinks setup).
  - Ahrefs data you already have: export a CSV from Ahrefs and give it to
    /seo links (it runs link_sources.py import --format ahrefs) or to
    /seo keywords.
  - Ahrefs' own hosted connector (paid Lite plan or higher; not supported by
    this plugin): https://docs.ahrefs.com/mcp/docs/claude-code.md

To remove an earlier install, delete %USERPROFILE%\.claude\skills\seo-ahrefs
and remove the "ahrefs" entry under mcpServers in %USERPROFILE%\.claude.json
if it runs the local @ahrefs/mcp package.
"@
