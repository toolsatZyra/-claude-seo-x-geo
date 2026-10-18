---
name: seo-competitors
description: >
  Competitor analysis hub. Confirms 3-7 competitors from the project profile,
  then runs the keyword gap (moat / battleground / gap / pioneer from ranking
  exports), the content and format gap (free, from competitor sitemaps), the
  backlink gap, the AI citation gap and comparison-page routing, and ends with
  a battlecard per competitor. Use when user says "competitor analysis",
  "competitive analysis", "keyword gap", "content gap", "what are competitors
  ranking for", "competitor keywords", "who are my competitors", "gap
  analysis", or "battlecard".
user-invocable: true
argument-hint: "[keywords|content|full] [domain] [competitor...]"
license: MIT
metadata:
  author: ZYRA
  version: "3.1.0"
  category: seo
---

# Competitor Analysis

This skill answers four questions:
- Where are competitors winning search, answer-engine and link equity that
  we are not?
- Which of those gaps are worth closing for leads?

**How this differs from `seo-competitor-pages`.** That skill *writes*
"X vs Y" and "alternatives to X" pages. This skill *finds and ranks* the
gaps, and routes comparison gaps there.

**Scripts** live in the plugin root `scripts/`: `competitor_gap.py`, plus
`seo_project.py` for the profile. The method and thresholds are in
`references/gap-segmentation.md`.

## Quick Reference

| Command | What it does |
|---|---|
| `/seo competitors full <domain>` | Steps 1-7 below, ending with battlecards |
| `/seo competitors keywords <domain>` | Keyword gap from ranking exports (paid tier, or client-supplied exports) |
| `/seo competitors content <domain> [competitor...]` | Format and topic gap from public sitemaps (free) |

## Step 1: Confirm 3-7 competitors

1. Load the profile: `python3 scripts/seo_project.py show <domain> --json`.
   Use its `competitors` list (name, domain, aliases).
2. If there are fewer than 3 competitors, or none, propose candidates and ask
   the user to confirm. Never silently add a competitor. Record the choice:
   - `seo_project.py add-competitor <domain> <competitor> --name <Name>`
   - `seo_project.py note <domain> "Competitor set confirmed" --approved-by user`
3. Keep two kinds of competitor distinct:
   - **Business competitors**: who the client sells against. These come from
     the client.
   - **Search competitors**: who ranks for the client's keywords. They are
     evidenced by `overlap_with_own` in Step 2, or by
     `/seo dataforseo competitors <domain>`.

   A domain can be one without the other. Report both, and say which list
   each recommendation is based on.

## Step 2: Keyword gap (needs ranking data)

A true keyword gap needs **third-party ranking data** for every domain.
Search Console only covers your own site. Obtain one export per domain:
- `/seo dataforseo ranked <domain>`, saving the raw JSON (cost-check first
  with `python3 scripts/dataforseo_costs.py check <endpoint> --count N`)
- Ahrefs "Organic keywords" CSV
- Semrush "Organic Research → Positions" CSV

Then run:

```bash
python3 scripts/competitor_gap.py keywords --project example.com \
    --own own_ranked.json --competitor rival=rival.csv --competitor other=other.json \
    --universe scored.json --threshold 20 --json > keyword_gap.json
```

The output has four segments. "Ranks" means position ≤ 20.

| Segment | Meaning | Ordered by |
|---|---|---|
| moat | Only we rank | volume, then our position |
| battleground | We and ≥ 1 competitor rank; `leader` and `position_delta` (positive = they lead) | competitor-led first, then opportunity score |
| gap | ≥ 1 competitor ranks, we don't | `gap_priority` (opportunity score with intent-based lead value), then number of competitors ranking, then best competitor position |
| pioneer | In `--universe`; nobody ranks | opportunity score |

Two exclusions apply by default: own-brand navigational queries, and
competitor-navigational queries such as "rival login". "rival vs <us>" is
kept as a gap. Gaps with
comparison intent or a competitor term are routed to
`seo-competitor-pages`, and BOFU gaps carry `bofu: true`.

**Without ranking data**, skip this step and say so in the tier disclosure.
Do not pass off the free content gap as a keyword gap.

## Step 3: Content and format gap (free)

```bash
python3 scripts/competitor_gap.py content --project example.com \
    --max-urls 2000 --max-sitemaps 20 --json > content_gap.json
# offline: --input inventory.json  ({"domains": {"example.com": [urls], ...}})
```

The script reads each domain's sitemaps through `url_safety` (SSRF-safe),
with byte, file and URL caps. It classifies every URL into a page type and
reports:
- **format gaps**: page types competitors publish that we lack (`missing`) or
  publish far fewer of (`thin`). BOFU/MOFU formats come first.
- **topic gaps**: competitor slugs with no own slug at Jaccard ≥ 0.5, ranked
  by how many competitors cover them.

This is an approximation. Every topic gap is **INFERRED** until someone
checks that we really lack the content.

## Step 4: Backlink gap

Route to `seo-links`: `/seo links gap <domain>` (it runs `scripts/link_sources.py`
and `scripts/link_gap.py` on one source for the client and every profile
competitor). Report the gap segment (domains linking to 2+ competitors but not
to us) with its coverage, then `/seo links prospects` for the ranked list.

## Step 5: AI citation gap

Route to `geo-share-of-voice` and use its competitor table. For each
competitor it gives mention rate, citation share and confidence interval
across the prompt panel. Report AI share of voice as a separate outcome
metric. Never blend it into the SEO or AEO readiness scores.

## Step 6: Comparison and alternatives pages

Collect the gaps with `route: seo-competitor-pages`, plus any `comparison` or
`alternatives` format gap. Hand them to `seo-competitor-pages` with the
competitor names, their best-ranking URLs, and the keyword list. Its fairness
and data-accuracy rules apply.

## Step 7: Battlecards

Write one battlecard per competitor, using only Steps 2-6 evidence:

```markdown
### Battlecard: <Competitor> (<domain>), <date>
**Competitor type:** business / search / both (overlap_with_own = 0.42) [CONFIRMED]
| Dimension | Them vs us | Evidence | Tag |
|---|---|---|---|
| Keyword gap | ranks for 37 keywords we don't (12 BOFU) | keyword_gap.json | CONFIRMED |
| Battlegrounds they lead | 9, median delta +4.0 | keyword_gap.json | CONFIRMED |
| Formats we lack | comparison (14 pages), integrations (41) | content_gap.json | CONFIRMED |
| Topic gaps | "sales pipeline stages" + 11 more | slug match only | INFERRED |
| Link gap | 63 referring domains we lack | seo-backlinks (Moz) | CONFIRMED |
| AI share of voice | 31% vs our 12% (n=60, thin) | geo-share-of-voice | CONFIRMED |
**Why they win (hypotheses, not findings):** 1) ... 2) ... [INFERRED]
**Counter-moves:** (each with observation, dependency, how we'd know it
failed, and a leading indicator)
```

## Output rules

- **Data tier disclosure first.** State which steps ran on paid exports,
  which ran on free sitemaps, and which were skipped.
- **Tag every finding.**
  - Counts, positions and segment membership are CONFIRMED.
  - Explanations of why a competitor wins, topic gaps and traffic forecasts
    are INFERRED.
  - When several causes are plausible, list them as numbered hypotheses.
- **Give every recommendation four parts:**
  - the first-principle observation it rests on
  - its dependency on other work
  - how we would know it failed (for example, "gap keyword not in top 20
    eight weeks after publishing")
  - a leading indicator (for example, GSC impressions for the new URL)
- **Compute sums with a tool call.** Any total quoted in prose must come from
  a tool call (Rule 4).
- Prioritize lead-generation formats in this order: BOFU gaps, then missing
  BOFU/MOFU formats, then battlegrounds within 5 positions, then everything
  else.

## Error handling

| Situation | Response |
|---|---|
| No ranking exports | Run Step 3 only; label the keyword gap "not measured" |
| No URLs for our own domain | `content` exits 1, because every competitor format would look "missing". Fix the sitemap or pass `--input` |
| A competitor has no discoverable sitemap | It is excluded and named in `limitations`; try `seo-firecrawl` for a crawl-based inventory |
| Inventory truncated by caps | Report `truncated`. "Thin" format gaps are approximate; raise the caps deliberately |
| DataForSEO budget check returns `blocked` | Stay on exports or the free tier and disclose it |
| GSC rows used as the own file | Note that positions are impression-weighted averages, unlike competitor rank-tracker positions |

After delivering the report, offer: "Generate a PDF report? Use `/seo google report`".
