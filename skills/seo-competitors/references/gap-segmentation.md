# Gap segmentation: definitions, rules and thresholds

This is the method behind `scripts/competitor_gap.py`. The idea of segmenting
keywords into four groups (moat / battleground / gap / pioneer) comes from
aaron-he-zhu/seo-geo-claude-skills (Apache-2.0). The rules and code here
are our own re-implementation. Shared maths (intent, lead value, opportunity
score) are covered in `skills/seo-keywords/references/keyword-scoring.md`.

## 1. Keyword gap: 4-way segmentation (`competitor_gap.py keywords`)

**Inputs.**
- One ranking export for us (`--own`).
- One export per competitor (`--competitor NAME=FILE`).
- Optionally a keyword universe (`--universe`), for example our scored
  keyword list or `suggest` output.

Any shape that `keyword_research.py score` accepts works:
- DataForSEO `ranked_keywords` JSON
- Ahrefs "Organic keywords" CSV
- Semrush "Organic Research → Positions" CSV
- GSC rows (own site only)

**"Ranks"** means position ≤ `--threshold` (default 20, the edge of
striking distance). A keyword missing from an export counts as not ranking.

| Segment | Rule | What it means |
|---|---|---|
| **moat** | we rank; no competitor ranks | Defend: keep it fresh, internally linked, monitored |
| **battleground** | we rank and ≥ 1 competitor ranks | Contest: record the leader and `position_delta = own − best competitor` (positive = they are ahead) |
| **gap** | ≥ 1 competitor ranks; we do not | Opportunity: content we lack or that underperforms |
| **pioneer** | in the universe; nobody ranks | Unclaimed demand; validate the SERP before investing |

Keywords that nobody ranks for and that are not in the universe are counted
(`excluded.nobody_ranks_not_in_universe`) but not listed.

**Exclusions (default; `--include-brand` keeps them).**
- Own-brand navigational queries ("acme", "acme login"). A query that names
  our brand with a comparison modifier ("rival vs acme") stays in, because it
  is a gap worth winning.
- Competitor-navigational queries: a competitor term plus a navigational
  modifier ("rival login"), or the bare competitor name.

Competitor terms come from the profile (name, domain label, aliases) plus
each `NAME`. "rival alternatives" and "rival vs acme" are **not** excluded:
they are BOFU comparison gaps.

**Gap priority.**
`gap_priority = opportunity_score(volume, difficulty, own position if any,
lead_value from intent)`. It uses the same weights and neutral prior for
missing data as keyword scoring, so read it next to `completeness`.

Sort order:
1. gap priority, descending
2. number of competitors ranking, descending
3. best competitor position, ascending
4. keyword

When several files carry volume or difficulty, the maximum is used.

**Battlegrounds** sort competitor-led keywords first, then by opportunity
score. **Moats** sort by volume, then own position.

**Routing.**

| Gap | `route` |
|---|---|
| comparison flag (vs / versus / compare / alternatives / difference between) or a competitor term | `seo-competitor-pages` |
| everything else | `seo-content-brief` (`seo-cluster` first when several gaps share a theme) |

Gaps also carry `bofu: true/false`. BOFU gaps (pricing, demo, vs, "best X
for Y") come first in a lead-generation plan.

**Competitor stats.** For each competitor the output reports:
- `ranking`: keywords it ranks for within the threshold
- `in_gaps`: gaps where it ranks
- `leads_battlegrounds`
- `overlap_with_own`: the share of our ranking keywords it also ranks for

Overlap is the evidence for calling a domain a *search* competitor rather
than only a *business* competitor.

## 2. Content and format gap (`competitor_gap.py content`): free tier

**Discovery.** For each domain:
1. Read `robots.txt` and collect its `Sitemap:` lines.
2. If there are none, try `/sitemap.xml`, then `/sitemap_index.xml`.
3. Walk sitemap indexes breadth-first, interleaved by sitemap "family" (the
   file name with digits removed), so a cap samples posts, pages and
   products alike. The walk stays within these caps:
   - `--max-sitemaps` (default 20) sitemap files
   - `--max-bytes` (default 20 MB) decompressed per file
   - `--max-urls` (default 2,000) page URLs kept per domain, taken
     round-robin across sitemaps
4. Keep only page URLs on the domain or its subdomains. Off-site URLs are
   counted in `offsite_ignored`.

Requests run 0.5 s apart per domain.

**Safety.**
- Every request goes through `url_safety`, which provides SSRF protection,
  DNS pinning and redirect-target validation.
- Bodies are streamed and cut at the byte cap.
- `.xml.gz` is decompressed with a hard output limit.
- Documents declaring XML entities are refused.
- lxml runs with entity resolution, DTD loading and network access off.

Truncation is reported per domain (`truncated`, `sitemaps_skipped`). When a
domain is truncated, its counts are samples, not totals.

**Page-type taxonomy** (by URL path; first rule that matches wins):

| Page type | Match | Funnel | Route |
|---|---|---|---|
| alternatives | any segment contains "alternative" | BOFU | seo-competitor-pages |
| comparison | a segment with `-vs-` / `versus`, or starting `compare`/`comparison` (not under /pricing) | BOFU | seo-competitor-pages |
| pricing | pricing, prices, price, plans | BOFU | seo-content-brief |
| customers | customers, case-studies, customer-stories, success-stories, testimonials, work, portfolio, showcase | BOFU | seo-content-brief |
| services | services, service, what-we-do, offerings (agency / local service pages) | BOFU | seo-content-brief |
| locations | locations, cities, areas, service-areas, stores, offices | BOFU | seo-programmatic |
| integrations | integrations, connectors, marketplace, apps, extensions, plugins | MOFU | seo-programmatic |
| features | features, capabilities, platform, tour, how-it-works | MOFU | seo-content-brief |
| solutions | solutions, use-cases, for, teams, roles | MOFU | seo-content-brief |
| industries | industries, sectors, verticals | MOFU | seo-programmatic |
| templates | templates; or slug ending in -template(s) | MOFU | seo-programmatic |
| tools | tools, calculators, generators, checker, grader; or slug ending in -calculator / -generator / -checker | MOFU | seo-content-brief |
| glossary | glossary, dictionary, definitions, wiki, what-is; or slug starting what-is- | TOFU | seo-programmatic |
| blog | blog, articles, news, insights, guides, learn, resources, academy | TOFU | seo-cluster |
| docs, careers, legal, company, home, other | (support, hiring, policy, about/contact/partners, root, unmatched) | none | not a gap format |

The type is decided in this order:
1. Alternatives.
2. Comparison.
3. The first path segment, read left to right, that matches a vocabulary.
4. Slug patterns (-template, -calculator / -generator / -checker / -grader,
   what-is-), applied only when no segment matched.

Locale prefixes such as `/en/` simply do not match. So
`/docs/integrations/slack` is **docs**, while `/integrations/slack` is
**integrations**.

**Format gaps.** For each funnel-bearing page type that at least one
competitor publishes:
- **missing**: we have 0 pages of this type.
- **thin**: the median count among competitors that have the type is ≥ 5,
  and our count is below 25% of that median.

Sort order:
1. missing before thin
2. funnel weight (BOFU 1.0 > MOFU 0.6 > TOFU 0.25)
3. number of competitors with the format
4. median count

Missing BOFU/MOFU formats (comparison, alternatives, integrations,
templates, tools) are usually the fastest lead-generation wins.

**Topic gaps.**
- The topic of a URL is the token set of its slug. The slug is the last
  path segment that is not an ID. Tokens are stopword-free and
  plural-folded; numbers and noise tokens are dropped.
- These page types are skipped: docs, careers, legal, company, home,
  customers and pricing.
- A competitor topic is **covered** when any of our URLs (of any type) has
  a slug-token Jaccard ≥ 0.5 with it.
- Uncovered topics are grouped across competitors by greedy best-fit
  Jaccard ≥ 0.5, **within one page type**. Each topic therefore has one
  format, funnel and route. Without this, a short slug such as
  `/integrations/hubspot` would merge with a `hubspot-alternatives` topic.

Sort order:
1. number of competitors covering the topic, descending
2. best funnel among its page types
3. page count

The list is capped by `--max-topics`, and the full count is reported.

## 3. What this cannot tell you

- **Sitemaps are not rankings.** A content gap shows that a competitor
  *published* something, not that the page ranks or converts. Confirm with
  ranking data (Section 1) or a SERP check before building.
- **Slugs are not content.** We may cover a topic under a different URL.
  Every topic gap is **INFERRED** until the matching own page is checked.
- **Missing sitemaps hide pages.** Sites often omit pages from sitemaps.
  A competitor with no discovered URLs is excluded and named in the
  limitations.
- **Exports are snapshots.** They come from one date, location and device,
  and providers sample SERPs differently.
- **GSC positions differ from rank-tracker positions.** If the own file is
  GSC rows, its positions are impression-weighted averages. Competitor
  positions come from a rank database, so compare the two with care.
