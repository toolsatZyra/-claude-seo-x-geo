# Commands Reference

## Overview

All Claude SEO commands start with `/seo` followed by a subcommand.

## Command List

### `/seo audit <url>`

Full website SEO audit with parallel analysis.

**Example:**
```
/seo audit https://example.com
```

**What it does:**
1. Crawls up to 500 pages
2. Detects business type
3. Delegates to 7 specialist subagents in parallel
4. Generates SEO Health Score (0-100)
5. Creates prioritized action plan

**Output:**
- `FULL-AUDIT-REPORT.md`
- `ACTION-PLAN.md`
- `screenshots/` (if Playwright available)

---

### `/seo page <url>`

Deep single-page analysis.

**Example:**
```
/seo page https://example.com/about
```

**What it analyzes:**
- On-page SEO (title, meta, headings, URLs)
- Content quality (word count, readability, E-E-A-T)
- Technical elements (canonical, robots, Open Graph)
- Schema markup
- Images (alt text, sizes, formats)
- Core Web Vitals potential issues

---

### `/seo technical <url>`

Technical SEO audit across 9 categories.

**Example:**
```
/seo technical https://example.com
```

**Categories:**
1. Crawlability
2. Indexability
3. Security
4. URL Structure
5. Mobile Optimization
6. Core Web Vitals (LCP, INP, CLS)
7. Structured Data
8. JavaScript Rendering
9. IndexNow Protocol

---

### `/seo content <url>`

E-E-A-T and content quality analysis.

**Example:**
```
/seo content https://example.com/blog/post
```

**What it evaluates:**
- Experience signals (first-hand knowledge)
- Expertise (author credentials)
- Authoritativeness (external recognition)
- Trustworthiness (transparency, security)
- AI citation readiness
- Content freshness

---

### `/seo content-brief <topic or url>`

Generate a detailed SEO content brief: target keywords, search intent, heading outline, internal link targets, and competitor angle.

**Example:**
```
/seo content-brief "best running shoes for flat feet"
```

**What it produces:**
- Primary and secondary target keywords
- Search intent and audience
- Section-by-section heading outline
- Internal link recommendations
- Competitor content angles to beat

---

### `/seo schema <url>`

Schema markup detection, validation, and generation.

**Example:**
```
/seo schema https://example.com
```

**What it does:**
- Detects existing schema (JSON-LD, Microdata, RDFa)
- Validates against Google's requirements
- Identifies missing opportunities
- Generates ready-to-use JSON-LD

---

### `/seo geo <url>`

AI Overviews / Generative Engine Optimization.

**Example:**
```
/seo geo https://example.com/blog/guide
```

**What it analyzes:**
- Citability score (quotable facts, statistics)
- Structural readability (headings, lists, tables)
- Entity clarity (definitions, context)
- Authority signals (credentials, sources)
- Structured data support

---

### `/seo images <url>`

Image optimization analysis.

**Example:**
```
/seo images https://example.com
```

**What it checks:**
- Alt text presence and quality
- File sizes (flag >200KB)
- Formats (WebP/AVIF recommendations)
- Responsive images (srcset, sizes)
- Lazy loading
- CLS prevention (dimensions)

---

### `/seo sitemap <url>`

Analyze existing XML sitemap.

**Example:**
```
/seo sitemap https://example.com/sitemap.xml
```

**What it validates:**
- XML format
- URL count (<50k per file)
- URL status codes
- lastmod accuracy
- Deprecated tags (priority, changefreq)
- Coverage vs crawled pages

---

### `/seo sitemap generate`

Generate new sitemap with industry templates.

**Example:**
```
/seo sitemap generate
```

**Process:**
1. Select or auto-detect business type
2. Interactive structure planning
3. Apply quality gates (30/50 location page limits)
4. Generate valid XML
5. Create documentation

---

### `/seo plan <type>`

Strategic SEO planning.

**Types:** `saas`, `local`, `ecommerce`, `publisher`, `agency`

**Example:**
```
/seo plan saas
```

**What it creates:**
- Complete SEO strategy
- Competitive analysis
- Content calendar
- Implementation roadmap (4 phases)
- Site architecture design

---

### `/seo competitor-pages [url|generate]`

Competitor comparison page generation.

**Examples:**
```
/seo competitor-pages https://example.com/vs/competitor
/seo competitor-pages generate
```

**Capabilities:**
- Generate "X vs Y" comparison page layouts
- Create "Alternatives to X" page structures
- Build feature comparison matrices with scoring
- Generate Product + AggregateRating schema markup
- Apply conversion-optimized CTA placement
- Enforce fairness guidelines (accurate data, source citations)

---

### `/seo hreflang [url]`

Hreflang and international SEO audit and generation.

**Example:**
```
/seo hreflang https://example.com
```

**Capabilities:**
- Validate self-referencing hreflang tags
- Check return tag reciprocity (A→B requires B→A)
- Verify x-default tag presence
- Validate ISO 639-1 language and ISO 3166-1 region codes
- Check canonical URL alignment with hreflang
- Detect protocol mismatches (HTTP vs HTTPS)
- Generate correct hreflang link tags and sitemap XML

---

### `/seo programmatic [url|plan]`

Programmatic SEO analysis and planning for pages generated at scale.

**Examples:**
```
/seo programmatic https://example.com/tools/
/seo programmatic plan
```

**Capabilities:**
- Assess data source quality (CSV, JSON, API, database)
- Plan template engines with unique content per page
- Design URL pattern strategies (`/tools/[tool-name]`, `/[city]/[service]`)
- Automate internal linking (hub/spoke, related items, breadcrumbs)
- Enforce thin content safeguards (quality gates, word count thresholds)
- Prevent index bloat (noindex low-value, pagination, faceted nav)

---

### `/seo local <url>`

Local SEO analysis covering Google Business Profile, citations, reviews, and the map pack.

**Example:**
```
/seo local https://example.com
```

**What it analyzes:**
- Google Business Profile signals (categories, hours, photos, posts)
- NAP (Name, Address, Phone) consistency across the page and external citations
- Review velocity, response rate, and sentiment
- Local schema markup (LocalBusiness, Restaurant, Service-specific types)
- Industry-specific local factors (brick-and-mortar, SAB, hybrid)
- Map pack visibility signals

---

### `/seo maps [command] [args]`

Maps intelligence: geo-grid rank tracking, GBP profile audits, review intelligence, cross-platform NAP verification, competitor radius mapping.

**Examples:**
```
/seo maps geogrid "coffee shop austin tx"
/seo maps audit https://www.google.com/maps/place/...
/seo maps reviews <place_id>
/seo maps competitors "auto repair denver" 5mi
```

**Capabilities:**
- Rank tracking on a geographic grid (typically 49 points)
- GBP profile audit with completeness scoring
- Review aggregation across Google, Yelp, Facebook, Bing
- Competitor discovery within a configurable radius

---

### `/seo backlinks <url>`

Backlink profile analysis with a 3-tier data cascade: free (Common Crawl + verification), free with signup (Moz, Bing Webmaster Tools), paid (DataForSEO).

**Examples:**
```
/seo backlinks https://example.com
/seo backlinks setup
/seo backlinks verify https://example.com
```

**What it analyzes:**
- Domain Authority and Page Authority (Moz)
- Referring domain count and growth
- Anchor text distribution (branded, exact, partial, naked URL)
- Toxic / spammy backlink detection
- Lost backlinks
- Competitor link gap

---

### `/seo cluster <seed-keyword>`

SERP-based semantic topic clustering for content architecture planning. Built on the Pro Hub Challenge Semantic Cluster Engine.

**Example:**
```
/seo cluster "claude code skills"
```

**What it produces:**
- Keyword expansion from the seed (50-200 candidates)
- Pairwise SERP overlap comparison to detect semantic clusters
- Intent classification per cluster (informational, commercial, transactional, navigational)
- Hub-and-spoke content architecture proposal
- Internal link matrix between cluster pages
- Interactive `cluster-map.html` visualization

---

### `/seo sxo <url>`

Search Experience Optimization: SERP backwards analysis, page-type mismatch detection, persona scoring.

**Example:**
```
/seo sxo https://example.com/blog/how-to-x
```

**What it produces:**
- Page-type taxonomy classification (article, landing, product, tool, listing)
- SERP intent vs page-type alignment check
- User stories derived from SERP signals
- Multi-persona scoring (researcher, buyer, expert, casual visitor)
- Wireframe-level recommendations for fixing mismatches

---

### `/seo drift baseline|compare|history <url>`

SEO drift monitoring. Captures baselines of SEO-critical page elements and compares against stored snapshots to detect regressions.

**Examples:**
```
/seo drift baseline https://example.com
/seo drift compare https://example.com
/seo drift history https://example.com
```

**What it tracks:** title, meta description, canonical, hreflang, Open Graph, schema, headings, internal links, robots, sitemap entry, indexability, Core Web Vitals, response status, redirect chain.

**17 comparison rules** classify changes by severity (CRITICAL, HIGH, MEDIUM). SQLite-backed baselines.

---

### `/seo ecommerce <url>`

E-commerce SEO covering product schema, marketplace intelligence, and pricing gap analysis.

**Example:**
```
/seo ecommerce https://shop.example.com/product/x
```

**What it analyzes:**
- Product schema (Product, Offer, AggregateRating, Review)
- Google Shopping visibility
- Amazon marketplace presence
- Pricing gap vs competitors
- Out-of-stock and availability signals
- Faceted navigation crawl traps

---

### `/seo flow [stage] [url|topic]`

FLOW framework integration: evidence-led prompts for the Find, Leverage, Optimize, Win, and Local stages of a content campaign.

**Examples:**
```
/seo flow find "topic"
/seo flow leverage https://example.com
/seo flow optimize "target keyword"
```

**41 prompts** sourced from FLOW (CC BY 4.0). Each prompt is grounded in a specific evidence source (SERP data, GSC, GA4, customer interviews) with attribution preserved.

---

### `/seo google [command] [url]`

Google SEO APIs. 4-tier credential system covering PageSpeed Insights, CrUX, CrUX History, Search Console, URL Inspection, Indexing API, GA4, and Keyword Planner.

**Examples:**
```
/seo google setup
/seo google check
/seo google psi https://example.com
/seo google gsc-queries https://example.com
/seo google indexing-notify https://example.com
/seo google ga4-organic
/seo google report full
```

**Tiers:**
- Tier 0 (API key only): PSI, CrUX, CrUX History
- Tier 1 (+ OAuth or Service Account): GSC, URL Inspection, Indexing API
- Tier 2 (+ GA4 property config): GA4 organic traffic
- Tier 3 (+ Google Ads developer token): Keyword Planner

PDF and HTML reports generated via WeasyPrint and matplotlib.

---

### `/seo image-gen [use-case] <description>`

AI image generation for SEO assets (extension). Powered by Gemini via nanobanana-mcp.

**Prerequisites:** Banana extension installed (`./extensions/banana/install.sh`)

**Use Cases:**
```
/seo image-gen og <description>          # OG/social preview image (16:9, 1K)
/seo image-gen hero <description>        # Blog hero image (16:9, 2K)
/seo image-gen product <description>     # Product photography (4:3, 2K)
/seo image-gen infographic <description> # Infographic visual (2:3, 4K)
/seo image-gen custom <description>      # Custom with full Creative Director pipeline
/seo image-gen batch <description> [N]   # Generate N variations (default: 3)
```

**What it does:**
1. Maps SEO use case to optimized domain mode, aspect ratio, and resolution
2. Constructs 6-component Reasoning Brief (Creative Director pipeline)
3. Generates image via Gemini API
4. Provides SEO checklist (alt text, file naming, WebP, schema markup)

---

### `/seo firecrawl [command] <url>`

Full-site crawling and URL discovery via Firecrawl MCP (extension).

**Prerequisites:** Firecrawl extension installed (`./extensions/firecrawl/install.sh`)

**Examples:**
```
/seo firecrawl crawl https://example.com
/seo firecrawl map https://example.com
/seo firecrawl scrape https://example.com/page
```

**What it does:**
- `crawl` walks the site discovering URLs and capturing content
- `map` returns the full URL inventory for a domain
- `scrape` extracts a single page in a model-friendly format

---

### `/seo dataforseo [command]`

Live SEO data via DataForSEO MCP server (extension). 23 commands across 9 API modules.

**Prerequisites:** DataForSEO extension installed (`./extensions/dataforseo/install.sh`)

**SERP Analysis:**
```
/seo dataforseo serp <keyword>              # Google organic results (also Bing/Yahoo)
/seo dataforseo serp-youtube <keyword>      # YouTube search results
/seo dataforseo youtube <video_id>          # YouTube video deep analysis
```

**Keyword Research:**
```
/seo dataforseo keywords <seed>             # Keyword ideas and suggestions
/seo dataforseo volume <keywords>           # Search volume metrics
/seo dataforseo difficulty <keywords>       # Keyword difficulty scores
/seo dataforseo intent <keywords>           # Search intent classification
/seo dataforseo trends <keyword>            # Google Trends data
```

**Domain & Competitors:**
```
/seo dataforseo backlinks <domain>          # Full backlink profile
/seo dataforseo competitors <domain>        # Competitor analysis
/seo dataforseo ranked <domain>             # Ranked keywords
/seo dataforseo intersection <domains>      # Keyword/backlink overlap
/seo dataforseo traffic <domains>           # Traffic estimation
/seo dataforseo subdomains <domain>         # Subdomains with ranking data
/seo dataforseo top-searches <domain>       # Top queries mentioning domain
```

**Technical / On-Page:**
```
/seo dataforseo onpage <url>                # On-page analysis (Lighthouse)
/seo dataforseo tech <domain>               # Technology detection
/seo dataforseo whois <domain>              # WHOIS data
```

**Content & Business Data:**
```
/seo dataforseo content <keyword/url>       # Content analysis and trends
/seo dataforseo listings <keyword>          # Business listings search
```

**AI Visibility / GEO:**
```
/seo dataforseo ai-scrape <query>           # ChatGPT web scraper for GEO
/seo dataforseo ai-mentions <keyword>       # LLM mention tracking
```

---

### `/seo preflight <domain>`

Client onboarding check before quoting: Search Console property access, CrUX
field data, AI answer-crawler access (same evaluator as the AEO score), and a
send-ready access-request email. Runs `scripts/client_preflight.py`.

**Exit codes:** 0 GO, 1 PARTIAL (crawl-only), 2 BLOCKED. Full runbook:
[CLIENT-ONBOARDING.md](CLIENT-ONBOARDING.md).

---

### `/seo project init|show|set|add-competitor|add-prompt|note <domain>`

Client profile every research, content and tracking skill reads: brand terms,
3-7 competitors, audiences, market, exact GSC property string, GA4 property,
money pages, conversion events, voice samples, AI prompt panel, and decision
notes with `approved_by: user|inferred` provenance. Runs
`scripts/seo_project.py`. Stored under `$CLAUDE_SEO_DATA_DIR` (0600), never in
the repo.

```
/seo project init example.com
/seo project add-prompt example.com "best crm for startups"
```

---

### `/seo growth <domain>`

Guided end-to-end loop with a checkpoint after each stage: preflight and
profile, baseline audit (separate SEO and AEO scores), keyword and competitor
research, cluster and content calendar, fixes and refreshes, AI share of
voice, then weekly tracking. Stops before any paid API call or CMS write.

---

### `/seo keywords plan|discover|gsc|score <seed|domain|file>`

Keyword research hub (`seo-keywords`). Free tier: Google autocomplete expansion
(unofficial, no volume) and Search Console opportunity mining: striking
distance (positions 4-20), CTR underperformers against a site-calibrated CTR
curve, and cannibalization. Paid tiers merge Keyword Planner, DataForSEO,
Ahrefs or Semrush exports. Every keyword gets intent, funnel stage (TOFU,
MOFU or BOFU), lead value, an opportunity score with its data completeness, an
action bucket (quick_win, growth, long_term or awareness), GEO answer-format
flags, and lead priority. Runs `scripts/keyword_research.py`.

**Output:** JSON or CSV with the data tier disclosed. Groups are lexical
approximations; use `/seo cluster` for SERP-overlap clustering.

---

### `/seo competitors full|keywords|content <domain>`

Competitor analysis hub (`seo-competitors`):
- **Keyword gap:** needs ranking exports. Every keyword is segmented as moat
  (only you rank), battleground (you and a competitor both rank), gap (only a
  competitor ranks) or pioneer (nobody ranks).
- **Content and format gap:** free, from competitor sitemaps. Shows missing
  page types such as comparison, alternatives and integrations pages.
- **Backlink gap:** routed to `seo-backlinks`.
- **AI-citation gap:** routed to `geo-share-of-voice`.
- **Battlecards:** one per competitor.

Generating "X vs Y" pages stays with `/seo competitor-pages`. Runs
`scripts/competitor_gap.py`.

---

### `/seo content-engine [plan|brief|draft|check|export|measure] <domain|item|file>`

Outrank-style content pipeline with human checkpoints (`seo-content-engine`):
1. Keyword selection, BOFU-first for leads.
2. Cannibalization pre-check against GSC and existing URLs.
3. Calendar with a volume guard against scaled-content abuse.
4. Brief, then draft.
5. Quality gates: claim verification, citability, content quality,
   humanizer, coverage, schema and IPTC labels.
6. Mandatory human review (`reviewed_by`).
7. Export as a draft (Markdown/HTML bundle, HMAC-signed webhook, or WordPress
   draft).
8. Measurement at +14 and +28 days.

Runs `scripts/content_export.py`. **Nothing is published without
`--status publish`, passing publish gates and `--confirm`.**

---

### `/seo content optimize <url> <keyword>`

Optimize mode of `seo-content`. Compares the page against competitor pages you
supply (or DataForSEO SERP data; Google is never scraped). Measures:
- term coverage over 1-3-grams present in at least 50% of competitor pages
- heading and question coverage
- length percentile
- keyword placement and keyword stuffing

The deterministic 0-100 score prints its own arithmetic and is correlational,
not a ranking guarantee. Runs `scripts/content_optimizer.py`.

---

### `/seo refresh [decay|candidates|brief|aio|export|measure] <domain|url>`

Content decay and improvement loop (`seo-refresh`). `content_decay.py analyze`
compares the last 90 days with the same window a year earlier (or the previous
90 days) and assigns:
- a tier: −20% warning, −40% high, −60% critical
- a cause: SERP feature or AI Overview, ranking loss, demand drop, or
  cannibalization
- a rule-traced action: refresh, rewrite, consolidate, redirect/retire review,
  or monitor

`candidates` lists high-impression pages at positions 4-25 with a CTR gap or
declining clicks. Also includes an AI-Overview recovery playbook and
date-hygiene rules.

---

### `/seo track setup|snapshot|report|ai-referrals|experiment|export <domain>`

Measurement hub (`seo-track`). `performance_tracker.py` keeps KPI history in
SQLite: GSC clicks (total and non-brand), rank visibility, GA4 organic and
AI-assistant sessions and key events, AI share of voice, the AEO score, and
CRM leads. Any script can contribute through a validated KPI envelope
(`scripts/seo_kpi.py`). `report --compare 28d --fail-on-drop N` exits 3 when a
watched metric drops. `experiment` gives holdout verdicts (Promote,
Keep-testing, Rollback or Unproven).

---

### `/seo rank add|ingest|import|report|history <domain>`

Rank tracking (`seo-track`, `scripts/rank_tracker.py`): daily GSC
average-position history plus SERP imports from DataForSEO, Ahrefs, Semrush or
manual files. Reports movers (|Δ| ≥ 3 with an impression floor, excluding the
newest 3 days of GSC lag), a visibility index, band distribution,
cannibalization, URL swaps and per-tag summaries. GSC position is an average,
not a SERP rank; the report says so.

---

### `/seo ai-visibility plan|run|ingest|report|compare <domain>`

AI share of voice (`geo-share-of-voice`, `scripts/ai_visibility.py`). It runs
a fixed prompt panel (unbranded headline, treatment and control groups, k ≥ 5
runs) through:
- Anthropic's API with web search (`--max-calls` required; dry run available)
- DataForSEO ChatGPT/LLM captures or manual captures (ingested)

It reports mention rate with Wilson 95% CI, share of voice, citation rate and
share, and competitor tables. n < 20 is flagged thin. API and consumer-UI
answers are never pooled. `compare` runs paired sign tests with Holm
correction. This is an outcome metric, never blended into the AEO readiness
score.

---

### `/seo agentic [lighthouse|fix|refresh] <url>`

Agent readiness (`seo-agentic`, ported from upstream v2.4). Covers:
- the Lighthouse Agentic Browsing category
- AI agent access rules and Content-Signal
- Markdown delivery (`Accept: text/markdown`)
- `ai-catalog.json`, `/.well-known` discovery files and WebMCP

Fix mode drafts the files.

---

## Quick Reference

| Command | Use Case |
|---------|----------|
| `/seo audit <url>` | Full website audit with parallel subagents |
| `/seo preflight <domain>` | Client onboarding: data access check + access request |
| `/seo project init <domain>` | Client profile read by every skill |
| `/seo growth <domain>` | Guided research → create → measure loop |
| `/seo keywords <seed\|domain>` | Keyword research, scoring, lead priority |
| `/seo competitors <domain>` | Keyword, content, backlink and AI-citation gaps |
| `/seo content-engine <domain>` | Calendar → brief → draft → gates → review → draft export |
| `/seo content optimize <url> <kw>` | Coverage vs ranking pages |
| `/seo refresh <domain>` | Content decay + improvement candidates |
| `/seo track <domain>` | KPI history and trend reports |
| `/seo rank <domain>` | Rank tracking from GSC history + SERP imports |
| `/seo ai-visibility <domain>` | AI share of voice with confidence intervals |
| `/seo agentic <url>` | AI agent readiness |
| `/seo page <url>` | Single page analysis |
| `/seo technical <url>` | Technical SEO across 9 categories |
| `/seo content <url>` | E-E-A-T and content quality |
| `/seo content-brief <topic>` | Detailed content brief: keywords, outline, internal links |
| `/seo schema <url>` | Schema markup detection, validation, generation |
| `/seo sitemap <url>` | Sitemap validation |
| `/seo sitemap generate` | Create new sitemap with industry templates |
| `/seo images <url>` | Image optimization |
| `/seo geo <url>` | AI search optimization (GEO) |
| `/seo local <url>` | Local SEO (GBP, citations, reviews) |
| `/seo maps [command]` | Maps intelligence (geo-grid, GBP audit, competitors) |
| `/seo backlinks <url>` | Backlink profile analysis |
| `/seo cluster <seed>` | SERP-based semantic clustering |
| `/seo sxo <url>` | Search Experience Optimization |
| `/seo drift baseline\|compare\|history <url>` | SEO drift monitoring |
| `/seo ecommerce <url>` | E-commerce SEO |
| `/seo hreflang [url]` | Hreflang and international SEO |
| `/seo plan <type>` | Strategic planning by industry |
| `/seo programmatic [url\|plan]` | Programmatic SEO analysis |
| `/seo competitor-pages [url\|generate]` | Competitor comparison pages |
| `/seo flow [stage] [url\|topic]` | FLOW framework prompts |
| `/seo google [command] [url]` | Google SEO APIs (GSC, PSI, CrUX, GA4) |
| `/seo dataforseo [command]` | Live SEO data (extension) |
| `/seo image-gen [use-case] <desc>` | AI image generation (extension) |
| `/seo firecrawl [command] <url>` | Full-site crawling (extension) |
