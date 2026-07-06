# SOURC-E framework — methodology summary (own words, attributed)

StudioHawk publishes a "SOURC-E" framework and citation-share methodology
for AEO/GEO work. License terms for verbatim redistribution of their
materials are unclear, so this is a summary in our own words with
attribution — not a copy of their text.

The framework's core idea, as we understand and apply it: score a page's
AEO readiness across independent dimensions rather than one blended metric,
similar to how this plugin already separates SEO and AEO scores. Dimensions
worth tracking independently, adapted for this plugin's cluster:

- **S**tructure — heading hierarchy, question-phrased headings, scannable format (`geo-citability`'s structural-readability rubric).
- **O**riginality — first-hand data, case studies, unique research (`citability_scorer.py`'s uniqueness-signals rubric).
- **U**ser-intent match — does the passage directly answer the query it targets (`geo-citability`'s answer-block-quality rubric).
- **R**eferences/citations — attributed statistics and sources (`citability_scorer.py`'s statistical-density rubric).
- **C**itation share — how often a brand appears across AI-cited platforms relative to competitors (`geo-compare`, `geo-brand-mentions`).
- **E**ntity clarity — schema markup and brand disambiguation (`seo-schema`'s AI-citation schema section).

This feeds prioritization: when a `geo-citability` or `seo-audit` AEO report
has to rank recommendations, prefer fixes that touch more SOURC-E dimensions
at once (e.g. adding an attributed statistic near the top of a section hits
both References and Structure).

Attribution: methodology inspired by StudioHawk's public SOURC-E framework
and citation-share commentary. This document does not reproduce their text.
