---
name: seo-links
description: >
  Competitor backlink study and white-hat link earning. Finds the sites that
  link to two or more competitors but not to you, classifies and scores them
  for relevance, drafts outreach that a named person approves and sends, tracks
  the pipeline, verifies won links and reports links.* KPIs. Sources: DataForSEO,
  Moz, or a CSV export (Ahrefs, Semrush, Search Console). Use when user says
  "link building", "link gap", "competitor backlinks", "who links to my
  competitors", "link prospects", "link outreach", "earn links", "link
  intersect", or "digital PR".
user-invocable: true
argument-hint: "[setup|gap|prospects|draft|track] [domain]"
license: MIT
metadata:
  author: ZYRA
  version: "3.1.0"
  category: seo
---

# Link Gap and Link Earning

This skill answers three questions:
- **Who links to our competitors and not to us,** and which of those sites are worth earning?
- **What should we offer each one,** and what exactly do we say?
- **Did it work?** Won links are verified on the page, then tracked as KPIs.

**Hard rules.** These come from `references/outreach-rules.md` and are not negotiable:
- No paid links, link exchanges, reciprocal links or "dofollow" asks.
- Nothing is ever sent by this skill. A named person approves every draft and sends it from their own email.
- Claim only what the client profile allows. Never invent clients, results or numbers.
- No personal email harvesting: contact paths are public pages only.

## Data source (one per run)

| Source | When | Cost |
|---|---|---|
| `dataforseo` | Default when `/seo links setup` shows REST credentials | About $0.02 per target (guard estimate), hard cap with `--max-cost` |
| `moz` | Free fallback or cross-check | Free tier: 2,500 rows a month, 50 per target |
| `csv-ahrefs`, `csv-semrush`, `csv-gsc`, `csv-generic` | You already have exports | Free |

A gap run uses **one** source for every domain. Never mix sources in one run: authority scales differ and row limits differ.

## Commands

Scripts live in `scripts/` and print JSON with `--json`.

### `/seo links setup`

1. `python3 scripts/backlinks_auth.py --check dataforseo --json`
   - `stale_config: true` means the credentials are in `~/.claude/settings.json`, which Claude Code never loads. Show the `fix` text and offer to run it.
   - `rest_credentials: true` means scripts can call DataForSEO now.
2. `python3 scripts/link_sources.py status --json`: Moz and CSV availability.
3. Confirm the profile: `python3 scripts/seo_project.py show <domain> --json`.
   - It needs 3-7 competitors and `markets.country`.
   - It needs `topics` (service terms). Set them with `python3 scripts/seo_project.py set <domain> topics '["term one", "term two"]'`.

### `/seo links gap <domain>`

1. **Estimate first:** `python3 scripts/link_sources.py fetch --project <domain> --source dataforseo --dry-run --json`. Show the estimated cost and **ask for approval** before any paid call.
2. **Fetch:** `python3 scripts/link_sources.py fetch --project <domain> --source dataforseo --max-cost <approved> --json`.
   - Exit code 3 means the run stopped early (insufficient funds or the cap). Report the coverage and do not retry automatically.
   - For CSV exports, run `link_sources.py import --project <domain> --target <domain-in-export> --format ahrefs <file>` once per domain instead.
3. **Segment:** `python3 scripts/link_gap.py gap --project <domain> --source <source> --json`.
4. **Report:**
   - the segment counts (gap, single, shared, moat);
   - coverage, with any warning (a missing competitor, a row cap, no topics);
   - the 10 largest gap domains.

### `/seo links prospects <domain>`

`python3 scripts/link_gap.py prospects --project <domain> --source <source> --top 30 --json`, optionally with `--csv prospects.csv`.

Present the results as three groups:
- **High-value** (score ≥ 70);
- **Quick wins** (low effort, score ≥ 50);
- **Backlog**.

For each prospect, show its score, type, the rule that matched, the competitors it links to, and one evidence line (sample URL plus anchor). Then list the excluded domains with their reasons. Types come from rules, so they are INFERRED; say so. The formula is in `references/prospect-scoring.md`.

### `/seo links draft <domain> --top N`

1. Run `python3 scripts/link_outreach.py add --project <domain> --source <source> --top N --json`.
2. For each added prospect, get its brief: `python3 scripts/link_outreach.py brief --project <domain> --domain <prospect> --json`.
3. Write the draft **from the brief only**, following `references/link-earning-playbook.md` for the tactic and `references/outreach-rules.md` for tone:
   - a subject of at most 90 characters;
   - a body of at most 150 words;
   - one ask;
   - links only to `asset_url` or `client_home`.
4. Save it: write the body to a temp file, then run `python3 scripts/link_outreach.py save-draft --project <domain> --domain <prospect> --brief-hash <hash> --subject "<subject>" --body-file <file> --json`.
   - A lint failure (exit 1) lists the offending spans.
   - Rewrite and save again. **Never** work around the lint.
5. Show every draft to the user and ask who approves it.

### `/seo links track <domain>`

| Action | Command |
|---|---|
| Approve (the user names the reviewer) | `link_outreach.py approve --project <domain> --domain <prospect> --reviewed-by "<Name>"` |
| Export approved drafts for the user's own email tool | `link_outreach.py export --project <domain> --out outreach.csv` |
| After the user says it was sent | `link_outreach.py mark --project <domain> --domain <prospect> --status contacted` |
| Outcome | `mark --status won --link-url <page on their site>`, or `lost`, `no_reply`, `skipped`, `do_not_contact` |
| Verify won links | `link_outreach.py verify --project <domain> --json` |
| Board | `link_outreach.py board --project <domain> --json` |
| KPIs for `/seo track` | `link_gap.py kpis --project <domain> --source <source> --emit-kpis kpis-links-gap.json` and `link_outreach.py kpis --project <domain> --emit-kpis kpis-links.json`, then `performance_tracker.py ingest kpis-links-gap.json kpis-links.json` |

Notes on the pipeline:
- **Follow-ups:** one only, at least 7 days after first contact. It needs its own draft and approval.
- **Cooldown:** `lost` and `no_reply` start a 90-day cooldown before the domain can be re-added.
- **Win rate:** `links.win_rate` stays null until 5 prospects have been contacted.

## Error handling

| Situation | Action |
|---|---|
| `link_sources.py` exit 2: no credentials | Run `/seo links setup`. Never switch source silently. |
| Exit 3: stopped (funds or cap) | Report the coverage. Ask before spending more. |
| `link_gap.py` error: no client snapshot | Fetch or import the client domain first, from the same source. |
| Warning: a competitor is missing from the source | Report the coverage gap. Do not fill it from another source. |
| `save-draft` exit 1 | Show the lint problems, rewrite, save again. |
| `mark` or `approve` exit 2 | The pipeline rule refused it. Explain the rule; do not force it. |

## Related skills

- `seo-backlinks`: the client's own profile, toxic links and disavow.
- `seo-competitors`: the full competitor hub. Its link-gap step routes here.
- `seo-track`: KPI history, including `links.*`.
- `geo-brand-mentions`: unlinked brand mentions. Import them with `--format generic` to reclaim them as links.
