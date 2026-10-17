---
name: seo-track
description: >
  Measurement hub for SEO, AEO and leads. Keyword rank tracking from Search
  Console history and SERP-tool imports (movers, position bands, visibility
  index, cannibalization, URL swaps, holdout tests with control groups), dated
  KPI snapshots across GSC, GA4, rankings, AI visibility and CRM leads,
  AI-assistant referral traffic from GA4, and client trend reports with a
  regression gate. Use when user says "rank tracking", "track rankings",
  "keyword positions", "performance report", "KPI", "monthly report",
  "traffic trends", "AI referrals", "ChatGPT traffic", "did rankings move",
  or "holdout test".
user-invocable: true
argument-hint: "setup|rank|snapshot|report|ai-referrals|experiment|export <domain> [args]"
license: MIT
metadata:
  author: ZYRA
  version: "3.1.0"
  category: seo
---

# SEO Track: the measurement hub

Audits say what to change; this skill says whether the change worked. It keeps
a local, per-project history so that "did it move?" is answered from stored
numbers, not from memory or a fresh guess:

- **Rankings**: tracked keywords, daily GSC observations and SERP imports
  (`scripts/rank_tracker.py`).
- **KPIs**: one dated snapshot per run across GSC, GA4, rankings, AI
  visibility, AEO readiness and leads (`scripts/performance_tracker.py`).
- **AI referrals**: sessions and key events from ChatGPT, Perplexity, Gemini,
  Copilot, Claude and others vs organic search (`scripts/ai_referrals.py`).

It does not detect on-page regressions (that is `seo-drift`), does not query
AI assistants (that is `geo-share-of-voice`, which writes `ai.*` KPIs here),
and does not write the client narrative (that is `geo-compare`, which reads
this skill's `export`).

## Commands

| Command | What it runs |
|---|---|
| `/seo track setup <domain>` | Profile check + tracked keywords with tags (section 1) |
| `/seo rank add <domain> <kw...>` | `rank_tracker.py add --project <domain> ...` |
| `/seo rank ingest <domain>` | `rank_tracker.py ingest-gsc --project <domain>` |
| `/seo rank import <domain> <file>` | `rank_tracker.py import --project <domain> <file> --source ...` |
| `/seo rank report <domain>` | `rank_tracker.py report --project <domain>` |
| `/seo rank history <domain> <kw>` | `rank_tracker.py history --project <domain> "<kw>"` |
| `/seo track experiment <domain>` | `rank_tracker.py experiment ...` (holdout verdict) |
| `/seo track snapshot <domain>` | `performance_tracker.py snapshot --project <domain>` |
| `/seo track report <domain>` | `performance_tracker.py report --project <domain> --compare 28d` |
| `/seo track ai-referrals <domain>` | `ai_referrals.py --project <domain>` |
| `/seo track export <domain>` | `performance_tracker.py export --project <domain> --json` |

Every script takes `--json` and `--data-dir`, prints `data_sources` and
`limitations` in JSON mode, and never prints credentials.

## Prerequisites and data tiers

| Tier | Needs | Unlocks |
|---|---|---|
| None | nothing | `record` (manual KPIs such as CRM leads), `ingest` of envelopes, SERP CSV imports, all reports on stored data |
| GSC | OAuth or service account with Search Console access | `ingest-gsc`, GSC totals in `snapshot`, rank reports |
| GA4 | + GA4 property access | AI referrals, organic sessions and key events in `snapshot` |
| Paid SERP data | DataForSEO / Ahrefs / Semrush export | `import` of true SERP ranks (kept separate by `source`) |

Check credentials first: `python3 scripts/google_auth.py --check --json`. If
Google access is missing for a client, run `python3 scripts/client_preflight.py
<domain> --request-email` and send the access request; do not substitute
estimates for missing data.

Storage: SQLite under `$CLAUDE_SEO_DATA_DIR` (default `~/.cache/claude-seo`),
stores `rankings` and `kpi`, directories created 0700. Every row is keyed by
`project` (the domain). Client data never goes in the repository.

## 1. Setup

1. **Project profile** (shared by every skill):
   ```bash
   python3 scripts/seo_project.py init example.com --name "Example" --brand example \
       --gsc-property sc-domain:example.com --ga4-property 123456789
   python3 scripts/seo_project.py set example.com conversion_events '["generate_lead"]'
   ```
   Brand terms drive the non-brand GSC totals and keep branded queries out of
   cannibalization. Conversion events are broken out per event in AI referrals.
2. **Tracked keywords** with tags. Use a CSV (`keyword,tags,target_url`, tags
   separated by `;`) or arguments:
   ```bash
   python3 scripts/rank_tracker.py add --project example.com --file keywords.csv
   python3 scripts/rank_tracker.py add --project example.com "crm pricing" --tag bofu \
       --target-url /pricing
   ```
   Tag conventions: funnel (`tofu`/`mofu`/`bofu`), page group (`money`,
   `blog`), and experiments as `treatment:<name>` / `control:<name>`. Assign
   experiment tags **before** the change ships and never re-tag after seeing
   results. Good sources of keywords: `seo-keywords` striking-distance output
   and the profile's money pages.
3. **Baseline**: `ingest-gsc --days 90` once, then the first `snapshot`.

## 2. Rank tracking

```bash
python3 scripts/rank_tracker.py ingest-gsc --project example.com --days 30
python3 scripts/rank_tracker.py report --project example.com --window 7 --lag 3 --json
python3 scripts/rank_tracker.py import --project example.com serp.csv --source dataforseo
python3 scripts/rank_tracker.py report --project example.com --source dataforseo
```

`ingest-gsc` stores `date x query x page` rows for tracked keywords only (a
server-side regex filter, so the row cap cannot cut them off); `--all-queries`
stores everything. Re-running is idempotent.

What the report computes (all deterministic):

| Section | Rule |
|---|---|
| Windows | current = `window` days ending `lag` days before `--as-of` (GSC lag); previous = the `window` days before it |
| Position | GSC: impression-weighted average; SERP imports: median of daily ranks, not-found days count as worst |
| Delta | previous - current (positive = improved); under 0.5 counts as unchanged |
| Movers | abs(delta) >= 3 **and** >= `--min-impressions` (default 10) in both windows |
| Bands | top3 (<=3), page1 (>3-10), striking (>10-20), deep (>20-50), far, unranked; `rank.striking` counts positions 4-20 |
| Visibility index | 100 x mean of expected CTR(position) / expected CTR(1); unranked = 0 |
| Cannibalization | `seo_metrics.detect_cannibalization` (two+ pages each >= 10% of a non-brand query's clicks) |
| URL swaps / target mismatch | top page changed between windows / differs from `target_url` |
| Per-tag stats | median delta, improved/declined counts, sign-test p |

How to read it. A movement is CONFIRMED (tool output). Its cause is INFERRED:
list the plausible explanations rather than picking one (a Google update via
`python3 scripts/seo_updates.py --since <yyyy-mm>`, a SERP feature change, a competitor, an
on-page change visible in `seo-drift history`, a URL swap shown in the same
report). Always state that GSC position is an average, not a rank on a SERP,
and that rare queries are anonymized, so a tracked low-volume keyword can show
no data while ranking.

## 3. KPI snapshots

```bash
python3 scripts/performance_tracker.py snapshot --project example.com --days 28
python3 scripts/performance_tracker.py ingest kpis-ai.json kpis-aeo.json
python3 scripts/performance_tracker.py record --project example.com --metric leads.total --value 42
```

`snapshot` records GSC site totals (dimensionless query, so anonymized clicks
are included) and non-brand totals, GA4 organic and AI-assistant sessions and
key events, and `rank.*` from the rank store, as one dated row set. A failing
source is listed under `errors` and the others are still stored.

Other skills hand numbers over as **KPI envelopes** (`--emit-kpis <path>`):

```json
{"kpi_envelope": 1, "project": "example.com", "date": "2026-10-17",
 "source": "ai_visibility.py", "metrics": {"ai.mention_rate": 0.32}, "meta": {"n": 60}}
```

`ingest` rejects a wrong version, a missing project or date, non-numeric
values and out-of-range reserved metrics (rates are 0-1 fractions); `null`
values are skipped, never stored as 0. Producers can call
`performance_tracker.write_envelope()`. Every reserved metric, its source,
caveats and whether it is a leading or lagging indicator:
[kpi-definitions.md](references/kpi-definitions.md).

## 4. AI referrals

```bash
python3 scripts/ai_referrals.py --project example.com --days 28 --emit-kpis kpis-ga4.json
python3 scripts/ai_referrals.py --project example.com --input ga4_export.csv --json
python3 scripts/ai_referrals.py --print-regex
```

Sessions are classified by `sessionSource` against a versioned host table
(ChatGPT, Perplexity, Gemini, Microsoft Copilot, Claude, You.com, Phind, Meta
AI, DeepSeek, Grok, Mistral). This is a heuristic floor: many assistants and
apps strip the referrer, so part of AI traffic arrives as Direct. Say so in
every client-facing number. `--print-regex` gives the same table as a GA4
custom-channel-group regex so the client's own GA4 UI matches the report.
Sources that look AI-related but are not in the table are listed for review,
never counted automatically.

## 5. Reports for clients

```bash
python3 scripts/performance_tracker.py report --project example.com --compare 28d
python3 scripts/performance_tracker.py report --project example.com --compare 90d --metrics gsc,ga4,ai,aeo,leads
```

The report compares each metric's latest value with a comparison snapshot
(`previous`, `Nd`, or a date), direction-aware (positions improve when they
fall; `rank.tracked` and `ai.n` are neutral). Structure the client write-up as:

1. Headline table: clicks (total and non-brand), organic sessions, AI-assistant
   sessions, key events / leads, AI mention rate, AEO score - each with the
   comparison and the source script.
2. Rankings: visibility index, band shifts, top movers, URL swaps, cannibalization.
3. AI visibility: `ai.*` from `geo-share-of-voice` and AI referrals; keep the AEO
   readiness score separate from AI share of voice (readiness is not outcome).
4. What we changed and what we will watch: every recommendation carries the
   observation it rests on, its dependency, "how we would know it failed", and a
   leading indicator (see the protocol below).

Tag every finding CONFIRMED or INFERRED (scoring-rubric Rule 9). Do not round
heuristic counts into precise claims ("AI traffic grew 40%" on 12 sessions is
noise; say the counts).

Then offer: "Generate a PDF report? Use `/seo google report`" -
`scripts/google_report.py` renders GSC data (`--type gsc-performance` or
`--type full`); KPI trend tables come from `performance_tracker.py export`.
For the monthly client narrative, hand the export to `geo-compare`.

## 6. Cadence

| When | Run |
|---|---|
| Weekly | `rank_tracker.py ingest-gsc --days 10`, `performance_tracker.py snapshot`, `performance_tracker.py report --fail-on-drop 20 --watch gsc.clicks_nonbrand,ga4.organic_key_events` |
| Monthly | `ai_referrals.py --emit-kpis` + `ingest`, `record` leads, `report --compare 28d`, `geo-compare` narrative |
| Quarterly | `report --compare 90d`; prune and re-tag the tracked list (new tags only for new experiments) |

The plugin does not schedule anything. Use the operator's own scheduler (cron,
launchd, CI). `--fail-on-drop` exits with code 3 when a watched metric worsens
by more than the given percent, so a scheduled job can alert:

```bash
python3 scripts/performance_tracker.py report --project example.com \
    --fail-on-drop 20 --watch gsc.clicks_nonbrand || echo "KPI gate failed"
```

Weekly snapshots of 28-day totals overlap; compare `--compare 28d` (or wider)
for non-overlapping windows, and keep `--days` the same across snapshots.

## 7. Holdout tests (did the change work?)

```bash
python3 scripts/rank_tracker.py experiment --project example.com \
    --treatment treatment:faq --control control:faq --start 2026-09-01 --horizon 28
```

Equal-length pre and post windows around the ship date; each treatment
keyword's change is adjusted by the control group's median change, then a sign
test decides. Verdicts: **Promote**, **Keep-testing** (horizon not reached,
no decision on interim data), **Rollback**, **Unproven**. The full protocol -
the four latency layers, horizon choice, decision rules and the falsifiability
requirement - is in [measurement-protocol.md](references/measurement-protocol.md).
Load it before designing or judging any test.

## Relationship to other skills

| Skill | Role |
|---|---|
| `seo-drift` | On-page regressions (title, canonical, schema). Use its history to explain a rank drop; this skill shows the drop. |
| `geo-share-of-voice` | Runs the AI prompt panel and writes `ai.*` envelopes that `ingest` stores. |
| `geo-compare` | Client-facing monthly AEO narrative; reads `performance_tracker.py export`. |
| `aeo_score.py` (via `seo-geo`) | Writes `aeo.*` readiness envelopes; never blended with `ai.*` outcomes. |
| `seo-google` | Point-in-time GSC/GA4/CrUX pulls; this skill keeps the history. |
| `seo-keywords` | Supplies striking-distance keywords to track. |

## Error handling

| Scenario | Action |
|---|---|
| No profile / no property | Scripts exit 1 with the missing field; run `seo_project.py init` or pass `--property`. |
| GSC or GA4 permission error | Report the error verbatim; suggest `client_preflight.py`; snapshot keeps other sources. |
| Tracked keyword has no GSC data | Listed under `tracked_without_data`; likely anonymized or not ranking - say both. |
| Envelope rejected | Show the `errors` list; fix the producer, never hand-edit values into the store. |
| GA4 rejects `keyEvents:<event>` | Script falls back to total key events and adds a limitation. |
| `--fail-on-drop` exit 3 | Report which watched metric worsened and by how much; investigate before reporting a cause. |

## References

- [measurement-protocol.md](references/measurement-protocol.md) - latency layers, holdouts, verdict rules, falsifiability
- [kpi-definitions.md](references/kpi-definitions.md) - every reserved metric with source, caveats, leading/lagging
