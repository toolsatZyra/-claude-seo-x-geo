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
| `dataforseo` | Default when `/seo links setup` shows REST credentials | About $0.02 per call plus $0.00004 per requested row: **$0.06 per target** at the 1,000-row default. `--dry-run` prints the exact estimate; `--max-cost` is a hard cap (see the note below the table) |
| `moz` | Free fallback or cross-check | Free tier: 2,500 rows a month, 50 per target |
| `csv-ahrefs`, `csv-semrush`, `csv-gsc`, `csv-generic` | You already have exports | Free |

A gap run uses **one** source for every domain. Never mix sources in one run: authority scales differ and row limits differ.

**The cost cap.** The dry run and the pre-run refusal price every target at the row-aware estimate. During the run a call starts only if what is already spent, plus the larger of that estimate and the costliest call seen so far, fits under `--max-cost`. So a cap equal to the dry-run estimate is not exceeded. A real call can still cost more than its estimate; when it does, the guard assumes the same for the next call and stops sooner.

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
   - Exit code 1 means some targets failed (a network error or an API error is recorded as that target's error snapshot) while the rest completed. Report which targets are missing.
   - For CSV exports, run `link_sources.py import --project <domain> --target <domain-in-export> --format ahrefs <file>` once per domain instead.
3. **Segment:** `python3 scripts/link_gap.py gap --project <domain> --source <source> --json`.
4. **Report:**
   - the segment counts (gap, single, shared, moat);
   - coverage, with any warning (a missing competitor or a row cap);
   - the gap-segment domains from the `domains` list (`segment` is `gap`): the sites that link to two or more competitors and not to the client, each with the competitors it links to. `gap` does not score or rank them; `prospects` does.

### `/seo links prospects <domain>`

**Gate: confirm the profile topics first.** Topic fit is 20 of the 100 points, so the terms matter.
1. `python3 scripts/seo_project.py show <domain> --json` and read `topics`.
2. If it is empty, ask the user for 3-6 service terms (what the business sells, as buyers search for it) and set them: `python3 scripts/seo_project.py set <domain> topics '["term one", "term two"]'`.
3. Only if the user declines, run on sitemap-derived terms. The first `prospects` run derives them, stores them in the links store (never in the profile) and warns that they are noisy; later runs reuse them, so `prospects` and `add` rank identically. `--refresh-topics` re-reads the sitemap. Profile topics always win.

Then run `python3 scripts/link_gap.py prospects --project <domain> --source <source> --top 30 --json`, optionally with `--csv prospects.csv`.

**Present gap prospects first.** `gap_prospects` holds the sites that link to two or more competitors and not to the client, in score order. Show them before anything else, as the core answer to "who links to our competitors and not to us". The score formula is unchanged, so a strong single-competitor site can still outscore a gap site in `prospects`; that list is the full ranking. Then show the rest in three groups:
- **High-value** (score ≥ 70);
- **Quick wins** (low effort, score ≥ 50);
- **Backlog**.

For each prospect, show its score, type, the rule that matched, the competitors it links to, and one evidence line (sample URL plus anchor). Types come from rules, so they are INFERRED; say so. The formula and the classification rules are in `references/prospect-scoring.md`. To see why a host was excluded or how it is typed, run `python3 scripts/link_hosts.py check <domain> [url]`; to fix a miss, add the host to the matching list in `scripts/link_hosts.py` with a test.

**Exclusions.** Show `excluded_counts`, then name the notable domains. The reasons: `own_property`, `competitor_property`, `social_ugc` (incl. Behance and Dribbble), `staging_or_dev_host`, `spam`, `paid_or_scheme` (link-selling words), `link_network` (the same page path or title on five or more unrelated sites, a link farm; the entry's `detail` says which). If the client is an SEO business, real articles about backlinks can land in `paid_or_scheme`; check that list before dismissing it.

### `/seo links draft <domain> --top N`

1. Confirm the profile topics first (see the gate under `prospects`). Then run `python3 scripts/link_outreach.py add --project <domain> --source <source> --top N --json`.
   - Gap domains are taken first, then single-competitor domains. `--segment gap` limits it to gap domains.
   - `add` uses the same stored topics as `prospects`, so it picks the same prospects the user just saw.
   - Domains are skipped, with the reason, when the organization (any subdomain) is do-not-contact, already tracked, or in cooldown, and when a prospect was skipped earlier (`--include-skipped` overrides only that last one).
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
| Verify won links | `link_outreach.py verify --project <domain> --json`. `verified_status` is `live`, `missing`, `unverifiable` (the page answered but is JS-rendered or redirected, so the link cannot be confirmed: check it by hand) or `unreachable`. The row stays won in every case. |
| Board | `link_outreach.py board --project <domain> --json` |
| KPIs for `/seo track` | `link_gap.py kpis --project <domain> --source <source> --emit-kpis kpis-links-gap.json` and `link_outreach.py kpis --project <domain> --emit-kpis kpis-links.json`, then `performance_tracker.py ingest kpis-links-gap.json kpis-links.json` |

Notes on the pipeline:
- **Follow-ups:** one only, at least 7 days after first contact. It needs its own draft and approval. If the prospect replies while a follow-up draft is waiting, record the outcome (`won`, `lost` or `no_reply`) directly; do not approve and mark a follow-up that was never sent.
- **Cooldown:** `lost` and `no_reply`, and `skipped` or `do_not_contact` after first contact, start a 90-day cooldown before the domain can be re-added.
- **Organization-wide:** do-not-contact, active status and cooldown cover the whole registrable domain, so `blog.example.org` is held back by anything recorded for `example.org`.
- **Skipped:** a skipped prospect stays skipped; `add --include-skipped` is the explicit way back.
- **Approval is bound to the brief:** if the brief changed after `save-draft`, `approve` refuses until the draft is saved again against the current brief hash.
- **Win rate:** `links.win_rate` stays null until 5 prospects have been contacted.

## Error handling

| Situation | Action |
|---|---|
| `link_sources.py` exit 2: no credentials | Run `/seo links setup`. Never switch source silently. |
| Exit 3: stopped (funds or cap) | Report the coverage. Ask before spending more. |
| `link_gap.py` error: no client snapshot | Fetch or import the client domain first, from the same source. |
| Warning: a competitor is missing from the source | Report the coverage gap. Do not fill it from another source. |
| `save-draft` exit 1 | Show the lint problems (banned asks, URLs or email addresses not in the brief, length), rewrite, save again. |
| `mark` or `approve` exit 2 | The pipeline rule refused it. Explain the rule; do not force it. |

## Related skills

- `seo-backlinks`: the client's own profile, toxic links and disavow.
- `seo-competitors`: the full competitor hub. Its link-gap step routes here.
- `seo-track`: KPI history, including `links.*`.
- `geo-brand-mentions`: unlinked brand mentions. Import them with `--format generic` to reclaim them as links.
