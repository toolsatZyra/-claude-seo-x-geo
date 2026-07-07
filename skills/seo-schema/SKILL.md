---
name: seo-schema
description: >
  Detect, validate, and generate Schema.org structured data. JSON-LD format
  preferred. Use when user says "schema", "structured data", "rich results",
  "JSON-LD", or "markup".
user-invocable: true
argument-hint: "[url]"
license: MIT
metadata:
  author: AgriciDaniel
  version: "3.0.0"
  category: seo
---

# Schema Markup Analysis & Generation

## Detection

1. Scan page source for JSON-LD `<script type="application/ld+json">`
2. Check for Microdata (`itemscope`, `itemprop`)
3. Check for RDFa (`typeof`, `property`)
4. Always recommend JSON-LD as primary format (Google's stated preference)

## Validation

- Check required properties per schema type
- Validate against Google's supported rich result types
- Test for common errors:
  - Missing @context
  - Invalid @type
  - Wrong data types
  - Placeholder text
  - Relative URLs (should be absolute)
  - Invalid date formats
- Flag deprecated types (see below)

## AI-citation-oriented schema (AEO)

Beyond classic SEO schema validity, these Schema.org types carry specific
weight for AI citation and entity recognition — folded in from
geo-seo-claude's `geo-schema` module:

- **Organization** — critical for entity recognition. AI systems use this to
  disambiguate "which brand is this page about," especially when `sameAs`
  links to Wikipedia, Wikidata, LinkedIn, Crunchbase, and other
  AI-cited platforms (cross-reference `geo-brand-mentions`). Missing or
  incomplete Organization schema is a common reason a page ranks well in
  classic SEO but is never cited by an AI answer engine.
- **Person** (author) — pairs with E-E-A-T signals. AI systems weigh
  byline authorship more heavily than classic SERPs do, particularly for
  YMYL content.
- **FAQPage-as-entity-signal** — not for "FAQ rich snippet" purposes (Google
  has scaled back FAQ rich results), but because a well-formed FAQPage block
  gives an AI answer engine a pre-structured, self-contained Q&A pair it can
  extract directly. Use sparingly — only for genuine, non-duplicative FAQs.

These are additive to classic SEO schema requirements below, not a
replacement — see the deprecation table above/below for what Google has
deprecated for search-result purposes specifically.

Import missing templates from `schema/` if this project lacks them:
`schema/software-saas.json`, `schema/article-author.json` (see Task 18 for
the selective merge that adds these two files).

## Schema Type Status (as of May 2026)

Read `references/schema-types.md` for the full list. Key rules:

### ACTIVE (recommend freely):
Organization, LocalBusiness, SoftwareApplication, WebApplication, Product (with Certification markup as of April 2025), ProductGroup, Offer, Service, Article, BlogPosting, NewsArticle, Review, AggregateRating, BreadcrumbList, WebSite, WebPage, Person, ProfilePage, ContactPage, VideoObject, ImageObject, Event, JobPosting, Course, DiscussionForumPosting

### VIDEO & SPECIALIZED (recommend freely):
BroadcastEvent, Clip, SeekToAction, SoftwareSourceCode

See `schema/templates.json` for ready-to-use JSON-LD templates for these types.

> **JSON-LD and JavaScript rendering:** Per Google's December 2025 JS SEO guidance, structured data injected via JavaScript may face delayed processing. For time-sensitive markup (especially Product, Offer), include JSON-LD in the initial server-rendered HTML.

### NO RICH RESULTS — KEEP FOR AI:
- **FAQPage**: Google retired FAQ rich results for ALL sites on May 7, 2026 (supersedes the Aug 2023 gov/health restriction). No SERP feature anymore — but flag existing FAQPage at Info (not Critical), since the markup still aids AI Mode / AI Overviews entity resolution. For genuine user Q&A pages, use **QAPage**.

### DEPRECATED (never recommend):
- **HowTo**: Rich results removed September 2023
- **SpecialAnnouncement**: Deprecated July 31, 2025
- **CourseInfo, EstimatedSalary, LearningVideo**: Retired June 2025
- **ClaimReview**: Retired from rich results June 2025
- **VehicleListing**: Retired from rich results June 2025
- **Practice Problem**: Retired from rich results late 2025
- **Dataset**: Retired from rich results late 2025
- **Book Actions**: Deprecated then reversed, still functional as of Feb 2026 (historical note)

## Generation

When generating schema for a page:
1. Identify page type from content analysis
2. Select appropriate schema type(s)
3. Generate valid JSON-LD with all required + recommended properties
4. Include only truthful, verifiable data. Use placeholders clearly marked for user to fill
5. Validate output before presenting

## Common Schema Templates

### Organization
```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "[Company Name]",
  "url": "[Website URL]",
  "logo": "[Logo URL]",
  "contactPoint": {
    "@type": "ContactPoint",
    "telephone": "[Phone]",
    "contactType": "customer service"
  },
  "sameAs": [
    "[Facebook URL]",
    "[LinkedIn URL]",
    "[Twitter URL]"
  ]
}
```

### LocalBusiness
```json
{
  "@context": "https://schema.org",
  "@type": "LocalBusiness",
  "name": "[Business Name]",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "[Street]",
    "addressLocality": "[City]",
    "addressRegion": "[State]",
    "postalCode": "[ZIP]",
    "addressCountry": "US"
  },
  "telephone": "[Phone]",
  "openingHours": "Mo-Fr 09:00-17:00",
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": "[Lat]",
    "longitude": "[Long]"
  }
}
```

### Article/BlogPosting
```json
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "[Title]",
  "author": {
    "@type": "Person",
    "name": "[Author Name]"
  },
  "datePublished": "[YYYY-MM-DD]",
  "dateModified": "[YYYY-MM-DD]",
  "image": "[Image URL]",
  "publisher": {
    "@type": "Organization",
    "name": "[Publisher]",
    "logo": {
      "@type": "ImageObject",
      "url": "[Logo URL]"
    }
  }
}
```

## Scoring

This skill previously had no numeric score at all, and a first attempt at
adding one (a Critical/High/Medium/Low deduction table) still produced a
28-point gap between two independent audits of the same page — one run
read "Organization schema" as present/absent (literal), the other read it
as complete/incomplete (docking points for a present-but-partial block).
The 5 criteria below are written to be checkable as **strict presence or
absence only** — never "how complete" or "how good" — precisely to close
that gap. Use the fixed-criteria method in
`skills/seo/references/scoring-rubric.md`, with cited evidence per
criterion (quote the actual JSON-LD, or state "No evidence found").

### Schema criteria (sum to 100)

| # | Criterion | Points | Excellent (100%) — literal presence/absence only |
|---|---|---|---|
| 1 | Valid JSON-LD syntax | 25 | At least one `<script type="application/ld+json">` block parses as valid JSON with a `@context` and `@type` — binary per block found (tier by fraction of blocks that parse cleanly if multiple exist) |
| 2 | Core entity/page-type schema is present | 25 | A schema type matching the detected page type exists **at all** (Organization for a homepage/business site, Product for a product page, Article for a blog post, LocalBusiness for a local page, etc.) — this criterion is satisfied by mere presence of the right `@type`; do **not** dock this criterion for missing optional properties like `sameAs`, `telephone`, or `openingHours` — that belongs to criterion 3, never here |
| 3 | Required properties present for each type in use | 20 | Every schema type detected on the page has all properties Google's documentation marks *required* for that type (see `references/schema-types.md`) — check against that literal required-properties list only, not a subjective "richness" judgment; missing *recommended* (non-required) properties does not fail this criterion |
| 4 | No deprecated schema types in use | 15 | None of the types in the DEPRECATED table above appear on the page (FAQPage is NOT deprecated — see the NO RICH RESULTS note — so its presence never fails this criterion) |
| 5 | Absolute URLs, no placeholder text, valid data types/dates | 15 | Every URL value in the schema is absolute (not relative); no placeholder strings (`"[Company Name]"`, `"TODO"`, etc.) remain; date fields parse as valid dates; property values match their expected type |

`Schema Score = sum(criterion_score across all 5 rows)`. If no schema
markup exists at all, criteria 1-3 all score 0 (Not Implemented) and 4-5
score 100 (nothing present to violate them) — state this explicitly
rather than treating "nothing found" as an error.

## Output

- `SCHEMA-REPORT.md`: detection and validation results
- `generated-schema.json`: ready-to-use JSON-LD snippets

### Schema Score: XX/100
State each criterion's tier and cited evidence (quote the JSON-LD or
state "No evidence found"). Per scoring-rubric.md Rule 4, compute the sum
with an actual tool call (e.g. `python3 -c "print(...)"`) using the 5 real
numbers and show that expression — do not add them in prose.

### Criteria Breakdown
| Criterion | Points possible | Points earned | Tier |
|---|---|---|---|
| Valid JSON-LD syntax | 25 | XX | ... |
| Core entity/page-type schema present | 25 | XX | ... |
| Required properties present | 20 | XX | ... |
| No deprecated types in use | 15 | XX | ... |
| Absolute URLs / no placeholders / valid data | 15 | XX | ... |

### Validation Results
| Schema | Type | Status | Issues |
|--------|------|--------|--------|
| ... | ... | ✅/⚠️/❌ | ... |

### Recommendations
- Missing schema opportunities
- Validation fixes needed
- Generated code for implementation

## Error Handling

| Scenario | Action |
|----------|--------|
| URL unreachable | Report connection error with status code. Suggest verifying URL and checking if the page requires authentication. |
| No schema markup found | Report that no JSON-LD, Microdata, or RDFa was detected. Recommend appropriate schema types based on page content analysis. |
| Invalid JSON-LD syntax | Parse and report specific syntax errors (missing brackets, trailing commas, unquoted keys). Provide corrected JSON-LD output. |
| Deprecated schema type detected | Flag the deprecated type with its retirement date. Recommend the current replacement type or advise removal if no replacement exists. |
