---
name: seo-refresh
description: >
  Search Console driven content refresh loop: finds decaying pages
  (year-over-year, seasonality-safe), diagnoses the cause (ranking loss,
  SERP feature or AI Overview, demand drop, cannibalization, lost
  visibility), picks refresh vs rewrite vs consolidate vs retire-review by
  rule, builds a refresh brief from the page's top queries, proposes a
  section-level diff for human approval, exports the update as a draft or
  reviewed update, and re-measures at +14/+28 days. Use when user says
  "content decay", "refresh content", "traffic drop", "update old posts",
  "improve existing pages", "AI Overview traffic loss", "content refresh",
  or "declining pages".
user-invocable: true
argument-hint: "[decay|candidates|brief|aio|export|measure] <domain|url|file>"
license: MIT
metadata:
  author: ZYRA
  version: "3.1.0"
  category: seo
---

# Content Refresh (GSC-driven improvements loop)

Existing pages that already rank are usually the cheapest traffic to win
back. This skill finds them in Search Console data, says why they slipped
(with the numbers), recommends one action per page by a fixed rule, and
walks each change through human approval before anything reaches the CMS.

**Scripts** (plugin root `scripts/`): `content_decay.py` (decay tiers,
causes, actions, improvement candidates), `content_optimizer.py`,
`content_export.py`, `drift_baseline.py` / `drift_compare.py`,
`rank_tracker.py`, `gsc_inspect.py`, `seo_project.py`.

**References:** [refresh-rules.md](references/refresh-rules.md) (decay tiers,
cause rules, decay-score weights, action rules, date hygiene) and
[aio-recovery.md](references/aio-recovery.md) (AI Overview recovery playbook).

## Quick Reference

| Command | What it does |
|---|---|
| `/seo refresh <domain>` | Steps 1-3: decay analysis plus improvement candidates, diagnosis and the approved action list |
| `/seo refresh decay <domain>` | `content_decay.py analyze --project <domain>`: decaying pages with tier, cause, action |
| `/seo refresh candidates <domain>` | `content_decay.py candidates --project <domain>`: high-impression pages at positions 4-25 with a CTR gap or slipping clicks |
| `/seo refresh brief <url>` | Refresh brief from the page's top queries, optimizer gaps and the decay diagnosis |
| `/seo refresh aio <url>` | AI Overview recovery playbook for one page |
| `/seo refresh export <file.md>` | Send the approved update (dry run first) |
| `/seo refresh measure <url>` | Re-check at +14 / +28 days |

## Step 1: Detect

```bash
python3 scripts/content_decay.py analyze --project example.com --json
python3 scripts/content_decay.py candidates --project example.com --json
```

Defaults: 90-day windows ending 3 days ago (GSC lag), compared with the same
90 days 52 weeks earlier. Without year-earlier data the script falls back to
the previous 90 days and says "seasonality NOT controlled" in
`baseline_reason`; repeat that caveat in the report. Tiers apply only when
the baseline had at least 20 clicks (`--min-baseline-clicks`): warning at
-20% clicks, high at -40%, critical at -60%. Money pages from the profile
sort first within a tier. Offline: `--input windows.json` (format in the
script docstring).

`candidates` is the Outrank-style improvements list: at least 500
impressions, average position 4-25, and a CTR below 0.7 of the expected CTR
for that position or clicks down 10% or more versus the previous window.
Each candidate carries its top queries, the input for the brief.

## Step 2: Diagnose

The script's `cause` is a rule-based inference (tagged INFERRED) over
CONFIRMED GSC numbers. Before acting, run the `action.verify_first` checks it
lists:

| Cause | First checks |
|---|---|
| `lost_visibility` | `gsc_inspect.py <url> --site-url <property>`: indexed, canonical, noindex, status code; `drift_compare.py <url>` if a baseline exists |
| `ranking_loss` | `drift_compare.py <url>`: did the title, H1, content or schema change? Who outranks it now for the top queries? |
| `serp_feature_or_ai_overview` | Check the top queries' SERPs for an AI Overview or other features (manual, dated, or DataForSEO); then [aio-recovery.md](references/aio-recovery.md) |
| `demand_drop` | Search interest for the top queries; if the baseline was the previous window, rule out seasonality |
| `cannibalization` | Which page should own each shared query (intent match, links, conversions) |

When more than one explanation fits, list them all (Rule 9). Never state a
Google update as the cause without a dated, primary-source announcement
that matches the drop.

## Step 3: Decide

The action comes from the rule table in
[refresh-rules.md](references/refresh-rules.md): `refresh`, `rewrite`,
`consolidate`, `redirect_or_retire_review` or `monitor`, with the rule ID
(`R1`-`R6`) shown. Retirement is always a **review** item for a human, never
a deletion, and is never suggested for money pages.

**Checkpoint:** the operator approves the action list before any rewriting.

## Step 4: Refresh brief

For each approved `refresh` or `rewrite`:

1. Top queries from `candidates` (or the GSC query × page export): the
   brief must serve the queries the page already earns impressions for.
2. Coverage gaps from the optimizer, using pages that rank for the main
   query (from the operator or DataForSEO, never scraped from Google):
   ```bash
   python3 scripts/content_optimizer.py analyze --keyword "<main query>" \
       --url https://example.com/blog/page --competitor <url> --competitor <url> --competitor <url>
   ```
3. `/seo content-brief <url>` in improve mode: keep what works, mark what is
   thin, outdated or missing.
4. For `serp_feature_or_ai_overview`, add the playbook's answer-first and
   quotable-passage requirements.

## Step 5: Section-level diff for approval

Do not hand over a rewritten article. Propose changes per section so the
operator can accept or reject each one:

```markdown
### Section: "How much does a CRM cost?"  [EDIT]
Reason: top query "crm cost per user" (1,240 impressions, pos 6.8) gets no
direct answer; competitors open with a price range. [CONFIRMED: GSC, optimizer]
Before (first 2 sentences): ...
After: ...
Sources added: <links>
Approve? yes / no / edit
```

Use `KEEP`, `EDIT`, `ADD` and `REMOVE` labels; every `EDIT` and `ADD` cites
its evidence; every new fact links to a source or carries `[needs source]`.
Keep the URL; a slug change needs a 301 and is a separate, explicit decision.

## Step 6: Gates, review and export

Apply only the approved sections to the Markdown source, then run the same
gates as `seo-content-engine` Step 6 and the publish check (updates usually
change live content):

```bash
python3 scripts/content_export.py check page.md --for publish --aeo
python3 scripts/content_export.py webhook page.md --url https://hooks.example.com/content \
    --event update_article                          # dry run; add --confirm after approval
python3 scripts/content_export.py wordpress page.md --site https://example.com --user editor \
    --status publish                                # live post; dry run first, --confirm after approval
```

`update_article` events and updates to live WordPress posts always need the
publish gates, a named `reviewed_by`, and the operator's explicit
confirmation in chat for that page.

**Dates:** change `dateModified` (and any visible "updated" date) only for a
substantive update, never to look fresh. Details in
[refresh-rules.md](references/refresh-rules.md).

## Step 7: Measure

Before shipping: `python3 scripts/drift_baseline.py <url>` and tag the page's
main queries in `seo-track`
(`rank_tracker.py add --project <domain> "<query>" --tag refresh:<yyyy-mm>`).
To learn whether refreshes work at all, tag a comparable set of unrefreshed
pages' queries as `control:<name>` and the refreshed ones as
`treatment:<name>`, then judge with `rank_tracker.py experiment`.

Re-check at **+14 and +28 days** (`/seo track report`,
`content_decay.py analyze` with `--as-of`). Expected leading indicators:

| Action | Indicator | Failure looks like |
|---|---|---|
| refresh / rewrite | position and clicks on the top queries recover toward baseline | no movement by +28 days: the diagnosis was probably wrong; revisit Step 2 |
| AIO recovery | CTR on the top queries; citation in the AI Overview | impressions hold, CTR keeps falling: see the playbook's segment rules |
| consolidate | the kept page gains the merged page's queries | both URLs still show for the queries: check the 301 and internal links |

## Output

1. Summary: pages analysed, tiers, baselines used (and the seasonality
   caveat when relevant), lost clicks in decaying pages.
2. Table per page: URL, money page, tier, clicks change and baseline, cause
   with evidence (INFERRED), action and rule ID, decay score with its
   expression, verify-first checks.
3. For approved pages: refresh brief, section diff, gate results, export
   dry run.
4. Falsifiability per recommendation: what we expect at +14/+28 days and
   what would show the action failed.

## Error handling

| Situation | Action |
|---|---|
| No profile or GSC property | `seo_project.py init` / set `gsc_property`; or use `--input` with exported rows |
| GSC error on the current window | Stop and report it (permissions or property string) |
| No year-earlier data | Proceed with the previous-window fallback and state the seasonality caveat |
| Query × page rows unavailable | Decay still works; cannibalization and top queries are skipped and the output says so |
| Page not in the profile's money pages but converts | Ask the operator to add it to `money_pages`, then re-run |
