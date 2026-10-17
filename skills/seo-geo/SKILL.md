---
name: seo-geo
description: >
  AEO (Answer Engine Optimization) router and orchestrator. Fans out to the
  first-class geo-* skill cluster (geo-citability, geo-platform-optimizer,
  geo-brand-mentions, geo-crawlers, geo-share-of-voice, geo-compare,
  geo-prospect, geo-proposal), computes the one AEO Readiness Score with
  scripts/aeo_score.py, and carries the reconciled llms.txt policy. AEO is
  scored separately from SEO — never blended into one number.
user-invocable: true
argument-hint: "[url]"
license: MIT
metadata:
  author: AgriciDaniel
  version: "3.1.0"
  category: seo
---

# seo-geo — AEO Router

This skill routes to the first-class `geo-*` skill cluster, defines the one
AEO Readiness Score, and carries the project-wide llms.txt policy. AEO is a
first-class, separately-scored dimension — an audit must never blend an AEO
number into the SEO score.

## Routing table

| Need | Route to |
|---|---|
| AI citability scoring / passage rewrite suggestions | `geo-citability` (backed by `scripts/citability_scorer.py`) |
| Per-platform optimization (Google AIO, ChatGPT, Perplexity, Gemini, Bing Copilot) | `geo-platform-optimizer` (its Platform Readiness Score is the AEO `platform` component) |
| Brand/AI visibility across YouTube, Reddit, Wikipedia, LinkedIn, etc. | `geo-brand-mentions` (backed by `scripts/brand_scanner.py`) |
| AI crawler access audit (answer-surface agents such as OAI-SearchBot, Claude-SearchBot, PerplexityBot, Googlebot, Bingbot; training crawlers such as GPTBot, ClaudeBot, Google-Extended reported separately) | `geo-crawlers` (also cross-linked from `seo-technical`) |
| AI crawler access sub-score (deterministic, robots.txt per RFC 9309, Cloudflare managed-robots detection) | `python3 scripts/aeo_score.py crawlers <url> --json` |
| The AEO Readiness Score (one number, from component scores) | `python3 scripts/aeo_score.py compute ... --json` (see below) |
| AI share of voice: are we actually mentioned and cited in AI answers (outcome, measured) | `geo-share-of-voice` (backed by `scripts/ai_visibility.py`) |
| KPI history and trends for `aeo.*` and `ai.*` metrics | `seo-track` (`scripts/performance_tracker.py`) |
| Month-over-month AEO delta reporting for a client | `geo-compare` (reads `performance_tracker.py export`) |
| Agency prospect/CRM pipeline | `geo-prospect` |
| Client-facing service proposal generation | `geo-proposal` |
| llms.txt audit/generation | this skill, via the policy below |

## The AEO Readiness Score (one definition)

`scripts/aeo_score.py compute` is the only place the AEO number is computed.
Every skill and agent that reports an AEO score (`seo-audit`, `geo-compare`,
`geo-proposal`, `geo-prospect`, `agents/seo-geo.md`, `agents/geo-ai-visibility.md`)
uses it. Components, each 0-100 and measured by its own skill:

| Component | Weight | Measured by |
|---|---|---|
| `citability` | 25 | `scripts/citability_scorer.py` (`geo-citability`) |
| `brand_authority` | 20 | `geo-brand-mentions` Brand Authority Score (part researcher judgment) |
| `content_eeat` | 20 | `seo-content` Content Quality / E-E-A-T score |
| `crawler_access` | 15 | `scripts/aeo_score.py crawlers` |
| `schema` | 10 | `seo-schema` score |
| `platform` | 10 | `geo-platform-optimizer` Platform Readiness Score |

Weights come from zubair-trabzada/geo-seo-claude's composite GEO score (MIT).
A component that was not measured is N/A: excluded from numerator and
denominator, remaining weights renormalized (scoring-rubric Rule 5), and the
output reports `completeness`. The output's `expression` reproduces the score
with `python3 -c "print(<expression>)"` (Rule 4). Report it as
`AEO Score: NN/100 (Rating, completeness 0.xx)` with the component table.
Never estimate a missing component, and compare two AEO scores only when
their `component_set` is identical.

AI share of voice (`geo-share-of-voice`) is the outcome metric. It is
reported next to the AEO Readiness Score and never folded into it.

## llms.txt policy (reconciled, exact — do not alter without re-reading references/llmstxt-evidence.md)

llms.txt is audited for presence and validity, and can be generated on
request via `scripts/llmstxt_generator.py`. It is reported as a
**forward-looking, low-confidence** signal, explicitly **not** a current
ranking or citation lever. No audit score is gained or lost based on its
presence. Rationale and evidence: [[llmstxt-evidence]].

Config flag: `aeo.llmstxt_mode: audit | generate | off`, default `generate`.

- `audit`: call `scripts/llmstxt_generator.py`'s `validate_llmstxt()` only. Never generate.
- `generate` (default): audit, and generate on explicit user request via `generate_llmstxt(url, mode="generate")`.
- `off`: audit only; `generate_llmstxt(url, mode="off")` raises `LlmsTxtGenerationDisabledError` and must not be called.

This flag lives in the user/project's Claude Code settings (or defaults to
`generate` if unset) and must be threaded through by any caller — including
`seo-audit`'s AEO fan-out (see `skills/seo-audit/SKILL.md`).

## AEO scoring weights (Princeton 2024 GEO study + 2026 citation data)

See [[aeo-scoring-weights]] for the full breakdown. These weights shape the
`citability` component; they are directional, not guarantees:
- Statistics, quotations and cited sources: strongest positive lift (statistics ≈+41%, citing sources up to ≈+115% for lower-ranked pages; Aggarwal et al., KDD 2024).
- Front-loading: the first ~30% of a page carries a large share of AI citations (the often-quoted ≈44% figure is unverified, see [[evidence-registry]]).
- Passage self-containment and question-phrased headings: positive.
- Keyword stuffing / AI-specific keyword rewriting: negative or neutral (magnitude unverified); do not recommend.

Determinism: citability is scored by `scripts/citability_scorer.py` (0-100),
not free-form judgment. Brand/AI visibility is scored by
`scripts/brand_scanner.py` plus documented researcher judgment. Crawler
access is scored by `scripts/aeo_score.py crawlers`; blocking training
crawlers and AI-use control tokens (GPTBot, ClaudeBot, Google-Extended,
Applebot-Extended, CCBot) is a licensing choice and never costs points
(Google-Extended also covers grounding in Gemini Apps, which the script notes;
it is not Google Search or AI Overviews eligibility, which Googlebot governs).

## Methodology references

- [[llmstxt-evidence]] — why llms.txt is not currently consumed by major AI systems.
- [[google-ai-optimization-guide]] — Google's own "AEO/GEO is still SEO" position, myth-busting section.
- [[aeo-scoring-weights]] — Princeton citation-lift weights, encoded as constants in `citability_scorer.py`.
- [[sourc-e-framework]] — StudioHawk SOURC-E framework, summarized in our own words (no verbatim copying — license unclear for redistribution).
- [[evidence-registry]] — every precise AEO/GEO statistic used across the `geo-*` cluster, with source, confidence, and retrieval date. Check here before quoting a number to a client, and add a row before introducing a new one.

## Evidence discipline

Every AEO recommendation keeps a falsifiability check: the observation it
rests on, its dependency, "how would we know it failed," and a leading
indicator — consistent with the rest of this plugin's evidence discipline.
