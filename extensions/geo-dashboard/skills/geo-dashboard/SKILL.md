---
name: geo-dashboard
description: >
  Optional CRM/report dashboard for viewing GEO prospect and audit data via
  a Rich-based terminal UI. Not a core skill — installed separately via
  extensions/geo-dashboard/install.sh. No core claude-seo skill depends on
  this extension or imports flask/rich.
metadata:
  version: "3.0.0"
  author: geo-seo-claude (grafted, extension-only)
---

# geo-dashboard

Run `python3 scripts/crm_dashboard.py` to view the prospect CRM summary, or
`--prospect PRO-001` for a single prospect's detail view, or `--refresh` to
update and display. Reads from `~/.geo-prospects/prospects.json`,
`~/.geo-prospects/audits/`, and `~/.geo-prospects/proposals/` — the same
data directories used by the `geo-prospect` and `geo-proposal` core skills.

This skill requires `flask` and `rich`, installed by
`extensions/geo-dashboard/install.sh` — never a dependency of any core
`seo-*` or `geo-*` skill.
