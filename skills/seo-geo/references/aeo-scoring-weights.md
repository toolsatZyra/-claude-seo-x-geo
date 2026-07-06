# AEO scoring weights — sourced figures vs. internal heuristics

These are directional weights used by `scripts/citability_scorer.py` and
referenced by `geo-citability`, `seo-content`'s citability pass, and
`seo-audit`'s AEO fan-out. Treat as directional signals, not guarantees —
no single page-level change is proven to move AI citation rates by an exact
percentage. Every figure below is now labeled with the confidence we can
actually back it with; do not upgrade an "unverified" row to a hard fact
without adding a real, checkable source to [[evidence-registry]] first.

## Verified against a named, checkable source

| Signal | Approximate lift/penalty | Source |
|---|---|---|
| Statistics presence in a passage | ≈+41% visibility | Aggarwal et al., "GEO: Generative Engine Optimization," ACM SIGKDD 2024 ([DOI](https://dl.acm.org/doi/10.1145/3637528.3671900)) — Princeton/Georgia Tech/IIT Delhi/Allen Institute for AI, one joint study |
| Quotations from authorities in a passage | ≈+28% visibility | Same paper as above |
| Citing external sources | up to ≈+115% visibility, specifically for content ranked around position 5 (lower-ranked pages have more room to gain; top-1 pages saw little change) | Same paper as above |
| Aggregate lift from the top-performing GEO techniques | commonly cited as "up to 40%" | Same paper as above |

## Not independently verified — do not present as proven research findings

| Signal | Claim as previously stated | Status |
|---|---|---|
| Front-loading (answer in first ~30% of page) | ≈44% of AI citations come from the first 30% of a page | Could not locate this specific figure in the cited paper or elsewhere. Directionally plausible (front-loading is a well-supported content practice) but the exact percentage is unconfirmed. Do not quote the 44% figure to a client without finding its actual source. |
| Keyword stuffing / AI-specific keyword rewriting | ≈-10% (negative or neutral) | Direction (keyword stuffing doesn't help, may hurt) is consistent with general GEO findings, but the -10% magnitude is unconfirmed. |
| Passage self-containment word-count band | 134-167 words optimal | This is `citability_scorer.py`'s own internal heuristic, not a figure drawn from the cited paper. Treat as an untested assumption, open to retuning. |

## How these map to `citability_scorer.py`'s rubric

- Answer Block Quality (30% of score): definition patterns, early-answer placement, question-form headings.
- Self-Containment (25%): word-count band (internal heuristic, see above), low pronoun density, named entities.
- Structural Readability (20%): sentence length distribution, list/step structure, paragraph breaks.
- Statistical Density (15%): percentages, dollar amounts, cited sources, year references.
- Uniqueness Signals (10%): original research language, case-study framing, tool/product specificity.

Last verified: 2026-07-06. Re-verify against `citability_scorer.py` if that
script's rubric constants ever change, and re-check the "not independently
verified" rows periodically — see [[evidence-registry]].
