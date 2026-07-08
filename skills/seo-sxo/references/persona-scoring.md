# Persona-Based Scoring Methodology

Score the target page from the perspective of each derived persona. This reveals
which audience segments the page serves well and which it fails.

---

## Persona Derivation

Derive 4-7 personas from SERP intent signals. Do not invent personas without
evidence -- every persona must trace back to a signal cluster.

### Sources for Persona Derivation

| Source | What It Reveals | Example Persona |
|--------|----------------|-----------------|
| PAA question cluster | Knowledge gaps by audience | Beginner, Technical Evaluator |
| Ad copy segments | Commercial audience targets | Budget Buyer, Enterprise Buyer |
| Related search themes | Journey stage groups | Researcher, Comparison Shopper |
| SERP result types | Content consumption preferences | Visual Learner, Data-Driven Analyst |
| Featured snippet format | Expected answer style | Quick-Answer Seeker |

### Persona Card Format

For each persona, document:

```
**[Persona Name]** -- [one-line description]
- Role: [job title or situation]
- Goal: [what they want to accomplish]
- Emotional state: [from user-story-framework.md]
- Journey stage: Awareness | Consideration | Decision
- Key questions: [2-3 questions this persona needs answered]
- SERP evidence: [specific signals that generated this persona]
```

---

## 4-Dimension Scoring Rubric

Score each persona on 4 dimensions using the fixed-criteria method in
`skills/seo/references/scoring-rubric.md` (Rules 1-9) — not a holistic "does
this feel adequate" read. Each dimension is broken into 4 named,
independently-checkable sub-criteria (Rule 8: each is its own condition, not
one blended judgment). Maximum 25 points each, 100 total per persona.

For each sub-criterion, cite evidence per Rule 3/6 — a quote, a page
element, a section name, or "No evidence found" (a complete, valid answer
that scores that sub-check as not satisfied). Compute
`dimension_score = round(25 x (sub-checks satisfied / 4))` per Rule 2's
sub-check tiering, using an actual tool call (Rule 4) — show the expression.
Where a sub-check requires interpretation rather than direct observation
(e.g. classifying which journey stage a piece of content targets), tag it
CONFIRMED or INFERRED per Rule 9 and state the reasoning briefly for any
INFERRED tag.

### Dimension 1: Relevance (0-25)

Does the page address THIS persona's specific need, not just the topic
generally? Tier by fraction of these 4 independent sub-checks satisfied:

- (a) Page content explicitly addresses the persona's derived goal — quote
  the specific copy/section.
- (b) Page addresses the specific barrier/objection identified in this
  persona's user story.
- (c) Content angle matches this persona's journey stage (awareness vs.
  consideration vs. decision) — not generic framing applied to all stages.
  Classifying the match is a judgment call: tag INFERRED.
- (d) No content actively contradicts or undermines this persona's need
  (e.g. enterprise-only framing surfacing for a budget-conscious persona).

### Dimension 2: Clarity (0-25)

Can this persona find their answer within 10 seconds, checked against
concrete page-structure signals, not a felt impression? Tier by fraction of
these 4 sub-checks satisfied:

- (a) The specific answer/content this persona needs is above the fold or
  within the first 2 scrolls — state where, by section/heading name.
- (b) A heading or label exists that a scanning user would recognize as
  "this is for me" — name the heading, or state "No evidence found."
- (c) No conflicting or competing information forces the persona to resolve
  an inconsistency before understanding the answer.
- (d) Content is not gated behind an accordion/interaction for the specific
  fact this persona needs (e.g. buried inside a collapsed FAQ) — if it is,
  this sub-check fails even if the content technically "exists on the page."

### Dimension 3: Trust (0-25)

Enumerate which of these named trust-signal types are present for this
persona — never a vague "adequate trust signals" judgment. Tier by fraction
of these 4 sub-checks satisfied:

- (a) Specific, named, checkable proof-of-outcome for this persona's concern
  (a metric, a named client result, a quantified claim) — example-list-OR:
  any ONE qualifying example is sufficient.
- (b) Third-party/external validation relevant to this persona (review-site
  presence, testimonial with attribution, case study, press mention).
- (c) No unresolved objection specific to this persona left visibly
  unanswered (e.g. a FAQ question exists about this persona's exact concern,
  but the answer contains no substantiating evidence).
- (d) Claims made are consistent with what's verifiable elsewhere on the
  site (no contradiction between a claim aimed at this persona and other
  page content).

A "big general trust signal" (e.g. a well-known client roster) only counts
toward THIS persona's Trust score if it's actually relevant/attributable to
what this specific persona needs to verify — do not credit generic brand
trust equally across all personas.

### Dimension 4: Action (0-25)

Is there a next step calibrated to this persona's readiness, not just "a CTA
exists somewhere on the page"? Tier by fraction of these 4 sub-checks
satisfied:

- (a) A clear, visible next step exists at this persona's journey stage (not
  just the page's default primary CTA if it mismatches the stage — e.g. a
  "Schedule a Call" CTA does not satisfy this for an awareness-stage persona
  not ready to talk).
- (b) The friction level of that next step matches this persona (low-
  friction option — e.g. download/read-more — for early-stage personas;
  direct-contact option acceptable for decision-stage personas).
- (c) The CTA/next-step is reachable without first resolving an unmet Trust
  or Clarity gap identified above — state which, if any.
- (d) No dead-end: the next step actually leads somewhere functional (not a
  broken link, not a generic contact form with no persona-specific framing).

---

## Score Interpretation

| Range | Rating | Implication |
|-------|--------|-------------|
| 80-100 | Excellent | Page serves this persona well -- minor optimizations only |
| 60-79 | Good | Page is relevant but has notable gaps for this persona |
| 40-59 | Needs Work | Page partially serves this persona -- significant improvements needed |
| 0-39 | Critical Mismatch | Page fails this persona -- major restructuring or new page needed |

---

## Aggregation and Prioritization

### Weighted Average

Not all personas are equally important. Weight by estimated search volume share:

- If SERP shows 70% informational intent, weight informational personas higher
- If ads dominate, weight commercial personas higher
- If local pack present, weight local personas higher

### Priority Ranking

Sort improvement recommendations by:

1. **Weakest persona with highest search volume weight** = biggest opportunity
2. **Lowest-scoring dimension across all personas** = systemic issue
3. **Critical mismatch personas** = fundamental page-type problem

### Output Format

The summary table below is the top-level rollup; it sits on top of a
mandatory per-dimension sub-check evidence table for each persona (Rule 3/6
— not optional, not folded into narrative prose only). Show the
`dimension_score` and `persona_total` computations as actual tool calls
(Rule 4), not prose arithmetic.

```
## Persona Scores for [URL]

| Persona | Relevance | Clarity | Trust | Action | Total | Rating |
|---------|-----------|---------|-------|--------|-------|--------|
| [Name] | XX/25 | XX/25 | XX/25 | XX/25 | XX/100 | [Rating] |
| ... | ... | ... | ... | ... | ... | ... |

### [Persona Name] — Dimension Detail

**Relevance (XX/25)**
| Sub-check | Satisfied | Evidence | Confidence |
|---|---|---|---|
| (a) Addresses persona's derived goal | Yes/No | [quote or "No evidence found"] | CONFIRMED/INFERRED |
| (b) Addresses specific barrier | Yes/No | ... | ... |
| (c) Matches journey stage | Yes/No | ... | INFERRED (classification judgment) |
| (d) No contradicting content | Yes/No | ... | ... |

(Repeat the same 4-row table shape for Clarity, Trust, and Action.)

### Weakest Persona: [Name] (XX/100)
**Top issue:** [specific problem, tied to the specific failed sub-check(s)]
**Recommended fix:** [concrete action with page-level detail]

### Systemic Issues
- [dimension]: [pattern across all personas, named by which sub-check(s) failed repeatedly]

### Priority Actions
1. [Action targeting weakest persona]
2. [Action targeting systemic issue]
3. [Action targeting next weakest persona]
```

---

## Validation Rules

- [ ] Every persona traces to specific SERP signals (no invented personas)
- [ ] Each of the 4 dimensions per persona has its own 4-row sub-check
      evidence table (not a single narrative paragraph) — "No evidence
      found" is a complete, valid answer per sub-check
- [ ] Dimension and persona-total scores are computed via an actual tool
      call (Rule 4 in `skills/seo/references/scoring-rubric.md`), with the
      expression shown
- [ ] Sub-checks requiring interpretation (not direct observation) are
      tagged CONFIRMED/INFERRED per Rule 9, with brief reasoning for any
      INFERRED tag
- [ ] Recommendations are concrete (section names, CTA text, placement) and
      tied to the specific sub-check(s) that failed
- [ ] At least 4 personas scored, no more than 7
- [ ] Weakest persona is addressed first in recommendations
- [ ] Score interpretation uses the standard ranges above
