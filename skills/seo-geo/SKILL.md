---
name: seo-geo
description: >
  AEO (Answer Engine Optimization) router and orchestrator. Fans out to the
  first-class geo-* skill cluster (geo-citability, geo-platform-optimizer,
  geo-brand-mentions, geo-crawlers, geo-compare, geo-prospect, geo-proposal)
  and carries the reconciled llms.txt policy. AEO is scored separately from
  SEO — never blended into one number.
user-invocable: true
argument-hint: "[url]"
license: MIT
metadata:
  author: AgriciDaniel
  version: "2.2.0"
  category: seo
---

# seo-geo — AEO Router

This skill no longer scores AEO itself. It routes to the first-class `geo-*`
skill cluster and carries the project-wide llms.txt policy. AEO is a
first-class, separately-scored dimension — an audit must never blend an AEO
number into the SEO score.

## Routing table

| Need | Route to |
|---|---|
| AI citability scoring / passage rewrite suggestions | `geo-citability` (backed by `scripts/citability_scorer.py`) |
| Per-platform optimization (Google AIO, ChatGPT, Perplexity, Gemini, Bing Copilot) | `geo-platform-optimizer` |
| Brand/AI visibility across YouTube, Reddit, Wikipedia, LinkedIn, etc. | `geo-brand-mentions` (backed by `scripts/brand_scanner.py`) |
| AI crawler access audit (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, Bingbot/Copilot) | `geo-crawlers` (also cross-linked from `seo-technical`) |
| Month-over-month AEO delta tracking | `geo-compare` |
| Agency prospect/CRM pipeline | `geo-prospect` |
| Client-facing service proposal generation | `geo-proposal` |
| llms.txt audit/generation | this skill, via the policy below |

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

See [[aeo-scoring-weights]] for the full breakdown. Directional weights, not
guarantees:
- Cited sources / statistics with attribution: strongest positive lift (≈+40% / ≈+37%).
- Front-loading: ≈44% of AI citations come from the first 30% of a page.
- Passage self-containment and question-phrased headings: positive.
- Keyword stuffing / AI-specific keyword rewriting: negative or neutral (≈-10%); do not recommend.

Determinism: citability is scored by `scripts/citability_scorer.py` (0-100),
not free-form judgment. Brand/AI visibility is scored by
`scripts/brand_scanner.py`.

## Methodology references

- [[llmstxt-evidence]] — why llms.txt is not currently consumed by major AI systems.
- [[google-ai-optimization-guide]] — Google's own "AEO/GEO is still SEO" position, myth-busting section.
- [[aeo-scoring-weights]] — Princeton citation-lift weights, encoded as constants in `citability_scorer.py`.
- [[sourc-e-framework]] — StudioHawk SOURC-E framework, summarized in our own words (no verbatim copying — license unclear for redistribution).

## Evidence discipline

Every AEO recommendation keeps a falsifiability check: the observation it
rests on, its dependency, "how would we know it failed," and a leading
indicator — consistent with the rest of this plugin's evidence discipline.
