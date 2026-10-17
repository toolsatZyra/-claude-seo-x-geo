# Refresh rules

The fixed rules `scripts/content_decay.py` applies, and the human procedure
for each action. Thresholds live as constants at the top of the script; if
you change one there, change it here.

## Windows and baseline

- Current window: the last `--days` (default 90) days ending `--lag` (default
  3) days before `--as-of`, because GSC data lags 2-3 days.
- Baseline, first match wins:
  1. **Year earlier**: the same window shifted back 364 days (52 weeks, so
     weekdays line up). Used when the page had at least
     `--min-baseline-clicks` (default 20) clicks there. Controls seasonality.
  2. **Previous window**: the `--days` immediately before the current one,
     when the year-earlier window has no data for the property or the page
     had too few clicks a year ago (for example a newer page). Seasonality is
     not controlled; every report must say so.
  3. Neither reaches the floor: tier `insufficient_data`, action `monitor`.
- CTR is always recomputed as clicks / impressions (GSC's exported CTR field
  is a percentage and is ignored).
- Row limit: each window asks GSC for up to 100,000 rows (the most
  `gsc_query.py` pages through). GSC returns the top rows by clicks, so a
  window that reaches the limit is **truncated** and low-click pages are cut
  from it. A page present in a baseline but missing from a truncated current
  window is `insufficient_data` (rule R0c), never `lost_visibility`, and is
  never routed to retirement; a page missing from a truncated baseline window
  has no baseline there. The report lists truncated windows in
  `summary.truncated_windows` and in its notes. For `--input` exports made
  with a row cap, set `"truncated": {"current": true}` (or the window
  concerned).

## Tiers (clicks change versus the baseline)

| Tier | Clicks change |
|---|---|
| critical | -60% or worse |
| high | -40% to -59.9% |
| warning | -20% to -39.9% |
| stable | better than -20% |
| insufficient_data | baseline below the click floor, or the page is missing from a truncated current window |

## Cause rules (decaying tiers only)

All matching causes are listed; the first in this order is primary.

| Cause | Rule | Typical meaning |
|---|---|---|
| `lost_visibility` | 0 impressions now, some in the baseline | Deindexed, noindex, redirected, 404/5xx, or the URL changed |
| `cannibalization` | The page is in a cannibalization pair: two or more pages each take at least 10% of a non-branded query's clicks and the query is at least 10% of each page's clicks (`seo_metrics.detect_cannibalization`) | Pages compete; Google alternates or splits them |
| `ranking_loss` | Average position worse by 1.0 or more | Competitors improved, the page changed, or relevance fell |
| `serp_feature_or_ai_overview` | Impressions not down by 15% or more, position change under 1.0, CTR down 20% or more | Rankings held but something on the results page takes the clicks; when impressions rose 15%+, new low-CTR queries are an alternative explanation |
| `demand_drop` | Impressions down 15% or more with position flat or better | Fewer people search; with a previous-window baseline this may be seasonal |
| `unclear` | None of the above | Inspect query-level data |

Causes are INFERRED (scoring-rubric Rule 9). GSC position is an
impression-weighted average across all of a page's queries, so a shift in
query mix can look like a ranking change. Confirm with the verify-first
checks before acting.

## Decay score (0-100)

Severity of the decline, for ordering within a tier. Components (0-1):

| Component | Weight | Formula |
|---|---|---|
| click_loss | 45 | max(0, -clicks change %) / 100, capped at 1 |
| position_loss | 20 | max(0, position change) / 5, capped at 1 (1.0 for lost visibility) |
| ctr_shortfall | 20 | max(0, 1 - actual CTR / expected CTR at the current position) |
| cannibalization | 15 | 1 if the page is in a cannibalization pair, else 0 |

`score = round(100 * sum(weight * component) / sum(weights of available components))`.
A component without data (no position, no query × page rows) is excluded and
the rest renormalized (Rule 5); the output lists excluded components and the
expression, so the arithmetic is auditable (Rule 4). The expression carries
the exact component values and the score is computed by that same
arithmetic, so evaluating the expression always gives the score (Python
`round()`, ties to even: 12.5 rounds to 12). Expected CTR uses a
curve calibrated on the site's own non-branded query rows when enough exist,
otherwise a pre-AI-Overview population curve that overstates CTR.

Sort order: tier, then money pages first, then decay score, then lost
clicks.

## Action rules

| Rule | When | Action |
|---|---|---|
| R0a | tier `insufficient_data` | monitor |
| R0b | tier `stable` | monitor |
| R0c | missing from a truncated current window (tier `insufficient_data`) | monitor; query GSC for the page alone before concluding anything |
| R1 | cause `lost_visibility` | redirect_or_retire_review (fix indexing if unintended; 301 to the closest live page if intended) |
| R2 | cause `cannibalization` | consolidate |
| R3 | cause `serp_feature_or_ai_overview` | refresh, following the AI Overview playbook |
| R4a | cause `ranking_loss`, tier warning/high, position 20 or better | refresh |
| R4b | cause `ranking_loss`, tier critical or position beyond 20 | rewrite |
| R5a | cause `demand_drop`, not critical, or a money page | monitor (refreshing cannot restore searches) |
| R5b | cause `demand_drop`, critical, not a money page | redirect_or_retire_review |
| R6a | cause `unclear`, tier warning | monitor and re-check next period |
| R6b | cause `unclear`, tier high/critical | refresh and inspect query-level data |

Money pages are flagged `urgent` for R1, R4 and R6b and are never routed to
retirement by R5.

## Improvement candidates (`candidates`)

Current impressions at least `--min-impressions` (500), average position
within `--min-pos`..`--max-pos` (4-25), and either CTR below 0.7 of expected
(`ctr_gap`) or clicks down 10% or more versus the previous window
(`declining`). Sorted money pages first, then by click shortfall.

## Procedures

**Refresh** (page still relevant and in reach): update facts, prices,
screenshots and dates that changed; answer the top queries directly, first
in each section; add missing subtopics and questions from the optimizer;
add internal links from related, stronger pages; recheck title and meta
against the top queries. Keep the URL and the parts that already rank.

**Rewrite** (severe loss or beyond page 2): re-check search intent on the
current SERP first; rebuild structure and depth around what ranks now; keep
the URL if it has links or history. Same gates as a new article.

**Consolidate** (cannibalization): choose the page that owns the query (best
intent match, most links, conversions); merge the unique, still-true content
from the other page into it; 301 the other URL to it; update internal links
and the sitemap; re-check both URLs in GSC after recrawl. If the pages serve
genuinely different intents, re-target the weaker one instead of merging.

**Retire review** (never automatic): check backlinks (`seo-backlinks`),
conversions (GA4), internal links and whether the topic still matters to the
business. Keep and refresh, merge with a 301 to the closest relevant page, or
return 410 only when nothing of value (links, traffic, conversions) remains.
The operator decides.

## Date hygiene

- Change `dateModified` in structured data, any visible "updated on" date,
  and the sitemap `lastmod` only when the update is **substantive**: new or
  corrected facts, new sections that answer real queries, updated data or
  prices, rewritten answers.
- Not substantive: typo fixes, rewording, swapping images, adding internal
  links, schema-only edits. Leave the dates alone.
- Never change `datePublished` on a refresh.
- Why: Google's helpful-content self-assessment lists changing a page's date
  to make it seem fresh, without substantial changes, as a sign of
  search-engine-first content; Google also uses a sitemap's `lastmod` only
  when it is consistently accurate. Fake freshness costs trust in both.
- Record the update (what changed, why, who reviewed) in the change log or
  the project notes so the +14/+28-day check can attribute movement.
