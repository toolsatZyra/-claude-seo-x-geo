---
name: geo-proposal
description: >
  Auto-generate a professional, client-ready AEO/GEO service proposal from audit data (AEO Score from scripts/aeo_score.py).
  Creates a full proposal in markdown and PDF including executive summary, findings,
  recommended service packages (Basic/Standard/Premium), pricing, timeline, and terms.
  Use when user says "proposal", "proposta", "offerta", "preventivo", "generate proposal",
  or after completing an AEO audit for a prospect.
tags: [geo, business, proposal, sales, pricing, client]
allowed-tools: Read, Write, Bash, Glob, WebFetch
metadata:
  version: "3.1.0"
  author: geo-seo-claude (grafted)
---

# GEO Proposal Generator

## Purpose

Generate a fully customized, client-ready GEO service proposal that:
1. Pulls findings directly from the prospect's AEO audit and AEO Score
2. Translates technical gaps into business pain points
3. Presents 3 service tiers with clear pricing
4. Includes an ROI framework built only from checkable inputs
5. Outputs a professional markdown document ready to send

---

## Command

```
/geo proposal <domain-or-audit-file> [--tier basic|standard|premium] [--client-name "Name"] [--monthly EUR]
```

**Examples:**
```
/geo proposal electron-srl.com
/geo proposal electron-srl.com --tier standard --client-name "Electron Srl"
/geo proposal ~/.geo-prospects/audits/electron-srl.com-2026-03-12.md
```

---

## Workflow

### Step 1: Load Audit Data

1. Check if `~/.geo-prospects/audits/<domain>*.md` exists, or whether the
   client has `aeo.*` snapshots in seo-track
   (`python3 scripts/performance_tracker.py export --project <domain> --metrics aeo.,ai. --json`).
2. If not, run `/seo geo <url>` to measure the AEO components, then
   `python3 scripts/aeo_score.py compute ... --json` to get the AEO Score
   (and `--emit-kpis` + `performance_tracker.py ingest` to start the
   client's history).
3. Extract from the audit / aeo_score.py output:
   - AEO Score with rating, completeness and the component table
   - Top 3 critical findings
   - Quick wins list
   - Business type
   - Measured traffic and leads, only if tracked (`ga4.*`, `leads.*`);
     never an estimated traffic impact

### Step 2: Customize the Proposal

Auto-fill proposal template with:
- Company name (from domain or prospect record)
- AEO score, rating and completeness
- 3 most critical pain points (translated to business language)
- Estimated revenue at risk from AI search shift
- Recommended service tier based on the AEO score (see Pricing
  Recommendation Logic below)

### Step 3: Generate Proposal File

Output to `~/.geo-prospects/proposals/<domain>-proposal-<date>.md`
Also update prospect record if it exists in `~/.geo-prospects/prospects.json`

---

## Proposal Template

Generate the following document, filling all `[PLACEHOLDERS]` with real audit data:

---

```markdown
# AEO / GEO Optimization Proposal
## [COMPANY NAME] — AI Search Visibility

**Prepared by:** [YOUR AGENCY NAME]
**Prepared for:** [CONTACT NAME], [COMPANY NAME]
**Date:** [DATE]
**Valid until:** [DATE + 30 DAYS]
**Reference:** GEO-PROP-[YYMMDD]-[DOMAIN]

---

## Executive Summary

[COMPANY NAME] operates in [INDUSTRY] and serves customers across [GEOGRAPHY].
Our AEO audit of [DOMAIN], conducted on [DATE], measured an AEO Readiness
Score of **[SCORE]/100 ([RATING])**, computed from [N] of 6 components
(completeness [C]).

This means your website currently has [RATING DESCRIPTION — Excellent 90+,
Good 75-89, Fair 60-74, Poor 40-59, Critical 0-39].
AI-powered search (ChatGPT, Google AI Overviews, Perplexity) is capturing a
growing share of discovery traffic -- **[X]% of online discovery** for [COMPANY]'s
industry -- and this gap represents a measurable risk to your pipeline.
[Before sending: pull a current AI-referral-growth figure and cite it with a
source and date; do not reuse a fixed year-over-year percentage without
checking it first -- see [[evidence-registry]]. Public reports on this have
ranged from roughly 390% to over 1000% YoY depending on source, vertical, and
month, so an old or generic number will look wrong to any client who's seen a
more recent report.]

The three most urgent issues are:
1. **[CRITICAL FINDING 1]** — [Business impact in one sentence]
2. **[CRITICAL FINDING 2]** — [Business impact in one sentence]
3. **[CRITICAL FINDING 3]** — [Business impact in one sentence]

We recommend the **[TIER NAME] package** at **€[PRICE]/month**, which addresses
all critical issues within 90 days and positions [COMPANY] as an AI-visible
authority in [INDUSTRY].

---

## The Opportunity: Why GEO Matters for [COMPANY NAME]

### The AI Search Shift Is Already Happening

> **Before using this table in a live proposal:** every figure below needs a
> current source and date. Re-check against [[evidence-registry]] first --
> AI-referral growth and conversion-rate figures in particular vary by 2-3x
> across published reports depending on source, vertical, and month, so
> stale or generic numbers are easy for a technical client to catch.

| Metric | Value | Status |
|--------|-------|--------|
| AI-referred traffic growth (YoY) | [pull current figure] | Public reports range ~390%-1000%+ YoY; find one specific to the client's industry/geo and cite it |
| AI traffic conversion vs. organic | [pull current figure] | Public reports range from "converts slightly better" to "11x higher" depending on methodology; do not default to a fixed multiplier |
| ChatGPT weekly active users | [pull current figure, cite source + date] | Grows quickly; a stale number undermines credibility with a client who's seen a newer one |
| Google AI Overviews monthly reach | [pull current figure, cite source + date] | Same caveat |
| Gartner: predicted decline in traditional search engine volume | **-25% by 2026** (Gartner press release, Feb 19, 2024) | This replaces a previous "-50% by 2028" figure in this template that did not match Gartner's actual published prediction -- verified against [gartner.com/en/newsroom/press-releases/2024-02-19-...](https://www.gartner.com/en/newsroom/press-releases/2024-02-19-gartner-predicts-search-engine-volume-will-drop-25-percent-by-2026-due-to-ai-chatbots-and-other-virtual-agents) |
| Marketers investing in GEO today | [pull current figure] | Could not independently verify "23%"; find and cite a current source |

**First-mover advantage is real.** Companies that invest in GEO now will
capture the AI search channel before competitors do. Make this case with
figures you can defend if the client's own team checks them -- a wrong or
unsourceable stat in a sales proposal is worse than a smaller, defensible one.

### Your Current Position

| Metric | [COMPANY] | How it was measured |
|--------|-----------|---------------------|
| AEO Readiness Score | [SCORE]/100 ([RATING]) | `aeo_score.py compute`, completeness [C] |
| AI answer engines allowed in robots.txt | [X]/9 answer-surface agents | `aeo_score.py crawlers` (training crawlers listed separately; blocking them is a licensing choice) |
| Brand Authority | [X]/100 | `geo-brand-mentions` rubric (part judgment) |
| Schema | [X]/100 | `seo-schema` |
| AI share of voice | [X% mention rate, n, engine] or "not yet measured" | `geo-share-of-voice` (outcome; only if the prospect agreed to a panel run) |
| llms.txt | [Yes/No] | audited only; not a ranking lever (see note) |

There is no published industry benchmark for this score; do not add an
"industry average" column or invent one.

> **Note on the llms.txt row:** this template previously hardcoded "12% have
> it" / "78% have it" adoption figures we could not verify. More importantly,
> quoting adoption percentages here creates FOMO pressure that contradicts
> this plugin's own reconciled stance (`seo-geo/SKILL.md`): llms.txt is
> audited and can be generated on request, but it is a forward-looking,
> low-confidence signal, **not** a current ranking or citation lever, and no
> score should be gained or lost based on its presence. If you fill in real
> adoption numbers here, keep the "not a ranking lever" framing intact rather
> than implying the client is falling behind by not having one.

---

## Audit Findings Summary

### AEO Score Breakdown

Copy the component table from `aeo_score.py compute --json`; do not
recompute or round differently.

| Component | Your Score | Weight | Priority |
|----------|-----------|--------|----------|
| Citability | [SCORE]/100 or N/A | 25 | [HIGH/MED/LOW] |
| Brand authority | [SCORE]/100 or N/A | 20 | [HIGH/MED/LOW] |
| Content E-E-A-T | [SCORE]/100 or N/A | 20 | [HIGH/MED/LOW] |
| AI crawler access | [SCORE]/100 or N/A | 15 | [HIGH/MED/LOW] |
| Schema | [SCORE]/100 or N/A | 10 | [HIGH/MED/LOW] |
| Platform readiness | [SCORE]/100 or N/A | 10 | [HIGH/MED/LOW] |
| **AEO SCORE** | | completeness [C] | **[SCORE]/100 ([RATING])** |

Computation: `python3 -c "print(<expression from aeo_score.py>)"` -> [SCORE]

### Critical Issues Found

[For each critical issue from audit:]

#### 🔴 [ISSUE TITLE]
**What we found:** [Technical finding in plain language]
**Business impact:** [What this means for their revenue/visibility]
**Our fix:** [What we will do to resolve it]
**Timeline:** [When they will see improvement]

---

## Our Solution: Service Packages

We offer three engagement models based on the scope of optimization needed.

---

### BASIC — €2,500/month
*Best for: Sites with an AEO score of 61-75 needing targeted improvements*

**What's included:**
- Quarterly full AEO audit (4x/year)
- Quarterly client report with AEO Score tracking
- Schema.org implementation (Organization + key page schemas)
- AI crawler access optimization (robots.txt, answer-surface agents)
- llms.txt creation on request (forward-looking; not a ranking lever)
- Email support (48-hour response)

**Success measures:** AEO Score and its components, tracked in seo-track; targets agreed after the baseline, not promised here
**Contract:** Minimum 6 months

---

### STANDARD — €5,000/month ⭐ Recommended for [COMPANY]
*Best for: Sites with an AEO score of 41-60 needing structured monthly work*

**Everything in Basic, plus:**
- Monthly full AEO audit + delta report (`geo-compare`)
- Monthly AI share-of-voice panel (`geo-share-of-voice`) with treatment/control measurement
- Monthly strategy call (60 minutes)
- Content citability optimization (up to 10 pages/month)
- Brand authority building (Wikipedia, Wikidata, LinkedIn optimization)
- Platform-specific optimization (Google AIO, ChatGPT, Perplexity)
- E-E-A-T improvements (author pages, credentials, freshness signals)
- Slack channel for fast communication (24-hour response)

**Success measures:** AEO Score, AI share of voice (mention rate with confidence interval) and AI-referred sessions, reported monthly
**Contract:** Minimum 6 months

---

### PREMIUM — €9,500/month
*Best for: Sites with an AEO score of 0-40 with critical issues, or competitive industries*

**Everything in Standard, plus:**
- Bi-weekly strategy calls
- Technical SEO implementation support (Core Web Vitals, SSR, speed)
- Full content strategy + production (4 optimized articles/month)
- Active brand building (Reddit, YouTube, industry citations)
- Competitor monitoring and response
- Dedicated account manager
- Priority support (4-hour response)

**Success measures:** as Standard, plus experiment verdicts (Promote / Keep-testing / Rollback / Unproven) for each major content change
**Contract:** Minimum 12 months

---

## ROI Framework for [COMPANY NAME]

Build this section only from inputs the client can check:

| Input | Value | Source |
|-------|-------|--------|
| Current AI-referred sessions / month | [X or "not measured"] | GA4 via `ai_referrals.py` |
| Current organic sessions / month | [X] | GA4 / Search Console |
| Lead conversion rate of organic visits | [X%] | client CRM / GA4 key events |
| Value of a lead | €[X] | client |

Break-even for a package = monthly fee / value of a lead = the number of
additional leads per month the work must produce. State it that way and let
the client judge plausibility. Do not project score gains, AI-traffic
growth percentages or conversion multipliers: published figures vary by
2-3x or more between studies (see [[evidence-registry]]), and none of them
is a forecast for this client. If you cite a market statistic for context,
give its source and date.

---

## Engagement Timeline

### Month 1 — Foundation
- Kick-off call and onboarding (Week 1)
- Full technical audit + baseline metrics capture (AEO Score, share-of-voice panel, AI-referred sessions)
- Quick wins implementation: robots.txt for answer-surface agents, schema, meta descriptions

### Month 2-3 — Optimization
- Content citability rewrites (top 10 pages)
- E-E-A-T improvements: author pages, credentials, dates
- Platform-specific optimization (Google AIO, ChatGPT, Perplexity)
- Brand presence: LinkedIn, Wikipedia/Wikidata groundwork

### Month 4-6 — Authority Building
- Brand mention campaigns (Reddit, industry sites, YouTube)
- Topical authority content strategy
- Monthly reports with measured changes and experiment verdicts

### Month 6 — Review
- Full re-audit with before/after comparison (`geo-compare`)
- ROI report from measured traffic and leads
- Renewal discussion

---

## Why Us

- **GEO specialists**: We focus exclusively on AI search optimization, not traditional SEO agencies adapting to GEO
- **Transparent reporting**: Monthly reports show exactly what changed and why
- **No lock-in beyond minimum**: Month-to-month after initial commitment
- **Reproducible methodology**: an AEO Readiness Score with a published formula and evidence for every component, plus measured AI share of voice
- **Fast results**: Quick wins visible within 30 days

---

## Investment Summary

| Package | Monthly | 6-Month | 12-Month |
|---------|---------|---------|----------|
| Basic | €2,500 | €15,000 | €30,000 |
| Standard | €5,000 | €30,000 | €60,000 |
| Premium | €9,500 | €57,000 | €114,000 |

*All prices exclude VAT. Payment terms: monthly, due within 15 days of invoice.*

---

## Next Steps

To move forward:

1. **Review this proposal** and share any questions
2. **Schedule a 30-minute call** to walk through findings together: [CALENDAR LINK]
3. **Sign the service agreement** (sent separately upon acceptance)
4. **Kick-off call** scheduled for your chosen start date

This proposal is valid for **30 days** from the date above.

---

## Terms & Conditions

- **Minimum commitment:** As stated per package above
- **Cancellation:** 30-day written notice after minimum term
- **Confidentiality:** All audit findings and client data are strictly confidential
- **Results:** We guarantee effort and methodology, not specific ranking outcomes
- **Reporting:** Monthly reports delivered by the 5th of each month
- **Access needed:** Read access to Google Analytics / Search Console (if available)

---

*This proposal reflects findings from the audit of [DOMAIN] conducted on
[DATE]. The AEO Score was computed with scripts/aeo_score.py; the formula and
component evidence are available on request.*
```

---

## Output

1. Save proposal to `~/.geo-prospects/proposals/<domain>-proposal-<date>.md`
2. Update prospect record: set `status` to `proposal`, save `proposal_file` path
3. Print confirmation:
   ```
   ✓ Proposal generated: ~/.geo-prospects/proposals/electron-srl.com-proposal-2026-03-12.md
   ✓ Prospect status updated: Qualified → Proposal
   ✓ Recommended package: STANDARD (€5,000/month) — AEO Score 52/100 (completeness 1.00)

   Next: Share the proposal file, or run `/seo google report` (scripts/google_report.py) for the PDF version.
   ```

## Pricing Recommendation Logic

Base recommendation on the AEO score from `aeo_score.py compute` (only when
completeness is at least 0.6; below that, measure the missing components
before recommending a tier):
- Score 0-40 → Recommend **Premium** (critical issues require intensive work)
- Score 41-60 → Recommend **Standard** (structured monthly optimization)
- Score 61-75 → Recommend **Basic** (maintenance + targeted improvements)
- Score 76+ → Offer **Basic** or quarterly retainer check-in
