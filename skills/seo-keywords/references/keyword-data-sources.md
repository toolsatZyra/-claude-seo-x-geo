# Keyword data sources: tiers, what each can and cannot tell you

Pick the highest tier the client can support. Disclose the tier in every
report. Never present a number that the chosen tier cannot produce. For
example, autocomplete never supplies search volume.

## Tier matrix

| Tier | Source | How it enters `keyword_research.py` | Cost / access |
|---|---|---|---|
| Free | Google autocomplete (suggest endpoint) | `suggest` | Free, unofficial; rate-limited + cached |
| Free | Google Search Console (own site) | `gsc --project` / `--property` / `--input` | Client grants access (see `client_preflight.py`) |
| Credentialed | Google Ads Keyword Planner | `keyword_planner.py ideas\|volume --json > kp.json`, then `score --input kp.json` | Ads developer token + customer ID |
| Paid | DataForSEO (extension) | `/seo dataforseo keywords\|volume\|difficulty\|intent\|ranked` saved as JSON → `score --input` | Per request; gate with `dataforseo_costs.py check` |
| Paid import | Ahrefs / Semrush / SE Ranking exports | CSV/TSV → `score --input` | The client's or operator's subscription |

## What each source can and cannot tell you

| Question | Autocomplete | GSC | Keyword Planner | DataForSEO | Ahrefs / Semrush |
|---|---|---|---|---|---|
| Keyword ideas | Yes (what people type) | Own queries only | Yes | Yes | Yes |
| Search volume | **No** | Impressions only, for own site | Yes (bucketed without ad spend) | Yes (Ads-derived) | Yes (modelled) |
| SEO difficulty | No | No | **No** (competition = paid ads) | Yes (their KD model) | Yes (their KD scale) |
| Own position | No | Yes (impression-weighted average) | No | Yes (`ranked`) | Yes (organic export) |
| Competitor positions | No | **No** | No | Yes (`ranked`, `intersection`) | Yes |
| Intent | Rule-based via `classify_intent` | Same | Same | Provider label + ours | Semrush label + ours |
| SERP features / PAA | No | No | No | Yes (SERP API) | Partial |

## Source notes

**Google autocomplete.**
- Endpoint: `https://suggestqueries.google.com/complete/search?client=firefox&hl=<lang>&gl=<country>&q=<query>`.
- It returns `[query, [suggestions...]]`. It is undocumented and not a
  published API, so it can change or start blocking at any time.
- The script runs one request per second by default, caps requests with
  `--max-requests` (default 60), and caches responses for 7 days under
  `<data root>/cache/suggest/` with 0600 file permissions.
- It stops sending requests after an HTTP 403, 429 or 503. Every output is
  labelled `google_suggest (unofficial, no volume data)`.
- Suggestions vary by `hl`/`gl` and drift over time. Treat them as a demand
  *signal*, not a measured quantity.

**Google Search Console.**
- Covers your own site only.
- Position is an impression-weighted average, not a SERP rank.
- Query rows omit anonymized queries. An Ahrefs study put these at roughly
  46% of clicks, so row sums undercount the property totals.
- Data lags 2-3 days, and the script ends its window 3 days before today.
- History goes back about 16 months. The API returns at most about 50k rows
  per day per search type.
- Access is granted per property form (`sc-domain:` vs URL prefix). Use the
  exact string from the profile (`gsc_property`).

**Google Ads Keyword Planner** (`scripts/keyword_planner.py`).
- Requires an approved developer token.
- Accounts without active spend receive **bucketed ranges** ("1K – 10K"),
  which the score step converts to the geometric midpoint and keeps as
  `volume_range`.
- Close variants are grouped.
- `competition` / `competition_index` measure **paid-ad** competition. They
  are not SEO difficulty and are never used as difficulty.

**DataForSEO** (`seo-dataforseo` extension).
- Keyword ideas/suggestions, search volume, keyword difficulty, search
  intent, ranked keywords per domain, and domain intersection.
- Each call costs money. Run `python3 scripts/dataforseo_costs.py check
  <endpoint> --count N` first and get approval when the result says
  `needs_approval`.
- Save the raw JSON. The score step reads the envelope
  (`tasks[].result[].items[]`) or bare item lists.

**Ahrefs / Semrush / SE Ranking exports.**
- Columns are detected case-insensitively:

  | Field | Accepted column names |
  |---|---|
  | keyword | keyword, query, search term, keyphrase |
  | volume | volume, search volume, avg. monthly searches |
  | difficulty | KD, keyword difficulty, difficulty |
  | position | position, current position, rank |
  | url | url, current url, page |
  | cpc | cpc |

- UTF-16 tab-separated exports with preamble lines (the Keyword Planner
  download format) are handled.
- KD scales differ between providers. When providers disagree, the merge
  keeps the highest value.
- Volumes are modelled estimates. They are not Google's numbers.

## What we refuse to do

- **No scraping of google.com/search** (People Also Ask, related searches,
  organic results). Google's robots.txt disallows `/search` and its terms
  prohibit automated querying. PAA and SERP features come only from the
  DataForSEO SERP API.
- No volume or difficulty is invented for free-tier keywords. Those fields
  stay null, count as neutral (0.5) in the score, and `completeness` shows the gap.

## Data-tier disclosure (put this at the top of every keyword report)

> **Data tier:** Free (autocomplete + Search Console, 2026-07-17..2026-10-14).
> No search volume or difficulty data: opportunity scores use lead value and,
> for queries the site already ranks for, current position (completeness
> 0.30-0.45). CTR expectations use the
> site-calibrated curve (4 buckets). Add Keyword Planner or DataForSEO to
> raise completeness.
