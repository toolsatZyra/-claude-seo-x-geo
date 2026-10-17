# AI share-of-voice metrics, statistics and verdicts

Definitions used by `scripts/ai_visibility.py`. Every number is computed from
stored raw answers, so it can be recomputed if a definition changes.

## Units

- **Answer**: one engine response to one prompt run. Status `ok`, `refused`
  or `error`; only `ok` answers are valid for metrics. Refusals and errors
  are counted and reported, never treated as "not mentioned".
- **Engine/surface**: e.g. `anthropic/api`, `chatgpt/ui`. Metrics are always
  computed within one engine/surface. API and UI answers are never pooled.
- **Mention**: a whole-word, case- and accent-folded (Unicode NFKD) match of
  any of the brand's terms in the answer text. Client terms: profile brand
  terms, the domain label, the profile name and the domain. Competitor terms:
  name, domain label, domain and aliases. A citation alone is not a mention.

## Metrics

| Metric | Definition |
|---|---|
| Mention rate | answers mentioning the client / valid answers |
| 95% CI | Wilson score interval (`seo_metrics.wilson_interval`), which behaves at small n and near 0 or 1 |
| Thin | n < 20 valid answers in the cell; say so next to the number |
| Share of voice (SoV) | answers mentioning the client / sum over tracked brands of answers mentioning that brand. Presence-based: repeating a name inside one answer does not add voice |
| Citation rate | answers citing at least one owned URL (client domain or subdomain) / valid answers |
| Citation share | owned cited URLs / all cited URLs (URLs de-duplicated within an answer) |
| Retrieval rate | answers whose own web search returned at least one client URL / valid answers. Says the engine *found* the site, not that it used or credited it; null when the engine reports no search results |
| Avg first position | among answers that mention the client, its rank by first appearance among tracked brands (1 = named first). Low weight: list order is the least stable property of an answer |
| Cited-source mix | each cited URL classed own / competitor / social (Reddit, YouTube, LinkedIn, forums ...) / reference (Wikipedia, Wikidata, .gov, .edu, .ac.xx ...) / other; top cited domains counted once per answer |

With the Anthropic engine's default `dynamic` search tool
(`web_search_20260209`), live answers came back with no structured citations
(observed 2026-10-17), so citation rate is "not measured" while retrieval rate
is still measured. Use `--search-tool basic` (`web_search_20250305`) when the
citation rate itself matters, and never compare windows run with different
search tools.

Citation metrics are "not measured" (null) for an engine/surface where no
answer carries any citation, which usually means the capture did not record
sources.

## Headline

The headline is the unbranded mention rate (with CI, n, SoV and citation
rate) of one engine/surface: the one with the most valid unbranded answers,
or the one named with `--engine`. Branded prompts are excluded because an
engine naming the client when asked about the client says nothing about
visibility in open questions. The headline feeds the KPI envelope:

| KPI | Value |
|---|---|
| `ai.mention_rate`, `ai.mention_rate_ci_low`, `ai.mention_rate_ci_high` | 0-1 fractions |
| `ai.citation_rate`, `ai.sov` | 0-1 fractions (null when not measured) |
| `ai.n` | valid unbranded answers |

The envelope's `meta` names the engine, surface and models, so trends never
silently mix sources. AEO readiness (`aeo.*`) is a separate envelope.

## Period comparison (`compare`)

Two non-overlapping windows, A (before) and B (after), per engine/surface:

1. Keep prompts with valid answers in both windows (paired). Branded prompts
   are excluded unless `--include-branded`.
2. Per prompt, mention rate in A and in B; the pair is **up**, **down** or a
   **tie**.
3. Per group: exact two-sided sign test on ups vs downs (ties dropped,
   `seo_metrics.sign_test_p`) and the mean change in percentage points.
4. Holm-Bonferroni adjustment (`seo_metrics.holm_adjust`) across every
   treatment and control test in the run (all engines). Other groups are
   descriptive and unadjusted.
5. Difference-in-change = treatment mean change - control mean change (pp).

The sign test uses direction only, so a prompt moving from 0/5 to 1/5 counts
the same as 0/5 to 5/5. It is deliberately conservative for small panels;
the mean change carries the magnitude.

## Verdict rule

Vocabulary shared with `seo-track`'s measurement protocol.

| Verdict | Rule |
|---|---|
| **Unproven** | No treatment/control split; or fewer than 6 paired prompts in treatment or control (a two-sided sign test cannot reach p < 0.05 below 6); or treatment improved significantly but control improved as much or more (engine-wide drift, not the change) |
| **Promote** | Treatment ups > downs with Holm-adjusted p < 0.05, difference-in-change > 0, and control not significantly improved |
| **Rollback** | Treatment downs > ups with Holm-adjusted p < 0.05 and difference-in-change < 0 |
| **Keep-testing** | Anything else: a valid design whose effect is not yet significant. Extend the outcome window or add prompts; do not re-slice the data until it looks significant |

A Promote verdict says the treatment prompts' answers changed more than the
control prompts' answers in this panel on this engine. It does not say by
how much traffic or leads changed; check `ai_referrals.py` and the lead KPIs
for that.

## Limitations (state them in client reports)

- **Non-determinism.** The same prompt yields different answers minutes
  apart. Rates are estimates; read the interval, not the point.
- **API is not the consumer app.** The API has no personalization, memory,
  location (unless `--country`) or app-side retrieval. Treat `anthropic/api`
  as a controlled proxy and the `ui` captures as the consumer reality.
- **Silent model and retrieval changes.** Vendors update models and search
  backends without notice. The store keeps the served model id per answer;
  compare windows only when it matches, and note known launches.
- **Lexical matching.** Misspellings, translations and unlisted product names
  are missed; generic or very short terms over-match. Keep aliases current
  and review a sample of answers each batch.
- **Citations are not traffic.** An answer can cite the client and send no
  visit. Pair with GA4 AI-referral sessions (`ai_referrals.py`).
- **A panel samples demand.** It does not represent the full distribution of
  real prompts; say "on this panel", never "in ChatGPT" in general.
- **Refusals and errors** reduce n; a high refusal count on a topic is a
  finding in itself, not a zero.

## Sources

- Wilson interval, sign test and Holm adjustment: standard statistics as
  implemented in `scripts/seo_metrics.py`.
- k >= 5 runs, raw-answer storage, branded-prompt exclusion, separate API
  and UI tracking: public methodology of open AI-visibility trackers
  (geo-score, Elmo, Limelit) and the SparkToro/Gumshoe study of answer
  consistency, as summarized in the v3.1 hub design spec
  (`docs/superpowers/specs/2026-10-17-seo-aeo-geo-hub-design.md`, section 3).
- Gemini grounding exclusion: Google's terms for Grounding with Google Search.
