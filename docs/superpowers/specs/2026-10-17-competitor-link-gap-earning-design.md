# Competitor link gap and link earning: design

- **Date:** 2026-10-17
- **Status:** approved in brainstorming. **Amended 2026-10-18** after the final whole-branch review and a live run on thezyra.studio (the amended rules are marked *(amended)*).
- **Scope:** a new `seo-links` skill and three scripts. It also fixes the backlink-source detection and wires the new skill into the hub.

## 1. Problem

The user asked for the skill to "study competitor backlinks and earn relevant links". The capability inventory on 2026-10-17 found:

- **Competitor link gap.** `/seo backlinks gap` and `/seo competitors` step 4 are prompt instructions, not scripts.
  - In practice they need DataForSEO.
  - The free Moz path only compares DA/PA, although `moz_api.py domains` already returns the referring domains of any domain.
  - Bing can only compare sites verified in the same Bing account.
- **Link earning does not exist.** "Link Building Opportunities (top 10)" is a report heading. There is no prospect scoring, no drafts, no tracker, no won-link verification and no link KPI.
- **Source detection misreports.** `backlinks_auth.py` reports "Tier 3, Premium (DataForSEO MCP)" because `~/.claude/settings.json` contains `mcpServers.dataforseo`.
  - Claude Code does not load MCP servers from that file. The upstream v2.3.0 fix moved installers to `~/.claude.json`, and `extensions/mcp_config_cleanup.py` exists to remove such stale entries.
  - So DataForSEO has never loaded on this machine, and its credentials sit in the wrong file.
- **Moz and Bing keys are empty** in `~/.config/claude-seo/backlinks-api.json`.

## 2. Decisions

| Question | Decision |
|---|---|
| Data source to build and live-test | DataForSEO (REST) as the primary source, a free Moz key as fallback and cross-check, and CSV import from any tool |
| How far "earn" goes | Prospects, outreach drafts that a human approves and sends, a pipeline tracker, won-link verification and KPIs |
| Architecture | A new `seo-links` skill on a small deterministic core (approach A). It does not extend `competitor_gap.py` (approach B) or rely on prompt-only MCP calls (approach C). |

**Non-negotiables carried over from the hub:**
- No paid links, link exchanges or reciprocal links. Outrank's link exchange was refused in v3.1 under Google's link-spam policy.
- Nothing is sent automatically.
- Client data lives in `$CLAUDE_SEO_DATA_DIR`, never in the repo.
- Scoring is deterministic and computed from stored snapshots.

## 3. Components

| Unit | Purpose | Depends on |
|---|---|---|
| `scripts/link_sources.py` | Fetch or import referring domains into normalized, dated snapshots | `seo_store`, `dataforseo_costs`, `backlinks_auth`, `moz_api`. It calls two fixed API hosts and takes no URL from input or fetched content, so it does not use `url_safety` *(amended)* |
| `scripts/link_store.py` | Shared `links` store schema plus snapshot read and write, used by all three scripts | `seo_store` |
| `scripts/link_gap.py` | Segment, exclude, classify and score prospects from snapshots. No network, except one optional sitemap read for topic terms (§5.3) | `link_store`, `seo_store`, `seo_project`, `seo_kpi` |
| `scripts/link_outreach.py` | Tracker, briefs, draft storage and lint, approvals, status, verification, export, KPIs | `link_gap`, `link_store`, `seo_store`, `verify_backlinks`, `seo_kpi` |
| `skills/seo-links/SKILL.md` | Routes `/seo links ...`, orchestrates, writes drafts from briefs | the three scripts |
| `skills/seo-links/references/link-earning-playbook.md` | Maps prospect type to tactic, asset and effort | |
| `skills/seo-links/references/outreach-rules.md` | Draft rules, banned asks, privacy, cadence | |
| `skills/seo-links/references/prospect-scoring.md` | The formula in section 6, with worked examples | |

Every script has a docstring, an argparse CLI and JSON output (with `--json`), plus tests.

## 4. Commands

| Command | Runs |
|---|---|
| `/seo links setup` | `backlinks_auth.py --check --json` (fixed detection), then the credential and Moz-key guidance |
| `/seo links gap <domain>` | `link_sources.py fetch` for the client and each profile competitor, then `link_gap.py gap` |
| `/seo links prospects <domain>` | Confirm the profile topics (a gate, §5.3), then `link_gap.py prospects`. Gap prospects are presented first *(amended)* |
| `/seo links draft <domain> --top N` | `link_outreach.py add` (`--segment gap\|single\|all`) and `brief`, Claude writes the drafts, then `link_outreach.py save-draft` (which lints) |
| `/seo links track <domain>` | `link_outreach.py board / approve / mark / verify / kpis / export` |

## 5. Data model and flow

### 5.1 Normalized referring-domain record

```json
{"domain": "example.org", "target": "competitor.com", "source": "dataforseo",
 "authority": 54.0, "authority_scale": "dataforseo_rank/10",
 "spam_score": 12, "dofollow": true, "attributes": ["nofollow"],
 "first_seen": "2025-03-01", "last_seen": "2026-10-10",
 "sample_url": "https://example.org/resources/training", "sample_anchor": "Competitor",
 "sample_title": "Training resources", "tld": "org"}
```

- **DataForSEO:** `POST /v3/backlinks/backlinks/live` with `mode: "one_per_domain"`, which returns one backlink per referring domain, ordered by rank descending.
  - Default limit: 1,000 per target.
  - Fields used: `domain_from`, `url_from`, `anchor`, `dofollow`, `domain_from_rank`, `backlink_spam_score`, `attributes`, `first_seen`, `last_seen` and `tld_from`. `page_from_title` is used where the response includes it.
  - Authority is `domain_from_rank` only. The backlink-level `rank` is never used as domain authority; if `domain_from_rank` is missing, authority is unknown.
  - Field names are checked against the API docs and were confirmed by the live smoke run of 2026-10-18 (fill rates about 1.0, `order_by` accepted). *(amended)* That response was not saved, so no sanitized live fixture exists; the adapter is tested against hand-built responses that use the documented fields. Recording a fixture is a follow-up (§14).
- **Moz:** `moz_api.get_linking_domains` gives the domain, Domain Authority and spam score, capped at 50 rows per call. It has no sample URL, anchor or title, so topic fit and link quality fall back to neutral and type classification uses the domain only.
- **CSV import:** formats `ahrefs`, `semrush`, `gsc` (Search Console "Top linking sites") and `generic`. Each has an explicit column map. *(amended)* Columns that are not in the map are **ignored** (real exports carry many); a missing `domain` column is an error that lists the expected columns. Files may be UTF-8 (with or without a byte-order mark) or UTF-16 (what Ahrefs writes), separated by comma, semicolon or tab (detected from the header). An unreadable encoding or a malformed row exits 2 with a message.
- **CSV source names.** CSV snapshots are stored with source `csv-<format>` (for example `csv-ahrefs`), so the single-source rule in §5.3 applies to them too.
- **Credentials:**
  - DataForSEO: the environment variables `DATAFORSEO_USERNAME`/`DATAFORSEO_PASSWORD` first, then `~/.claude.json` → `mcpServers.dataforseo.env` at user scope, then (*amended*) only the project-scope entry whose directory contains the current directory (deepest match first), so one client's account is never used for another. Read-only, never printed or logged. `~/.claude/settings.json` is never read for credentials.
  - Moz: the existing `backlinks_auth` loader.

### 5.2 Storage

All tables live in the `links` store (`seo_store.connect("links", ...)`; directories 0700, database 0600):

- `snapshots(id, project, target, source, collected_at, row_count, row_cap_hit, cost_usd, error)`
- `referring_domains(snapshot_id, domain, authority, authority_scale, spam_score, dofollow, attributes, first_seen, last_seen, sample_url, sample_anchor, sample_title, tld)`
- `prospects(project, domain, status, source, segment, type, matched_rule, score, effort, bucket, tactic, evidence_json, brief_json, brief_hash, draft_brief_hash, draft_subject, draft_body, reviewed_by, reviewed_at, contacted_at, followup_at, outcome_at, link_url, verified_at, verified_status, link_rel, cooldown_until, notes, created_at, updated_at)`, with UNIQUE(project, domain)
- `events(project, domain, at, from_status, to_status, actor, note)`: an audit trail
- `topics(project, terms_json, origin, derived_at)`: *(amended)* the topic terms derived from the client's sitemap, one row per project, reused by every later run (§5.3). It is a cache in the links store; the profile file is never written. Stores created before this amendment gain the table and the `draft_brief_hash` column when opened.

### 5.3 Flow

1. **Inputs.** The profile supplies the domain, 3–7 competitors, `markets.country` and the new optional `topics` list. *(amended)* Topic terms are resolved in this order:
   1. the profile's `topics`, origin `profile`;
   2. the terms stored for the project in the `topics` table, origin `sitemap`;
   3. otherwise the 10 most frequent slug tokens in the client's sitemap URLs (stopwords and brand terms removed; ties broken alphabetically), read **once** and stored, origin `sitemap`. `--refresh-topics` re-reads the sitemap and replaces the stored terms; if that read finds nothing, the stored terms are kept.
   
   Only `prospects` and `add` may read the sitemap. `gap` and `kpis` never do, and `--no-sitemap` still uses stored terms. This keeps scores reproducible from stored data: `prospects` and `add` rank identically even if a later crawl would fail. Derived terms are never written to the profile. When the origin is `sitemap`, the output warns that sitemap tokens are noisy and says how to set real topics, and `/seo links prospects` makes confirming the profile topics a step before the first run. The terms and their origin are reported.
2. **Fetch.** `fetch` makes one snapshot per target (the client plus each competitor) from one source.
3. **Gap.** `gap` reads the latest snapshot per target **from a single source**. A target without a snapshot from that source is a reported coverage gap, never filled from another source.
4. **Segment.** With n = the number of competitors that have data, each referring domain gets one segment:

| Segment | Rule |
|---|---|
| `gap` | Links to ≥ 2 competitors and not to the client |
| `single` | Links to exactly 1 competitor and not to the client |
| `shared` | Links to the client and to ≥ 1 competitor |
| `moat` | Links to the client only |

5. **Prospects.** `gap` and `single` domains are excluded, classified, scored and ranked. `shared` and `moat` are reported as relationships to keep.
6. **Gap first.** *(amended)* The score formula (§6.3) is unchanged, so a strong single-competitor site can outscore a weak gap site. The sites that link to two or more competitors and not to the client are the core answer, so `prospects` also returns `gap_prospects` (the gap segment alone, same relative order) and the skill presents it first. `add --segment gap|single|all` (default `all`) selects by segment and takes gap domains before single ones, each group in the unchanged ranking.

## 6. Exclusion, classification and scoring

### 6.1 Exclusions

*(amended)* These are applied in order, reported with a reason, and counted in `excluded_counts`. They are never prospects.

1. `own_property`: the client's own domain and subdomains.
2. `competitor_property`: the competitors' domains.
3. `social_ugc`: social, user-generated and portfolio platforms (a fixed list: LinkedIn, Facebook, X/Twitter, Instagram, YouTube, Pinterest, TikTok, Medium, Threads, Behance, Dribbble and similar). Reason: "create or complete a profile; no outreach". Behance and Dribbble were added after a Behance job post ranked as a prospect.
4. `staging_or_dev_host`: a staging, preview or dev site, which is never an editorial prospect:
   - a subdomain of a hosting platform: `*.wpengine.com`, `*.kinsta.cloud`, `*.netlify.app`, `*.vercel.app`, `*.herokuapp.com`, `*.pages.dev`, `*.hostingersite.com`;
   - a subdomain label that starts with `staging`, `stage`, `dev`, `test`, `uat` or `preview` and is not followed by a letter (`staging.x.com`, `dev2.x.com`; `devops.x.com` and `dev.to` are kept);
   - `stage` or `staging` as a hyphenated part of a label (`acme-staging.com`; `stage.com` and `backstage.io` are kept).
5. `spam`: a spam score of 60 or more, on DataForSEO's 0–100 scale or Moz's percentage.
6. `paid_or_scheme`: a `sponsored` attribute, or any of these as whole words in the sample URL, title or anchor, after reading every run of non-alphanumerics as one space: `sponsored`, `advertorial`, `guest post pricing`, `buy backlinks`, `link insertion`, `paid post`, `backlink(s)`, `seo links`, `buy links`, `dofollow` / `do follow`, `link building service(s)`, `guest post service(s)`. `write-for-us` is not a paid signal; §7.1 uses such pages as contact paths. For an SEO-industry client, real articles about backlinks can match; the excluded list always names the domain and the reason so that it can be reviewed.
7. `link_network`: a link farm's footprint. The same distinctive sample path (two or more segments after a language prefix, the last at least 10 characters) or the same sample title (at least 3 words and 20 characters, and not a CMS default such as "Just another WordPress site") on at least **5 distinct organizations in one competitor snapshot**. Organizations are counted by registrable label, so one company on several country domains is not a network. The excluded entry's `detail` names the footprint. On the live run one network covered more than 900 domains.

### 6.2 Classification

The first matching rule wins, and `matched_rule` is stored. Every type is INFERRED.

*(amended)* Rules 1–6 use two signals only: the **first path segment** of the sample URL (after a language prefix such as `/en/` or `/id/`), when it is a short slug of at most two words, and the words of the domain itself. A token deeper in the path, in a long article slug, or in the page title does not count, so a blog post that mentions "partner" or "agencies" stays a blog post. The one title exception is the ranking listicle `top N … companies|agencies` (`tools for agencies` is not one).

| # | Type | Rule |
|---|---|---|
| 1 | directory or review | A known listing or profile host (clutch.co, goodfirms.co, designrush.com, g2.com, capterra.com, sortlist.com, themanifest.com, upcity.com, trustpilot.com, crunchbase.com, indiamart.com, justdial.com, sulekha.com, tradeindia.com, cbinsights.com, golden.com, dealroom.co, wellfound.com, tracxn.com, owler.com, zaubacorp.com), unless the path starts with `/blog` or the host is `blog.`/`learn.`; or a first segment of `directory`, `listing(s)`, `companies`, `company`, `vendors`, `agencies`, `organization(s)`, `profile(s)`, `wiki`, `apps`, `startups`; or one of the directory words as a label of the domain; or a `top N … companies\|agencies` listicle in the path or the title |
| 2 | association, education or government | TLD `.edu`, `.ac.*`, `.gov`, `.gov.*`, or the tokens `association`, `society`, `council`, `chamber`, `institute` |
| 3 | community | reddit.com, quora.com, `*.stackexchange.com`, or the tokens `forum`, `community` |
| 4 | event or podcast | The tokens `podcast`, `episode`, `conference`, `summit`, `webinar`, `expo`, `awards`, `event` |
| 5 | resource page | A first segment with the token `resources`, `links`, `tools` or `recommended` (so `useful-links` matches and `useful-tips` does not) |
| 6 | partner or integration | A first segment with the token `partners`, `integrations`, `marketplace`, `customers`, `clients` |
| 7 | publication | Authority ≥ 60 plus an article-like URL (`/news/`, `/article/`, or a `/YYYY/MM/` path), or `news`, `magazine`, `journal` or `times` inside a domain label, or `media` as a whole label or hyphen part (`my-media.com`, not `antillesdigitalmedia.com`) |
| 8 | blog | A `blog.` or `learn.` subdomain or a `/blog/` path |
| 9 | unclassified | Anything else |

Tokens in rules 2–4 are matched in the first segment and the domain's words. The live run showed why the earlier "anywhere in the path or title" matching was wrong: 9 of 12 quick wins were blog posts typed as partner or directory pages, while company, wiki and apps profile pages were unclassified.

### 6.3 Prospect score (0–100)

```
score = round_half_up(30*O + 20*A + 20*T + 10*M + 10*Q + 10*V)
```

| Signal | Definition | Unknown value |
|---|---|---|
| O, competitor overlap | min(k, 3) / 3, where k is the number of competitors it links to | (never unknown) |
| A, authority | DataForSEO domain rank / 1000, or Moz DA / 100 | 0.5 |
| T, topic fit | min(m, 3) / 3, where m is the number of distinct topic terms found in the sample title, URL tokens and anchor. Matching is case-insensitive whole-phrase on text normalized to lowercase alphanumerics separated by single spaces, with naive plural folding (`videos` matches `video`) *(amended)*. | 0.5 when there is no text or no topic terms *(amended)* |
| M, market fit | Same-country ccTLD 1.0; generic TLD (com, org, net, io, co, ai) 0.5; any other ccTLD 0.2 | (never unknown) |
| Q, link quality | 1.0 dofollow; 0.0 nofollow or UGC | 0.5 |
| V, type value | Publication or association 1.0; resource or partner 0.8; event or podcast 0.7; directory or blog 0.6; unclassified 0.5; community 0.3 | |

- **Comparability.** Authority from different sources is not comparable, and a run uses one source (section 5.3), so scores are comparable within a run only.
- **Effort tag.** This is separate from the score and never enters it:
  - low: directory or review, partner or integration;
  - medium: resource page, event or podcast, association, community, unclassified;
  - high: publication, blog.
- **Plan buckets:** evaluated in this order, so each prospect lands in exactly one:
  1. high-value: score ≥ 70;
  2. quick win: effort low and score ≥ 50;
  3. backlog: everything else.
- **Ranking.** Sort by score descending, then k descending, then domain ascending. That makes the order deterministic. Gap-first presentation (§5.3 step 6) changes what is shown first, never a score.

## 7. Outreach

### 7.1 Brief

`link_outreach.py brief <project> <domain>` returns JSON containing:
- the prospect evidence: type, `matched_rule`, the competitors it links to, and the sample URL, anchor and title;
- the playbook tactic for the type;
- the client's best-matching asset: the page from the client's sitemap or `money_pages` whose path words overlap most with the words of the evidence (title, URL and anchor), or the homepage if none overlap *(amended: the code does not yet drop stopwords or use topic terms; see §14)*;
- the **allowed claims**: the profile name and topics, plus profile `notes` approved by the user. Nothing else may be claimed;
- the prospect's public contact path: a `/contact`, `/write-for-us` or `/about` URL, only if it is in the evidence. Personal email addresses are never scraped;
- `brief_hash`.

### 7.2 Draft and lint

Claude writes `subject` plus `body` (at most 150 words, one ask, personalized from the evidence). `save-draft` lints the draft deterministically and rejects it when:
- **Banned asks** *(amended)*: after normalization (Unicode compatibility forms, invisible characters removed, lowercase, every dash and underscore read as a space) it contains a whole-word form of any of these: `pay` (pays, paying, payment, payout), `paid`, `sponsor*`, `link exchange(s)` or `exchange links`, `swap links` or `link swap(s)`, `reciprocal*`, `guest post fee(s)`, `dofollow` / `do-follow` / `do follow`, `compensat*`. "PayPal", "payroll", "repay" and "unpaid" pass. The reported `term` is the canonical name (for example `pay`, `dofollow`);
- **Unbriefed URLs** *(amended)*: it contains a URL that is not in the brief, found case-insensitively with or without a scheme or `www.`, as a host with a path, or as a bare host with a common TLD, and compared by host and path (scheme, `www.`, case and a trailing slash are ignored). An unparseable URL counts as unbriefed. A name that looks like a domain (`ASP.NET`) is read as one;
- **Email addresses** *(amended)*: it contains one (plain or `mailto:`). Contact goes through the public contact page or the sender's own email tool;
- **Length:** the body is over 150 words or the subject is over 90 characters;
- **Hash mismatch:** the brief hash differs from the stored prospect's (a stale brief).

Lint failures return each offending span. Nothing is ever sent. `export` writes a CSV (domain, contact_path, subject, body, status) for the user's own email or CRM; cells that start with `=`, `+`, `-` or `@` get a leading apostrophe so that a spreadsheet shows them as text *(amended)*. The address column stays empty for the human to fill in.

### 7.3 Tracker state machine

```
new → drafted → approved → contacted → won | lost | no_reply
any → do_not_contact (permanent)      any non-terminal → skipped
contacted → drafted (the one follow-up)
drafted | approved → won | lost | no_reply   only when contacted_at is set (amended)
```

| Rule | Detail |
|---|---|
| Approve | `approve` requires `--reviewed-by NAME` and records `reviewed_at`. *(amended)* `save-draft` stores `draft_brief_hash`; `approve` refuses when it differs from the prospect's current `brief_hash`, so a draft cannot be approved unchecked against a replaced brief. |
| Contacted | `mark contacted` is allowed only from `approved` |
| Follow-up | One follow-up: a new draft and approval, allowed ≥ 7 days after `contacted_at` |
| Outcome during a follow-up *(amended)* | While a follow-up draft is pending (the row is `drafted` or `approved`), `won`, `lost` and `no_reply` can still be recorded, because a reply may arrive. This is allowed only after first contact, and it writes no follow-up "sent". |
| Won | `mark won` requires `--link-url` on the prospect's own domain, then runs verification |
| Verify | `verify` calls `verify_backlinks.py` on won links. *(amended)* It stores `verified_status` (`live`, `missing`, `unverifiable` or `unreachable`) and `link_rel` (dofollow, nofollow, sponsored or ugc). `unverifiable` means the page answered but the link cannot be confirmed over plain HTTP (JS-rendered, redirected, or existence-only); `unreachable` means an error. In every case the row stays `won` and is never moved to `lost`. The checker's `verify_single_backlink` has no `allow_local_targets` parameter, so the "data-derived URLs refuse operator-allowlisted local hosts" rule is not threaded through yet (§14). |
| Cooldown *(amended)* | `lost` and `no_reply` set `cooldown_until = +90 days`. So does moving to `skipped` or `do_not_contact` from a row that was contacted, so "skipped" cannot be used to dodge the cooldown or the one-follow-up rule. `add` refuses the domain until then. |
| Organization scope *(amended)* | Do-not-contact, active status and cooldown are checked by **registrable domain** (`seo_store.registrable_domain`, which understands `co.uk`-style suffixes and shared hosting such as `blogspot.com`). `blog.example.org` is held back by anything recorded for `example.org`, and the reverse. DataForSEO is queried with subdomains included, so sibling hosts are routine. |
| Suppression | `do_not_contact` is never re-added, for the whole organization |
| Skipped *(amended)* | A `skipped` prospect is not re-added by `add` unless `--include-skipped` is passed; a cooldown still applies |
| Audit | Every transition writes an `events` row. Illegal transitions are errors and change nothing. |

## 8. KPIs

New `seo_kpi` reserved metrics:

| Metric | Kind | Definition |
|---|---|---|
| `links.referring_domains` | count | The client's own count, from its latest snapshot |
| `links.gap_domains` | count | Domains in the gap segment, counted before exclusions (a gap domain later excluded as spam or a staging host still counts) *(amended)* |
| `links.prospects` | count | Active (non-terminal) prospects |
| `links.contacted` | count | Prospects with a `contacted_at` now. A re-add after a cooldown clears it, so the count can fall; `events` holds the history *(amended)* |
| `links.won` | count | Prospects marked won |
| `links.won_verified` | count | Won links verified live |
| `links.win_rate` | fraction | won / contacted; null below 5 contacted |

- **Source.** `link_gap.py kpis --emit-kpis` and `link_outreach.py kpis --emit-kpis` write envelopes whose `source` field names the data source, so that DataForSEO and Moz counts are never compared silently.
- **Tracking.** `performance_tracker` ingests these envelopes unchanged, and `/seo track` gains a Links row.

## 9. Cost control

- **Estimate first.** *(amended)* A `backlinks/backlinks/live` call is billed per request **and per row**: measured 19 rows $0.0247 and 1,000 rows $0.06. `fetch --source dataforseo` therefore prices each target at `dataforseo_costs.estimate_backlinks_call(limit)` = $0.02 + $0.00004 × rows ($0.06 at the 1,000-row default), not at the flat `COST_TABLE` price. `COST_TABLE` keeps $0.02 as the base for other callers.
  - `--dry-run` prints the per-call and total estimate and exits (3 targets at 1,000 rows: $0.18).
  - The pre-run refusal compares that total with `--max-cost` (default $1.00).
  - **The cap is hard.** During the run a call starts only if spent so far plus the larger of the per-call estimate and the highest real per-call cost seen so far fits under `--max-cost`. A cap equal to the dry-run estimate is therefore never exceeded; if real calls cost more than estimated, the run stops sooner. The first live run under the old flat model had estimated $0.06 and spent $0.1447, and `--max-cost 0.06` would have spent $0.0847.
- **Actual cost.** It is read from each response's `cost` field, written to the existing ledger, and stored on the snapshot. The snapshot is saved before the ledger is written, and a ledger failure is reported as a warning, so paid data is not lost.
- **Insufficient funds.** HTTP 402 or the DataForSEO status "insufficient funds" is fatal. The run stops, keeps the snapshots already saved, and reports the coverage. No retries.
- **Moz.** It keeps its existing 1 request per 10 s limiter. `fetch --source moz` warns that the free tier is 2,500 rows per month and defaults to 50 rows per target.

## 10. Changes to existing code

- **`backlinks_auth.py`.** DataForSEO detection reads `~/.claude.json` (user scope plus project scopes).
  - An entry found only in `~/.claude/settings.json` reports `"dataforseo": {"available": false, "stale_config": true}`, with the fix command, and never counts toward the tier.
  - The script also reports whether the REST credentials (environment, or the `~/.claude.json` entry) are present, since scripts need those, not the MCP server.
- **Migration on the user's machine (user-approved).**
  1. Back up `~/.claude.json` and `~/.claude/settings.json`.
  2. Copy `mcpServers.dataforseo` unchanged into `~/.claude.json` user scope.
  3. Remove the stale copy with `extensions/mcp_config_cleanup.py`.

  Secrets are never printed, and the DataForSEO tools load from the next session.
- **`seo_project.py`.** Add an optional `topics: []` field, validated as a list of strings and merged into defaults (backward-compatible).
- **`seo_store.py`.** *(amended)* Add `registrable_domain()` and `same_organization()` (§7.3), and share the two-part country-suffix list with `seo_project`.
- **`backlinks_auth.py`.** *(amended)* Every config read tolerates odd shapes (a string or list where an object is expected). Credentials come from the user-scope entry, then only from the project scope that contains the current directory; detection of "the MCP server is configured" still counts every project scope.
- **`seo_kpi.py`.** Add the `links.*` metrics.
- **Routing.** `skills/seo/SKILL.md` gets the hub routing and the jobs-to-be-done row. `skills/seo-competitors/SKILL.md` step 4 and `skills/seo-backlinks/SKILL.md` §6 (gap) route to `link_gap.py`. `seo-backlinks` "Link Building Opportunities" points to `/seo links prospects`.
- **Manifests and docs.**
  - The skill count goes from 39 to 40 in `plugin.json`, `marketplace.json`, `CLAUDE.md`, `AGENTS.md`, the README and `docs/ARCHITECTURE.md`.
  - `docs/COMMANDS.md`.
  - `consistency_check.py` command aliases.
  - CHANGELOG "Unreleased". The version bump to v3.2.0 waits for a release decision.

## 11. Error handling

| Situation | Behaviour |
|---|---|
| No credentials for the chosen source | Error naming `/seo links setup`. Never switch source silently. |
| DataForSEO insufficient funds, or `--max-cost` reached | Stop, keep the snapshots, report coverage ("3 of 5 targets") |
| A target's fetch fails (an API error, or a dropped connection or timeout) | A snapshot row with `error` is recorded as a fact and the run continues with the next target (exit code 1). The gap reports the coverage. *(amended: network errors used to abort the run)* |
| Capped results | `row_cap_hit: true` in the snapshot and the output |
| CSV with a missing `domain` column, an unreadable encoding or a malformed row | Rejected with exit 2, with the expected columns for that format. Unmapped columns are ignored *(amended)* |
| A profile with fewer than 2 competitors with data | `gap` still runs, but the `gap` segment needs at least 2 competitors with data. It warns and reports only the `single` segment. |
| An illegal tracker transition | An error. Nothing changes. |
| Verification cannot reach the site | `verified_status: unreachable`; the status stays `won` |
| Verification reaches the page but cannot confirm the link (JS-rendered, redirected) | `verified_status: unverifiable`; the status stays `won` *(amended)* |
| A profile file that belongs to another domain, an empty `--project`, an unparseable URL | An error message and exit 2, never a traceback *(amended)* |

## 12. Security and privacy

- **Credentials.** They are never printed, logged or written. *(amended)* `link_sources.redact()` removes the known secret values and credential-shaped text (`Basic …`, `Bearer …`, `password=…`) from every error message before it is stored in a snapshot or printed.
- **Network.** *(amended)* `link_sources.py` calls two fixed API hosts and takes no URL from input or fetched content, so it does not use `url_safety`. Verification of won links goes through the checker's `validate_url` SSRF guard. Threading `allow_local_targets=False` into `verify_single_backlink` (so that operator-allowlisted local hosts are refused for data-derived URLs) needs a change to that shared checker and is listed in §14.
- **Contact data.** Contact discovery is limited to public contact pages already in the evidence. No personal email harvesting.
- **Location.** Client data lives in `$CLAUDE_SEO_DATA_DIR`, outside the repo.

## 13. Testing

All tests run without the network:

- **Adapters.** DataForSEO against a sanitized recorded response; Moz against a recorded JSON-RPC response; CSV fixtures for Ahrefs, Semrush, Search Console and generic.
- **Storage and data.** Snapshot storage, latest-per-source selection and coverage gaps.
- **Rules.** Segmentation, exclusions and classification, all table-driven.
- **Scoring.** Golden values for the score, neutral priors, the deterministic ordering and the plan buckets.
- **Cost.** The row-aware estimate, a cap equal to the dry-run estimate never being exceeded (including replayed live costs and a run whose real costs beat the estimate), insufficient funds as fatal, a network error as a per-target error, and the actual cost logged.
- **Tracker.** Every `(from, to)` transition against a map written from the spec, cooldown, organization-wide suppression, `skipped`, the follow-up rule, outcomes while a follow-up is pending, and approval bound to the brief.
- **Drafts and verification.** Draft lint (each banned ask and its inflections, Unicode tricks, unbriefed URLs in every form, email addresses, length, stale hash, no false positives on "PayPal" or "payroll"); verification with a mocked `verify_backlinks` for every status mapping.
- **KPIs.** Envelopes validate and are ingested by `performance_tracker`.
- **Credentials and detection.** Resolution order (environment, then `~/.claude.json`; `settings.json` ignored); the `backlinks_auth` stale-config detection.
- **End to end.** One integration test runs CSV fixtures (client plus 3 competitors) through the real CLIs: gap, prospects, add, brief, draft lint, approve, contacted, won, KPIs and ingest. *(amended)* The verify step runs in-process with a fake checker, because the real one fetches the linking page.
- **Live-run regressions.** *(amended)* Table-driven tests use the real URLs from the 2026-10-18 run: the staging and portfolio hosts, a link farm's footprint, the 12 misclassified quick wins and the profile pages that were unclassified.
- **Repo gates.** Full suite, `consistency_check.py`, `portability_check.py`, manifest counts.
- **Live smoke.** DataForSEO on thezyra.studio against Galleri5 and Superside with `--max-cost 0.25` ran on 2026-10-18 and spent $0.1447. Moz once the user has saved a key.

## 14. Out of scope (possible follow-ups)

- **Broken-link replacement:** competitor links that point to dead pages.
- **Automated discovery of unlinked brand mentions.** v1 accepts a mentions CSV through `import --format generic`.
- **Link velocity / new-and-lost tracking** over time, beyond snapshot-to-snapshot diffs.
- **An Ahrefs MCP adapter.** CSV import covers Ahrefs exports.
- **Email sending of any kind.**
- **Follow-ups from the final review (amended):**
  - thread `allow_local_targets=False` through `verify_single_backlink` (a change to the shared checker);
  - record a sanitized live DataForSEO response as a test fixture on the next paid run;
  - default `prospects --csv`, `export` and the KPI files to a folder under `$CLAUDE_SEO_DATA_DIR`, so client data cannot land in a repository by accident;
  - make the brief's asset choice use topic terms and drop stopwords, as §7.1 describes;
  - rename the locals in `dataforseo_costs` that shadow `unit_cost`, and take the ledger lock once in `cmd_log`.
