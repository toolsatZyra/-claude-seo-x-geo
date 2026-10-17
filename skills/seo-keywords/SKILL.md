---
name: seo-keywords
description: >
  Keyword research entry point. Covers free discovery (Google autocomplete),
  Search Console opportunity mining (striking distance, CTR gaps,
  cannibalization) and deterministic scoring of keywords from any source
  (Keyword Planner, DataForSEO, Ahrefs, Semrush). Scoring yields search intent,
  funnel stage, opportunity score, scenario bucket and lead priority, with
  handoffs to clustering, briefs and the content calendar. Use when user says
  "keyword research", "find keywords", "keyword opportunities", "keyword
  ideas", "striking distance", "quick wins", "search intent", "keyword
  difficulty", "what should we rank for", or "prioritize keywords".
user-invocable: true
argument-hint: "[discover|gsc|score|plan] [seed, file or domain]"
license: MIT
metadata:
  author: ZYRA
  version: "3.1.0"
  category: seo
---

# Keyword Research

This skill is the plugin's one entry point for keyword research. It covers
discovery, scoring, bucketing and handoff. `seo-google keywords`,
`seo-dataforseo keywords` and Ahrefs/Semrush exports are **data tiers** that
feed it; they are not separate workflows. Every number is computed by a
script, so the same inputs always produce the same ranking.

**Scripts** live in the plugin root `scripts/`: `keyword_research.py` (this
skill) and `seo_metrics.py` (the shared maths). The formulas are in
`references/keyword-scoring.md`. The data tiers and their terms of service are
in `references/keyword-data-sources.md`.

## Quick Reference

| Command | What it does | Script |
|---|---|---|
| `/seo keywords plan <seed> [--project <domain>]` | Full workflow: Steps 0-5 below | all three |
| `/seo keywords discover <seed...>` | Autocomplete expansion (free, unofficial, no volume) | `keyword_research.py suggest` |
| `/seo keywords gsc [--project <domain>]` | Striking distance, CTR underperformers, cannibalization | `keyword_research.py gsc` |
| `/seo keywords score <file...>` | Merge any exports, then score, bucket and group them | `keyword_research.py score` |

Competitor keyword gaps are handled by `seo-competitors`, which runs
`competitor_gap.py keywords`.

## Step 0: Project and data tier

1. Load the client profile:
   `python3 scripts/seo_project.py show <domain> --json`.
   It supplies brand terms, competitors, market (`hl`/`gl`), the exact GSC
   property and money pages. If no profile exists, offer
   `seo_project.py init <domain> --brand <term> --competitor <domain> ...`.
   Every script below accepts `--project <domain>`, and an explicit flag
   always overrides the profile value.
2. Detect the tier:
   - Run `python3 scripts/google_auth.py --check`. Tier 1+ gives GSC; tier 3
     gives Keyword Planner.
   - Check whether the DataForSEO MCP is available.
   - Ask whether the client has Ahrefs or Semrush exports.
3. State the tier before any finding. Use the disclosure block in
   `references/keyword-data-sources.md`. If the data has no volume or
   difficulty, say so plainly, and show `completeness` next to every score.

## Step 1: Discovery

Run every source the tier allows and save each output as a file.

```bash
# Free: autocomplete. Unofficial, 1 req/s, cached 7 days, hard request cap.
python3 scripts/keyword_research.py suggest "crm software" "sales pipeline" \
    --project example.com --depth basic --max-requests 60 --output suggest.json
#   --depth full adds a-z and 0-9 suffixes (~57 queries per seed). Raise
#   --max-requests deliberately; never loop the command to get around the cap.

# Credentialed: Keyword Planner (volume; its "competition" is paid ads, not SEO difficulty)
python3 scripts/keyword_planner.py ideas "crm software" --json > kp.json

# Paid: run /seo dataforseo keywords|volume|difficulty|intent and save the raw JSON.
#   Gate the cost first: python3 scripts/dataforseo_costs.py check <endpoint> --count N
# Imports: Ahrefs / Semrush / SE Ranking CSV exports are used as-is.
```

**Never scrape google.com/search** (People Also Ask, related searches). Google
disallows it in robots.txt and in its terms. PAA comes only from the
DataForSEO SERP API.

## Step 2: GSC opportunity mining (striking distance first)

Keywords the site already ranks for are the cheapest wins. Mine them before
chasing new keywords.

```bash
python3 scripts/keyword_research.py gsc --project example.com --days 90 --json > gsc.json
# offline / client export: --input gsc_rows.json (gsc_query.py JSON, a row list, or CSV)
```

The script pulls query×page rows for the last 90 days with `dataState=final`,
ending 3 days before today. It recomputes CTR as clicks/impressions and
produces three lists:

- **striking**: position 4-20 and at least 50 impressions. Each row has
  `opp_clicks` (extra clicks if the query rose 5 places), `opp_clicks_monthly`,
  intent, funnel, `lead_priority` and GEO flags. Rows are sorted by lead
  priority.
- **ctr_underperformers**: position ≤ 10 with CTR below half of the expected
  CTR. The data cannot separate the causes, so list them as hypotheses:
  snippet, SERP feature or AI Overview, or intent mismatch.
- **cannibalization**: two or more pages that each take ≥ 10% of a query's
  clicks, where the query is also ≥ 10% of each page's clicks. Route these
  to consolidation before any new content is briefed for the query.

Always report `curve_source`. A site-calibrated curve needs at least 3 position
buckets of non-branded rows. Otherwise the output uses the pre-AI-Overview
Backlinko fallback curve, which overstates expected CTR.

Brand-navigational queries ("acme login") are excluded from the lists.
Queries that mention the brand with a commercial modifier ("acme vs hubspot")
stay in the lists and are flagged `brand: true`.

## Step 3: Merge and score

```bash
python3 scripts/keyword_research.py score --input suggest.json --input gsc.json \
    --input kp.json --input ahrefs.csv --project example.com \
    [--relevance relevance.csv] [--min-volume 50] --output scored.json
python3 scripts/keyword_research.py score ... --format csv --output scored.csv
```

**Inputs.** Columns are detected case-insensitively across Ahrefs, Semrush,
Keyword Planner (including UTF-16 TSV), DataForSEO envelopes and the
script's own `suggest`/`gsc` JSON.

**Merging.** Duplicate keywords are merged as follows:
- volume: the maximum
- difficulty: the maximum
- position: the best (lowest)
- sources: the union of all files

**Per-keyword fields:**
- `intent`, `funnel`, `lead_value`
- `opportunity_score` (0-100) with `completeness`
- `bucket`
- `traffic_potential`
- `lead_priority`, which uses GSC opportunity clicks when available and
  traffic potential otherwise
- `geo_flags`
- `route`
- a lexical `group_id` and `group_label`

**Relevance.** `--relevance` takes the operator's or client's business-fit
multipliers (0-1) as a `keyword,relevance` CSV. Mark these INFERRED unless
the client supplied them.

## Step 4: Bucket and prioritize for leads

| Bucket | Rule | Typical action |
|---|---|---|
| quick_win | striking distance, or KD < 30 with lead value ≥ 0.6 | Optimize the existing page, or ship a short new page |
| growth | KD 30-59, lead value ≥ 0.6 | Brief and build in the next content cycle |
| long_term | KD ≥ 60, lead value ≥ 0.6 | Needs links and authority; plan with `seo-backlinks` |
| awareness | TOFU (lead value < 0.6) | Publish for topical authority and AEO, not leads |

Order work by `lead_priority` inside each bucket. Funnel stage carries the
lead weighting (BOFU 1.0 / MOFU 0.6 / TOFU 0.25).

Keywords with GEO flags (question, definition, comparison, list, how_to)
need answer-first formatting: each major section opens with a direct,
self-contained answer. Do not recommend keyword stuffing or AI-specific
keyword rewriting; both are neutral or negative for AEO.

## Step 5: Handoffs

| Signal in the output | Hand to |
|---|---|
| Several keywords in one lexical group; deciding pages and architecture | `seo-cluster` (SERP-overlap clustering is authoritative; lexical groups are approximate) |
| A prioritized keyword ready to write | `seo-content-brief` |
| A scored set ready to schedule | `seo-content-engine` (calendar, with its cannibalization pre-check) |
| `route: seo-competitor-pages` (vs / alternatives / competitor terms) | `seo-competitor-pages` |
| "What do competitors rank for that we don't?" | `seo-competitors` |
| A repeating modifier pattern ("crm for {industry}", "{tool} integration") | `seo-programmatic` (template keyword sets with quality gates) |
| Cannibalized queries | `seo-content` / `seo-refresh` (consolidate before new work) |
| Rankings to track after shipping | `seo-track` |

## Output format

```markdown
## Keyword Research: <domain or seed> (<date>)
**Data tier:** <disclosure block from references/keyword-data-sources.md>
**CTR curve:** <curve_source>

### Top opportunities
| Keyword | Intent / Funnel | Score (completeness) | Bucket | Lead priority (basis) | Evidence | Tag |
|---|---|---|---|---|---|---|
| crm pricing | transactional / BOFU | 81.5 (1.00) | quick_win | 88.0 (gsc_opp_clicks) | GSC pos 8.1, 2,000 imp/90d | CONFIRMED |

### Striking distance · CTR underperformers · Cannibalization
(tables from `gsc` output, each with an Evidence column and a Rule-9 tag)

### Groups (lexical, approximate — confirm with seo-cluster)

### Recommendations
1. <action>
   - Observation: <the CONFIRMED evidence it rests on>
   - Dependency: <what must happen first / what it unblocks>
   - How we'd know it failed: <falsifiable check, e.g. "position not < 6 after 6 weeks">
   - Leading indicator: <e.g. GSC impressions for the query, weekly>
```

**Rule-9 tagging:**
- Script outputs (positions, impressions, scores, buckets) are **CONFIRMED**:
  they are tool-computed from the stated inputs.
- Causes of a CTR gap, predicted traffic, and "this keyword will convert"
  are **INFERRED**.
- When several causes are plausible, list them all as hypotheses.
- Totals or sums in prose must be computed with a tool call and shown as an
  expression (Rule 4).

## Rules

- Never attach a search volume to autocomplete-only keywords. Never call Ads
  `competition` "difficulty".
- Always show `completeness` beside a score. A 0.45-completeness score is not
  comparable with a 1.0-completeness score.
- Always disclose the GSC caveats:
  - position is an impression-weighted average
  - anonymized queries are missing from query rows
  - data lags 2-3 days
- Lexical groups are never a substitute for SERP-overlap clusters when
  deciding page architecture.
- Do not run `suggest` repeatedly to evade `--max-requests`, or after an HTTP
  429. Wait for the cache, or move to a paid tier.

## Error handling

| Situation | Response |
|---|---|
| No profile for `--project` | Exit 1 with the `seo_project.py init` command; offer to create the profile |
| GSC credentials missing or no access | `gsc` exits 1 with the error; run `client_preflight.py <domain>` and use the free tier or `--input` |
| `suggest` returns HTTP 429/403 | Run stops sending; cached and partial results kept; report it and retry later |
| `suggest` returns no suggestions at all | Exit 1; check network/locale, or fall back to Keyword Planner / DataForSEO ideas |
| Export with an unknown keyword column | Exit 1 naming the accepted headers; rename the column or convert the file |
| Ads competition column only | Note in `limitations`; difficulty left empty (opt in with `--difficulty-column` only with a stated reason) |
| DataForSEO cost check returns `blocked` | Stay on the free/credentialed tier and say so in the disclosure |

After delivering the report, offer: "Generate a PDF report? Use `/seo google report`".
