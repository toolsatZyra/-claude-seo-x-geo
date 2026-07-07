# Deterministic Scoring Rubric

Every category skill that emits a `Score: XX/100` (Technical, On-Page,
Content Quality, Schema, Images, Performance) must compute it with the
fixed-criteria method below, not free-form judgment or an open-ended
severity deduction. Two runs against an unchanged page must produce the
same subscore, from the same stated evidence.

## Rule 1: Fixed criteria, not free-standing severity

Every scored category is broken into a small, named set of criteria whose
max point values sum to exactly 100. Each skill file defines its own
criteria table (see `seo-technical`, `seo-content`, `seo-schema`,
`seo-images`, `agents/seo-performance.md`). Do not invent, skip, merge, or
reweight criteria at scoring time — the table in that skill is the only
source of criteria and point values.

## Rule 2: Six-tier scale per criterion

Score every criterion on this scale, applied to that criterion's own max
points:

| Tier | % of max | Meaning |
|---|---|---|
| Excellent | 100% | Fully satisfies the criterion — no ambiguity, nothing to fix |
| Minor improvements needed | 80% | Satisfies the criterion; small, non-blocking gaps |
| Good but several weaknesses | 60% | Partially satisfies; multiple gaps but the core intent is met |
| Significant issues | 40% | Mostly unmet; gaps a reviewer would flag as a real problem |
| Poor | 20% | Barely present; only token/superficial evidence |
| Not implemented | 0% | Absent entirely, or could not be verified |

```
criterion_score = round(max_points x tier_percentage)     # round half up
category_score  = sum(criterion_score across that category's criteria)
```

Round at the criterion level, not just once at the end — per-criterion
rounding is what keeps two independent runs landing on the same integer,
since it removes the accumulated fractional drift that surfaced in testing.

### Sub-check tiering for criteria built from a checklist

Several criteria bundle a handful of named sub-checks (e.g. Crawlability's
"robots.txt valid," "sitemap valid," "no unintentional noindex," etc.).
For these, tier by the share of sub-checks satisfied:

```
tier_percentage = nearest of {0, 20, 40, 60, 80, 100} to
                   (sub-checks satisfied / total sub-checks) x 100
```

A criterion with only 4 or 5 sub-checks may never land on every tier
(e.g. a 4-sub-check criterion can only produce 0/25/50/75/100%, which
round to 0/20/60/80/100 — Poor is simply unreachable for that criterion).
That's fine; not every criterion needs all six tiers reachable. Each
skill's criteria table lists the sub-checks that count for that criterion
— do not add or drop a sub-check at scoring time.

### Proportion-based tiering for multi-instance criteria

Some criteria apply to many instances at once (e.g. "images have
dimensions set" across dozens of images, "titles are correctly sized"
across hundreds of pages). For these, tier by the share of instances that
fail the criterion, not by picking one representative instance:

| Tier | Failing share |
|---|---|
| Excellent | 0% |
| Minor improvements needed | <10% |
| Good but several weaknesses | 10-30% |
| Significant issues | 30-60% |
| Poor | 60-90% |
| Not implemented | >90%, or the check could not be run at all |

State the true count and denominator ("14 of 17 images") in the report
regardless of which tier that produces — never cap or truncate the count
for display, only for the tier lookup.

## Rule 3: Evidence is mandatory, not optional

For every criterion, before assigning a tier:

1. **State the specific evidence** — a quote, an HTML attribute, a
   measured number, a URL, a file path — or state **"No evidence found."**
2. Assign the tier **the stated evidence actually demonstrates**, never
   the tier that seems generically likely for a page like this one.
3. If evidence is absent for a criterion, the tier is **Not implemented
   (0%)** — do not assume good faith and award a higher tier because the
   feature "probably" exists elsewhere on the site. Absence of evidence is
   scored as absence of the feature, not as unknown-so-skip.
4. **Do not adjust a tier based on intuition**, overall impression of the
   site's quality, or how a *different* criterion scored. A well-built page
   can legitimately score Not Implemented on one narrow criterion it
   happens to miss, even if every other criterion is Excellent.
5. **Do not double-count.** If a single gap (e.g. "no author byline
   anywhere on the page") could plausibly trigger two differently-worded
   criteria, score it under the one criterion whose definition most
   specifically names that evidence, and explicitly state in the report
   which other criterion you deliberately did *not* also dock for the same
   gap, and why.

## Rule 4: Compute the final sum with a tool call, not prose arithmetic

A live two-run test of `geo-platform-optimizer` (same fixed-criteria method
as this file, run against an unchanged site) found that **neither run's
reported total matched its own itemized per-criterion evidence** — one run's
line items summed to 23 but it reported 38; the other's summed to 10 but it
reported 24. The criteria and evidence were sound; the mental addition of
9-10 numbers in prose was not. This is a distinct failure mode from Rules
1-3 and needs its own fix:

1. After scoring every criterion, **actually run the addition as a tool
   call** — e.g. `python3 -c "print(15+10+0+20+...)"` or an equivalent
   Bash arithmetic expression — using the exact criterion scores just
   assigned. Do not add them in your head or in prose and then write down
   whatever number "feels right."
2. **Show the expression you computed**, not just the result, so the sum
   is auditable against the itemized breakdown in the same report.
3. If a category/platform score is reported without a shown computation
   (or without one that a reader can re-add by hand from the criteria
   table), treat that score as unverified — this applies retroactively to
   every rubric in this project, including ones written before this rule.

### N/A criteria and renormalization

Some criteria are conditionally not applicable (e.g. "GitHub presence" for
a non-technical brand, "Bing Places" for a non-local business, "Google
Merchant Center" for a non-e-commerce site). When a criterion is N/A:

```
category_score = round(100 x sum(earned points, applicable criteria only)
                            / sum(max points, applicable criteria only))
```

Exclude the N/A criterion's points from **both** the numerator and the
denominator, then rescale to /100 — do not score an N/A criterion as 0
against the full 100-point denominator (that silently penalizes a
criterion that was never supposed to apply), and do not leave the
denominator ambiguous. State which criteria were excluded as N/A and why,
alongside the rescaled computation from Rule 4 above.

## Why this replaced the severity-deduction table

An earlier version of this rubric scored categories as
`100 - sum(severity deductions)` against a shared Critical/High/Medium/Low
table. A live two-run test against the same site (see repo history) showed
the *arithmetic* was reproducible once findings were fixed, but the
*findings themselves* still varied 15-28 points between independent runs —
because "severity" invited a judgment call, and vague checks like "Missing
Organization or Person schema" were read as "absent" by one run and
"present but incomplete" by another. Named criteria with fixed point
values, explicit tier definitions, and mandatory cited evidence remove the
judgment call: there is no severity to weigh, only "does the stated
evidence match this tier's definition, yes or no."

## Category subscore -> Health Score

Unchanged: once every category subscore is computed via its own criteria
table, the top-level aggregation in `seo-audit/SKILL.md` and
`seo/SKILL.md` is a plain weighted sum using the published weight table
there — see `## Scoring Weights` / `## Scoring Methodology` in those files.

## What this still does not fix

1. **The site changed between runs** (content edits, new pages, a fixed
   robots.txt) — the score should change, and the report should say what
   changed.
2. **Underlying data sources have a rolling window** — CrUX field data is a
   28-day rolling average; DataForSEO/SERP data reflects the moment of the
   query. Note the data timestamp/window in the report so a score delta a
   few points wide, with the same findings, isn't mistaken for
   nondeterminism.
3. **Lab-only performance data** (single Lighthouse run, no CrUX
   available) still has real run-to-run noise on an unchanged page — see
   the median-of-3 guidance in `agents/seo-performance.md`.
4. **Coverage** — a run that never fetched a given page or never checked a
   given attribute will report "No evidence found" for that criterion
   (correctly, per Rule 3), which is not the same as the criterion being
   satisfied. Two audits that crawled different subsets of a large site
   can still legitimately diverge; that is a crawl-completeness question,
   not a scoring-rubric one.
