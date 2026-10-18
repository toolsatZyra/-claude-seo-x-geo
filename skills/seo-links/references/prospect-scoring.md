# Prospect scoring

The scoring is deterministic: the same snapshot always gives the same scores.
It is implemented in `scripts/link_gap.py`.

## Formula

score = round_half_up(30·O + 20·A + 20·T + 10·M + 10·Q + 10·V)

| Signal | Definition | Unknown value |
|---|---|---|
| O, competitor overlap | min(k, 3) / 3, where k is the number of competitors the domain links to | (never unknown) |
| A, authority | DataForSEO domain rank / 1000, or Moz DA / 100 (CSV: DR or AS / 100) | 0.5 |
| T, topic fit | min(m, 3) / 3, where m is the number of distinct profile `topics` found as whole phrases (plural-folded) in the sample title, URL or anchor | 0.5 when there is no text or no topics |
| M, market fit | 1.0 for a same-country ccTLD; 0.5 for com, org, net, io, co, ai; 0.2 for any other ccTLD | (never unknown) |
| Q, link quality | 1.0 if any sampled link is dofollow; 0.0 if all are nofollow or UGC | 0.5 |
| V, type value | publication or association 1.0; resource or partner 0.8; event or podcast 0.7; directory or blog 0.6; unclassified 0.5; community 0.3 | (never unknown) |

**Comparability.** Scores compare within one run, which uses one source. Authority from different sources is not comparable.

## Excluded before scoring

The order is fixed, and each exclusion is reported with its reason:
1. own property;
2. competitor property;
3. social or user-generated platform;
4. spam score ≥ 60;
5. paid or link-scheme signal: a `sponsored` attribute, or `sponsored`, `advertorial`, `guest-post-pricing`, `buy-backlinks`, `link-insertion` or `paid-post` in the sample URL or title.

## Effort and buckets

Effort is never part of the score:
- **Low:** directory or review, partner or integration.
- **Medium:** resource, event, association, community, unclassified.
- **High:** publication, blog.

Buckets are checked in this order, so each prospect lands in exactly one:
1. high-value: score ≥ 70;
2. quick win: low effort and score ≥ 50;
3. backlog: everything else.

Ties are ordered by score, then k (descending), then domain (A→Z).

## Worked examples

**1. A gap publication.**
- Inputs: k = 2, rank 800, two topic phrases in the title, `.com` for an Indian client, dofollow, publication.
- Sum: 30·0.667 + 20·0.8 + 20·0.667 + 10·0.5 + 10·1 + 10·1 = 20 + 16 + 13.33 + 5 + 10 + 10 = 74.33.
- Result: **74**, high-value.

**2. A directory.**
- Inputs: k = 2, rank 700, no topic match, `.co`, dofollow, directory.
- Sum: 20 + 14 + 0 + 5 + 10 + 6 = 55.
- Result: **55**, a quick win (low effort).

**3. A blog with no data.**
- Inputs: k = 1, authority unknown, no topic match, `.net`, link type unknown.
- Sum: 10 + 10 + 0 + 5 + 5 + 6 = 36.
- Result: **36**, backlog.

**4. Rounding.**
- Inputs: k = 1, authority 52.5, neutral topic, `.com`, unknown link type, blog.
- Sum: 10 + 10.5 + 10 + 5 + 5 + 6 = 46.5.
- Result: **47**. It is rounded half up, never to even.

## Classification rules (first match wins; every type is INFERRED)

| # | Type | Rule |
|---|---|---|
| 1 | directory | A known listing host (Clutch, GoodFirms, DesignRush, G2, Capterra, Sortlist, The Manifest, UpCity, Trustpilot, Crunchbase, IndiaMART, Justdial, Sulekha, TradeIndia), or the tokens directory, listing, companies, vendors, agencies, or a `top-…-companies` path |
| 2 | association | `.edu`, `.gov`, `.mil`, `.ac.xx`, `.gov.xx`, or the tokens association, society, council, chamber, institute |
| 3 | community | reddit, quora, stackexchange, stackoverflow, or the tokens forum, community |
| 4 | event | podcast, episode, conference, summit, webinar, expo, awards, event |
| 5 | resource | path tokens resources, links, tools, useful, recommended |
| 6 | partner | path tokens partners, integrations, marketplace, customers, clients |
| 7 | publication | authority ≥ 60 and an article path (`/news/`, `/article/`, `/YYYY/MM/`), or news, magazine, journal, times or media in the domain name |
| 8 | blog | a `blog.` subdomain or a `/blog/` path |
| 9 | unclassified | anything else |
