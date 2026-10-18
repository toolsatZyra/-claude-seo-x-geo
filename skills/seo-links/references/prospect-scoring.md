# Prospect scoring

The scoring is deterministic: the same snapshot always gives the same scores.
It is implemented in `scripts/link_gap.py`.

## Formula

score = round_half_up(30·O + 20·A + 20·T + 10·M + 10·Q + 10·V)

| Signal | Definition | Unknown value |
|---|---|---|
| O, competitor overlap | min(k, 3) / 3, where k is the number of competitors the domain links to | (never unknown) |
| A, authority | DataForSEO domain rank / 1000, or Moz DA / 100 (CSV: DR or AS / 100) | 0.5 |
| T, topic fit | min(m, 3) / 3, where m is the number of distinct topic terms found as whole phrases (plural-folded) in the sample title, URL or anchor. The terms are the profile `topics`; if the profile has none, the 10 commonest sitemap slug tokens, derived once and stored in the links store | 0.5 when there is no text or no topics |
| M, market fit | 1.0 for a same-country ccTLD; 0.5 for com, org, net, io, co, ai; 0.2 for any other ccTLD | (never unknown) |
| Q, link quality | 1.0 if any sampled link is dofollow; 0.0 if all are nofollow or UGC | 0.5 |
| V, type value | publication or association 1.0; resource or partner 0.8; event or podcast 0.7; directory or blog 0.6; unclassified 0.5; community 0.3 | (never unknown) |

**Comparability.** Scores compare within one run, which uses one source. Authority from different sources is not comparable.

## Excluded before scoring

The order is fixed, and each exclusion is reported with its reason (and counted in `excluded_counts`):
1. `own_property`: the client's own domain or subdomain;
2. `competitor_property`: a competitor's domain;
3. `social_ugc`: social, user-generated and portfolio platforms (LinkedIn, Facebook, X, Instagram, YouTube, Pinterest, TikTok, Medium, Threads, Behance, Dribbble);
4. `staging_or_dev_host`: a staging or preview site. Either a platform host (`*.wpengine.com`, `*.kinsta.cloud`, `*.netlify.app`, `*.vercel.app`, `*.herokuapp.com`, `*.pages.dev`, `*.hostingersite.com`), or a subdomain label that starts with `staging`, `stage`, `dev`, `test`, `uat` or `preview` (followed by a non-letter), or has `stage`/`staging` as a hyphenated part of its label. `dev.to`, `stage.com` and `backstage.io` are kept;
5. `spam`: spam score ≥ 60;
6. `paid_or_scheme`: a `sponsored` attribute, or one of these whole words in the sample URL, title or anchor (dashes and underscores read as spaces): sponsored, advertorial, guest post pricing, buy backlinks, link insertion, paid post, backlink(s), seo links, buy links, dofollow, link building service(s), guest post service(s). `write-for-us` is not a signal;
7. `link_network`: the same distinctive sample path (two or more segments, a long last one, language prefix ignored) or the same title (at least 3 words and 20 characters, not a CMS default) on at least 5 distinct organizations in one competitor snapshot. Organizations are counted by registrable label, so one company on several country domains is not a network. The excluded entry's `detail` names the footprint.

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

**Gap first is presentation, not scoring.** The formula is unchanged, so a strong single-competitor site can outscore a weak gap site. `gap_prospects` lists the gap segment alone in the same relative order; `add` takes gap domains before single ones.

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

Rules 1-6 look only at the **first path segment** (after a language prefix such as `/en/` or `/id/`) when it is a short slug of at most two words, and at the words of the domain itself. A token deeper in the path, in a long article slug, or in the page title does not count, so a blog post that mentions "partner" or "agencies" is still a blog post. The one title exception is the ranking listicle `top N … companies|agencies` ("tools for agencies" is not one).

| # | Type | Rule |
|---|---|---|
| 1 | directory | A known listing or profile host (Clutch, GoodFirms, DesignRush, G2, Capterra, Sortlist, The Manifest, UpCity, Trustpilot, Crunchbase, IndiaMART, Justdial, Sulekha, TradeIndia, CB Insights, Golden, Dealroom, Wellfound, Tracxn, Owler, Zaubacorp), unless the path starts with `/blog` or the host is `blog.`/`learn.`; or a first segment of directory, listing(s), companies, company, vendors, agencies, organization(s), profile(s), wiki, apps, startups; or one of the directory words as a label of the domain; or a `top N … companies|agencies` listicle in the path or title |
| 2 | association | `.edu`, `.gov`, `.mil`, `.ac.xx`, `.gov.xx`, or the tokens association, society, council, chamber, institute (first segment or domain) |
| 3 | community | reddit, quora, stackexchange, stackoverflow, or the tokens forum, community (first segment or domain) |
| 4 | event | podcast, episode, conference, summit, webinar, expo, awards, event (first segment or domain) |
| 5 | resource | first segment resources, resource, links, tools, recommended (so `useful-links` and `recommended-tools` match; `useful-tips` does not) |
| 6 | partner | first segment partners, integrations, marketplace, customers, clients |
| 7 | publication | authority ≥ 60 and an article path (`/news/`, `/article/`, `/YYYY/MM/`), or news, magazine, journal or times inside a domain label, or media as a whole label or hyphen part (`my-media.com`, not `antillesdigitalmedia.com`) |
| 8 | blog | a `blog.` or `learn.` subdomain, or a `/blog/` path |
| 9 | unclassified | anything else |
