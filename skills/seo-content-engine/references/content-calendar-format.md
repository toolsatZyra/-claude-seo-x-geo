# Content calendar format

The calendar is a JSON file the operator approves before any drafting starts.
`scripts/content_export.py calendar <file>` validates it, checks for planned
duplicates and existing pages, and runs the volume guard. Keep calendars in
the client's working folder, not in this repository.

## Top level

```json
{
  "calendar_version": 1,
  "project": "example.com",
  "generated_at": "2026-10-17T09:00:00Z",
  "cadence_per_week": 2,
  "indexed_pages": 240,
  "indexed_pages_source": "GSC Pages report, 2026-10-15",
  "approved_by": "",
  "items": []
}
```

| Field | Required | Meaning |
|---|---|---|
| `project` | yes | Profile domain (`seo_project.py`) |
| `cadence_per_week` | recommended | Planned new pages per week; defaults to the profile's `content.cadence_per_week` |
| `indexed_pages` | recommended | Indexed pages today; sizes the volume guard. `--indexed-pages` overrides it |
| `indexed_pages_source` | recommended | Where the count came from, so the guard's input is traceable |
| `approved_by` | at approval | Name of the person who approved the plan |
| `items` | yes | One object per article (below) |

## Items

```json
{
  "date": "2026-10-20",
  "keyword": "crm pricing for small business",
  "kind": "new",
  "intent": "transactional",
  "funnel": "BOFU",
  "article_type": "pricing guide",
  "expected_length": "1400-1900 words (competitor median 1650)",
  "slug": "crm-pricing-small-business",
  "target_url": "",
  "internal_links": [
    {"url": "/pricing", "anchor": "our pricing plans"},
    {"url": "/blog/how-to-choose-a-crm", "anchor": "how to choose a CRM"}
  ],
  "competitor_urls": ["https://a.example/crm-pricing", "https://b.example/crm-cost"],
  "instructions": "Open with the typical per-user price range and what drives it. Include a cost table.",
  "quality_questions": [
    "Does the first paragraph answer 'how much does a CRM cost' on its own?",
    "Is every price linked to the vendor's own pricing page with the date checked?",
    "What does this page offer that the top three results do not?"
  ],
  "keyword_source": "GSC (striking distance, avg position 14.2)",
  "status": "planned"
}
```

| Field | Required | Rules |
|---|---|---|
| `date` | yes | `YYYY-MM-DD`; planned draft date, never an automatic publish date |
| `keyword` | yes | One primary keyword per item; unique across the calendar (case and punctuation ignored) |
| `kind` | no | `new` (default) or `refresh`. Refresh items target an existing URL and go to `seo-refresh` |
| `intent` | yes | `informational`, `commercial`, `transactional` or `navigational` (from `seo_metrics.classify_intent`) |
| `funnel` | yes | `TOFU`, `MOFU` or `BOFU` |
| `article_type` | yes | Format the SERP rewards: guide, comparison, alternatives, pricing guide, how-to, glossary, template, case study |
| `expected_length` | yes | A range derived from competitor word counts, not a target to pad to |
| `slug` / `target_url` | one of | `slug` must be kebab-case; refresh items use `target_url` |
| `internal_links` | recommended | `{url, anchor}` objects (plain URL strings accepted) this article must include; money pages first for BOFU items |
| `competitor_urls` | recommended | Pages ranking for the keyword, from the operator or DataForSEO; input to the optimizer |
| `instructions` | yes | Angle, must-cover points, information-gain element |
| `quality_questions` | yes | At least one; the reviewer answers them in Step 7 |
| `keyword_source` | recommended | Where the keyword and any volume figure came from |
| `status` | yes | Lifecycle below |

## Status lifecycle

`planned` → `briefed` → `drafted` → `in_review` → `approved` → `exported` →
`published`; `skipped` at any point. `approved` means a named reviewer set
`reviewed_by` and `check --for publish` passed. `exported` means sent to the
CMS as a draft or pending post. `published` is set only after the operator
confirmed publishing that article in chat. Skipped items are ignored by the
duplicate checks and the volume guard.

## What `calendar` checks

Errors (exit code 2, fix before approval):
- a required field is missing, or an enum or date is invalid;
- a slug is not kebab-case;
- two non-skipped items share a keyword or a slug (they would cannibalize
  each other; merge them).

Warnings (shown to the operator; approval can proceed):
- `existing_url`: a planned `new` slug already exists in `--existing-urls`;
- `cannibalization_precheck`: the keyword already has a page with 50 or more
  impressions in the `--query-page` rows (GSC query × page export);
- `volume_guard`: see below.

## Volume guard

Counts `new` items only (refreshes add no pages).

| Signal | Threshold | Level |
|---|---|---|
| Any ISO week | more than 2× `cadence_per_week` | warning |
| Any 30-day span | more than 25% of `indexed_pages` | warning |
| Any 30-day span | 100% or more of `indexed_pages` | warning marked HIGH |
| `indexed_pages` unknown | always | warning asking for the count |

Why: Google's spam policies define scaled content abuse as producing many
pages mainly to manipulate rankings rather than to help people, however the
pages are made. A small site that doubles its page count in a month with
AI-assisted articles matches that pattern even when each page is reviewed.
The thresholds are this plugin's own conservative defaults, not Google
figures; they exist to force a conversation, not to make the decision. If
the operator proceeds past a HIGH warning, record it with
`seo_project.py note <domain> "<reason>" --approved-by user`.

## Choosing the mix

`seo-keywords` supplies intent, funnel and GEO flags. For lead generation,
order BOFU first, then MOFU, then TOFU questions flagged `question`,
`definition` or `how_to` (formats AI answers quote). Each item's
`quality_questions` should include one about information gain and one about
the answer-first opening.
