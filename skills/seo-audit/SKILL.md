---
name: seo-audit
description: "Full website SEO audit with parallel subagent delegation. Crawls up to 500 pages, detects business type, delegates to up to 15 specialists (8 always + 7 conditional), generates health score. Use when user says audit, full SEO check, analyze my site, or website health check."
user-invocable: true
argument-hint: "[url]"
license: MIT
metadata:
  author: AgriciDaniel
  version: "3.1.0"
  category: seo
---

# Full Website SEO Audit

## Process

1. **Render homepage**: use `python3 scripts/render_page.py <url> --mode auto --json` to capture raw HTML, rendered HTML, extracted text, SPA status, and accessibility data when needed
2. **Detect business type**: analyze homepage signals per seo orchestrator
3. **Crawl site**: follow internal links up to 500 pages, respect robots.txt
3a. **Snapshot evidence** (per `skills/seo/references/scoring-rubric.md`
    Rule 7): before any specialist scores anything, write every fetched
    page and every external check result (robots.txt, sitemap.xml, any
    API/search lookups a specialist will need) to
    `{domain}-audit/evidence-snapshot.json`, stamped with the collection
    date/time. Include outright failures (a CAPTCHA'd search, a 404, a
    timeout) as facts in the snapshot, not as gaps to silently retry
    later. This snapshot is the single source of truth for every
    specialist below — none of them re-fetch live data mid-scoring.
4. **Delegate to subagents** (if available, otherwise run inline sequentially) — each one scores exclusively from `{domain}-audit/evidence-snapshot.json`, per Rule 7:
   - `seo-technical` -- robots.txt, sitemaps, canonicals, Core Web Vitals, security headers
   - `seo-content` -- E-E-A-T, readability, thin content, AI citation readiness
   - `seo-schema` -- detection, validation, generation recommendations
   - `seo-images` -- alt text, file size, format, dimensions, lazy loading (always include — this is the sole source of the weighted "Images" category score; a prior version of this list omitted it, which meant Images had no data source in full audits)
   - `seo-sitemap` -- structure analysis, quality gates, missing pages
   - `seo-performance` -- LCP, INP, CLS measurements
   - `seo-visual` -- screenshots, mobile testing, above-fold analysis
   - `seo-geo` -- AEO findings (AI crawler access, citability, llms.txt, entity and platform notes) written to `findings/geo.md`; it does not produce its own AEO number (the AEO score is computed once, in `## AEO fan-out` below, by `scripts/aeo_score.py compute`)
   - `seo-local` -- GBP signals, NAP consistency, reviews, local schema, industry-specific local factors (spawn when Local Service industry detected: brick-and-mortar, SAB, or hybrid business type)
   - `seo-maps` -- Geo-grid rank tracking, GBP audit, review intelligence, competitor radius mapping (spawn when Local Service detected AND DataForSEO MCP available)
   - `seo-google` -- CWV field data (CrUX), URL indexation (GSC), organic traffic (GA4) (spawn when Google API credentials detected via `python3 scripts/google_auth.py --check`)
   - `seo-backlinks` -- Backlink profile data: DA/PA, referring domains, anchor text, toxic links (spawn when Moz or Bing API credentials detected via `python3 scripts/backlinks_auth.py --check`, or always include Common Crawl domain-level metrics)
   - `seo-cluster` -- Semantic clustering analysis (spawn when content strategy signals detected: blog, pillar pages, topic clusters)
   - `seo-sxo` -- Search experience analysis: page-type mismatch, user stories, persona scoring (always include in full audits)
   - `seo-drift` -- Drift analysis: compare against stored baseline (spawn when drift baseline exists for the URL via `python3 scripts/drift_history.py <url>`)
   - `seo-ecommerce` -- Product schema, marketplace intelligence (spawn when E-commerce industry detected)
5. **Score** -- aggregate into SEO Health Score (0-100). Each category
   subscore must already come from that specialist's own deterministic
   formula (see `skills/seo/references/scoring-rubric.md` and the
   `## Scoring Weights` table below) — this step is a plain weighted sum of
   those subscores, never a fresh judgment call
6. **Persist audit artifacts** -- write all outputs under `{domain}-audit/`
7. **Report** -- generate prioritized action plan and optional PDF/HTML report

## Crawl Configuration

```
Max pages: 500
Respect robots.txt: Yes
Follow redirects: Yes (max 3 hops)
Timeout per page: 30 seconds
Concurrent requests: 5
Delay between requests: 1 second
```

## Output Files

- `{domain}-audit/evidence-snapshot.json`: Every fetched page and external
  check result, collected once and timestamped (Rule 7) — the sole
  evidence source every specialist below scores from. Re-running the
  scoring pass against an unchanged snapshot must reproduce identical
  scores; a new audit takes a new, separately dated snapshot rather than
  silently refreshing this one.
- `{domain}-audit/FULL-AUDIT-REPORT.md`: Comprehensive findings
- `{domain}-audit/ACTION-PLAN.md`: Prioritized recommendations (Critical > High > Medium > Low)
- `{domain}-audit/audit-data.json`: Structured audit envelope for report generation
- `{domain}-audit/findings/*.md`: Per-category specialist findings (`technical.md`, `content.md`, `schema.md`, `performance.md`, `visual.md`, etc.)
- `{domain}-audit/screenshots/`: Desktop + mobile captures (if Playwright available)
- **PDF Report** (recommended): Generate a professional A4 PDF using `scripts/google_report.py --type full --data {domain}-audit/audit-data.json --domain <domain> --output-dir {domain}-audit/`. This produces a white-cover enterprise report with TOC, executive summary, charts (Lighthouse gauges, query bars, index donut), metric cards, threshold tables, prioritized recommendations with effort estimates, and implementation roadmap. Always offer PDF generation after completing an audit.

## Structured Audit Data Envelope

Write `{domain}-audit/audit-data.json` with this shape so `python3 scripts/google_report.py --type full --data {domain}-audit/audit-data.json --domain <domain> --output-dir {domain}-audit/` can generate a report even when Google API data is unavailable:

```json
{
  "summary": {
    "health_score": 0,
    "business_type": "detected type",
    "top_findings": [],
    "quick_wins": []
  },
  "categories": [
    {
      "name": "Technical SEO",
      "score": 0,
      "what_works": [],
      "findings": [
        {
          "title": "Finding title",
          "severity": "Critical|High|Medium|Low|Info",
          "description": "Evidence-backed detail",
          "recommendation": "Specific fix"
        }
      ]
    }
  ],
  "action_plan": {
    "phases": [
      {"name": "Phase 1: Critical Fixes", "timeframe": "Week 1", "items": []},
      {"name": "Phase 2: High-Impact Improvements", "timeframe": "Weeks 2-3", "items": []},
      {"name": "Phase 3: Content & Authority", "timeframe": "Month 2", "items": []},
      {"name": "Phase 4: Monitoring & Iteration", "timeframe": "Ongoing", "items": []}
    ]
  },
  "artifacts": {
    "findings_dir": "findings/",
    "screenshots_dir": "screenshots/"
  }
}
```

## Scoring Weights

This table must stay identical to the `## Scoring Methodology` table in
`skills/seo/SKILL.md` — it is one formula defined in two places, not two
independent ones.

| Category | Weight | Subscore source |
|----------|--------|------------------|
| Technical SEO | 25% | `seo-technical` (categories 1-9, excludes On-Page) |
| Content Quality | 25% | `seo-content` (Content Quality Score, excludes AEO Citability) |
| On-Page SEO | 22% | `seo-technical` (category 10 — see that skill's Scoring section) |
| Schema / Structured Data | 13% | `seo-schema` |
| Performance (CWV) | 10% | `seo-performance` agent |
| Images | 5% | `seo-images` |

```
SEO Health Score = round(sum(category_subscore_i * weight_i for each row above))
```

Round half up, once, at this final step — do not re-round or adjust an
individual category subscore during aggregation. Per Rule 4 in that file,
compute this weighted sum with an actual tool call (e.g.
`python3 -c "print(round(99*0.25+82*0.25+80*0.22+72*0.13+0*0.10+0*0.05))"`)
using the real category subscores, and show that expression — do not add
them in prose. See `skills/seo/references/scoring-rubric.md` for the full
criteria formula each subscore must already satisfy before it reaches this
step.

**AI Search Readiness / AEO is not in this table.** It was previously
blended in at 10% weight; as of the AEO fan-out (see below), it is scored
and reported as a fully separate 0-100 AEO figure and must never be folded
back into the SEO Health Score above.

## Report Structure

### Executive Summary
- Overall SEO Health Score (0-100)
- Business type detected
- Top 5 critical issues
- Top 5 quick wins

### Technical SEO
- Crawlability issues
- Indexability problems
- Security concerns
- Core Web Vitals status

### Content Quality
- E-E-A-T assessment
- Thin content pages
- Duplicate content issues
- Readability scores

### On-Page SEO
- Title tag issues
- Meta description problems
- Heading structure
- Internal linking gaps

### Schema & Structured Data
- Current implementation
- Validation errors
- Missing opportunities

### Performance
- LCP, INP, CLS scores
- Resource optimization needs
- Third-party script impact

### Images
- Missing alt text
- Oversized images
- Format recommendations

**AI Search Readiness / AEO is reported as its own section, not a
subsection of the SEO report above.** See `## AEO fan-out` below for what
runs and `### Final report structure (mandatory)` for the exact shape.

## AEO fan-out (distinct scored track)

A full `seo-audit` run additionally fans out to the AEO cluster as a
**separate, parallel scored track** — never blended into the SEO score
computed above. First compute each AEO component score, then combine them
with `scripts/aeo_score.py compute`, the single AEO score definition (see
`skills/seo-geo/SKILL.md`, "The AEO Readiness Score"):

1. `citability`: run `scripts/citability_scorer.py::analyze_page_citability(url)`
   and take `average_citability_score` (deterministic 0-100). Citability
   stays a component; it is no longer the whole AEO score.
2. `crawler_access`: run `python3 scripts/aeo_score.py crawlers <url> --json`
   during evidence collection and store its JSON (it records the HTTP status
   and quotes the deciding robots.txt line per agent) in the evidence
   snapshot; re-score a saved robots.txt with `--robots-file` rather than
   re-fetching (Rule 7). Answer-surface agents are scored, training crawlers
   reported but never scored, Cloudflare managed robots.txt flagged. Run
   `geo-crawlers` for the page-level checks (meta robots, X-Robots-Tag,
   rendering) that robots.txt cannot show.
3. `brand_authority`: if a brand name is available, run
   `scripts/brand_scanner.py::generate_brand_report(brand, domain)` and score
   the Brand Authority Score per `geo-brand-mentions`; otherwise leave it
   unmeasured.
4. `platform`: run `geo-platform-optimizer` for per-platform readiness
   (Google AIO, ChatGPT, Perplexity, Gemini, Bing Copilot) and take its
   Platform Readiness Score.
5. `content_eeat` and `schema`: reuse the `seo-content` and `seo-schema`
   subscores already computed for the SEO track (the same evidence feeds two
   separately reported scores; it is not re-scored).
6. Combine: `python3 scripts/aeo_score.py compute --citability N
   --crawler-access N [--brand-authority N] [--content-eeat N] [--schema N]
   [--platform N] --json`. Omit any component that was not measured; the
   script renormalizes and reports `completeness`. Never estimate one.
7. Audit llms.txt via `scripts/llmstxt_generator.py::validate_llmstxt(url)`,
   respecting the current `aeo.llmstxt_mode` (see `skills/seo-geo/SKILL.md`)
   — generate only if mode is `generate` and the user explicitly asks. It
   carries no weight in the AEO score.

AI share of voice (`geo-share-of-voice`) is an outcome metric that needs a
prompt panel and paid API calls; an audit does not run it implicitly. If the
client already tracks it, quote the latest `ai.*` figures beside the AEO
score, never inside it.

### Final report structure (mandatory)

The audit report must present:

```
## SEO Score: <0-100>
<existing SEO category breakdown, unchanged>

## AEO Score: <score from aeo_score.py compute>/100 (<rating>, completeness <0.xx>)
| Component | Score | Weight | Status |
|---|---|---|---|
| citability | NN | 25 | measured |
| brand_authority | NN or N/A | 20 | measured / not measured |
| content_eeat | NN or N/A | 20 | ... |
| crawler_access | NN or N/A | 15 | ... |
| schema | NN or N/A | 10 | ... |
| platform | NN or N/A | 10 | ... |
Computation: `python3 -c "print(<expression from aeo_score.py>)"` -> NN
- Per-platform notes: AIO / ChatGPT / Perplexity / Gemini / Bing Copilot
- AI-crawler access: answer surfaces (OAI-SearchBot, ChatGPT-User, Claude-SearchBot, Claude-User, PerplexityBot, Perplexity-User, Googlebot, Bingbot, Applebot); training crawlers (GPTBot, ClaudeBot, Google-Extended, Applebot-Extended, CCBot ...) listed separately, unscored; Cloudflare managed robots.txt flag
- Brand/AI-visibility findings (if brand name available)
- llms.txt status (forward-looking, low-confidence — see policy)
```

**These two scores are never averaged, weighted together, or presented as a
single number.** A page can score 95 SEO / 40 AEO or vice versa — that
divergence is the point of treating AEO as first-class.

## Priority Definitions

- **Critical**: Blocks indexing or causes penalties (fix immediately)
- **High**: Significantly impacts rankings (fix within 1 week)
- **Medium**: Optimization opportunity (fix within 1 month)
- **Low**: Nice to have (backlog)

## DataForSEO Integration (Optional)

If DataForSEO MCP tools are available, spawn the `seo-dataforseo` agent alongside existing subagents to enrich the audit with live data: real SERP positions, backlink profiles with spam scores, on-page analysis (Lighthouse), business listings, and AI visibility checks (ChatGPT scraper, LLM mentions).

## Google API Integration (Optional)

If Google API credentials are configured (`python3 scripts/google_auth.py --check`), spawn the `seo-google` agent to enrich the audit with real Google field data: CrUX Core Web Vitals (replaces lab-only estimates), GSC URL indexation status, search performance (clicks, impressions, CTR), and GA4 organic traffic trends. The Performance (CWV) category score benefits most from field data.

## Error Handling

| Scenario | Action |
|----------|--------|
| URL unreachable (DNS failure, connection refused) | Report the error clearly. Do not guess site content. Suggest the user verify the URL and try again. |
| robots.txt blocks crawling | Report which paths are blocked. Analyze only accessible pages and note the limitation in the report. |
| Rate limiting (429 responses) | Back off and reduce concurrent requests. Report partial results with a note on which sections could not be completed. |
| Timeout on large sites (500+ pages) | Cap the crawl at the timeout limit. Report findings for pages crawled and estimate total site scope. |
| Subagent hits its `maxTurns` budget on a large site | Findings are not lost: every audit subagent writes a partial `output_dir/findings/*.md` after its first analysis pass and overwrites it with the complete findings before finishing. Read whatever findings file exists and merge it into the report, noting it may be partial. |
