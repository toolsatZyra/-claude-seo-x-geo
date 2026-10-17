---
name: seo-content-engine
description: >
  Draft-first content pipeline with human checkpoints: project profile,
  keyword selection (BOFU first for lead generation, plus answer-engine
  friendly TOFU), cannibalization pre-check, a 30-day content calendar with a
  scaled-content volume guard, briefs, source-linked answer-first drafts,
  quality gates (claims, quality, citability, optimizer, schema), mandatory
  human review, export as a CMS draft (WordPress, HMAC-signed webhook, HTML
  bundle) and re-measurement at +14/+28 days. Never auto-publishes. Use when
  user says "content calendar", "content plan", "write articles", "blog
  autopilot", "content engine", "publish to WordPress", "outrank", or
  "content pipeline".
user-invocable: true
argument-hint: "[plan|brief|draft|check|export|measure] <domain|file> [args]"
license: MIT
metadata:
  author: ZYRA
  version: "3.1.0"
  category: seo
---

# Content Engine (draft-first, human-reviewed)

This skill runs the same pipeline content autopilots such as Outrank sell
(product profile, keywords, calendar, article generation, CMS export), with
the controls those tools leave out. Every article is a **draft** until a named
person has reviewed it, unsupported claims are marked rather than invented,
publishing volume is checked against the site's size, and nothing is sent to
a CMS without the operator's explicit confirmation.

**Scripts** (plugin root `scripts/`): `seo_project.py` (profile),
`content_export.py` (calendar validation, publishing gates, HTML/webhook/
WordPress export), `content_optimizer.py` (competitor coverage),
`content_verify.py`, `content_quality.py`, `content_humanize.py`,
`citability_scorer.py`, `schema_generate.py`, `iptc_ai_label.py`,
`drift_baseline.py`, `rank_tracker.py`.

## Non-negotiables

1. **Draft is the default everywhere.** Front matter can never escalate a
   status on its own; `publish` needs `--status publish`, a passing
   `check --for publish`, and the operator's explicit "yes, publish <title>"
   in chat **for that article**. One confirmation never covers a batch.
2. **Nothing scheduled publishes itself.** The calendar plans work; it does
   not trigger exports.
3. **No invented facts.** A claim without a source you actually opened gets
   `[needs source]`. The publish gate blocks every unresolved marker.
4. **Volume guard.** Many new pages relative to the site's indexed pages is
   the pattern Google's scaled-content-abuse policy targets; the calendar
   check flags it (thresholds in
   [content-calendar-format.md](references/content-calendar-format.md)).
5. **Refused outright:** link exchanges, paid or automated link placement,
   scraping Google results or People-Also-Ask, publishing unreviewed AI text.
6. **Evidence tags.** Every finding in a gate report is CONFIRMED (tool
   output) or INFERRED (reasoning), per scoring-rubric Rule 9.

Every gate and the reason it exists:
[publishing-gates.md](references/publishing-gates.md).

## Quick Reference

| Command | Steps | Tools |
|---|---|---|
| `/seo content-engine <domain>` | Whole pipeline, stopping at every checkpoint | all below |
| `/seo content-engine plan <domain>` | 0-3: profile, keywords, cannibalization pre-check, calendar | `seo_project.py`, `seo-keywords`, `gsc_query.py`, `content_export.py calendar` |
| `/seo content-engine brief <calendar item>` | 4 | `seo-content-brief` |
| `/seo content-engine draft <calendar item>` | 5 | `fetch_page.py`, brief, profile voice samples |
| `/seo content-engine check <file.md>` | 6 | gate table in Step 6 |
| `/seo content-engine export <file.md> [bundle\|wordpress\|webhook]` | 7-8 | `content_export.py` (dry run first) |
| `/seo content-engine measure <domain>` | 9 | `drift_baseline.py`, `rank_tracker.py`, `gsc_inspect.py` |

## Step 0: Project profile

```bash
python3 scripts/seo_project.py show example.com --json
```

If no profile exists, create one (`seo_project.py init ...`). The engine
needs: `brand_terms`, `competitors` (3-7), `money_pages`,
`conversion_events`, `voice_samples` (URLs or local paths of on-brand posts),
`content.cadence_per_week` and `content.cms`. Ask the operator for missing
values; do not guess. Record decisions with
`seo_project.py note example.com "<decision>" --approved-by user`.

## Step 1: Keyword selection

Run `seo-keywords` (`/seo keywords plan <seed> --project example.com`) and
reuse its intent, funnel, opportunity and GEO-format fields. Ordering rule
for lead-generation sites:

1. **BOFU first** (transactional, comparison, alternatives, pricing): these
   produce leads.
2. **MOFU** next (best-of, how-to-choose, use cases).
3. A deliberate share of **TOFU questions** with GEO flags (question,
   definition, how_to): they earn AI-answer citations and topical authority.

Default mix for lead generation is roughly half BOFU, a third MOFU, the rest
TOFU; the operator approves or changes it. Publishers and pure-awareness
sites can invert it. Each keyword keeps its source (GSC, Keyword Planner,
DataForSEO, autocomplete) so volume claims stay traceable.

**Checkpoint:** operator approves the keyword list.

## Step 2: Cannibalization pre-check

Before scheduling, make sure the site does not already have a page for each
keyword:

```bash
python3 scripts/gsc_query.py --property sc-domain:example.com --days 90 \
    --dimensions query,page --limit 25000 --json > qp.json
python3 scripts/content_export.py calendar calendar.json \
    --query-page qp.json --existing-urls site-urls.txt --indexed-pages 240
```

`site-urls.txt` is one URL per line from the XML sitemap (`seo-sitemap`) or a
crawl. Rules:

- A page already getting impressions for the keyword: make the item
  `kind: "refresh"` targeting that URL and hand it to `seo-refresh`, rather
  than writing a competing page.
- A planned slug that already exists: refresh, or pick a distinct angle.
- Two planned items for the same keyword: merge them (the check blocks this).

## Step 3: Calendar

Write the calendar JSON described in
[content-calendar-format.md](references/content-calendar-format.md): one
keyword per item, dated by the profile cadence (`content.cadence_per_week`,
default 2), each with `article_type`, `expected_length`, `internal_links`,
`instructions` and `quality_questions`. Derive `expected_length` from the
competitor median (Step 6 optimizer or the brief), never from a word-count
target.

Validate it; fix every error before showing it:

```bash
python3 scripts/content_export.py calendar calendar.json --indexed-pages 240 --json
```

State where the indexed-page count came from (GSC Pages report, sitemap
count) and tag it CONFIRMED or INFERRED. Keep the calendar in the client's
working folder, never in this repository.

**Checkpoint:** operator approves the calendar, including any volume-guard
warning.

## Step 4: Brief per item

Run `/seo content-brief <keyword> <page-type>`. Add to the brief:

- 3-10 **competitor URLs** that rank for the keyword, supplied by the
  operator or taken from DataForSEO SERP data. Never scrape Google.
- The **answer-first statement**: the one or two sentences that answer the
  query on their own.
- **Information gain**: at least one thing the top pages lack (first-party
  data, a worked example, an expert quote the client can supply, a tested
  template).
- Facts that need sources, and the internal links from the calendar item.

## Step 5: Draft

1. Read the competitor pages in full through `fetch_page.py` (SSRF-safe).
   Learn what they cover; do not copy their wording or structure.
2. Every statistic, price, date-sensitive fact or study gets an inline link
   to the primary source you opened. No source: write `[needs source]`.
   Never invent numbers, quotes, studies or customer stories.
3. Answer first: the page's main answer sits in its first 30%, and each H2
   opens with a self-contained answer in 1-3 sentences. Use question
   headings where the searcher asks a question.
4. Brand voice: read the profile's `voice_samples` and match tone, sentence
   length and terminology. Do not reuse their content.
5. Add the calendar item's internal links with descriptive anchors.
6. Where readers would ask how the article was made, say that AI assisted and
   a named person reviewed it (Google's Who/How/Why test).
7. Save `<slug>.md` with front matter in the `content_export.py` format,
   `status: draft` and an **empty** `reviewed_by`.

## Step 6: Quality gates

Run all of them and report a table (gate, result, evidence, CONFIRMED or
INFERRED). Fix and re-run until the blocking gates pass.

| Gate | Command | Blocks when |
|---|---|---|
| Claims | `python3 scripts/content_verify.py draft.md --json` | an uncited claim you cannot source (mark it `[needs source]`); uncited ratio above 0.4 |
| Quality | `python3 scripts/content_quality.py draft.md --json` | `overall_quality` below 60, or `filler` / `ai-patterns` flags |
| Phrasing | `python3 scripts/content_humanize.py draft.md -o draft.clean.md` | never blocks; review the diff before accepting it |
| AEO citability | `python3 scripts/content_export.py check draft.md --aeo` | never blocks; rewrite sections scoring below 50; report separately from SEO scores |
| Coverage | `python3 scripts/content_optimizer.py analyze --keyword "<kw>" --page-file draft.md --competitor <url> ...` | never blocks; close real topic and question gaps, never stuff terms (density above 3% is flagged) |
| Schema | `seo-schema` / `schema_generate.py`; save JSON-LD and set `schema:` in front matter | JSON that does not parse (export gate) |
| AI images | `python3 scripts/iptc_ai_label.py audit <dir>`, then `inject` for AI-generated images | missing IPTC label on an AI image; any image without alt text (export gate) |
| Export gates | `python3 scripts/content_export.py check draft.md --for draft` | any error in [publishing-gates.md](references/publishing-gates.md) |

Use Article or BlogPosting schema with the reviewer or author as a Person.
Add FAQPage only for a genuine FAQ section that is visible on the page.

## Step 7: Human review (mandatory)

The reviewer checks every fact against its source, resolves or removes every
`[needs source]`, answers the calendar item's `quality_questions`, and checks
claims about products, pricing, legal or health topics. Then they set
`reviewed_by: <their name>`. **Never fill `reviewed_by` yourself**; only the
reviewer, or the operator naming the reviewer in chat, may set it. Then:

```bash
python3 scripts/content_export.py check draft.md --for publish
```

## Step 8: Export

Always a dry run first; show the operator what would be sent; add
`--confirm` only after they approve in chat.

```bash
# Local bundle: <slug>.html (noindex until status publish), <slug>.json, <slug>.md
python3 scripts/content_export.py bundle draft.md --out-dir out/

# WordPress draft, idempotent by slug (Application Password in an env var)
python3 scripts/content_export.py wordpress draft.md --site https://example.com --user editor
python3 scripts/content_export.py wordpress draft.md --site https://example.com --user editor --confirm

# Outrank-compatible webhook, HMAC-SHA256 signed (X-Signature-SHA256).
# Drafts are sent as event save_draft; publish_articles/update_article need the publish gates.
python3 scripts/content_export.py webhook draft.md --url https://hooks.example.com/content \
    --secret-env CONTENT_WEBHOOK_SECRET
```

The operator puts secrets in environment variables themselves (for example
`export WP_APP_PASSWORD=...` in their own shell); never ask them to paste a
secret into chat, and never pass one as a command-line value. Publishing
(`--status publish`) follows the rule in Non-negotiable 1. A live WordPress
post is never downgraded: updating one needs `--status publish` and the
publish gates.

## Step 9: Measure

When the article is live:

```bash
python3 scripts/drift_baseline.py https://example.com/blog/<slug>
python3 scripts/rank_tracker.py add --project example.com "<keyword>" --tag bofu \
    --tag content:2026-11 --target-url https://example.com/blog/<slug>
python3 scripts/gsc_inspect.py https://example.com/blog/<slug> --site-url sc-domain:example.com
```

Re-check at **+14 and +28 days** with `/seo track report example.com` and
`/seo drift compare <url>`. To test a content pattern (for example
answer-first intros), tag treatment and control keywords before shipping and
judge with `rank_tracker.py experiment` (see `seo-track`).

Falsifiability per article: the leading indicator is impressions for the
target query within 28 days. No impressions at +28 days and not indexed:
fix indexing. Indexed but no impressions: the page probably mismatches the
query's intent (INFERRED; check the SERP). Impressions but position beyond
20 after 8 weeks: hand it to `seo-refresh`.

## How this differs from neighbouring skills

| Skill | Role |
|---|---|
| `seo-plan` | Strategy and site architecture. This skill executes the content part of a plan. |
| `seo-content-brief` | One brief. This skill calls it per calendar item. |
| `seo-refresh` | Existing pages that decay. Step 2 routes overlaps there. |
| `seo-content` | Audits a published page; its optimize mode is Step 6's coverage gate. |
| `seo-cluster` | Hub-and-spoke architecture; use it before Step 3 for large topics. |

## Output

For `plan`: approved keyword list (with sources), cannibalization pre-check
results, the validated calendar and its volume-guard figures. For `check`:
the gate table. For `export`: the dry-run summary (target, status, gates,
signed or not), then the result after confirmation. End every run with the
next human checkpoint.

## Error handling

| Situation | Action |
|---|---|
| No project profile | Stop; run `seo_project.py init` with the operator |
| No GSC access for the pre-check | Run the calendar check with `--existing-urls` only; say the query-level check was skipped |
| Fewer than 3 usable competitor pages | Optimizer exits 2; ask for more URLs or DataForSEO SERP data |
| A gate blocks | Report the findings; never bypass a gate or edit `reviewed_by` to pass it |
| Webhook secret or WordPress password env var unset | Dry run still works; ask the operator to set it in their shell |
| CMS returns 401/403 | Check user, Application Password and capabilities; never print the password |
