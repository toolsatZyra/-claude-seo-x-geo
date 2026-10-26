# Ahrefs extension retirement: design

- **Date:** 2026-10-26.
- **Status:** approved by Riya ("No, retire it", then "remove this from skill").

## Why

1. **It never worked.** `extensions/ahrefs/install.sh` wrote the key as `env.AHREFS_API_TOKEN`, but `@ahrefs/mcp@0.0.11` reads `process.env.API_KEY` (checked in the npm tarball). The server always started without a key.
2. **The package is dead.** Ahrefs archived `ahrefs/ahrefs-mcp-server` on 2026-02-24. Its README says it "IS NOT maintained" and points to the hosted server.
3. **The replacement needs a paid plan.** Ahrefs' hosted MCP (`https://api.ahrefs.com/mcp/mcp`, OAuth) needs a Lite plan or higher, and ZYRA has none.

## What changes

| Piece | Change |
|---|---|
| `extensions/ahrefs/skills/seo-ahrefs/` | Deleted |
| `extensions/ahrefs/install.sh`, `install.ps1` | Print a retirement notice and the alternatives, then exit 0. They write nothing and change no configuration. |
| `extensions/ahrefs/uninstall.sh` | Removes `~/.claude/skills/seo-ahrefs`. Removes `mcpServers.ahrefs` from `~/.claude.json` **only** when it is the old local entry (an arg mentions `@ahrefs/mcp`); a hosted `api.ahrefs.com` entry is left alone. The legacy `~/.claude/settings.json` copy is still removed. |
| `extensions/ahrefs/docs/AHREFS-SETUP.md` | Same filename, so links still work. Rewritten as the retirement notice: why, alternatives, clean-up. |
| README, `docs/MCP-INTEGRATION.md`, `skills/seo/SKILL.md`, `.claude-plugin/marketplace.json` | Ahrefs dropped as a bundled extension; the count goes from 8 to 7. The MCP-integration table keeps Ahrefs as an ecosystem entry, with the hosted endpoint and "not bundled". |
| `CHANGELOG.md` | An Unreleased entry recording the removal and the key-name bug |
| Tests | Ahrefs removed from the lists of "has a skill / takes a secret / PS1 writes config". New `tests/test_ahrefs_retired.py` (see below). |

**Unchanged:** Ahrefs CSV imports (`link_sources.py` `--format ahrefs`, keyword and rank-tracker CSV readers). Ahrefs remains a data source through exports.

## Tests (`tests/test_ahrefs_retired.py`)

1. The installer, run with a temporary `HOME`, exits 0, says "retired" and creates no `.claude.json` and no skill directory.
2. No `seo-ahrefs` skill ships under `extensions/ahrefs/`.
3. The uninstaller removes the legacy entry and the installed skill directory, and keeps a hosted entry.
4. No file outside the history (`CHANGELOG.md`, `docs/MIGRATION-v1-to-v2.md`, `docs/superpowers/`) and the retirement doc mentions `@ahrefs/mcp@0.0.11`.
5. The marketplace description lists 7 extensions and not Ahrefs.

## Out of scope

- A hosted-connector integration. Revisit only if ZYRA buys an Ahrefs plan.
- The user's machine. Removing the installed broken skill there needs Riya's OK at that step.
