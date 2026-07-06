# AEO scoring weights — Princeton GEO study + 2026 citation data

These are directional weights used by `scripts/citability_scorer.py` and
referenced by `geo-citability`, `seo-content`'s citability pass, and
`seo-audit`'s AEO fan-out. Treat as directional signals, not guarantees —
no single page-level change is proven to move AI citation rates by an exact
percentage; these figures summarize aggregate research findings.

| Signal | Approximate lift/penalty | Source basis |
|---|---|---|
| Cited sources / statistics with attribution | ≈+40% visibility | Princeton 2024 GEO study |
| Statistics presence (numbers, data points) | ≈+37% visibility | Princeton 2024 GEO study |
| Front-loading (answer in first ~30% of page) | ≈44% of AI citations come from the first 30% of a page | Princeton 2024 GEO study |
| Keyword stuffing / AI-specific keyword rewriting | ≈-10% (negative or neutral) | Princeton 2024 GEO study |
| Passage self-containment (low pronoun density, 134-167 optimal word count) | Positive | `citability_scorer.py` self-containment rubric |
| Question-phrased headings | Positive | `citability_scorer.py` answer-block-quality rubric |

## How these map to `citability_scorer.py`'s rubric

- Answer Block Quality (30% of score): definition patterns, early-answer placement, question-form headings.
- Self-Containment (25%): optimal word count (134-167), low pronoun density, named entities.
- Structural Readability (20%): sentence length distribution, list/step structure, paragraph breaks.
- Statistical Density (15%): percentages, dollar amounts, cited sources, year references.
- Uniqueness Signals (10%): original research language, case-study framing, tool/product specificity.

Last verified: 2026-07-06 (merge date). Re-verify against `citability_scorer.py`
if that script's rubric constants ever change.
