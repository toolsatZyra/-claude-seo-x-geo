# Competitor link gap and link earning: design

- **Date:** 2026-10-17
- **Status:** approved in brainstorming. Awaiting the user's spec review.
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
| `scripts/link_sources.py` | Fetch or import referring domains into normalized, dated snapshots | `url_safety`, `seo_store`, `dataforseo_costs`, `moz_api` |
| `scripts/link_store.py` | Shared `links` store schema plus snapshot read and write, used by all three scripts | `seo_store` |
| `scripts/link_gap.py` | Segment, exclude, classify and score prospects from snapshots (no network) | `seo_store`, `seo_project`, `seo_kpi` |
| `scripts/link_outreach.py` | Tracker, briefs, draft storage and lint, approvals, status, verification, export, KPIs | `seo_store`, `verify_backlinks`, `seo_kpi` |
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
| `/seo links prospects <domain>` | `link_gap.py prospects` |
| `/seo links draft <domain> --top N` | `link_outreach.py add` and `brief`, Claude writes the drafts, then `link_outreach.py save-draft` (which lints) |
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
  - Field names are checked against the API docs and confirmed by the recorded live-smoke response, which becomes a sanitized test fixture.
- **Moz:** `moz_api.get_linking_domains` gives the domain, Domain Authority and spam score, capped at 50 rows per call. It has no sample URL, anchor or title, so topic fit and link quality fall back to neutral and type classification uses the domain only.
- **CSV import:** formats `ahrefs`, `semrush`, `gsc` (Search Console "Top linking sites") and `generic`. Each has an explicit column map. Unknown columns are an error that lists the expected columns.
- **CSV source names.** CSV snapshots are stored with source `csv-<format>` (for example `csv-ahrefs`), so the single-source rule in §5.3 applies to them too.
- **Credentials:**
  - DataForSEO: the environment variables `DATAFORSEO_USERNAME`/`DATAFORSEO_PASSWORD` first, then `~/.claude.json` → `mcpServers.dataforseo.env`, read-only and never printed or logged. `~/.claude/settings.json` is never read for credentials.
  - Moz: the existing `backlinks_auth` loader.

### 5.2 Storage

All tables live in the `links` store (`seo_store.connect("links", ...)`; directories 0700, database 0600):

- `snapshots(id, project, target, source, collected_at, row_count, row_cap_hit, cost_usd, error)`
- `referring_domains(snapshot_id, domain, authority, authority_scale, spam_score, dofollow, attributes, first_seen, last_seen, sample_url, sample_anchor, sample_title, tld)`
- `prospects(project, domain, status, source, segment, type, matched_rule, score, effort, bucket, tactic, evidence_json, brief_json, brief_hash, draft_subject, draft_body, reviewed_by, reviewed_at, contacted_at, followup_at, outcome_at, link_url, verified_at, verified_status, link_rel, cooldown_until, notes, created_at, updated_at)`, with UNIQUE(project, domain)
- `events(project, domain, at, from_status, to_status, actor, note)`: an audit trail

### 5.3 Flow

1. **Inputs.** The profile supplies the domain, 3–7 competitors, `markets.country` and the new optional `topics` list. If `topics` is empty, the topic terms are the 10 most frequent slug tokens in the client's sitemap URLs (stopwords and brand terms removed; ties broken alphabetically). Both the terms and their origin are recorded.
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

## 6. Exclusion, classification and scoring

### 6.1 Exclusions

These are applied in order and reported with a reason. They are never prospects.

1. The client's own domain and subdomains, and the competitors' domains.
2. Social and user-generated platforms (a fixed list: LinkedIn, Facebook, X/Twitter, Instagram, YouTube, Pinterest, TikTok, Medium and similar). Reason: "create or complete a profile; no outreach".
3. Spam: a spam score of 60 or more, on DataForSEO's 0–100 scale or Moz's percentage.
4. Paid or link-scheme signals:
   - a `sponsored` attribute;
   - URL or title tokens: `sponsored`, `advertorial`, `guest-post-pricing`, `buy-backlinks`, `link-insertion`, `paid-post`. `write-for-us` is not a paid signal; §7.1 uses such pages as contact paths.

### 6.2 Classification

The first matching rule wins, and `matched_rule` is stored. Every type is INFERRED.

| # | Type | Rule |
|---|---|---|
| 1 | directory or review | A known list (clutch.co, goodfirms.co, designrush.com, g2.com, capterra.com, sortlist.com, themanifest.com, upcity.com, trustpilot.com, crunchbase.com, indiamart.com, justdial.com, sulekha.com, tradeindia.com), or the tokens `directory`, `listing`, `companies`, `vendors`, `agencies`, `top-*-companies` |
| 2 | association, education or government | TLD `.edu`, `.ac.*`, `.gov`, `.gov.*`, or the tokens `association`, `society`, `council`, `chamber`, `institute` |
| 3 | community | reddit.com, quora.com, `*.stackexchange.com`, or the tokens `forum`, `community` |
| 4 | event or podcast | The tokens `podcast`, `episode`, `conference`, `summit`, `webinar`, `expo`, `awards`, `event` |
| 5 | resource page | The URL tokens `resources`, `links`, `tools`, `useful-links`, `recommended` |
| 6 | partner or integration | The tokens `partners`, `integrations`, `marketplace`, `customers`, `clients` |
| 7 | publication | Authority ≥ 60 plus an article-like URL (`/news/`, `/article/`, or a `/YYYY/MM/` path), or the tokens `news`, `magazine`, `journal`, `times`, `media` in the domain |
| 8 | blog | A `blog.` subdomain or a `/blog/` path |
| 9 | unclassified | Anything else |

### 6.3 Prospect score (0–100)

```
score = round_half_up(30*O + 20*A + 20*T + 10*M + 10*Q + 10*V)
```

| Signal | Definition | Unknown value |
|---|---|---|
| O, competitor overlap | min(k, 3) / 3, where k is the number of competitors it links to | (never unknown) |
| A, authority | DataForSEO domain rank / 1000, or Moz DA / 100 | 0.5 |
| T, topic fit | min(m, 3) / 3, where m is the number of distinct topic terms found in the sample title, URL tokens and anchor. Matching is case-insensitive whole-phrase on text normalized to lowercase alphanumerics separated by single spaces. | 0.5 when there is no text |
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
- **Ranking.** Sort by score descending, then k descending, then domain ascending. That makes the order deterministic.

## 7. Outreach

### 7.1 Brief

`link_outreach.py brief <project> <domain>` returns JSON containing:
- the prospect evidence: type, `matched_rule`, the competitors it links to, and the sample URL, anchor and title;
- the playbook tactic for the type;
- the client's best-matching asset: the page from the client's sitemap or `money_pages` with the most topic-term overlap with the evidence, or the homepage if none overlap;
- the **allowed claims**: the profile name and topics, plus profile `notes` approved by the user. Nothing else may be claimed;
- the prospect's public contact path: a `/contact`, `/write-for-us` or `/about` URL, only if it is in the evidence. Personal email addresses are never scraped;
- `brief_hash`.

### 7.2 Draft and lint

Claude writes `subject` plus `body` (at most 150 words, one ask, personalized from the evidence). `save-draft` lints the draft deterministically and rejects it when:
- **Banned asks:** it contains any of these terms (case-insensitive, whole words): `pay`, `payment`, `paid`, `sponsor`, `sponsored`, `sponsorship`, `link exchange`, `swap links`, `reciprocal`, `guest post fee`, `dofollow`, `do-follow`;
- **Unbriefed URLs:** it contains any URL not present in the brief;
- **Length:** the body is over 150 words or the subject is over 90 characters;
- **Hash mismatch:** the brief hash differs from the stored prospect's (a stale brief).

Lint failures return each offending span. Nothing is ever sent. `export` writes a CSV (domain, contact_path, subject, body, status) for the user's own email or CRM. The address column stays empty for the human to fill in.

### 7.3 Tracker state machine

```
new → drafted → approved → contacted → won | lost | no_reply
any → do_not_contact (permanent)      any non-terminal → skipped
```

| Rule | Detail |
|---|---|
| Approve | `approve` requires `--reviewed-by NAME` and records `reviewed_at` |
| Contacted | `mark contacted` is allowed only from `approved` |
| Follow-up | One follow-up: a new draft and approval, allowed ≥ 7 days after `contacted_at` |
| Won | `mark won` requires `--link-url`, then runs verification |
| Verify | `verify` calls `verify_backlinks.py` (through `url_safety`, `allow_local_targets=False`) on won links. It stores `verified_status` (live, missing or unreachable) and `link_rel` (dofollow, nofollow, sponsored or ugc). An unreachable site stays `won`, marked unverified, and is never moved to `lost`. |
| Cooldown | `lost` and `no_reply` set `cooldown_until = +90 days`, and `add` refuses the domain until then |
| Suppression | `do_not_contact` is never re-added |
| Audit | Every transition writes an `events` row. Illegal transitions are errors and change nothing. |

## 8. KPIs

New `seo_kpi` reserved metrics:

| Metric | Kind | Definition |
|---|---|---|
| `links.referring_domains` | count | The client's own count, from its latest snapshot |
| `links.gap_domains` | count | Domains in the gap segment |
| `links.prospects` | count | Active (non-terminal) prospects |
| `links.contacted` | count | Prospects marked contacted |
| `links.won` | count | Prospects marked won |
| `links.won_verified` | count | Won links verified live |
| `links.win_rate` | fraction | won / contacted; null below 5 contacted |

- **Source.** `link_gap.py kpis --emit` and `link_outreach.py kpis --emit` write envelopes whose `source` field names the data source, so that DataForSEO and Moz counts are never compared silently.
- **Tracking.** `performance_tracker` ingests these envelopes unchanged, and `/seo track` gains a Links row.

## 9. Cost control

- **Estimate first.** `fetch --source dataforseo` estimates the cost with `dataforseo_costs.py` (`backlinks_backlinks` = $0.02 per call) before any call.
  - The hard cap is `--max-cost` (default $1.00).
  - `--dry-run` prints the estimate and exits.
- **Actual cost.** It is read from each response's `cost` field, written to the existing ledger, and stored on the snapshot.
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
| A target's fetch fails | A snapshot row with `error` is recorded as a fact. The gap reports the coverage. |
| Capped results | `row_cap_hit: true` in the snapshot and the output |
| CSV with unknown or missing columns | Rejected, with the expected columns for that format |
| A profile with fewer than 2 competitors with data | `gap` still runs, but the `gap` segment needs at least 2 competitors with data. It warns and reports only the `single` segment. |
| An illegal tracker transition | An error. Nothing changes. |
| Verification cannot reach the site | `verified_status: unreachable`; the status stays `won` |

## 12. Security and privacy

- **Credentials.** They are never printed, logged or written. Outputs redact anything credential-shaped.
- **Network.** Every fetch goes through `url_safety`. URLs that came from data use `allow_local_targets=False`.
- **Contact data.** Contact discovery is limited to public contact pages already in the evidence. No personal email harvesting.
- **Location.** Client data lives in `$CLAUDE_SEO_DATA_DIR`, outside the repo.

## 13. Testing

All tests run without the network:

- **Adapters.** DataForSEO against a sanitized recorded response; Moz against a recorded JSON-RPC response; CSV fixtures for Ahrefs, Semrush, Search Console and generic.
- **Storage and data.** Snapshot storage, latest-per-source selection and coverage gaps.
- **Rules.** Segmentation, exclusions and classification, all table-driven.
- **Scoring.** Golden values for the score, neutral priors, the deterministic ordering and the plan buckets.
- **Cost.** The estimate, the cap stop, insufficient funds as fatal, and the actual cost logged.
- **Tracker.** Every legal and illegal transition, cooldown, suppression and the follow-up rule.
- **Drafts and verification.** Draft lint (each banned ask, unbriefed URLs, length, stale hash); verification with a mocked `verify_backlinks`.
- **KPIs.** Envelopes validate and are ingested by `performance_tracker`.
- **Credentials and detection.** Resolution order (environment, then `~/.claude.json`; `settings.json` ignored); the `backlinks_auth` stale-config detection.
- **End to end.** One integration test runs CSV fixtures (client plus 3 competitors) through gap, prospects, add, brief, draft lint, approve, contacted, won, verify (mocked), KPIs and ingest.
- **Repo gates.** Full suite, `consistency_check.py`, `portability_check.py`, manifest counts.
- **Live smoke (after the user approves the spend).** DataForSEO on thezyra.studio against Galleri5 and Superside with `--max-cost 0.25`. Moz once the user has saved a key.

## 14. Out of scope (possible follow-ups)

- **Broken-link replacement:** competitor links that point to dead pages.
- **Automated discovery of unlinked brand mentions.** v1 accepts a mentions CSV through `import --format generic`.
- **Link velocity / new-and-lost tracking** over time, beyond snapshot-to-snapshot diffs.
- **An Ahrefs MCP adapter.** CSV import covers Ahrefs exports.
- **Email sending of any kind.**
