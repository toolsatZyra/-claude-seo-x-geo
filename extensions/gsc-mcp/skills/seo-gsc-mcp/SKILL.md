---
name: seo-gsc-mcp
description: >
  OAuth-free alternative to seo-google's native Google Search Console
  integration, via an MCP server. Documented as an alternative, not a
  requirement — the native google-api-python-client path in seo-google
  (scripts/gsc_query.py, scripts/gsc_inspect.py) remains the primary,
  test-covered GSC integration for this plugin.
metadata:
  version: "3.0.0"
  author: GrowthZyra (new, extension-only)
---

# seo-gsc-mcp

Installed via `extensions/gsc-mcp/install.sh` (or `.ps1` on Windows). Wires a
Google Search Console MCP server for operators who want live GSC data
(Search Analytics, URL Inspection, Sitemaps) without setting up a GCP OAuth
app themselves.

**This does not replace `seo-google`.** Prefer `seo-google`'s native path
(`scripts/gsc_query.py`, `scripts/gsc_inspect.py`) whenever OAuth setup is
feasible — it is deterministic and covered by `tests/test_gsc_query.py`.
Use this extension only when the operator explicitly wants the OAuth-free
path.

## Usage

Once installed, GSC data is available through whatever tool names the
configured MCP server exposes (server-dependent — check the server's own
documentation for exact tool names). Typical operations: list verified
sites, query Search Analytics (clicks/impressions/CTR/position by
query/page/date), request URL inspection status, list/submit sitemaps.

Cross-reference `seo-google/SKILL.md` for what live GSC data feeds into
which claude-seo report sections — the same report sections apply
regardless of which GSC integration (native or MCP) supplied the data.
