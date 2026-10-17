# Design: SEO × AEO × GEO hub (v3.1.0)

Status: written 2026-10-17 from the user's brief ("audit our existing skill,
prepare an implementation plan, then implement and test"). The brief asked for
the work to proceed end to end, so this spec records decisions rather than
waiting on approval gates; every decision below is reversible in a follow-up.

## 1. Goal

Turn the plugin from a strong *audit* toolkit into a centralized hub that
covers the whole organic-growth loop — research → create/optimize → measure —
for classic search (SEO), answer engines (AEO) and generative engines (GEO),
optimized for organic traffic, AI-search visibility and **qualified leads**.

Non-goals: building a SaaS, auto-publishing content without human review,
any link-exchange or paid-link mechanism, scraping Google SERPs.

## 2. Audit of the existing plugin (v3.0.0)

Baseline: 32 skills, 20 agents, 56 scripts, **340 tests passing, 1 failing**
(`test_sync_flow.py::test_dry_run_produces_valid_json` — hits the live GitHub
API and fails on rate limit; pre-existing and network-dependent).

### 2.1 Coverage against the target capability list

| Capability | Before | Gap |
|---|---|---|
| Keyword research | Three disconnected entry points: `seo-google keywords` (Ads API, needs a developer token), `seo-dataforseo keywords` (paid), `seo-cluster` step 1 (ad-hoc WebSearch expansion) | No free discovery path, no shared intent/funnel classifier, no deterministic opportunity score, no lead-value weighting |
| Keyword ranking | `gsc_query.py` quick wins (position 4-10, point-in-time); `seo-maps` geo-grid (local, paid) | No time series, no movers, no visibility index, no cannibalization detection |
| Technical audits | Strong (seo-technical, audit, drift, preload, unlighthouse, schema hook) | Upstream security fixes not yet ported (see 2.3) |
| Content optimization | E-E-A-T review, `content_quality`, citability scorer, briefs, humanizer, claim verifier | No competitor term/heading/question coverage scoring; no decay/refresh detection |
| Competitor analysis | `seo-competitor-pages` (page generation), backlink gap | No keyword gap or content gap |
| Programmatic SEO | `seo-programmatic` (planning + quality gates) | Adequate |
| AI search visibility | `geo-*` readiness checks (citability, platform, crawlers, brand presence) | Readiness only — no measured outcome (prompt-panel share of voice over time) |
| Performance tracking | Point-in-time GSC/GA4; `seo-drift` (on-page regressions); `geo-compare` (regex over markdown) | No KPI history across SEO + AEO + leads |
| Lead generation | `seo-sxo` personas; `geo-prospect` (Zyra's own agency CRM) | Prioritization ignores funnel stage / conversion value; no conversion KPI tracked |

### 2.2 Defects and overlaps found

1. **AEO score has four competing definitions**: `seo-audit` (citability figure
   alone), `agents/seo-geo.md` (5-dimension weighted "GEO Health"),
   `geo-platform-optimizer` ("Combined GEO Score" = mean of 5 platforms),
   `geo-compare`/`geo-proposal`/`geo-prospect` ("GEO Score", produced by
   nothing — the geo-seo-claude composite was never ported). This breaks the
   prospect → proposal → monthly-report pipeline.
2. **`geo-compare` violates the scoring rubric**: it tells the model to
   "estimate approximate scores" from prose when numbers are missing
   (contradicts Rules 3-4) and parses "6 categories / 14 crawlers" from the
   deleted `geo-audit` skill.
3. **`agents/seo-geo.md` contradicts its own router skill** (pre-merge
   5-dimension weights; uncited "11% of domains" stat).
4. **Dead commands**: `/geo quick` and `/geo report-pdf` are referenced by
   `geo-prospect`, `geo-proposal`, `geo-compare` but were removed in v3.0.0.
5. **AI-crawler facts are wrong** in `geo-crawlers` / `geo-ai-visibility`
   (GPTBot described as powering ChatGPT search; ClaudeBot described as Claude
   search; `anthropic-ai` listed though undocumented; Claude-SearchBot and
   Claude-User missing) — these distort the AEO score.
6. Keyword research and "quick win" logic duplicated across skills with
   different thresholds and no shared code.

### 2.3 Upstream drift

Upstream `AgriciDaniel/claude-seo` shipped 11 releases (v2.2.1 → v2.4.2) since
our fork point. Neither upstream added keyword, rank, content-pipeline or
AI-visibility-tracking skills, so those gaps are ours to fill. Upstream did
ship fixes we lack: SSRF hardening (100.64/10, IPv4-mapped IPv6, proxy
checks), path traversal in `commoncrawl_graph.py`, unvalidated WHOIS referral
in `domain_history.py`, extension installers writing MCP config to a file
Claude Code ignores and leaking secrets via argv, CVE dependency floors,
schema-hook diagnostics, prompt-injection guidance in agents, Cloudflare
managed-robots detection (geo-seo-claude), plus new `seo-agentic`,
`metadata_template`, `sitemap_discovery`, `consistency_check`.

## 3. Research synthesis (what we borrowed, what we refused)

| Source | Borrowed (re-implemented, not copied, unless noted) | Refused |
|---|---|---|
| **outrank.so** (functional benchmark only) | Persistent product profile; keyword → calendar pipeline; cannibalization pre-check before scheduling; staged write → review pipeline; GSC-driven "Improvements" loop (≥500 impressions, position 4-25, CTR gap, decline); draft-first CMS output adapters with an Outrank-compatible webhook shape; fill its admitted gap — it does not monitor AI answers | Credit-based link exchange and paid-link marketplace (Google link-spam policy: "excessive link exchanges", "automated programs… to create links", paid links without `rel=sponsored`); auto-publishing unreviewed AI content (scaled-content-abuse policy; Google's gen-AI guidance requires human review) |
| **aaron-he-zhu/seo-geo-claude-skills** (Apache-2.0 — ideas only, credited) | Striking-distance-first keyword workflow; scenario buckets; GEO answer-format flags; content-decay scoring and refresh/rewrite/retire rule; AI-Overview recovery playbook; 4-way gap segmentation (moat / battleground / gap / pioneer); AI-referral analytics from GA4; holdout measurement protocol with Promote/Keep-testing/Rollback/Unproven verdicts; client memory with decision provenance | Blended SEO+GEO "total" (violates our never-blend rule); unsourced CTR-uplift figures |
| **AgriciDaniel/claude-seo upstream** (MIT — code ports) | Security/bug fixes in 2.3; `seo-agentic`; `metadata_template`; `sitemap_discovery`; `consistency_check` | Managed runtime launcher (L effort, touches ~180 call sites — follow-up) |
| **zubair-trabzada/geo-seo-claude** (MIT) | Composite AEO weights (citability 25, brand 20, content E-E-A-T 20, technical/crawler 15, schema 10, platform 10); Cloudflare managed robots.txt detection | — |
| **OSS survey** (advertools, SerpBear, mcp-gsc, geo-score, Elmo, Limelit, Princeton GEO, claude-blog) | GSC-snapshot rank history; striking-distance opp-clicks formula; 10%/10% cannibalization rule; 20/40/60% decay tiers with cause diagnosis; AI tracking stats (k ≥ 5 runs, Wilson CI, n < 20 "thin", branded prompts out of the headline, paired sign test + Holm); spend caps and dry-run | SERP/PAA scraping (robots.txt + Google ToS); Gemini grounding for tracking (ToS bans analyzing grounded results); AGPL autopilot code |

## 4. Architecture

```
                         skills/seo  (hub router — jobs-to-be-done map + data tiers)
                                 │
   RESEARCH            CREATE / OPTIMIZE            AEO / GEO                MEASURE
   seo-keywords        seo-content-engine (new)     seo-geo (router)         seo-track (new)
   seo-competitors     seo-refresh (new)            geo-share-of-voice (new) seo-drift
   seo-cluster         seo-content (+optimize)      geo-* (fixed)            geo-compare (fixed)
   seo-plan            seo-content-brief            seo-agentic (port)
                       seo-programmatic …
                                 │
 shared core:  seo_project.py (client profile) · seo_metrics.py (intent, CTR, scores, stats,
               cannibalization) · seo_store.py (SQLite history under $CLAUDE_SEO_DATA_DIR)
```

### 4.1 Shared core (done first; single source of truth)

- `seo_project.py` — one JSON profile per client (`<root>/projects/<slug>.json`,
  0600): domain, brand terms, 3-7 competitors, audiences, market, exact GSC
  property string, GA4 property, money pages, conversion events, voice
  samples, AI prompt panel (with treatment/control groups), notes with
  `approved_by: user|inferred` provenance.
- `seo_metrics.py` — intent/funnel/lead value; position bands (striking
  distance = 4-20); CTR curve (site-calibrated preferred, fallback labelled as
  pre-AI-Overview); opportunity score (renormalized weights, completeness);
  scenario buckets; GEO flags; Wilson CI; sign test; Holm; cannibalization.
- `seo_store.py` — storage root resolution and SQLite connections (0700).

### 4.2 New scripts (all: docstring, argparse CLI, `--json`, offline `--input` path for tests)

| Script | Purpose | Data sources (tiered) |
|---|---|---|
| `keyword_research.py` | `suggest` (autocomplete expansion), `gsc` (striking distance, CTR gap, cannibalization), `score` (merge any sources → intent, funnel, opportunity, bucket, GEO flags, lead priority, lexical groups) | Free: Google suggest (unofficial, rate-limited, cached); GSC. Paid: Keyword Planner, DataForSEO / Ahrefs / Semrush CSV import |
| `competitor_gap.py` | `keywords` (4-way segmentation + gap priority from ranking exports), `content` (sitemap topic inventory + page-type/format gaps) | Free: competitor sitemaps (SSRF-safe). Paid: DataForSEO ranked keywords import |
| `rank_tracker.py` | Tracked keywords, GSC daily snapshots, SERP imports, movers, bands, visibility index, cannibalization, URL swaps | GSC; DataForSEO SERP import; manual CSV |
| `ai_referrals.py` | GA4 sessions/key events from AI assistants vs organic; AI landing pages | GA4 |
| `performance_tracker.py` | KPI snapshots (SEO + AEO + leads) in SQLite, trend report, `--fail-on-drop`, export for geo-compare / PDF | GSC, GA4, rank store, KPI envelopes from other scripts, manual CRM leads |
| `content_decay.py` | Period comparison (YoY + previous), decay tiers, cause diagnosis, refresh/rewrite/consolidate/retire action, improvement candidates | GSC |
| `content_optimizer.py` | Page vs competitor pages: term/heading/question coverage, length percentile, placement → content score | Pages fetched SSRF-safe; competitor URLs from user/DataForSEO (never scraped from Google) |
| `content_export.py` | Draft markdown → HTML / Outrank-compatible webhook JSON (HMAC-signed) / WordPress **draft**; pre-publish gates | Local files; operator's own CMS |
| `ai_visibility.py` | Prompt panel × engines × k runs; raw answers stored; mention rate, SoV, citation rate/share, CI, thin flags; paired period compare; spend caps | Anthropic API (web search tool, optional SDK); JSONL ingest (DataForSEO ChatGPT scraper, manual capture) |
| `aeo_score.py` | The single AEO Readiness Score (weighted composite, N/A renormalized) + deterministic AI-crawler access sub-score with Cloudflare-managed-robots detection | Component scores from existing scorers |

### 4.3 Interface contracts between workstreams

**KPI envelope** — any script that produces trackable numbers accepts
`--emit-kpis <path>` and writes:

```json
{"kpi_envelope": 1, "project": "example.com", "date": "2026-10-17",
 "source": "ai_visibility.py", "metrics": {"ai.mention_rate": 0.32},
 "meta": {"n": 60, "engines": ["anthropic"]}}
```

`performance_tracker.py ingest <file>` stores envelopes. Canonical metric
names (others allowed, these are reserved):

| Prefix | Metrics |
|---|---|
| `gsc.` | clicks, impressions, ctr, position, clicks_nonbrand, impressions_nonbrand |
| `rank.` | tracked, top3, top10, striking, visibility |
| `ga4.` | organic_sessions, organic_key_events, organic_cvr, ai_sessions, ai_key_events, ai_cvr |
| `ai.` | mention_rate, mention_rate_ci_low, mention_rate_ci_high, citation_rate, sov, n |
| `aeo.` | score, citability, brand_authority, content_eeat, crawler_access, schema, platform |
| `seo.` | health |
| `leads.` | total, organic |

**Export** — `performance_tracker.py export <project> --json` →
`{"project", "generated_at", "snapshots": [{"date", "metrics": {name: {"value", "source"}}}]}`.
`geo-compare` computes deltas from two snapshots instead of regex-parsing
markdown.

**AEO score** — `aeo_score.py compute` takes component scores (each 0-100 or
null) and returns `{score, components, weights_used, completeness,
expression}`; the expression is the Rule-4 tool-computed sum. AEO is never
blended with SEO Health, and AI share of voice (an *outcome*) is never blended
into AEO readiness.

### 4.4 Safety rules baked into the new code

- All URL fetching goes through `fetch_page.fetch_page` / `url_safety` (SSRF
  + DNS-rebinding protection).
- No Google SERP / PAA scraping. Autocomplete uses the public suggest
  endpoint, flagged unofficial, 1 req/s, cached, fail-soft.
- Paid API calls (Anthropic) require explicit `--max-calls`, support
  `--dry-run`, and never run implicitly from a skill without the operator
  confirming the estimated call count.
- Export adapters default to **draft**; `publish` requires a `reviewed_by`
  front-matter field and no unresolved `[needs source]` markers. Network
  sends require `--confirm`. Webhook payloads are HMAC-SHA256 signed.
- Client data lives under the storage root with 0700/0600 permissions, never
  in the repo.

## 5. Consolidation decisions

1. **One AEO score** (`aeo_score.py`) consumed by `seo-audit`, `seo-geo`,
   `geo-compare`, `geo-proposal`, `geo-prospect`; `geo-platform-optimizer`'s
   figure is renamed "Platform Readiness" and becomes one component.
2. **One keyword entry point** (`seo-keywords`); `seo-google keywords` and
   `seo-dataforseo keywords` become data tiers it routes to; `seo-plan`,
   `seo-cluster`, `seo-content-brief` reuse its scoring.
3. **One measurement hub** (`seo-track`) for rankings + KPIs + AI referrals;
   `seo-drift` stays the on-page regression tool; `geo-compare` stays the
   client-facing monthly narrative but reads `seo-track` data.
4. **Content optimization** becomes a mode of `seo-content`, not a new skill.
5. `agents/seo-geo.md` aligned to the router; dead `/geo` commands rewired.

Net skill count: 32 → 39 (+6 new: seo-keywords, seo-competitors,
seo-content-engine, seo-refresh, seo-track, geo-share-of-voice; +1 ported:
seo-agentic). Agents: 20 → 21 (+seo-agentic).

## 6. Testing

- Every new script ships a `tests/test_<area>.py` with offline fixtures; no
  test touches the network or the operator's real cache (`tmp_path` +
  `--data-dir`).
- Existing suite must stay green except the pre-existing network-dependent
  `test_sync_flow` case.
- Manifest/portability/version tests updated for new counts and v3.1.0.

## 7. Known limitations (documented in README + CHANGELOG)

- GSC position is an impression-weighted average, not a SERP rank; ~46% of
  clicks come from anonymized queries; data lags 2-3 days.
- Free keyword research has no search volume; volume/difficulty need Keyword
  Planner (developer token) or a paid provider. Autocomplete is unofficial.
- True keyword gap needs third-party ranking data (DataForSEO etc.); the free
  path is a sitemap-based content-gap approximation.
- AI answers are non-deterministic and API answers differ from consumer apps;
  only Anthropic is called natively — ChatGPT/Perplexity/AI Overviews come in
  via DataForSEO or manual capture; Gemini grounding is excluded by its ToS.
- CTR curves are population averages; site calibration needs data.
- Managed runtime (`${CLAUDE_PLUGIN_ROOT}`-anchored launcher) is not yet
  ported; scripts are still invoked relative to the plugin root.
