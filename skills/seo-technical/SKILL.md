---
name: seo-technical
description: >
  Technical SEO audit across 9 categories: crawlability, indexability, security,
  URL structure, mobile, Core Web Vitals, structured data, JavaScript rendering,
  and IndexNow protocol. Use when user says "technical SEO", "crawl issues",
  "robots.txt", "Core Web Vitals", "site speed", or "security headers".
user-invocable: true
argument-hint: "[url]"
license: MIT
metadata:
  author: AgriciDaniel
  version: "3.0.0"
  category: seo
---

# Technical SEO Audit

## Categories

### 1. Crawlability
- robots.txt: exists, valid, not blocking important resources
- XML sitemap: exists, referenced in robots.txt, valid format
- Noindex tags: intentional vs accidental
- Crawl depth: important pages within 3 clicks of homepage
- JavaScript rendering: check if critical content requires JS execution
- Crawl budget: for large sites (>10k pages), efficiency matters

#### AI Crawler Management

As of 2025-2026, AI companies actively crawl the web to train models and power AI search. Managing these crawlers via robots.txt is a critical technical SEO consideration.

**Known AI crawlers:**

| Crawler | Company | robots.txt token | Purpose |
|---------|---------|-----------------|---------|
| GPTBot | OpenAI | `GPTBot` | Model training |
| ChatGPT-User | OpenAI | `ChatGPT-User` | Real-time browsing |
| ClaudeBot | Anthropic | `ClaudeBot` | Model training |
| PerplexityBot | Perplexity | `PerplexityBot` | Search index + training |
| Bytespider | ByteDance | `Bytespider` | Model training |
| Google-Extended | Google | `Google-Extended` | Gemini training (NOT search) |
| CCBot | Common Crawl | `CCBot` | Open dataset |
| Bingbot / Copilot | Microsoft | `Bingbot` | Classic Bing indexing + Bing Copilot answer sourcing (same UA handles both) |

**Key distinctions:**
- Blocking `Google-Extended` prevents Gemini training use but does NOT affect Google Search indexing or AI Overviews (those use `Googlebot`)
- Blocking `GPTBot` prevents OpenAI training but does NOT prevent ChatGPT from citing your content via browsing (`ChatGPT-User`)
- Blocking any of these does not affect classic Google/Bing search rankings — it only controls whether that specific AI system's answer engine or model training can access the page
- ~3-5% of websites now use AI-specific robots.txt rules

**Example, selective AI crawler blocking:**
```
# Allow search indexing, block AI training crawlers
User-agent: GPTBot
Disallow: /

User-agent: Google-Extended
Disallow: /

User-agent: Bytespider
Disallow: /

# Allow all other crawlers (including Googlebot for search)
User-agent: *
Allow: /
```

**Recommendation:** Consider your AI visibility strategy before blocking. Being cited by AI systems drives brand awareness and referral traffic. Recommend allowing these crawlers unless the client has an explicit content-licensing objection; blocking is a business decision, not a technical-SEO best practice. Cross-reference the `seo-geo` skill for AI visibility strategy, and the `geo-crawlers` skill for a complete Tier 1/2/3 crawler reference and per-crawler audit.

Core Web Vitals, INP, and the rest of this skill's technical checks remain authoritative and unaffected by AI crawler configuration — see the sections below.

### 2. Indexability
- Canonical tags: self-referencing, no conflicts with noindex
- Duplicate content: near-duplicates, parameter URLs, www vs non-www
- Thin content: pages below minimum word counts per type
- Pagination: rel=next/prev or load-more pattern
- Hreflang: correct for multi-language/multi-region sites
- Index bloat: unnecessary pages consuming crawl budget

### 3. Security
- HTTPS: enforced, valid SSL certificate, no mixed content
- Security headers:
  - Content-Security-Policy (CSP)
  - Strict-Transport-Security (HSTS)
  - X-Frame-Options
  - X-Content-Type-Options
  - Referrer-Policy
- HSTS preload: check preload list inclusion for high-security sites

### 4. URL Structure
- Clean URLs: descriptive, hyphenated, no query parameters for content
- Hierarchy: logical folder structure reflecting site architecture
- Redirects: no chains (max 1 hop), 301 for permanent moves
- URL length: flag >100 characters
- Trailing slashes: consistent usage

### 5. Mobile Optimization
- Responsive design: viewport meta tag, responsive CSS
- Touch targets: minimum 48x48px with 8px spacing
- Font size: minimum 16px base
- No horizontal scroll
- Mobile-first indexing: Google indexes mobile version. **Mobile-first indexing is 100% complete as of July 5, 2024.** Google now crawls and indexes ALL websites exclusively with the mobile Googlebot user-agent.

### 6. Core Web Vitals
- **LCP** (Largest Contentful Paint): target <2.5s
- **INP** (Interaction to Next Paint): target <200ms
  - INP replaced FID on March 12, 2024. FID was fully removed from all Chrome tools (CrUX API, PageSpeed Insights, Lighthouse) on September 9, 2024. Do NOT reference FID anywhere.
- **CLS** (Cumulative Layout Shift): target <0.1
- Evaluation uses 75th percentile of real user data
- Use PageSpeed Insights API or CrUX data if MCP available

### 7. Structured Data
- Detection: JSON-LD (preferred), Microdata, RDFa
- Validation against Google's supported types
- See seo-schema skill for full analysis

### 8. JavaScript Rendering
- Check if content visible in initial HTML vs requires JS
- Identify client-side rendered (CSR) vs server-side rendered (SSR)
- Flag SPA frameworks (React, Vue, Angular) that may cause indexing issues
- Verify dynamic rendering setup if applicable

#### JavaScript SEO: Canonical & Indexing Guidance (December 2025)

Google updated its JavaScript SEO documentation in December 2025 with critical clarifications:

1. **Canonical conflicts:** If a canonical tag in raw HTML differs from one injected by JavaScript, Google may use EITHER one. Ensure canonical tags are identical between server-rendered HTML and JS-rendered output.
2. **noindex with JavaScript:** If raw HTML contains `<meta name="robots" content="noindex">` but JavaScript removes it, Google MAY still honor the noindex from raw HTML. Serve correct robots directives in the initial HTML response.
3. **Non-200 status codes:** Google does NOT render JavaScript on pages returning non-200 HTTP status codes. Any content or meta tags injected via JS on error pages will be invisible to Googlebot.
4. **Structured data in JavaScript:** Product, Article, and other structured data injected via JS may face delayed processing. For time-sensitive structured data (especially e-commerce Product markup), include it in the initial server-rendered HTML.

**Best practice:** Serve critical SEO elements (canonical, meta robots, structured data, title, meta description) in the initial server-rendered HTML rather than relying on JavaScript injection.

### 9. IndexNow Protocol
- Check if site supports IndexNow for Bing, Yandex, Naver
- Supported by search engines other than Google
- Recommend implementation for faster indexing on non-Google engines

### 10. On-Page SEO

No other specialist covers this for full-site audits — `seo-page` covers it
for single-page runs, but `seo-audit` does not spawn `seo-page`, so this
skill is the sole source of the "On-Page SEO" figure in the aggregate
Health Score. Check per crawled page (reuse the per-page crawl already
performed for categories 1-2, don't re-crawl):

- Title tag: present, 50-60 characters, unique across the site
- Meta description: present, 150-160 characters
- H1: exactly one, matches page intent
- H2-H6: logical hierarchy, no skipped levels
- Internal links: no orphan pages (zero inbound internal links), 3-5 relevant links per 1000 words
- External links: to authoritative sources where topically expected

## Agent-Friendly Pages (forward-looking)

AI agents (not just AI summarizers) increasingly read sites through three
channels: vision models on screenshots, raw HTML/DOM, and the **accessibility
tree** (the cleanest signal). Audit criteria — semantic HTML (real `<button>`
and `<a>`, not `<div onclick>`), label associations, interactive target sizing,
layout stability across templates, `cursor: pointer` correctness — live in
`references/agent-friendly-pages.md`.

### Audit command

```bash
# Render with Playwright + capture accessibility tree, then score
python3 scripts/agent_ux_check.py https://example.com --json
```

The scanner outputs an Agent-UX score (0-100) plus itemized issues:
- HTML findings: real buttons / anchors, `<div onclick>` widgets, semantic
  landmarks, inputs without `<label for>`, inputs without ARIA labels
- Accessibility tree findings: total nodes, interactive nodes, unnamed
  interactive elements, `role="generic"` ratio

The accessibility-tree snapshot uses Playwright's
`page.accessibility.snapshot(interesting_only=False)`. To capture the tree
without scoring, use `python3 scripts/render_page.py <url> --a11y-tree --json`.

Surface findings as **opportunities**, not failures. The standards (WebMCP,
agent UX heuristics) are early — don't gate audits on a sub-100 score.

## Scoring

Compute both scores using the fixed-criteria method in
`skills/seo/references/scoring-rubric.md`: each criterion below has its
own point allocation, is scored on the 6-tier scale via its sub-checks
(`nearest of 0/20/40/60/80/100% to satisfied/total sub-checks`), and
**requires cited evidence per sub-check** — state what you found, or
"No evidence found," never an assumption. Do not add, drop, or reweight
criteria at scoring time.

### Technical Score criteria (sum to 100)

| Criterion | Points | Sub-checks (tier by fraction satisfied) |
|---|---|---|
| Crawlability | 15 | robots.txt exists/valid/not blocking important resources; XML sitemap exists/referenced/valid; no unintentional noindex on an important page; important pages ≤3 clicks from homepage; critical content has SSR/prerender (not JS-only) |
| Indexability | 15 | canonical present and non-conflicting; no unresolved duplicate/parameter URLs; no thin content below the page-type floor; hreflang correct (mark satisfied if single-language/region — not applicable); no index bloat |
| Security | 10 | HTTPS enforced + valid SSL + no mixed content; CSP present; HSTS present; X-Frame-Options present; X-Content-Type-Options and Referrer-Policy both present (one combined sub-check) |
| URL Structure | 8 | no query-parameter URLs for indexable content; no redirect chains (>1 hop); URLs ≤100 characters; consistent hierarchy and trailing-slash usage |
| Mobile | 12 | viewport meta / responsive layout present; content parity between mobile and desktop; touch targets ≥48x48px and base font ≥16px; no horizontal scroll |
| Core Web Vitals (presence check only — full CWV scoring lives in the Performance category) | 10 | LCP at "Good" tier; INP at "Good" tier; CLS at "Good" tier (per the thresholds in `agents/seo-performance.md`) — state "No evidence found" per metric if no CrUX/Lighthouse data was pulled this run, which scores that sub-check as unsatisfied |
| Structured Data (presence check only — full validation lives in `seo-schema`) | 10 | valid, parseable JSON-LD is present somewhere on the page; no deprecated schema type is in use |
| JS Rendering | 15 | critical content visible in raw HTML (SSR/prerender, not CSR-only); canonical and meta-robots identical between raw HTML and JS-rendered output; time-sensitive structured data (Product/Offer) is not JS-only |
| IndexNow | 5 | IndexNow key file or protocol support detected |

`Technical Score = sum(criterion_score across all 9 rows)`. On-Page SEO
is scored and reported separately below — never folded into this number.

### On-Page SEO criteria (sum to 100)

This is the sole source of the weighted "On-Page SEO" aggregate category
for full-site audits — no other specialist covers it (see note in the
category description above). Tier each criterion across all crawled
pages using the proportion-based table in the scoring rubric (share of
pages failing), not a single representative page.

| Criterion | Points | What "Excellent" (100%) looks like |
|---|---|---|
| Title tag | 20 | Present, 50-60 characters, unique across the site, on every crawled page |
| Meta description | 15 | Present, 150-160 characters, on every crawled page |
| H1 | 20 | Exactly one H1 per page, matching page intent, on every crawled page |
| Heading hierarchy | 10 | H2-H6 follow a logical order with no skipped levels, on every crawled page |
| Internal linking | 20 | Zero orphan pages; 3-5 relevant internal links per 1000 words site-wide |
| External linking | 15 | Links to authoritative sources where topically expected, in reasonable count |

`On-Page SEO Score = sum(criterion_score across all 6 rows)`.

## Output

### Technical Score: XX/100
Sum of the 9 criteria above. State each criterion's tier and the cited
evidence/sub-check results that produced it. Per scoring-rubric.md Rule 4,
compute the sum with an actual tool call (e.g. `python3 -c "print(...)"`)
using the 9 real numbers and show that expression — do not add them in
prose. A live test found reported totals did not match their own itemized
scores when this step was skipped.

### Criteria Breakdown
Evidence is a mandatory column (Rule 6), not optional — "No evidence
found" is a complete answer and forces that row's score to 0.

| Criterion | Points possible | Points earned | Tier | Evidence |
|----------|--------|-------|-------|-------|
| Crawlability | 15 | XX | ... | ... |
| Indexability | 15 | XX | ... | ... |
| Security | 10 | XX | ... | ... |
| URL Structure | 8 | XX | ... | ... |
| Mobile | 12 | XX | ... | ... |
| Core Web Vitals | 10 | XX | ... | ... |
| Structured Data | 10 | XX | ... | ... |
| JS Rendering | 15 | XX | ... | ... |
| IndexNow | 5 | XX | ... | ... |

### On-Page SEO Score: XX/100
Reported separately (see Scoring section above) — feeds the "On-Page SEO"
line of the aggregate Health Score, not the Technical Score above. Include
the same per-criterion breakdown (6 rows, points possible/earned/tier/
evidence), and the same tool-computed sum required above (Rule 4) — not
prose addition.

### Critical Issues (fix immediately)
### High Priority (fix within 1 week)
### Medium Priority (fix within 1 month)
### Low Priority (backlog)

## DataForSEO Integration (Optional)

If DataForSEO MCP tools are available, use `on_page_instant_pages` for real page analysis (status codes, page timing, broken links, on-page checks), `on_page_lighthouse` for Lighthouse audits (performance, accessibility, SEO scores), and `domain_analytics_technologies_domain_technologies` for technology stack detection.

## Google API Integration (Optional)

If Google API credentials are configured, use `python3 scripts/pagespeed_check.py <url> --json` for real PSI + CrUX field data (replaces lab-only CWV estimates), `python3 scripts/crux_history.py <url> --json` for 25-week CWV trends, and `python3 scripts/gsc_inspect.py <url> --json` for real indexation status per URL.

## Error Handling

| Scenario | Action |
|----------|--------|
| URL unreachable | Report connection error with status code. Suggest verifying URL, checking DNS resolution, and confirming the site is publicly accessible. |
| robots.txt not found | Note that no robots.txt was detected at the root domain. Recommend creating one with appropriate directives. Continue audit on remaining categories. |
| HTTPS not configured | Flag as a critical issue. Report whether HTTP is served without redirect, mixed content exists, or SSL certificate is missing/expired. |
| Core Web Vitals data unavailable | Note that CrUX data is not available (common for low-traffic sites). Suggest using Lighthouse lab data as a proxy and recommend increasing traffic before re-testing. |
