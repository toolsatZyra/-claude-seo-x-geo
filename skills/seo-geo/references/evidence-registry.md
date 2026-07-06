# Evidence registry — AEO/GEO claim tracking

Every precise statistic used anywhere in the `geo-*` skill cluster or in
client-facing proposal material should trace back to a row here: claim,
value used, source, date retrieved, confidence, and who owns re-checking it.
This exists because two independent reviews of this plugin (2026-07-06)
both flagged the same root problem from different angles: precise-sounding
AEO/GEO statistics were being stated as fact without sourcing, without
confidence levels, and without a mechanism to catch staleness. This file is
that mechanism. When you add or requote a stat, add or update its row here.

## How to use this file

- **Confidence: Verified** — traced to a specific, checkable, named source
  during the 2026-07-06 audit. Still re-check before quoting in a
  high-stakes client deliverable; "verified" means "we found a real source
  for it," not "guaranteed accurate forever."
- **Confidence: Directionally plausible, unverified magnitude** — the
  underlying behavior/trend is credible, but we could not confirm the
  specific number. Do not present the number itself as fact.
- **Confidence: Removed / could not verify** — we actively searched and
  found no trace of this claim in real research or reporting. Treat any
  reintroduction of the old number as a regression, not a restoration.

## Citability / GEO research (skills/geo-citability, aeo-scoring-weights.md)

| Claim | Value | Confidence | Source | Retrieved |
|---|---|---|---|---|
| Statistics presence in a passage | ~41% visibility lift | Verified | Aggarwal et al., "GEO: Generative Engine Optimization," ACM SIGKDD 2024. [DOI](https://dl.acm.org/doi/10.1145/3637528.3671900) | 2026-07-06 |
| Quotations from authorities | ~28% visibility lift | Verified | Same paper | 2026-07-06 |
| Citing external sources (lower-ranked content, ~position 5) | up to ~115% visibility lift | Verified | Same paper | 2026-07-06 |
| Aggregate top-technique lift | "up to 40%" | Verified | Same paper | 2026-07-06 |
| Front-loading: ~44% of AI citations from first 30% of page | ~44% | Directionally plausible, unverified magnitude | Could not locate this specific figure in the cited paper or elsewhere | 2026-07-06 |
| Keyword stuffing penalty | ~-10% | Directionally plausible, unverified magnitude | Direction consistent with general GEO findings; magnitude unconfirmed | 2026-07-06 |
| Optimal passage length | 134-167 words | Removed / could not verify | Not found in the cited paper or any other located source. This is `citability_scorer.py`'s own internal heuristic band, not a research finding | 2026-07-06 |
| Definition-pattern citation multiplier | "2.1x, Georgia Tech 2024" | Removed / could not verify | The cited paper is one joint Princeton/Georgia Tech/IIT Delhi/Allen AI study, not separate per-university findings; this multiplier and its attribution could not be traced | 2026-07-06 |
| "Bortolato 2025 analysis of AI Overview passages" | 134-167 word claim | Removed / could not verify | No trace of this source found | 2026-07-06 |

## AI crawlers (skills/geo-crawlers)

| Claim | Value | Confidence | Source | Retrieved |
|---|---|---|---|---|
| GPTBot purpose and scope | Training-data collection only; does not control ChatGPT Search inclusion | Verified | [developers.openai.com/api/docs/bots](https://developers.openai.com/api/docs/bots) | 2026-07-06 |
| OAI-SearchBot purpose and scope | Powers ChatGPT Search; not used for training; independent of GPTBot | Verified | Same source | 2026-07-06 |
| Crawler settings are independent (blocking one bot doesn't block another) | — | Verified | Same source | 2026-07-06 |
| OAI-AdsBot exists (4th OpenAI crawler, added 2026) | — | Verified | Same source; also covered by Search Engine Journal reporting | 2026-07-06 |
| Originality.ai 2025: 35%+ of top 1,000 sites block ≥1 AI crawler, 5-10% block all | 35%, 5-10% | Directionally plausible, unverified magnitude | Named source (Originality.ai) but not independently re-confirmed this session | 2026-07-06 |

## Brand mentions (skills/geo-brand-mentions, scripts/brand_scanner.py)

| Claim | Value | Confidence | Source | Retrieved |
|---|---|---|---|---|
| Brand web-mention correlation vs. backlink correlation with AI Overview visibility | ~0.664 vs. ~0.218 (~3x) | Verified | Ahrefs, 75,000 brands, Dec 2025 follow-up study. [ahrefs.com/blog/ai-brand-visibility-correlations](https://ahrefs.com/blog/ai-brand-visibility-correlations/) | 2026-07-06 |
| YouTube mention correlation with AI visibility | ~0.737 (strongest of all factors tested) | Verified | Same source | 2026-07-06 |
| Wikipedia citation rate by platform | ChatGPT ~16.3%, Perplexity ~12.5%, AI Overviews ~8.4% | Verified | Ahrefs research, cited in multiple 2026 analyses of the same dataset | 2026-07-06 |
| "Reddit" appended to 10-15% of Google searches | 10-15% | Removed / could not verify | No source located; underlying behavior (users appending "Reddit" to searches) is plausible, the percentage is not confirmed | 2026-07-06 |
| "Corroborating research from Profound (2025) and Terakeet (2025)" | — | Removed / could not verify | Named without a specific claim or link attached | 2026-07-06 |

## AI Overviews / platform citation shares (skills/geo-platform-optimizer)

| Claim | Value | Confidence | Source | Retrieved |
|---|---|---|---|---|
| Share of AIO citations from top-10 organic results | Volatile: 38% in one Ahrefs study, 76% in a later one within the same research period | Verified (as "volatile," not as a fixed number) | [ahrefs.com/blog/ai-overview-citations-top-10](https://ahrefs.com/blog/ai-overview-citations-top-10/), [ahrefs.com/blog/search-rankings-ai-citations](https://ahrefs.com/blog/search-rankings-ai-citations/) | 2026-07-06 |
| Cross-platform citation domain overlap (ChatGPT vs. AIO) | previously stated as a fixed "11%" | Directionally plausible, unverified magnitude | Low overlap between platforms is a consistent theme in GEO research; the specific 11% figure is unconfirmed | 2026-07-06 |
| ChatGPT Wikipedia domain share | previously stated as "47.9%" | Removed / could not verify | Actual verified figure is ~16.3% (see Brand mentions section above); the 47.9% figure did not match any located source and has been replaced | 2026-07-06 |
| Perplexity Reddit domain share | previously stated as "46.7%" | Removed / could not verify | No matching source located; removed rather than left uncorrected | 2026-07-06 |

## Sales/proposal figures (skills/geo-proposal)

| Claim | Value | Confidence | Source | Retrieved |
|---|---|---|---|---|
| Gartner: predicted decline in traditional search engine volume | -25% by 2026 | Verified | Gartner press release, Feb 19, 2024. [gartner.com/en/newsroom/press-releases/2024-02-19-...](https://www.gartner.com/en/newsroom/press-releases/2024-02-19-gartner-predicts-search-engine-volume-will-drop-25-percent-by-2026-due-to-ai-chatbots-and-other-virtual-agents) | 2026-07-06 |
| Previous in-template claim: "-50% by 2028" | — | Removed / confirmed wrong | Did not match Gartner's actual prediction; corrected | 2026-07-06 |
| AI-referred traffic YoY growth | previously fixed at "+527%" | Directionally plausible, unverified magnitude | Public reports found during this audit ranged from ~390% to over 1000%+ YoY depending on source, vertical, and month; no single fixed figure is defensible for more than a few months | 2026-07-06 |
| AI traffic conversion vs. organic | previously fixed at "4.4x" | Directionally plausible, unverified magnitude | Public reports found ranged from modest lifts to "11x"; methodology varies widely between sources | 2026-07-06 |
| llms.txt adoption ("12% have it" / "78% have it") | — | Removed / could not verify | No source located; also contradicts this plugin's own stance that llms.txt is not a ranking lever and adoption shouldn't be used to create FOMO | 2026-07-06 |
| ChatGPT weekly active users, Google AI Overviews monthly reach | previously fixed at "900M+" / "1.5B users, 200+ countries" | Not verified this session | Left as fill-in-the-blank placeholders; pull and cite a current, dated figure before use | 2026-07-06 |

## Maintenance

- Add a row here before adding any new precise statistic anywhere in the
  `geo-*` cluster, `seo-content`'s citability pass, or `seo-audit`'s AEO
  fan-out output.
- Re-check "Verified" rows roughly quarterly — AI platform market share and
  crawler policy details change fast. A stale "Verified" row is worse than
  an honest "unverified" one, because it invites false confidence.
- If a number can't be traced to a source during a review, remove it rather
  than leaving it in place "until someone checks."
