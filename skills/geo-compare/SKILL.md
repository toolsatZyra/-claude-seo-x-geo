---
name: geo-compare
description: >
  Monthly delta tracking and progress reporting for AEO/GEO clients. Computes
  baseline-vs-current deltas deterministically from the seo-track KPI history
  (performance_tracker.py export / report --compare) for the AEO Readiness
  Score, its components and AI share of voice, tracks action item completion,
  and generates a "here's your progress" client report. Missing metrics are
  reported as not measured, never estimated. Use when user says "AEO progress",
  "GEO progress", "monthly AEO report", "AEO delta", "confronta", "progressi",
  "report mensile", or when running a monthly client check-in.
tags: [geo, business, delta, monthly, reporting, client, progress]
allowed-tools: Read, Write, Bash, Glob
metadata:
  version: "3.1.0"
  author: geo-seo-claude (grafted)
---

# AEO Monthly Progress Report

## Purpose

Show a client exactly what changed since the engagement started, using
numbers a reviewer can recompute. Every delta in this report comes from the
KPI history kept by `seo-track` (`scripts/performance_tracker.py`); nothing is
parsed out of prose and nothing is estimated. Declines are reported as
declines.

---

## Commands

```
/geo compare <domain>
/geo compare <domain> --baseline 2026-03-12
/geo compare <domain> --month 2026-10
```

---

## Where the numbers come from

| Metric family | Producer | Stored as |
|---|---|---|
| AEO Readiness Score + components | `scripts/aeo_score.py compute --emit-kpis` | `aeo.score`, `aeo.citability`, `aeo.brand_authority`, `aeo.content_eeat`, `aeo.crawler_access`, `aeo.schema`, `aeo.platform` |
| AI crawler access (alone) | `scripts/aeo_score.py crawlers --emit-kpis` | `aeo.crawler_access` |
| AI share of voice (outcome) | `scripts/ai_visibility.py report --emit-kpis` | `ai.mention_rate`, `ai.mention_rate_ci_low`, `ai.mention_rate_ci_high`, `ai.citation_rate`, `ai.sov`, `ai.n` |
| Search, traffic, leads (optional context) | `performance_tracker.py snapshot` / `record` | `gsc.*`, `ga4.*`, `leads.*` |

Each producer's envelope is stored with `python3 scripts/performance_tracker.py ingest <file>`.
If the client has no snapshots yet, run the producers first; there is nothing
to compare until two dated snapshots exist.

---

## Workflow

### Step 1: List the available snapshots

```bash
python3 scripts/performance_tracker.py export --project <domain> --metrics aeo.,ai. --json
```

Output contract: `{"project", "generated_at", "snapshots": [{"date", "metrics": {name: {"value", "source"}}}]}`.
Choose:
- **Current** = the latest snapshot containing `aeo.score` (or the latest in
  `--month`).
- **Baseline** = the engagement's first snapshot, or the date given with
  `--baseline`, or the previous month for a month-over-month view.

### Step 2: Compute deltas with the tracker (deterministic)

```bash
python3 scripts/performance_tracker.py report --project <domain> \
    --metrics aeo.,ai.,ga4.,leads. --compare <baseline-date|28d> --json
```

Use its latest value, comparison value and change for every metric verbatim.
If you need a delta the report does not show, compute it from the export
with a tool call (`python3 -c "print(round(<current> - <baseline>, 4))"`) and
show the expression (scoring-rubric Rule 4).

Rules for every row:
- A metric missing in either snapshot is **not measured** for that period.
  Never fill it from prose, from an older report, or by inferring it from
  the written findings.
- **AEO score comparability:** the score is comparable only when both
  snapshots carry the same set of `aeo.<component>` metrics (missing
  components were N/A and renormalized). If the sets differ, show the
  component-level deltas and mark the overall delta "not comparable
  (different component set)".
- **AI share of voice:** compare only figures from the same engine and
  surface (see the envelope `meta`, or rerun `ai_visibility.py report` for
  each window). When the two 95% intervals overlap, describe the change as
  "not distinguishable at this sample size". Only
  `python3 scripts/ai_visibility.py compare ...` (paired test with a verdict)
  can call a change real; quote its verdict when one exists.
- Rates are 0-1 fractions in the tracker; show them as percentages and the
  change in percentage points.

### Step 3: Legacy fallback (clients whose history predates seo-track)

Only if no tracker snapshot exists for the baseline date: read the old
markdown audit and accept exactly one line shape, the v3.1 `seo-audit`
heading `AEO Score: NN/100` (regex `AEO Score:\**\s*(\d{1,3})/100`). Parse
nothing else. Older "GEO Score" figures were produced by retired, differently
defined formulas; report them as "legacy score, not comparable", never as a
baseline for a delta. If you accept a legacy AEO score, store it so the
history is complete:

```bash
python3 scripts/performance_tracker.py record --project <domain> --metric aeo.score \
    --value NN --date <audit-date> --source audit-markdown --note "<file>"
```

### Step 4: Generate the report

Output to `~/.geo-prospects/reports/<domain>-monthly-<YYYY-MM>.md`.

---

## Report Template

```markdown
# AEO Monthly Progress Report
## [COMPANY NAME] — [MONTH YEAR]

**Reporting period:** [BASELINE DATE] → [CURRENT DATE]
**Prepared by:** [AGENCY NAME]
**Data:** seo-track KPI history (performance_tracker.py), snapshots [dates]

---

## Executive Summary

[2-3 factual sentences: what moved, in which direction, by how much, and
what is next. Name declines as declines.]

Example: "The AEO Readiness Score rose from 41 to 52 (+11) with the same six
components measured both months; the largest component gain was crawler
access (56 → 100) after the Cloudflare managed robots.txt rule that blocked
Claude-SearchBot was removed. AI share of voice on the ChatGPT app panel
moved from 18% to 24%, which is not distinguishable at n = 40; the treatment
experiment remains Keep-testing."

---

## AEO Readiness Score

| | Baseline | Current | Change |
|---|---|---|---|
| AEO Score | [X]/100 ([rating], completeness [c]) | [X]/100 ([rating], completeness [c]) | [+/-X] or "not comparable" |

| Component | Weight | Baseline | Current | Change |
|---|---|---|---|---|
| Citability | 25 | [X] | [X] | [+/-X] |
| Brand authority | 20 | [X or not measured] | [X] | [...] |
| Content E-E-A-T | 20 | [...] | [...] | [...] |
| Crawler access | 15 | [...] | [...] | [...] |
| Schema | 10 | [...] | [...] | [...] |
| Platform readiness | 10 | [...] | [...] | [...] |

---

## AI Share of Voice (outcome, reported separately)

| [engine/surface] | Baseline | Current | Change |
|---|---|---|---|
| Mention rate (unbranded prompts) | [X%] (95% CI [a-b], n [N]) | [X%] (CI [a-b], n [N]) | [+/-X pp]; [distinguishable / not distinguishable] |
| Share of voice | [X%] | [X%] | [+/-X pp] |
| Citation rate | [X%] | [X%] | [+/-X pp] |

Experiment verdict (ai_visibility.py compare): [Promote / Keep-testing / Rollback / Unproven — reason], or "no experiment this period".

---

## AI Crawler Access Changes

From the saved `aeo_score.py crawlers --json` outputs of both dates (show
only agents whose status changed):

| Agent | Kind | Baseline | Current |
|---|---|---|---|
| OAI-SearchBot | answer surface (ChatGPT Search) | Blocked | Allowed |
| GPTBot | training (unscored) | Allowed | Blocked (client decision) |

---

## Action Plan Progress

| # | Action | Owner | Status | Evidence |
|---|--------|-------|--------|----------|
| 1 | Remove the Cloudflare managed rule blocking answer-surface agents | Client dev | Done | robots.txt line removed, crawler access 56 → 100 |
| 2 | Add Organization schema to homepage | Client dev | Done | seo-schema score 40 → 62 |
| 3 | Rewrite top 10 pages with question-led sections | Agency | In progress (3/10) | — |

**Completed: [X]/[Y]**

---

## This Month's Wins

Only CONFIRMED changes, each tied to a metric above (scoring-rubric Rule 9):
- [e.g., "OAI-SearchBot and Claude-SearchBot are now allowed; ChatGPT Search and Claude search can retrieve the site's pages."]
- [e.g., "Organization schema is live on the homepage (schema component +22)."]

## Declines and New Issues

- [Metric that fell, by how much, and the likely cause tagged CONFIRMED or INFERRED]

---

## Next Month Focus

| Priority | Action | Owner | Metric it should move | Leading indicator | How we'd know it failed |
|---|---|---|---|---|---|
| 1 | [Action] | [Agency/Client] | [e.g., aeo.citability] | [e.g., citability of the 3 rewritten pages] | [no change after re-crawl] |

No point forecasts: targets are agreed with the client, not projected.

---

## History

| Date | AEO Score | Completeness | Mention rate ([engine/surface]) |
|---|---|---|---|
| [snapshot dates from the export, actual values only] | | | |

## Traffic and Leads (if tracked)

| Metric | Baseline | Current | Change |
|---|---|---|---|
| AI-assistant sessions (ga4.ai_sessions) | [X or not measured] | [X] | [...] |
| Organic leads (leads.organic) | [...] | [...] | [...] |

Do not convert score changes into traffic or revenue estimates.
```

---

## Trend Symbols

| Change | Symbol | Meaning |
|-------|-------------|---------|
| +5 or more points | ▲▲ | Strong improvement |
| +1 to +4 | ▲ | Improvement |
| 0 | ── | No change |
| -1 to -4 | ▼ | Slight decline |
| -5 or more | ▼▼ | Significant decline; discuss the cause |
| either side missing | n/m | Not measured |

For share-of-voice rates, use the symbols only when the change is
distinguishable (non-overlapping intervals or a `compare` verdict);
otherwise write "within noise".

A decline can come from a real regression, from a component measured for the
first time, or from a stricter re-audit. Say which, with evidence; do not
reframe it.

---

## Output

1. Save the report to `~/.geo-prospects/reports/<domain>-monthly-<YYYY-MM>.md`
2. Print confirmation with key stats:
   ```
   ✓ Monthly report generated: ~/.geo-prospects/reports/example.com-monthly-2026-10.md

   SUMMARY:
   AEO Score: 41 → 52 (+11), same components
   AI mention rate (chatgpt/ui): 18% → 24%, not distinguishable (n=40)
   Actions completed: 3/5
   ```
3. Suggest next action: "Share with the client, or run `/seo google report`
   (`scripts/google_report.py`) for the PDF version."
