---
name: seo-content
description: >
  Content quality and E-E-A-T analysis with AI citation readiness assessment.
  Use when user says "content quality", "E-E-A-T", "content analysis",
  "readability check", "thin content", or "content audit".
user-invocable: true
argument-hint: "[url]"
license: MIT
metadata:
  author: AgriciDaniel
  version: "3.0.0"
  category: seo
---

# Content Quality & E-E-A-T Analysis

## Google's "Who / How / Why" Test (canonical heuristic)

Before scoring E-E-A-T sub-factors, every page audit should pass Google's
own three-question heuristic from the helpful-content guide:

| Question | What to look for |
|---|---|
| **Who** created it? | Visible byline, author bio page, professional credentials. Required where readers expect it; non-negotiable for YMYL. |
| **How** was it created? | Process disclosure where readers would reasonably ask — especially for AI-assisted content. Original research / first-hand evidence / lived experience. |
| **Why** does it exist? | "To help people" rather than "to attract search clicks." Watch for niche entry without expertise, content churn for freshness signals, content written to a word-count target. |

Primary source:
https://developers.google.com/search/docs/fundamentals/creating-helpful-content

When all three answers are weak, the page is at risk under the core ranking
system's helpfulness signals (formerly the standalone Helpful Content System,
merged into core during the March 2024 update).

## E-E-A-T Framework (updated Sept 2025 QRG)

Read `skills/seo/references/eeat-framework.md` for full criteria.

### Experience (first-hand signals)
- Original research, case studies, before/after results
- Personal anecdotes, process documentation
- Unique data, proprietary insights
- Photos/videos from direct experience

### Expertise
- Author credentials, certifications, bio
- Professional background relevant to topic
- Technical depth appropriate for audience
- Accurate, well-sourced claims

### Authoritativeness
- External citations, backlinks from authoritative sources
- Brand mentions, industry recognition
- Published in recognized outlets
- Cited by other experts

### Trustworthiness
- Contact information, physical address
- Privacy policy, terms of service
- Customer testimonials, reviews
- Date stamps, transparent corrections
- Secure site (HTTPS)

## Content Metrics

### Word Count Analysis
Compare against page type minimums:
| Page Type | Minimum |
|-----------|---------|
| Homepage | 500 |
| Service page | 800 |
| Blog post | 1,500 |
| Product page | 300+ (400+ for complex products) |
| Location page | 500-600 |

> **Important:** These are **topical coverage floors**, not targets. Google has confirmed word count is NOT a direct ranking factor. The goal is comprehensive topical coverage; a 500-word page that thoroughly answers the query will outrank a 2,000-word page that doesn't. Use these as guidelines for adequate coverage depth, not rigid requirements.

### Readability
- Flesch Reading Ease: target 60-70 for general audience

> **Note:** Flesch Reading Ease is a useful proxy for content accessibility but is NOT a direct Google ranking factor. John Mueller has confirmed Google does not use basic readability scores for ranking. Yoast deprioritized Flesch scores in v19.3. Use readability analysis as a content quality indicator, not as an SEO metric to optimize directly.
- Grade level: match target audience
- Sentence length: average 15-20 words
- Paragraph length: 2-4 sentences

### Keyword Optimization
- Primary keyword in title, H1, first 100 words
- Natural density (1-3%)
- Semantic variations present
- No keyword stuffing

### Content Structure
- Logical heading hierarchy (H1 -> H2 -> H3)
- Scannable sections with descriptive headings
- Bullet/numbered lists where appropriate
- Table of contents for long-form content

### Multimedia
- Relevant images with proper alt text
- Videos where appropriate
- Infographics for complex data
- Charts/graphs for statistics

### Internal Linking
- 3-5 relevant internal links per 1000 words
- Descriptive anchor text
- Links to related content
- No orphan pages

### External Linking
- Cite authoritative sources
- Open in new tab for user experience
- Reasonable count (not excessive)

## AI Content Assessment (Sept 2025 QRG addition)

Google's raters now formally assess whether content appears AI-generated.

### Acceptable AI Content
- Demonstrates genuine E-E-A-T
- Provides unique value
- Has human oversight and editing
- Contains original insights

### Low-Quality AI Content Markers
- Generic phrasing, lack of specificity
- No original insight
- Repetitive structure across pages
- No author attribution
- Factual inaccuracies

> **Helpful Content System (March 2024):** The Helpful Content System was merged into Google's core ranking algorithm during the March 2024 core update. It no longer operates as a standalone classifier. Helpfulness signals are now weighted within every core update. The same principles apply (people-first content, demonstrating E-E-A-T, satisfying user intent), but enforcement is continuous rather than through separate HCU updates.

## AI Citation Readiness (GEO signals)

Optimize for AI search engines (ChatGPT, Perplexity, Google AI Overviews):

- Clear, quotable statements with statistics/facts
- Structured data (especially for data points)
- Strong heading hierarchy (H1->H2->H3 flow)
- Answer-first formatting for key questions
- Tables and lists for comparative data
- Clear attribution and source citations

### AI Search Visibility & GEO (2025-2026)

**Google AI Mode** is Google's conversational AI search surface — powered by **Gemini 3.5 Flash** since I/O 2026 (May 2026) and now past **1 billion monthly users** globally. Unlike AI Overviews (which appear above organic results), AI Mode is a fully conversational experience with **zero organic blue links**, making AI citation the only visibility mechanism. It is a *distinct citation engine* from AI Overviews — the two share only ~14% of cited URLs — so optimize for both surfaces, not one (see the `seo-geo` skill).

**Key optimization strategies for AI citation:**
- **Structured answers:** Clear question-answer formats, definition patterns, and step-by-step instructions that AI systems can extract and cite
- **First-party data:** Original research, statistics, case studies, and unique datasets are highly cited by AI systems
- **Schema markup:** Article, FAQPage (Google retired FAQ *rich results* in May 2026, but the markup still aids AI parsing/entity resolution) or QAPage for genuine user Q&A, and structured content schemas help AI systems parse and attribute content
- **Topical authority:** AI systems preferentially cite sources that demonstrate deep expertise. Build content clusters, not isolated pages
- **Entity clarity:** Ensure brand, authors, and key concepts are clearly defined with structured data (Organization, Person schema)
- **Multi-platform tracking:** Monitor visibility across Google AI Overviews, AI Mode, ChatGPT, Perplexity, and Bing Copilot, not just traditional rankings. Treat AI citation as a standalone KPI alongside organic rankings and traffic.

**Generative Engine Optimization (GEO):**
[Google's own position](skills/seo-geo/references/google-ai-optimization-guide.md) is that "AEO" and "GEO" are rebranded labels for SEO — AI Overviews and AI Mode are grounded in the same ranking and quality systems as classic Search. This fork overrides that position: AEO/GEO is treated here as a first-class, separately-scored dimension, not a relabeling of SEO. Google's eligibility floor still applies (pages must be indexed and eligible for snippet display to appear in any AI feature), but this build additionally measures citation-structure signals classic SEO doesn't, via the deterministic `scripts/citability_scorer.py` pass below — reported as a distinct **AEO Citability Score**, never averaged into the Content Quality Score. Cross-reference the `seo-geo` skill for detailed workflows; `skills/seo-geo/references/google-ai-optimization-guide.md` is the primary-source synthesis of the position being overridden/contextualized here, not endorsed as this fork's stance.

## Content Freshness

- Publication date visible
- Last updated date if content has been revised
- Flag content older than 12 months without update for fast-changing topics

## Citability pass (AEO)

Every content audit run through this skill also runs a deterministic
citability pass via `scripts/citability_scorer.py::analyze_page_citability(url)`.
This returns a 0-100 score per content block plus a page-level average — it
is not free-form judgment. Report this as a distinct **AEO citability score**
(surfaced in Output below as "AEO Citability Score"), never averaged into
this skill's SEO/content-quality score. This scorer is the mechanical backend
for the qualitative "AI Citation Readiness (GEO signals)" guidance above —
that section explains *what* to look for; this pass is *how it gets scored*.

### Front-loading check (mandatory, not just guidance)

Per [[aeo-scoring-weights]], approximately 44% of AI citations come from the
first 30% of a page. This skill's content check must explicitly verify:

1. Does each major H2/H3 section open with a direct, self-contained answer
   in its first 1-3 sentences (not a lead-in, not a rhetorical question)?
2. Is the single most important fact/answer on the page located within the
   first 30% of total word count?

If either check fails, flag it as a specific, actionable finding — "Section
X buries its answer after 400 words of preamble" — not a vague "improve
readability" note.

### What this pass does NOT recommend

Per the evidence in `skills/seo-geo/references/google-ai-optimization-guide.md`
and this plugin's AEO stance (see root `CLAUDE.md`), do not recommend:
keyword stuffing, AI-specific keyword rewriting/long-tail variant stuffing,
or content "chunking" purely for AI parsing. These are neutral-to-negative
per the Princeton weights in [[aeo-scoring-weights]].

## Scoring

Compute the Content Quality Score using the fixed-criteria method in
`skills/seo/references/scoring-rubric.md`: 7 named criteria, each with its
own point allocation, scored on the 6-tier scale, **with cited evidence
per criterion** — state what you found, or "No evidence found," never an
assumption. Do not add, drop, or reweight criteria at scoring time, and do
not double-count: criterion 5 below (Who/How/Why + AI-content quality) is
the *single* place low-quality-AI-content and missing-authorship evidence
gets scored — a live test run previously double-counted the same "no
author byline" gap under two separately-worded checks, producing a 15-point
swing between two audits of the same page. If you find yourself docking
points under more than one criterion for the same missing piece of
evidence, stop and consolidate it into criterion 5 only.

### Content Quality criteria (sum to 100)

| # | Criterion | Points | What "Excellent" (100%) looks like |
|---|---|---|---|
| 1 | Experience (E-E-A-T) | 20 | Original research/case studies/before-after results; personal anecdotes/process documentation; unique data/proprietary insights; photos/videos from direct experience — rate each of these 4 signals present/absent, tier by fraction present |
| 2 | Expertise (E-E-A-T) | 20 | Author credentials/certifications/bio; professional background relevant to topic; technical depth appropriate for audience; accurate, well-sourced claims — 4 signals, tier by fraction present |
| 3 | Authoritativeness (E-E-A-T) | 15 | External citations/backlinks from authoritative sources; brand mentions/industry recognition; published in recognized outlets; cited by other experts — 4 signals, tier by fraction present |
| 4 | Trustworthiness (E-E-A-T) | 15 | Contact info/physical address; privacy policy/terms of service; testimonials/reviews; date stamps/transparent corrections; secure HTTPS — 5 signals, tier by fraction present |
| 5 | Who/How/Why helpfulness + AI-content quality (single combined criterion — see note above) | 15 | Visible byline/author bio; process disclosure where readers would expect it; content exists "to help" not just to attract clicks; no generic/repetitive AI-typical phrasing; no factual inaccuracies |
| 6 | Content depth vs. page-type floor | 10 | Word count at/above the floor in the Word Count Analysis table above (topical-coverage floor, not a target) |
| 7 | Freshness | 5 | Publication date visible; last-updated date visible if revised; not stale (>12 months, no update) on a fast-moving topic |

`Content Quality Score = sum(criterion_score across all 7 rows)`.

Front-loading/citability checks are AEO signals, not SEO content-quality
signals — they belong only in the AEO Citability Score below, never in
these 7 criteria (this mirrors the "never blend" rule already stated for
that pass).

## Output

### Content Quality Score: XX/100
State each criterion's tier and cited evidence. Per scoring-rubric.md
Rule 4, compute the sum with an actual tool call (e.g.
`python3 -c "print(...)"`) using the 7 real numbers and show that
expression — do not add them in prose.

### Criteria Breakdown
| Criterion | Points possible | Points earned | Tier |
|---|---|---|---|
| Experience | 20 | XX | ... |
| Expertise | 20 | XX | ... |
| Authoritativeness | 15 | XX | ... |
| Trustworthiness | 15 | XX | ... |
| Who/How/Why + AI-content quality | 15 | XX | ... |
| Content depth | 10 | XX | ... |
| Freshness | 5 | XX | ... |

### AEO Citability Score: XX/100
Per-block scores plus page-level average from `analyze_page_citability(url)`.
Reported separately from — never averaged into — the Content Quality Score above.

### Issues Found
### Recommendations

## DataForSEO Integration (Optional)

If DataForSEO MCP tools are available, use `kw_data_google_ads_search_volume` for real keyword volume data, `dataforseo_labs_bulk_keyword_difficulty` for difficulty scores, `dataforseo_labs_search_intent` for intent classification, and `content_analysis_summary` for content quality analysis.

## Error Handling

| Scenario | Action |
|----------|--------|
| URL unreachable (DNS failure, connection refused) | Report the error clearly. Do not guess page content. Suggest the user verify the URL and try again. |
| Content behind paywall (402/403, login wall) | Report that the content is not publicly accessible. Analyze only the visible portion (meta tags, headers) and note the limitation. |
| Thin content (fewer than 100 words retrievable) | Report the findings as-is rather than guessing. Flag the page as potentially JavaScript-rendered or gated, and suggest the user provide the full text directly. |

## FLOW Framework Integration

For prompt-guided content optimization, use `/seo flow optimize <url>` and `/seo flow win <url>` — FLOW's optimize and win prompts provide structured E-E-A-T improvement and BOFU conversion workflows.
