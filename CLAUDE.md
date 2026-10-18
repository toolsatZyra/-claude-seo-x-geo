# Claude SEO: Universal SEO Analysis Skill

## Project Overview

This repository contains **Claude SEO**, a Tier 4 Claude Code skill for comprehensive
SEO analysis across all industries. It follows the Agent Skills open standard and the
3-layer architecture (directive, orchestration, execution). 40 sub-skills (36 core +
1 orchestrator + 1 framework integration + 2 extension mirrors), 21 sub-agents, and
an extensible reference system make it a central SEO + AEO + GEO hub: keyword
research, rank and KPI tracking, competitor gap analysis, an Outrank-style content
engine with human review gates, content-decay refresh, AI share-of-voice tracking,
plus technical SEO, content quality,
schema markup, image optimization, sitemap architecture, first-class AEO/GEO
(deterministic citability scoring, per-platform optimization, AI crawler access,
brand-mention tracking),
local SEO (GBP, citations, reviews, map pack), maps intelligence, semantic topic
clustering, search experience optimization (SXO), SEO drift monitoring, e-commerce
SEO, and international SEO with cultural adaptation profiles.

## Architecture

```
claude-seo/
  CLAUDE.md                          # Project instructions (this file)
  CONTRIBUTORS.md                    # Community credits (Pro Hub Challenge)
  AGENTS.md                          # Multi-platform agent instructions (Cursor, Antigravity)
  .claude-plugin/
    plugin.json                    # Plugin manifest (v3.1.0)
    marketplace.json               # Marketplace catalog for distribution
  skills/                            # 40 sub-skills (auto-discovered)
    seo/                           # Main orchestrator skill
      SKILL.md                     # Entry point, routing table, core rules
      references/                  # On-demand knowledge files (15 files)
    seo-audit/SKILL.md            # Full site audit with parallel agents
    seo-page/SKILL.md            # Deep single-page analysis
    seo-technical/SKILL.md       # Technical SEO (9 categories)
    seo-content/SKILL.md         # E-E-A-T and content quality
    seo-schema/SKILL.md          # Schema.org markup detection/generation
    seo-sitemap/SKILL.md         # XML sitemap analysis/generation
    seo-images/SKILL.md          # Image optimization analysis
    seo-geo/SKILL.md             # AI search / GEO optimization
    seo-local/SKILL.md           # Local SEO (GBP, citations, reviews, map pack)
    seo-maps/SKILL.md            # Maps intelligence (geo-grid, GBP audit, reviews, competitors)
    seo-plan/SKILL.md            # Strategic SEO planning
    seo-programmatic/SKILL.md    # Programmatic SEO at scale
    seo-competitor-pages/SKILL.md # Competitor comparison pages
    seo-hreflang/SKILL.md       # International SEO / hreflang
    seo-google/                  # Google SEO APIs
      SKILL.md
      references/                # API reference files (10 files)
    seo-backlinks/SKILL.md      # Backlink profile analysis
    seo-cluster/                 # Semantic topic clustering (v1.9.0, by Lutfiya Miller)
      SKILL.md
      references/                # Clustering methodology, architecture, workflow
      templates/                 # cluster-map.html interactive visualization
    seo-sxo/                     # Search Experience Optimization (v1.9.0, by Florian Schmitz)
      SKILL.md
      references/                # Page-type taxonomy, user stories, personas, wireframes
    seo-drift/                   # SEO drift monitoring (v1.9.0, by Dan Colta)
      SKILL.md
      references/                # Comparison rules (17 rules, 3 severity levels)
    seo-ecommerce/               # E-commerce SEO (v1.9.0, by Matej Marjanovic)
      SKILL.md
      references/                # Marketplace API endpoints
    seo-dataforseo/SKILL.md     # Live SEO data via DataForSEO MCP (extension mirror)
    seo-image-gen/              # AI image generation for SEO assets (extension mirror)
      SKILL.md
      references/                # Image gen reference files
    seo-keywords/                # Keyword research hub: discovery tiers, intent, opportunity, lead priority (v3.1)
    seo-competitors/             # Competitor analysis hub: keyword gap, content/format gap (v3.1)
    seo-content-engine/          # Calendar -> brief -> draft -> gates -> review -> draft export (v3.1)
    seo-refresh/                 # Content decay + GSC improvement loop, AIO recovery (v3.1)
    seo-track/                   # Rank tracking, KPI history, AI referrals, holdout tests (v3.1)
    seo-links/                   # Competitor link gap + link earning (prospects, approved drafts, tracker)
    seo-agentic/                 # Agent readiness (ported from upstream v2.4)
    geo-citability/ geo-platform-optimizer/ geo-brand-mentions/ geo-crawlers/
    geo-compare/ geo-prospect/ geo-proposal/ geo-share-of-voice/   # AEO cluster (routed by seo-geo)
  agents/                          # 21 subagents (auto-discovered)
    seo-technical.md             # Crawlability, indexability, security
    seo-content.md               # E-E-A-T, readability, thin content
    seo-schema.md                # Structured data validation
    seo-sitemap.md               # Sitemap quality gates
    seo-performance.md           # Core Web Vitals, page speed
    seo-visual.md                # Screenshots, mobile rendering
    seo-geo.md                   # AI crawler access, GEO, citability
    seo-local.md                 # GBP, NAP, citations, reviews, local schema
    seo-maps.md                  # Geo-grid, GBP audit, reviews, competitor radius
    seo-google.md                # Google API analyst (CrUX, GSC, GA4)
    seo-backlinks.md             # Backlink profile analyst (Moz, Bing, CC, verify)
    seo-dataforseo.md            # DataForSEO data analyst
    seo-image-gen.md             # SEO image audit analyst
    seo-cluster.md               # Semantic clustering analysis
    seo-sxo.md                   # Search experience optimization
    seo-drift.md                 # SEO drift monitoring
    seo-ecommerce.md             # E-commerce SEO analysis
    seo-agentic.md               # Agent readiness checks
    geo-ai-visibility.md, geo-platform-analysis.md   # AEO specialists
  hooks/                           # Quality gate hooks
    hooks.json                   # PostToolUse schema validation
  scripts/                         # Python execution scripts (75)
    # --- v3.1 hub core (shared, deterministic; import, don't copy) ---
    seo_metrics.py               # Intent/funnel/lead value, CTR curve, opportunity score, stats, cannibalization
    seo_store.py                 # Storage root ($CLAUDE_SEO_DATA_DIR) + SQLite access (0700/0600)
    seo_project.py               # Client profile (brand terms, competitors, GSC/GA4 property, prompts)
    seo_kpi.py                   # KPI envelope contract (validated at write and ingest)
    # --- v3.1 research / create / measure ---
    keyword_research.py          # Autocomplete expansion, GSC striking distance, multi-source scoring
    competitor_gap.py            # 4-way keyword gap, sitemap content/format gap
    rank_tracker.py              # GSC rank history + SERP imports, movers, visibility, holdout experiments
    performance_tracker.py       # KPI snapshots, trend report, --fail-on-drop, export
    ai_referrals.py              # GA4 AI-assistant sessions/key events vs organic
    content_decay.py             # Decay tiers, cause diagnosis, refresh actions, improvement candidates
    content_optimizer.py         # Term/heading/question coverage vs competitor pages
    content_export.py            # Draft-first export: HTML bundle, HMAC webhook, WordPress draft, calendar checks
    ai_visibility.py             # AI share of voice: prompt panels, Anthropic engine, ingest, CI, paired compare
    link_store.py                # links store: referring-domain snapshots, prospects, events
    link_sources.py              # DataForSEO / Moz / CSV referring domains, cost-capped
    link_gap.py                  # Competitor link gap, prospect classification and scoring
    link_outreach.py             # Approval-gated outreach tracker, draft lint, verification, KPIs
    aeo_score.py                 # The single AEO Readiness Score + AI crawler access sub-score
    # --- AEO / GEO (v3.0) ---
    citability_scorer.py         # Deterministic passage citability (0-100)
    brand_scanner.py             # Brand presence on AI-cited platforms
    llmstxt_generator.py         # llms.txt audit/generation (policy in seo-geo)
    brand_config.py              # White-label report branding
    client_preflight.py          # Client onboarding access check (GO/PARTIAL/BLOCKED)
    # --- upstream ports (v3.1) ---
    agentic_check.py, agentic_fix.py, lighthouse_agentic.py   # Agent readiness (seo-agentic)
    metadata_template.py         # Templated-metadata detector
    sitemap_discovery.py         # SSRF-safe sitemap discovery
    consistency_check.py         # Dead-reference / routing CI check
    ga4_report.py                # GA4 organic traffic reports
    google_auth.py               # Credential management (OAuth, SA, API key, 4-tier detection)
    backlinks_auth.py            # Backlink API credential management (Moz, Bing)
    moz_api.py                   # Moz Link Explorer API (DA/PA, spam, domains, anchors)
    bing_webmaster.py            # Bing Webmaster Tools API (links, competitor comparison)
    commoncrawl_graph.py         # Common Crawl web graph parser (PageRank, in-degree)
    verify_backlinks.py          # Backlink existence verification crawler
    pagespeed_check.py           # PSI v5 + CrUX API
    crux_history.py              # CrUX History API (25-week trends)
    gsc_query.py                 # Search Console (queries, pages, sitemaps, sites)
    gsc_inspect.py               # URL Inspection (single + batch)
    indexing_notify.py           # Indexing API v3 (URL_UPDATED/URL_DELETED)
    ga4_report.py                # GA4 organic traffic reports
    google_report.py             # PDF/HTML report generator (WeasyPrint + matplotlib)
    youtube_search.py            # YouTube Data API v3
    nlp_analyze.py               # Cloud Natural Language API
    keyword_planner.py           # Google Ads Keyword Planner
    fetch_page.py                # Page fetcher with UA rotation
    parse_html.py                # HTML parser for SEO elements
    capture_screenshot.py        # Playwright screenshots
    analyze_visual.py            # Visual analysis helper
    drift_baseline.py            # SEO drift baseline capture (SQLite)
    drift_compare.py             # SEO drift comparison engine (17 rules)
    drift_report.py              # SEO drift HTML report generator
    drift_history.py             # SEO drift history query
    dataforseo_costs.py          # DataForSEO cost estimation and budget tracking
    dataforseo_merchant.py       # Google Shopping / Amazon data fetching
    dataforseo_normalize.py      # DataForSEO response normalization utility
    sync_flow.py                 # FLOW prompt library sync (GitHub API, CC BY 4.0 headers, --dry-run, --ref)
    url_safety.py                # Canonical URL/SSRF safety module (validate, DNS-pin, safe fetch)
    render_page.py               # Shared headless renderer (SPA-aware, Playwright)
    lcp_subparts.py              # LCP subparts breakdown via CrUX API
    preload_check.py             # Speculation Rules / bfcache / prerender / preload detector
    agent_ux_check.py            # Agent-friendly page auditor
    content_quality.py           # QRG-aligned content quality detector
    content_humanize.py          # AI-pattern remover (rewrites AI-typical phrasing)
    content_verify.py            # Claim extractor + citation-gap detector
    schema_generate.py           # JSON-LD generators for high-leverage v2 schema types
    schema_ecommerce_validate.py # Product schema validator (merchant-listing requirements)
    iptc_ai_label.py             # IPTC DigitalSourceType audit/injection for AI imagery
    parasite_risk.py             # Parasite-SEO risk scanner
    gbp_deprecation_lint.py      # GBP feature-deprecation linter
    domain_history.py            # Expired-domain heritage check
    seo_updates.py               # Primary-source Google updates query tool
    indexnow_submit.py           # IndexNow submitter
    ucp_check.py                 # UCP (Universal Commerce Protocol) profile auditor
    unlighthouse_run.py          # Unlighthouse CLI wrapper (site-wide Lighthouse)
    validate_backlink_report.py  # Backlink report validation
    portability_check.py         # Cross-platform portability lint for SKILL.md files
    release_sign.py              # SHA-256 manifest generator for release signing
    verify_release.py            # Verify checkout integrity against a release manifest
  schema/                          # Schema.org JSON-LD templates
  extensions/                      # Optional add-on install helpers
    dataforseo/                  # DataForSEO MCP install scripts
    firecrawl/                   # Firecrawl MCP install scripts
    banana/                      # Banana MCP install scripts
  docs/                            # Extended documentation
```

## Commands

| Command | Purpose |
|---------|---------|
| `/seo audit <url>` | Full site audit with up to 15 parallel subagents |
| `/seo page <url>` | Deep single-page analysis |
| `/seo technical <url>` | Technical SEO audit (9 categories) |
| `/seo content <url>` | E-E-A-T and content quality analysis |
| `/seo content-brief <topic>` | Detailed SEO content brief: keywords, outline, internal links |
| `/seo schema <url>` | Schema.org detection, validation, generation |
| `/seo sitemap <url>` | XML sitemap analysis or generation |
| `/seo images <url or optimize>` | Image SEO: on-page audit, SERP analysis, file optimization |
| `/seo geo <url>` | AI search / Generative Engine Optimization |
| `/seo plan <type>` | Strategic SEO planning by industry |
| `/seo programmatic` | Programmatic SEO analysis and planning |
| `/seo competitor-pages` | Competitor comparison page generation |
| `/seo local <url>` | Local SEO analysis (GBP, citations, reviews, map pack) |
| `/seo maps [command] [args]` | Maps intelligence (geo-grid, GBP audit, reviews, competitors) |
| `/seo hreflang <url>` | International SEO / hreflang audit |
| `/seo google [command] [url]` | Google SEO APIs (GSC, PageSpeed, CrUX, Indexing, GA4) |
| `/seo backlinks <url>` | Backlink profile analysis (free: Moz, Bing, CC; premium: DataForSEO) |
| `/seo backlinks setup` | Setup instructions for free backlink APIs |
| `/seo backlinks verify <url>` | Verify known backlinks still exist |
| `/seo cluster <seed-keyword>` | SERP-based semantic clustering and content architecture |
| `/seo sxo <url>` | Search Experience Optimization: page-type analysis, personas |
| `/seo drift baseline <url>` | Capture SEO baseline for change monitoring |
| `/seo drift compare <url>` | Compare current state to stored baseline |
| `/seo drift history <url>` | Show drift history over time |
| `/seo ecommerce <url>` | E-commerce SEO: product schema, marketplace intelligence |
| `/seo flow <url>` | Apply the FLOW framework: stage prompts and structured search-and-conversion output |
| `/seo firecrawl [command] <url>` | Full-site crawling and site mapping (extension) |
| `/seo dataforseo [command]` | Live SEO data via DataForSEO MCP (extension) |
| `/seo image-gen [use-case] <desc>` | AI image generation for SEO assets (extension) |
| `/seo preflight <domain>` | Client onboarding: data access check + access-request email |
| `/seo project init <domain>` | Client profile read by every research/content/tracking skill |
| `/seo growth <domain>` | Guided research -> create -> measure loop with checkpoints |
| `/seo keywords <seed\|domain>` | Keyword research: discovery, intent/funnel, opportunity, lead priority |
| `/seo competitors <domain>` | Keyword gap, content/format gap, backlink + AI-citation gap, battlecards |
| `/seo links <setup\|gap\|prospects\|draft\|track> <domain>` | Competitor link gap, scored prospects, approval-gated outreach, tracker |
| `/seo content-engine <domain>` | Content calendar -> brief -> draft -> gates -> human review -> draft export |
| `/seo content optimize <url> <kw>` | Coverage vs ranking pages (correlational) |
| `/seo refresh <domain>` | Content decay + improvement candidates, AI-Overview recovery |
| `/seo track <domain>` | KPI history: GSC, GA4 organic/AI, rank visibility, AEO, AI SoV, leads |
| `/seo rank <domain>` | Rank tracking from GSC history + SERP imports |
| `/seo ai-visibility <domain>` | AI share of voice with confidence intervals |
| `/seo agentic <url>` | AI agent readiness |

## Development Rules

- Keep SKILL.md files under 500 lines / 5000 tokens
- Reference files should be focused and under 200 lines
- Scripts must have docstrings, CLI interface, and JSON output
- Follow kebab-case naming for all skill directories
- Agents invoked via Agent tool, never via Bash
- Python dependencies install into `~/.claude/skills/seo/.venv/`
- Test with `python3 -m pytest tests/` after changes (if applicable)

## Security Rules

- **Never commit credentials**: `.env`, `client_secret*.json`, `oauth-token.json`, `service_account*.json` are all in `.gitignore`
- **URL validation**: All scripts that accept user URLs must call `validate_url()` from `google_auth.py` before making API calls. This blocks private IPs, loopback, and GCP metadata endpoints (SSRF protection).
- **OAuth tokens**: Never store `client_secret` in the token file. Read it from the client_secret.json file at runtime.
- **No hardcoded paths**: Use `os.path.dirname(os.path.abspath(__file__))` for relative paths, never `/home/username/...`
- **Config location**: `~/.config/claude-seo/google-api.json` and `~/.config/claude-seo/backlinks-api.json` (user-space, not in repo)

## Report Generation Rules

- **All SEO reports must use `scripts/google_report.py`** as the canonical report generator
- **Dependencies**: `matplotlib>=3.8.0` (charts) + `weasyprint>=61.0` (HTML-to-PDF), both in `requirements.txt`
- **Format**: A4 PDF via WeasyPrint + matplotlib charts at 200 DPI
- **Style**: Clean white title page with navy (#1e3a5f) accent, Times New Roman body font
- **Color palette**: Navy #1e3a5f (headers), dark gold #b8860b (accents), forest green #2d6a4f (pass), warm amber #d4740e (warnings), deep red #c53030 (fail), warm cream #faf9f7 (backgrounds)
- **Structure**: Title page → TOC with scores → Executive Summary → Data sections → Recommendations → Methodology
- **Charts**: 85% width, max-height 120mm, figure captions on every chart, saved to `charts/` at 200 DPI
- **No `page-break-inside: avoid`** on any element (causes white gaps in WeasyPrint)
- **Post-generation review**: `_review_pdf()` runs automatically, checking for empty images, thin sections, duplicates
- **Before presenting any PDF to the user**: verify the review passes (`"status": "PASS"`)
- **Cross-skill enforcement**: After completing ANY analysis command (audit, page, technical, content, schema, geo, local, maps), offer: "Generate a PDF report? Use `/seo google report`"
- **Google logo** appears on title page when using Google API data ("Powered by Google APIs")

## Ecosystem

Part of the Claude Code skill family:
- [Claude Banana](https://github.com/AgriciDaniel/banana-claude) -- standalone image gen (bundled as extension here)
- [Claude Blog](https://github.com/AgriciDaniel/claude-blog) -- companion blog engine, consumes SEO findings
- [AI Marketing Claude](https://github.com/zubair-trabzada/ai-marketing-claude) -- community marketing suite (copy, emails, ads, funnels, CRO)

## Key Principles

1. **Progressive Disclosure**: Metadata always loaded, instructions on activation, resources on demand
2. **Industry Detection**: Auto-detect SaaS, e-commerce, local, publisher, agency
3. **Parallel Execution**: Full audits spawn up to 15 subagents simultaneously
4. **Extension System**: DataForSEO MCP for live data, Firecrawl MCP for site crawling, Banana MCP for AI image generation

## Repository Topology

This repository is ZYRA's maintained fork/distribution, published at
`https://github.com/toolsatZyra/-claude-seo-x-geo`. It is a fork of
`AgriciDaniel/claude-seo` (MIT), grafted with the AEO/GEO modules from
`zubair-trabzada/geo-seo-claude` (MIT) — see [NOTICE.md](NOTICE.md) and
[CONTRIBUTORS.md](CONTRIBUTORS.md) for full attribution.

| Remote | URL | Role |
|---|---|---|
| `origin` | `https://github.com/toolsatZyra/-claude-seo-x-geo` | This fork's published distribution. `main` reflects released/authorized history. |

The dual-remote public/private release workflow that this section
previously described (a `AgriciDaniel/claude-seo` + `AI-Marketing-Hub`
topology) was specific to the upstream project this repo was forked from
and does not apply here — this fork has a single remote. If ZYRA later adds
a private working remote alongside `origin`, document its role and safety
rules here before relying on it.

### Safety rules

- **Never push to `origin/main` autonomously.** Pushes are user-authorized;
  confirm before pushing, especially for anything affecting the default
  branch.
- **History stays shared.** Never rewrite history on `origin` with
  force-push unless explicitly authorized for that specific operation.
- **This is a fork, not the upstream project.** Do not push to
  `AgriciDaniel/claude-seo` or `AI-Marketing-Hub/claude-seo` from this
  checkout — those are the upstream repos this project was forked from,
  not remotes of this repository, and this fork has no authorization to
  publish to them.

## Release Blog Post

The upstream project this repo was forked from has a `/release-blog`
workflow that publishes to `https://claude-seo.md/blog/` — that domain and
workflow belong to the upstream project (`AgriciDaniel/claude-seo`), not
this fork. Do not run `/release-blog` expecting it to publish anywhere on
ZYRA's behalf until it's been reconfigured with ZYRA's own publishing
target, if one is set up.

## Answer Engine Optimization (AEO) - stance override

This build treats AEO/GEO as a FIRST-CLASS, SEPARATELY-SCORED dimension, not a
relabeling of SEO. Audits must surface an AEO score distinct from the SEO score.
The eligibility floor is still normal indexation, but AEO adds citation-structure
signals that classic SEO does not measure.

Scoring weights (grounded in Princeton's 2024 GEO study and 2026 citation data):
- Cited sources / statistics with attribution: strongest positive lift.
- Front-loading: the first ~30% of a page carries a large share of AI citations;
  major sections must open with a direct, self-contained answer.
- Passage self-containment and question-phrased headings: positive.
- Keyword stuffing / AI-specific keyword rewriting: negative or neutral; do not
  recommend.

Determinism: citability is scored by scripts/citability_scorer.py (0-100), not by
free-form judgment. Brand/AI visibility is scored by scripts/brand_scanner.py.
The AEO score itself is computed ONLY by scripts/aeo_score.py (weighted composite:
citability 25, brand authority 20, content E-E-A-T 20, AI crawler access 15,
schema 10, platform readiness 10; missing components renormalized and reported
as completeness). AI share of voice (scripts/ai_visibility.py) is an OUTCOME
metric and is never blended into the AEO readiness score; neither is ever
blended into the SEO Health Score.

llms.txt: audited and optionally generated, reported as forward-looking and
low-confidence, never as a ranking lever. See seo-geo/references/llmstxt-evidence.md
and the aeo.llmstxt_mode flag.

Evidence discipline retained: every AEO recommendation keeps a falsifiability check
(observation it rests on, dependency, "how would we know it failed", leading
indicator), consistent with the rest of this plugin.
