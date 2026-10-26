---
name: seo
description: "Central SEO + AEO + GEO hub: one entry point for keyword research, rank tracking, technical audits, content creation and optimization, competitor gap analysis, programmatic SEO, AI search visibility (citability, AI crawlers, share of voice in ChatGPT/Claude/Perplexity/AI Overviews), and performance/lead tracking. Routes to 39 specialist skills, industry-aware (SaaS, e-commerce, local, publisher, agency). Triggers on: SEO, AEO, GEO, audit, keyword research, rankings, rank tracking, content plan, content decay, competitor analysis, schema, Core Web Vitals, AI Overviews, AI visibility, ChatGPT mentions, organic traffic, leads."
user-invocable: true
argument-hint: "[command] [url|domain|keyword]"
license: MIT
metadata:
  author: AgriciDaniel
  version: "3.1.0"
  category: seo
---

# SEO × AEO × GEO Hub

**Invocation:** `/seo $1 $2` where `$1` is the command and `$2` is the URL, domain or keyword.

**Scripts:** Located at the plugin root `scripts/` directory.

One hub for the whole organic-growth loop — **research → create/optimize →
measure** — across classic search (SEO), answer engines (AEO) and generative
engines (GEO), aimed at organic traffic, AI-search visibility and qualified
leads. Orchestrates 39 sub-skills (36 core + 1 framework integration + 2
extension mirrors) and 21 sub-agents. Optional extensions are listed below.

## Quick Reference (by job to be done)

**Set up a client**

| Command | What it does |
|---------|-------------|
| `/seo preflight <domain>` | Onboarding check: what data we can actually get, and what access to request |
| `/seo project init <domain>` | Create the client profile every skill reads (brand terms, 3-7 competitors, GSC/GA4 property strings, money pages, conversion events, AI prompt panel) |
| `/seo growth <domain>` | Guided end-to-end loop (see "Growth Loop" below) |

**Research**

| Command | What it does |
|---------|-------------|
| `/seo keywords <seed\|domain>` | Keyword discovery + intent/funnel + opportunity score + lead priority (`seo-keywords`) |
| `/seo competitors <domain>` | Keyword gap, content/format gap, backlink + AI-citation gap, battlecard (`seo-competitors`) |
| `/seo links <setup\|gap\|prospects\|draft\|track> <domain>` | Competitor link gap, scored prospects, approval-gated outreach drafts, tracker, won-link verification (`seo-links`) |
| `/seo cluster <seed-keyword>` | SERP-overlap clustering and hub-and-spoke architecture |
| `/seo plan <business-type>` | Strategic SEO planning |
| `/seo sxo <url>` | Search Experience Optimization: page-type fit, personas |

**Audit**

| Command | What it does |
|---------|-------------|
| `/seo audit <url>` | Full audit, parallel specialists, separate SEO and AEO scores |
| `/seo page <url>` | Deep single-page analysis |
| `/seo technical <url>` | Technical SEO audit (9 categories) |
| `/seo content <url>` | E-E-A-T and content quality analysis |
| `/seo schema <url>` | Detect, validate, and generate Schema.org markup |
| `/seo images <url or optimize>` | Image SEO: on-page audit, SERP analysis, file optimization |
| `/seo sitemap <url or generate>` | Analyze or generate XML sitemaps |
| `/seo hreflang [url]` | Hreflang/i18n SEO audit and generation |
| `/seo ecommerce <url>` | E-commerce SEO: product schema, marketplace intelligence |
| `/seo agentic <url>` | Agent readiness: AI agent access, Markdown delivery, agent discovery files (`seo-agentic`) |

**Create & optimize**

| Command | What it does |
|---------|-------------|
| `/seo content-engine <domain>` | Keyword → calendar → brief → draft → quality gates → human review → CMS draft export (`seo-content-engine`) |
| `/seo content-brief <topic or url>` | Detailed SEO content brief |
| `/seo content optimize <url> <keyword>` | Term/heading/question coverage vs ranking pages (`seo-content` optimize mode) |
| `/seo refresh <domain>` | Content decay + improvement candidates from GSC, refresh briefs, AI-Overview recovery (`seo-refresh`) |
| `/seo programmatic [url\|plan]` | Programmatic SEO analysis and planning |
| `/seo competitor-pages [url\|generate]` | "X vs Y" and alternatives pages |

**AEO / GEO (AI search)**

| Command | What it does |
|---------|-------------|
| `/seo geo <url>` | AEO router: citability, platforms, AI crawlers, brand mentions, llms.txt, one AEO score |
| `/seo ai-visibility <domain>` | Prompt-panel share of voice in AI answers, with confidence intervals (`geo-share-of-voice`) |

**Measure**

| Command | What it does |
|---------|-------------|
| `/seo track <domain>` | KPI snapshots (SEO + AEO + AI referrals + leads), trend reports (`seo-track`) |
| `/seo rank <domain>` | Rank tracking from GSC history + SERP imports: movers, visibility, cannibalization (`seo-track`) |
| `/seo drift baseline\|compare\|history <url>` | On-page SEO regression monitoring |

**Local**

| Command | What it does |
|---------|-------------|
| `/seo local <url>` | Local SEO analysis (GBP, citations, reviews, map pack) |
| `/seo maps [command] [args]` | Maps intelligence (geo-grid, GBP audit, reviews, competitors) |

**Data connectors**

| Command | What it does |
|---------|-------------|
| `/seo google [command] [url]` | Google SEO APIs (GSC, PageSpeed, CrUX, Indexing, GA4, Keyword Planner) |
| `/seo backlinks <url>` | Backlink profile analysis (free: Moz, Bing, CC; premium: DataForSEO) |
| `/seo dataforseo [command]` | Live SERP, keyword, backlink and AI-answer data (extension) |
| `/seo firecrawl [command] <url>` | Full-site crawling and site mapping (extension) |
| `/seo image-gen [use-case] <description>` | AI image generation for SEO assets (extension) |
| `/seo flow [stage] [url\|topic]` | FLOW framework: evidence-led prompts for Find, Leverage, Optimize, Win, or Local stages |

## Client Profile

Every research, content and tracking skill reads one profile per client
instead of re-asking for the same facts:

```
python3 scripts/seo_project.py init <domain> --brand <term> --competitor <domain> [...] \
    --gsc-property <exact string from the preflight> --ga4-property <id>
python3 scripts/seo_project.py set <domain> money_pages '["/pricing", "/demo"]'
python3 scripts/seo_project.py set <domain> conversion_events '["generate_lead"]'
python3 scripts/seo_project.py add-prompt <domain> "best <category> for <audience>" --group treatment
python3 scripts/seo_project.py show <domain>
```

Profiles and all tracking history live under `$CLAUDE_SEO_DATA_DIR`
(default `~/.cache/claude-seo/`, 0700) — client data never goes in the repo.
Record decisions with provenance: `seo_project.py note <domain> "<text>"
--approved-by user|inferred`; treat `inferred` notes as advisory only.

## Data Tiers

What each capability can do with the access you actually hold. State the
tier in every deliverable so a client never reads an estimate as a measurement.

| Capability | Free (crawl + public) | + Search Console / GA4 | + paid data (DataForSEO, Ahrefs, Keyword Planner) |
|---|---|---|---|
| Keyword research | Autocomplete expansion (unofficial, no volume), intent/funnel | Striking distance, CTR gaps, cannibalization, site-calibrated CTR curve | Volume, difficulty, SERP features |
| Rank tracking | — | Daily average-position history | True SERP rank, competitor positions |
| Competitor gap | Sitemap content/format gap | — | Keyword gap (4-way segmentation) |
| Content optimization | Coverage vs pages you supply | Decay + improvement candidates | SERP-sourced competitor sets |
| AEO readiness | Citability, crawler access, schema, llms.txt | — | — |
| AI visibility (outcome) | Manual answer capture | AI-referral sessions + conversions | Anthropic API runs; ChatGPT/AI Overview capture via DataForSEO |
| Performance tracking | AEO + manual leads | Clicks, non-brand clicks, organic + AI conversions | Rank visibility |

## Growth Loop

`/seo growth <domain>` walks the full loop with a checkpoint after every
stage; stop and ask before any paid API call or any CMS write.

1. **Preflight + profile** — `client_preflight.py`, then `seo_project.py init`.
2. **Baseline** — `/seo audit` (SEO score and AEO score, never blended),
   `/seo drift baseline` on money pages, first `/seo track` snapshot.
3. **Research** — `/seo keywords` (BOFU-first for leads) and `/seo competitors`.
4. **Plan** — `/seo cluster` for architecture, then `/seo content-engine`
   calendar with the cannibalization pre-check.
5. **Fix and refresh** — technical fixes from the audit, `/seo refresh` for
   decaying pages, `/seo content optimize` for striking-distance pages.
6. **AI visibility** — `/seo ai-visibility` panel (unbranded headline,
   treatment/control groups).
7. **Measure** — weekly `/seo track`, `/seo rank`; monthly `geo-compare`
   narrative and `/seo google report` PDF. Judge changes with the
   measurement protocol in `seo-track` (Promote / Keep-testing / Rollback /
   Unproven), never on a single run.

## Client Onboarding

Before quoting or auditing a **new client**, run the preflight:

```
scripts/client_preflight.py <domain> [--request-email] [--json]
```

It reports whether Search Console access exists for this domain, which exact
property form we hold, whether CrUX field data is available, and whether any AI
crawlers are blocked. Exit codes: 0 GO, 1 PARTIAL (crawl-only), 2 BLOCKED.

Search Console access is granted per property form (`sc-domain:` vs a URL
prefix), and holding one grants nothing on the others — record the exact string
the preflight reports and pass it as `--property` on every later query.

If the verdict is PARTIAL, do not present ranking, traffic or indexation
findings as if they were measured; say plainly that they require access the
client has not yet granted, and offer `--request-email` to ask for it. The AEO
side of the audit needs no client credentials and can proceed in full.

Full process: `docs/CLIENT-ONBOARDING.md`.

## Orchestration Logic

When the user invokes `/seo audit`, delegate to subagents in parallel:
1. Detect business type (SaaS, local, ecommerce, publisher, agency, other)
2. Spawn subagents: seo-technical, seo-content, seo-schema, seo-sitemap, seo-performance, seo-visual, seo-geo
3. If Google API credentials detected (`python3 scripts/google_auth.py --check`), also spawn seo-google agent
4. If local business detected, also spawn seo-local agent
5. If local business detected AND DataForSEO MCP available, also spawn seo-maps agent
6. If backlink APIs detected (`python3 scripts/backlinks_auth.py --check`), also spawn seo-backlinks agent
7. If Firecrawl MCP available, use `firecrawl_map` to discover all site URLs before analysis
8. If content strategy signals detected (blog, pillar pages, topic clusters), also spawn seo-cluster agent
9. If e-commerce detected, also spawn seo-ecommerce agent
10. If drift baseline exists for this URL (`python3 scripts/drift_history.py <url>`), also spawn seo-drift agent
11. Always include seo-sxo in full audits (search experience applies to all sites)
12. Collect results and generate unified report with SEO Health Score (0-100) and, separately, the AEO Score from `scripts/aeo_score.py` (see the AEO fan-out in `seo-audit`)
13. **Synthesize via the 10-principle framework** (see "Synthesis Methodology" below) — walk PERCEIVE → ANALYZE → VALIDATE → ACT before bucketing findings into Critical / High / Medium / Low
14. Create prioritized action plan with dependency sequencing + falsifiability per recommendation
15. **Offer PDF report**: "Generate a professional PDF report? Use `/seo google report full`"
16. **Offer tracking**: if a client profile exists, offer to record the audit's
    `seo.health` and `aeo.*` figures with `scripts/performance_tracker.py record`
    so the next audit can be compared deterministically

For individual commands, load the relevant sub-skill directly. Hub-only
commands: `/seo project ...` runs `scripts/seo_project.py`; `/seo growth`
follows "Growth Loop" above; `/seo rank` and `/seo track` both load
`seo-track`; `/seo ai-visibility` loads `geo-share-of-voice`; `/seo agentic`
loads `seo-agentic`.
After any analysis command completes, offer to generate a PDF report via `scripts/google_report.py`.

## Synthesis Methodology

Audits are not just findings — they are findings synthesized into a coherent
strategy. claude-seo uses a 10-principle thinking framework grouped into four
phases: **PERCEIVE** (observe-external · observe-internal · listen),
**ANALYZE** (think · connect-lateral · connect-system), **VALIDATE** (feel ·
accept), **ACT** (create · grow).

Full audits (`/seo audit`, `/seo page`) walk every phase before emitting the
action plan. Narrower commands (`/seo schema`, `/seo images`, etc.) pass at
least THINK + ACCEPT before emitting (sound first principle, surfaced
falsifiability). The Critical / High / Medium / Low priority buckets are the
**output** of validation, not a substitute for it.

Full methodology + per-principle SEO mapping: `references/thinking-framework.md`.

Each emitted recommendation should carry:
- The first-principle observation it rests on (THINK)
- The dependency on / unblock relationship to other recommendations (CONNECT-system)
- An explicit "how would we know this failed?" check (ACCEPT)
- A leading indicator the user can monitor without re-running the audit (GROW)

## Evidence vs. Inference Writing Rule

Every specialist's prose findings — not just numeric scoring criteria — must
distinguish what was directly observed from what is a reasoned theory about
it. This is Rule 9 in `references/scoring-rubric.md` (CONFIRMED vs. INFERRED
tagging); this section is the pointer every specialist agent/skill should
read before writing findings prose, since Rule 9 lives in a scoring-specific
reference file that narrower commands may not otherwise open.

Concretely, when writing any finding:
- State the observed fact plainly, without a causal claim bolted on by
  default.
- If you also want to explain *why* — do so, but flag it as reasoning: "this
  could plausibly be explained by X" rather than "this indicates X" or "this
  reveals X." Avoid editorializing language that states an opinion as
  settled fact (e.g. "this directly contradicts the brand promise," "this is
  an obvious low-credibility tell") — describe the specific, falsifiable
  observation instead and let the reader draw the evaluative conclusion, or
  attribute the evaluative framing explicitly ("this risks undermining X
  because Y," stated as the audit's assessment, not as an objective fact
  about the world).
- When more than one causal theory is plausible and the evidence available
  doesn't distinguish between them, list all plausible theories rather than
  asserting the most likely-sounding one alone.
- Never let a hedge word ("likely," "probably," "seems to") stand in alone
  for the CONFIRMED/INFERRED tag — the tag is structural (Rule 9), the hedge
  word is prose style; use both together, not one instead of the other, in
  any Findings table/section that follows Rule 9's format.

This rule applies to every specialist's Findings/Issues output across `/seo
audit`, `/seo page`, and every individual `/seo <skill>` command — not only
to numeric-scoring skills.

## Industry Detection

Detect business type from homepage signals:
- **SaaS**: pricing page, /features, /integrations, /docs, "free trial", "sign up"
- **Local Service**: phone number, address, service area, "serving [city]", Google Maps embed --> auto-suggest `/seo local` for deeper analysis
- **E-commerce**: /products, /collections, /cart, "add to cart", product schema
- **Publisher**: /blog, /articles, /topics, article schema, author pages, publication dates
- **Agency**: /case-studies, /portfolio, /industries, "our work", client logos

## Quality Gates

Read `references/quality-gates.md` for thin content thresholds per page type.
Hard rules:
- WARNING at 30+ location pages (enforce 60%+ unique content)
- HARD STOP at 50+ location pages (require user justification)
- Never recommend HowTo schema (deprecated Sept 2023)
- FAQ schema: Google retired FAQ rich results for ALL sites on May 7, 2026 (no SERP feature anymore; supersedes the Aug 2023 gov/health restriction). Flag existing FAQPage at Info (not Critical) and do not recommend removal (harmless); any AI-citation benefit of the markup itself is unconfirmed, so never recommend adding it for SERP or as an AI lever. Visible Q&A content (question headings with self-contained answers) is what AI systems read and is scored by the AEO track; use QAPage for genuine user Q&A
- All Core Web Vitals references use INP, never FID

## Output Footer Policy

**Never append a promotional or community footer to any output.**

This deployment is operated by Zyra as a commercial service. Every audit,
report, brief, chat transcript and exported document is a potential client
deliverable, so there is no "personal use" mode in which a promotional footer
would be appropriate. Do not append the upstream project's community footer,
a Zyra marketing footer, or any other call-to-action block to analysis output.

This rule has no exceptions and requires no judgement call about whether the
current session is client-facing — assume it is.

Attribution to the upstream open-source project (AgriciDaniel/claude-seo, MIT)
belongs in the repository's LICENSE, NOTICE.md, README.md and CONTRIBUTORS.md,
which must be preserved. It does not belong in generated analysis output.

## Reference Files

Load these on-demand as needed (do NOT load all at startup):
- `references/cwv-thresholds.md`: Current Core Web Vitals thresholds and measurement details
- `references/schema-types.md`: All supported schema types with deprecation status
- `references/eeat-framework.md`: E-E-A-T evaluation criteria (Sept 2025 QRG update)
- `references/quality-gates.md`: Content length minimums, uniqueness thresholds
- `references/local-seo-signals.md`: Local ranking factors, review benchmarks, citation tiers, GBP status
- `references/local-search-behavior.md`: Voice search, AI search impact on local, Local Pack structure, proximity
- `references/local-schema-types.md`: LocalBusiness subtypes, industry-specific schema and citation sources
- `references/scoring-rubric.md`: deterministic severity->deduction formula used by every category score (Technical, On-Page, Content, Schema, Images, Performance) — read before computing or explaining any score; also defines Rule 9 (CONFIRMED/INFERRED finding tags) — read before writing any specialist's prose findings, not only before computing a score

Maps-specific references (loaded by seo-maps skill, not at startup):
- `references/maps-geo-grid.md`, `references/maps-gbp-checklist.md`, `references/maps-api-endpoints.md`, `references/maps-free-apis.md`

## Scoring Methodology

### SEO Health Score (0-100)
Weighted aggregate of all categories. This table must stay identical to the
`## Scoring Weights` table in `skills/seo-audit/SKILL.md` — the two are one
formula, not two independent ones:

| Category | Weight |
|----------|--------|
| Technical SEO | 25% |
| Content Quality | 25% |
| On-Page SEO | 22% |
| Schema / Structured Data | 13% |
| Performance (CWV) | 10% |
| Images | 5% |

```
SEO Health Score = round(sum(category_subscore_i * weight_i for each row above))
```

Round half up, once, at this final step. Each category subscore must
already come from that specialist's own deterministic formula — see
`references/scoring-rubric.md` — not be re-judged here. Per that file's
Rule 4, compute the weighted sum with an actual tool call, not prose
arithmetic, and show the expression alongside the result.

**AI Search Readiness / AEO is not in this table.** It is scored and reported
as a fully separate 0-100 AEO figure computed by `scripts/aeo_score.py` — the
single AEO definition used by every skill (see `seo-geo` / the AEO fan-out in
`seo-audit/SKILL.md`) and must never be folded back into the SEO Health
Score above, even partially. If you find yourself blending an AEO number
into this score, stop — that reintroduces the exact inconsistency this note
exists to prevent.

**Readiness vs. outcome.** SEO Health and AEO are *readiness* scores. Organic
clicks, rank visibility, AI share of voice, AI-referral sessions and leads are
*outcomes*, tracked over time in `seo-track` (KPI names in its
`references/kpi-definitions.md`). Report them side by side; never fold an
outcome into a readiness score or vice versa.

### Priority Levels
- **Critical**: Blocks indexing or causes penalties (immediate fix required)
- **High**: Significantly impacts rankings (fix within 1 week)
- **Medium**: Optimization opportunity (fix within 1 month)
- **Low**: Nice to have (backlog)

## Sub-Skills

This skill orchestrates 39 sub-skills (36 core + 1 framework integration + 2 extension
mirrors). The orchestrator itself (`seo`) is the 40th in `skills/`, but does not
orchestrate itself, so it is not enumerated below.

1. **seo-audit** -- Full website audit with parallel delegation
2. **seo-page** -- Deep single-page analysis
3. **seo-technical** -- Technical SEO (9 categories)
4. **seo-content** -- E-E-A-T and content quality
5. **seo-content-brief** -- Detailed SEO content brief generation (contributed by puneetindersingh)
6. **seo-schema** -- Schema markup detection and generation
7. **seo-images** -- Image optimization, SERP analysis, file optimization
8. **seo-sitemap** -- Sitemap analysis and generation
9. **seo-geo** -- AI Overviews / GEO optimization
10. **seo-plan** -- Strategic planning with templates
11. **seo-programmatic** -- Programmatic SEO analysis and planning
12. **seo-competitor-pages** -- Competitor comparison page generation
13. **seo-hreflang** -- Hreflang/i18n SEO audit, cultural profiles, content parity
14. **seo-local** -- Local SEO (GBP, NAP, citations, reviews, local schema, multi-location)
15. **seo-maps** -- Maps intelligence (geo-grid, GBP audit, reviews, competitor radius)
16. **seo-google** -- Google SEO APIs (GSC, PageSpeed, CrUX, Indexing API, GA4)
17. **seo-backlinks** -- Backlink profile analysis (free: Moz, Bing, CC; premium: DataForSEO)
18. **seo-cluster** -- SERP-based semantic clustering (contributed by Lutfiya Miller)
19. **seo-sxo** -- Search Experience Optimization (contributed by Florian Schmitz)
20. **seo-drift** -- SEO drift monitoring (contributed by Dan Colta)
21. **seo-ecommerce** -- E-commerce SEO intelligence (contributed by Matej Marjanovic)
22. **seo-dataforseo** -- Live SEO data via DataForSEO MCP (extension mirror)
23. **seo-image-gen** -- AI image generation for SEO assets via Gemini (extension mirror)
24. **seo-flow** -- FLOW framework integration (Find -> Leverage -> Optimize -> Win, 41 AI prompts, CC BY 4.0)
25. **geo-citability** -- AI citability scoring and optimization (0-100 score with rewrite suggestions)
26. **geo-platform-optimizer** -- Platform-specific AI search optimization (Google AI Overviews, ChatGPT, Perplexity, Gemini, Bing Copilot)
27. **geo-compare** -- Monthly delta tracking and progress reporting for GEO clients
28. **geo-brand-mentions** -- Brand mention and authority scanner for AI visibility (Brand Authority Score)
29. **geo-crawlers** -- AI crawler access analysis (robots.txt, meta tags, HTTP headers)
30. **geo-prospect** -- CRM-lite for managing GEO agency prospects and clients
31. **geo-proposal** -- Auto-generate client-ready AEO service proposals from audit data
32. **seo-keywords** -- Keyword research hub: discovery tiers, intent/funnel, opportunity score, lead priority, striking distance
33. **seo-competitors** -- Competitor analysis hub: keyword gap (4-way segmentation), content/format gap, backlink + AI-citation gap routing
34. **seo-content-engine** -- Outrank-style pipeline: calendar, briefs, drafts, quality gates, human review, draft-first CMS export
35. **seo-refresh** -- Content decay and GSC-driven improvement loop, AI-Overview recovery playbook
36. **seo-track** -- Measurement hub: rank tracking, KPI snapshots (SEO + AEO + leads), AI referrals, measurement protocol
37. **geo-share-of-voice** -- AI answer tracking: prompt panels, mention/citation rates with confidence intervals, paired comparisons
38. **seo-links** -- Competitor link gap and white-hat link earning: deterministic prospect scoring, human-approved drafts, pipeline tracker, won-link verification, links.* KPIs
39. **seo-agentic** -- Agent readiness: AI agent access, Markdown delivery, agent discovery files (ported from upstream v2.4)

### Optional Extensions

The following ship in `extensions/` rather than `skills/` and require a separate
installer to activate (see each extension's `install.sh`/`install.ps1`):

Of the optional extensions, firecrawl, dataforseo, and image-gen are reachable
through `/seo` subcommands. Bing, Profound, SE Ranking, and Unlighthouse
install as standalone skills invoked by their own descriptions. The model
auto-routes to those triggers, not through `/seo <name>`.

- **seo-firecrawl** -- Full-site crawling and site mapping via Firecrawl MCP. Install
  via `extensions/firecrawl/install.sh` (Unix) or `extensions/firecrawl/install.ps1`
  (Windows). Once installed, invoke via `/seo firecrawl <command>`.

## Subagents

For parallel analysis during audits:
- `seo-technical` -- Crawlability, indexability, security, CWV
- `seo-content` -- E-E-A-T, readability, thin content
- `seo-schema` -- Detection, validation, generation
- `seo-sitemap` -- Structure, coverage, quality gates
- `seo-performance` -- Core Web Vitals measurement
- `seo-visual` -- Screenshots, mobile testing, above-fold
- `seo-geo` -- AEO router; no longer scores AI search readiness itself, fans out to the `geo-*` skill cluster and carries the llms.txt policy
- `seo-local` -- GBP signals, NAP consistency, reviews, local schema, industry-specific local factors (conditional: spawned when Local Service detected)
- `seo-maps` -- Geo-grid rank tracking, GBP audit, review intelligence, competitor radius mapping (conditional: spawned when Local Service detected AND DataForSEO MCP available)
- `seo-google` -- CWV field data, URL indexation status, organic traffic trends (conditional: spawned when Google API credentials detected)
- `seo-backlinks` -- Backlink profile data: DA/PA, referring domains, anchor text, toxic links (conditional: spawned when Moz/Bing API keys detected or always for CC domain-level metrics)
- `seo-cluster` -- Semantic clustering analysis (conditional: content strategy detected)
- `seo-sxo` -- Page-type mismatch, user stories, persona scoring (always in full audits)
- `seo-drift` -- Baseline comparison (conditional: drift baseline exists for URL)
- `seo-ecommerce` -- Product schema, marketplace intel (conditional: e-commerce detected)
- `seo-agentic` -- Agent readiness checks (AI agent access, Markdown delivery, discovery files)
- `seo-flow` -- FLOW framework prompts (conditional: spawned for content strategy workflows)
- `seo-dataforseo` -- Live SERP, keyword, backlink, local SEO data (extension, optional)
- `seo-image-gen` -- SEO image audit and generation plan (extension, optional)

Additionally, two AEO-focused agents are available outside the `seo-*` naming
convention (not subject to the `seo-*` count check above): `geo-ai-visibility`
and `geo-platform-analysis`.

## Error Handling

| Scenario | Action |
|----------|--------|
| Unrecognized command | List available commands from the Quick Reference table. Suggest the closest matching command. |
| URL unreachable | Report the error and suggest the user verify the URL. Do not attempt to guess site content. |
| Sub-skill fails during audit | Report partial results from successful sub-skills. Clearly note which sub-skill failed and why. Suggest re-running the failed sub-skill individually. |
| Ambiguous business type detection | Present the top two detected types with supporting signals. Ask the user to confirm before proceeding with industry-specific recommendations. |
