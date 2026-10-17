# Keyword scoring: formulas, weights, thresholds and sources

Every number `seo-keywords` and `seo-competitors` report is computed by
`scripts/seo_metrics.py` (shared core) or `scripts/keyword_research.py` /
`scripts/competitor_gap.py`. This file is the single written record of those
rules. If code and this file disagree, the code is what ran. Fix whichever
one is wrong in the same change.

**What is sourced and what is a decision.** The CTR curves and the
cannibalization rule come from published studies (cited below). The intent
modifier lists, lead values, opportunity weights and bucket thresholds are
**ZYRA prioritization decisions**. They are fixed so that runs are
reproducible. They are not measured conversion rates. Present them that way
in reports.

## 1. Intent, funnel stage, lead value (`classify_intent`)

Deterministic modifier matching on word boundaries. No model call is made.

| Family | Example modifiers (full lists in `seo_metrics.py`) |
|---|---|
| transactional | buy, price/pricing, cost, quote, demo, trial, hire, book, near me, plans, download |
| commercial | best, top, vs/versus, alternative(s), compare, review(s), software, tool(s), agency, provider, solution(s) |
| informational | what, how, why, guide, tutorial, examples, template(s), checklist, is/are/can/does |
| navigational | login, sign in, official, portal, account, dashboard |

Precedence when several families match: **own-brand navigational >
transactional > commercial (or a competitor term) > informational > generic
navigational > informational (default)**. A query counts as own-brand
navigational when it contains a brand term and either has a navigational
modifier or is at most one word longer than the brand term ("acme",
"acme pricing").

| Funnel | Rule | Lead value |
|---|---|---|
| BOFU | transactional; navigational; commercial with vs/versus/alternative(s)/compare/comparison/review(s) or a competitor term | 1.0 |
| MOFU | other commercial | 0.6 |
| TOFU | informational | 0.25 |
| (own brand) | own-brand navigational: existing demand to defend, not new acquisition | 0.3 |

`confidence` is high with 2+ signals in the winning family, medium with 1,
and low with none (the label was defaulted). `local` is set by near me /
nearby / open now / closest / local / in my area, or by a US ZIP code.

## 2. Position bands (`position_band`, `is_striking_distance`)

top3 ≤ 3 · page1 (3, 10] · striking (10, 20] · deep (20, 50] · far > 50 ·
unranked = none. **Striking distance = average position 4-20** (page 1 below
the fold, or page 2). The page is already judged relevant there, so on-page
work moves clicks most often.

## 3. Expected CTR

Fallback curve, positions 1-10 (Backlinko, 4M Google results,
https://backlinko.com/google-ctr-stats): 27.6, 15.8, 11.0, 8.4, 6.3, 4.9,
3.9, 3.3, 2.7, 2.4 %. Positions 11-20 use 0.63% (Backlinko page-2 figure).
Beyond 20 we assume a 0.1% floor. Fractional positions interpolate linearly.

**This curve predates AI Overviews and overstates CTR.** Ahrefs measured
position-1 CTR on AI-Overview keywords falling from 7.3% to 1.6% (Dec 2023 to
Dec 2025, https://ahrefs.com/blog/ai-overviews-reduce-clicks-update/).
Every output names the curve it used (`curve_source`).

**Site calibration** (`calibrate_ctr_curve` + `keyword_research gsc`):
- Rows: **non-branded** GSC query×page rows. Any query that mentions a brand
  term is excluded.
- Bucket = rounded position 1-10. Bucket CTR = Σclicks / Σimpressions, so the
  bucket is impression-weighted.
- A bucket counts only with **≥ 50 impressions** (core) **and ≥ 5 rows**
  (`MIN_BUCKET_ROWS`). With fewer rows, a bucket mostly reproduces the CTR of
  the query that dominates it.
- The calibrated curve is used only when **≥ 3 buckets** qualify. Positions
  with no qualifying bucket fall back to the default curve.
- Caveat: calibration to the site's own average makes an "underperformer"
  mean "below this site's norm", not "below the market".

## 4. GSC opportunity maths (`keyword_research gsc`)

- **CTR is recomputed as clicks / impressions (a 0-1 fraction).** The
  `ctr` field of `gsc_query.py` is a percentage and is ignored.
- Striking-distance opportunity (`striking_distance_opportunity`):
  `target = max(1, round(position) − lift)` with lift = 5, and
  `opp_clicks = impressions × max(0, CTR(target) − actual CTR)`.
  Example: position 12, 3,000 impressions, CTR 0.4% gives target 7, whose
  CTR is 3.9%, so opp_clicks = 105.0. The calculation is conservative: it
  assumes the snippet keeps its current CTR behaviour relative to the curve.
- `opp_clicks_monthly = opp_clicks × 30 / period_days`. This puts it in the
  same unit as `traffic_potential` (monthly).
- Row filters: impressions ≥ 50 (`--min-impressions`). Brand-navigational
  queries are excluded unless `--include-brand`. Queries that mention the
  brand with a commercial modifier ("acme vs hubspot") are kept and flagged.
- CTR gap (`ctr_gap`): expected CTR, `ctr_ratio = actual / expected`, and
  `click_shortfall = impressions × max(0, expected − actual)`. A row is a
  **CTR underperformer** when position ≤ 10 and ratio < 0.5. Example:
  position 4 at 1.0% CTR on 1,000 impressions gives ratio 0.12 and shortfall
  74.0.
- `lead_priority = opp_clicks_monthly (or click_shortfall_monthly) × lead_value`.

## 5. Cannibalization (`detect_cannibalization`)

This follows J.C. Chouinard's published rule. A query is cannibalized when
**at least two pages each take ≥ 10% of the query's clicks AND the query is
≥ 10% of each of those pages' clicks**. Branded queries are skipped. When a
query has no clicks, impressions are used instead, and the output is labelled
`basis: impressions` because that is weaker evidence.

## 6. Opportunity score (`opportunity_score`, 0-100)

| Component | Formula (each 0-1) | Weight |
|---|---|---|
| demand | log10(volume + 1) / log10(100,001), capped at 1 | 0.30 |
| ease | 1 − KD / 100 | 0.25 |
| lead_value | from section 1 | 0.30 |
| position | none: N/A · ≤ 0: 0.5 · ≤ 3: 0.3 · ≤ 20: 1.0 · ≤ 50: 0.6 · > 50: 0.4 | 0.15 |

`score = 100 × relevance × Σ(w·c) / Σ(w)`, where a component with no data
counts as a neutral **0.5**. Unknown is not "not applicable": dropping it and
renormalizing (scoring-rubric Rule 5) would let a keyword with one favourable
guess outrank a fully measured one. `completeness` = Σ(w with data) / 1.0.
(`missing="renormalize"` keeps Rule-5 semantics for components that genuinely
do not apply.)

Worked example: "crm pricing", volume 2,400, KD 35, position 8.
demand = 0.676, ease = 0.65, lead = 1.0, position = 1.0.
0.3·0.676 + 0.25·0.65 + 0.3·1 + 0.15·1 = 0.815, so the **score is 81.5**
and completeness is 1.0.

**Still show completeness next to every score.** With volume and intent only,
the same keyword scores 70.3 at completeness 0.6: the neutral prior pulls thin
scores toward 50 rather than inflating them, but a 0.6-completeness score is
still a weaker claim than a 1.0 one.

`relevance` (0-1, default 1.0) is the operator's business-fit multiplier,
supplied as a `keyword,relevance` CSV. It is a judgment input, so label it
INFERRED unless the client supplied it.

## 7. Traffic potential, lead priority, buckets

- `traffic_potential = volume × expected_ctr(3)` on the fallback curve
  (2,400 × 11.0% = 264). Treat it as an upper bound.
- `lead_priority = base × lead_value × relevance`. The base is
  `opp_clicks_monthly` when GSC data exists for the keyword
  (`lead_priority_basis: gsc_opp_clicks`), otherwise `traffic_potential`
  (`traffic_potential`). With neither, lead_priority is null.
- `scenario_bucket`, evaluated in order:
  1. Striking distance (4-20) with lead value ≥ 0.25 → **quick_win**.
  2. Lead value < 0.6 → **awareness**.
  3. KD < 30 → **quick_win**.
  4. KD < 60 → **growth**.
  5. Otherwise → **long_term**.

  Unknown KD counts as 45.

## 8. Answer-engine format flags (`geo_flags`)

| Flag | Pattern |
|---|---|
| question | starts with what/how/why/when/who/which/where/is/are/can/does/do/should, or ends with ? |
| definition | what is / what are / meaning / definition / define |
| comparison | vs / versus / compare / comparison / difference between / alternative(s) |
| list | best / top / examples / ideas / types / ways / tools / list |
| how_to | how to / steps / guide / tutorial |

A flag is a format hint. It does not predict that an AI answer will appear.
Content for flagged keywords should open each major section with a direct,
self-contained answer, per the AEO stance in CLAUDE.md (Princeton GEO study,
KDD 2024).

## 9. Merging and parsing (`keyword_research score`)

- Merge key: NFKC, lowercase, zero-width characters removed, whitespace
  collapsed. Punctuation is kept.
- Duplicates keep the **max volume** (and that record's range), the **max
  difficulty** (conservative when providers disagree), the **best (lowest)
  position** with its URL, the max of cpc / impressions / clicks / opp, and
  the union of sources. Max is used rather than a sum because the same row is
  often present in several files.
- A volume range such as "1K – 10K" becomes its **geometric midpoint**
  (3,162), or the arithmetic midpoint when the low end is 0. The demand
  component is log-scaled, and the geometric midpoint is the centre of the
  range on that scale. The `volume_range` field is kept.
- Ads `competition` / `competition_index` / "Competitive Density" is
  paid-ad competition and is **never** used as difficulty unless
  `--difficulty-column` names it explicitly.
- Blank or non-positive positions are treated as unknown, not as position 0.
- `--min-volume` drops only keywords whose volume is known.

## 10. Lexical grouping (approximate)

Tokens come from `seo_metrics.tokenize` (stopwords removed) plus naive plural
folding ("agencies" → "agency", "tools" → "tool"; "-ss" endings kept).
Keywords are visited in score order. Each keyword joins the existing group
whose **head** has the highest token-set **Jaccard ≥ 0.5** (ties go to the
older group); otherwise it starts a new group. The label is the tokens shared
by every member, or else the two most frequent tokens. This is **lexical
(approximate)**. Use `seo-cluster` for SERP-overlap clustering before you
commit to a page architecture.

Competitor-gap thresholds (4-way segmentation, gap priority, format and topic
gaps) are documented in `skills/seo-competitors/references/gap-segmentation.md`.
