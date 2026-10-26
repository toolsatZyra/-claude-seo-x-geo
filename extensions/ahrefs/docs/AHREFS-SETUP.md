# Ahrefs extension: retired

The Ahrefs extension was retired on 2026-10-26. `install.sh` and
`install.ps1` now only print this notice; they install nothing and change no
settings.

## Why

- **It never worked.** The installer saved the key as `AHREFS_API_TOKEN`,
  but the package it ran, `@ahrefs/mcp@0.0.11`, reads `API_KEY`. The server
  always started without a key.
- **The package is archived.** Ahrefs archived `ahrefs/ahrefs-mcp-server` on
  2026-02-24 and says it "IS NOT maintained".
- **The replacement needs a paid plan.** Ahrefs' hosted MCP server
  (`https://api.ahrefs.com/mcp/mcp`, browser sign-in) requires a Lite plan or
  higher, and every call uses API units.

## What to use instead

| Need | Use |
|---|---|
| Backlink and referring-domain data | DataForSEO (`./extensions/dataforseo/install.sh`) or Moz's free tier (`/seo backlinks setup`) |
| Ahrefs data you already have | Export a CSV from Ahrefs and give it to `/seo links` (it runs `link_sources.py import --format ahrefs`) or to `/seo keywords` |
| Live Ahrefs data, with a paid Ahrefs plan | Ahrefs' own hosted connector: [Ahrefs MCP for Claude Code](https://docs.ahrefs.com/mcp/docs/claude-code.md). It is not supported by this plugin. |

## Clean up an earlier install

```bash
./extensions/ahrefs/uninstall.sh
```

The uninstaller:
- removes `~/.claude/skills/seo-ahrefs`;
- removes `mcpServers.ahrefs` from `~/.claude.json` **only** if it runs the
  old local `@ahrefs/mcp` package (an Ahrefs hosted connector you added
  yourself is kept);
- removes the stale copy older releases wrote to `~/.claude/settings.json`.

On Windows, delete `%USERPROFILE%\.claude\skills\seo-ahrefs`, then remove the
`ahrefs` entry under `mcpServers` in `%USERPROFILE%\.claude.json` if it runs
the local `@ahrefs/mcp` package.
