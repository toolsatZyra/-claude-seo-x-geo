# KPI definitions

The reserved metric names in the KPI store (`performance_tracker.py`), what
each one means, which script produces it, the caveats a report must carry,
and whether it is a leading or lagging indicator. Other names are allowed
(`namespace.metric`, lowercase letters, digits, underscores), but a
non-reserved name under a reserved prefix (`ai.mention_rat`) triggers a
warning on ingest because it is usually a typo.

## Value rules (enforced on ingest)

| Kind | Range | Applies to |
|---|---|---|
| count | >= 0 | clicks, impressions, sessions, key events, keyword counts, leads, `ai.n` |
| fraction | 0-1, never a percent | `gsc.ctr`, `ai.mention_rate`, its CI bounds, `ai.citation_rate`, `ai.sov` |
| rate | >= 0 | `ga4.*_cvr` (can exceed 1 when the basis is key events per session) |
| score | 0-100 | `aeo.*`, `seo.health`, `rank.visibility` |
| position | > 0, lower is better | `gsc.position` (and any metric ending in `position`) |

`null` means "not measured" and is skipped; it is never stored as 0. An
envelope with one invalid value is rejected whole.

Direction in reports: higher is better except positions. `rank.tracked` and
`ai.n` are neutral (they change with configuration and sample size) and never
trip `--fail-on-drop`.

## Search Console (`gsc.*`) - producer: `performance_tracker.py snapshot`

| Metric | Definition | Indicator |
|---|---|---|
| `gsc.clicks` | Web search clicks in the snapshot window (default 28 days ending 3 days before the snapshot date) | Lagging |
| `gsc.impressions` | Impressions in the same window | Lagging (leads clicks by weeks) |
| `gsc.ctr` | clicks / impressions as a fraction | Lagging |
| `gsc.position` | Site-wide average position | Lagging |
| `gsc.clicks_nonbrand` | Clicks excluding queries matching the profile brand terms | Lagging; the best SEO growth signal |
| `gsc.impressions_nonbrand` | Impressions excluding brand queries | Lagging |

Caveats:

- **Position is an impression-weighted average**, not a rank on any SERP. A
  page can "improve" because it lost impressions at poor positions.
- **Anonymized queries**: Google hides rare queries for privacy. An Ahrefs
  analysis (2022) put the hidden share near half of all clicks; it varies by
  site. Totals here come from a dimensionless query, so they include those
  clicks; any per-query sum undercounts.
- **Non-brand totals use a query filter**, which drops anonymized queries, so
  `gsc.clicks_nonbrand` + brand clicks < `gsc.clicks`. Compare non-brand with
  non-brand over time, never with the site total.
- **Lag**: data arrives 2-3 days late; only `dataState=final` days are used.
- Brand terms come from the project profile; if it has none, non-brand
  metrics are not recorded (stated in `limitations`).

## Rankings (`rank.*`) - producer: `rank_tracker.py report` / `snapshot`

| Metric | Definition | Indicator |
|---|---|---|
| `rank.tracked` | Tracked keywords in scope (all, or the `--tag` subset) | Neutral |
| `rank.top3` | Tracked keywords with current position <= 3 | Lagging |
| `rank.top10` | Tracked keywords with current position <= 10 (includes top 3) | Lagging |
| `rank.striking` | Tracked keywords at position 4-20 (striking distance) | Leading for clicks |
| `rank.visibility` | 100 x mean of expected CTR(position) / expected CTR(1); unranked = 0 | Lagging |

Caveats: positions are GSC window averages (default 7 days) unless the report
was run on a SERP-import source; a keyword with no GSC rows counts as
unranked, which may mean anonymized rather than absent. The visibility curve
is the fallback population curve in `seo_metrics.py` (pre-AI-Overview, an
upper bound on CTR); it is fine for trends, not for traffic forecasts. A
`--tag`-filtered run describes that subset only. The store keeps one value per
metric per date, so emit `rank.*` from one source per project (GSC via
`snapshot`, or one SERP source via `report --source X --emit-kpis`), not both.

## GA4 (`ga4.*`) - producer: `ai_referrals.py` / `snapshot`

| Metric | Definition | Indicator |
|---|---|---|
| `ga4.organic_sessions` | Sessions with default channel group "Organic Search" (not AI-classified) | Lagging |
| `ga4.organic_key_events` | GA4 key events in those sessions | Lagging; closest to leads |
| `ga4.organic_cvr` | Share of organic sessions with a key event (`sessionKeyEventRate`), else key events per session | Lagging |
| `ga4.ai_sessions` | Sessions whose source matches the AI-assistant host table | Outcome (layer 3) |
| `ga4.ai_key_events` | Key events in AI-assistant sessions | Outcome |
| `ga4.ai_cvr` | Same basis as `ga4.organic_cvr`, for AI sessions | Outcome; unstable at small n |

Caveats:

- **AI classification is a heuristic.** The host table (`AI_SOURCES`, version
  stamped in every output) covers assistants that pass a referrer or tag links.
  Many apps strip the referrer, so a share of AI traffic lands in Direct:
  `ga4.ai_sessions` is a floor. A table change is a measurement change; note it
  when comparing across versions.
- **Key events** are what GA4 called conversions before 2024. Per-event counts
  use the Data API's `keyEvents:<eventName>` metric; if a property rejects it
  the script falls back to total key events and says so. Key events include any
  event the property marks as key, which may not all be leads.
- The CVR basis is stored in the snapshot meta (`cvr_basis`); do not compare
  values with different bases.
- GA4 can apply thresholding and an "(other)" row on high-cardinality reports;
  GA4 data for the last 24-48 hours may still change, so windows end yesterday.

## AI visibility (`ai.*`) - producer: `ai_visibility.py` (`geo-share-of-voice`)

| Metric | Definition | Indicator |
|---|---|---|
| `ai.mention_rate` | Share of non-branded panel answers that mention the brand | Outcome (layer 3) |
| `ai.mention_rate_ci_low` / `_ci_high` | 95% Wilson interval for the mention rate | Context for the above |
| `ai.citation_rate` | Share of answers citing a URL on the client's domain | Outcome (layer 3) |
| `ai.sov` | Brand mentions / all tracked-brand mentions (client + competitors) | Outcome (layer 3) |
| `ai.n` | Answers behind the rates (prompts x engines x runs) | Neutral |

Caveats: AI answers are non-deterministic and API answers differ from the
consumer apps; with `ai.n` under 20 the rate is flagged thin. Read the CI
bounds before calling a change. Branded prompts are excluded from the headline
rate.

## AEO readiness (`aeo.*`) - producer: `aeo_score.py`

| Metric | Definition | Indicator |
|---|---|---|
| `aeo.score` | The single AEO Readiness Score (weighted composite, N/A renormalized) | Leading proxy (layer 2) |
| `aeo.citability`, `aeo.brand_authority`, `aeo.content_eeat`, `aeo.crawler_access`, `aeo.schema`, `aeo.platform` | Its component scores, 0-100 | Leading; `crawler_access` is layer 1 |

Readiness is not outcome: never blend `aeo.*` with `ai.*` or with `seo.health`.

## Other

| Metric | Definition | Producer | Indicator |
|---|---|---|---|
| `seo.health` | SEO Health Score from a full audit, 0-100 | `seo-audit` | Leading proxy |
| `leads.total` | Leads in the period from the client's CRM | `performance_tracker.py record` | Lagging; the business outcome |
| `leads.organic` | Leads attributed to organic search in the CRM | `record` | Lagging |

Record leads for the same calendar period every time (for example the
previous month, recorded on the 1st) and state the CRM's attribution model in
`--note`; first-touch and last-touch counts are not comparable.

## Leading vs lagging, at a glance

- Leading (move first, prove nothing alone): `aeo.*`, `seo.health`,
  `rank.striking`, `gsc.impressions`.
- Outcomes during a test horizon: `ai.*`, `ga4.ai_*`.
- Lagging (the business case): `gsc.clicks*`, `rank.top3`/`top10`/`visibility`,
  `ga4.organic_*`, `leads.*`.
