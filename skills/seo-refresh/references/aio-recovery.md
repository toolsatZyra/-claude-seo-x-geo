# AI Overview recovery playbook

For pages whose rankings held but whose clicks fell because an AI Overview
(or another results-page feature) now answers the query. The goal is not to
"beat" the AI Overview; it is to be the source it cites and to give searchers
a reason to click through.

## Trigger

`content_decay.py` reports cause `serp_feature_or_ai_overview`: impressions
not down by 15% or more, average position within 1.0 of the baseline, CTR
down 20% or more. That pattern says something on the results page changed;
it does not say what. Confirm before acting.

Context: Ahrefs measured position-1 CTR on keywords that show an AI Overview
falling from 7.3% to 1.6% between December 2023 and December 2025
(ahrefs.com/blog/ai-overviews-reduce-clicks-update/). Treat it as an industry
measurement, not a forecast for this page.

## Step 1: Confirm the feature (CONFIRMED evidence only)

For the page's top 5-10 queries (from `content_decay.py candidates` or a GSC
query × page export):

- Check whether an AI Overview appears: a manual check (record date,
  location, device, signed-out browser) or DataForSEO SERP data that
  includes AI Overview items. Never scrape Google.
- Record which sources the AI Overview cites, and whether our page is one.
- Note other features that take clicks (featured snippet, People Also Ask,
  video, local pack, shopping).

If no feature is present for the main queries, the cause is something else
(query mix, snippet quality, a competitor's richer result): go back to
Step 2 of the skill.

## Step 2: Segment each affected query

| Segment | Definition | Response |
|---|---|---|
| **Cited** | Our page is a cited source in the AI Overview | Protect the cited passage (keep it accurate and stable); add depth the summary cannot give (tools, templates, worked examples, original data) so the click is worth it; strengthen the snippet. Expect partial, not full, CTR recovery |
| **Not cited** | AI Overview present, our page absent, no single competitor dominates | Answer-first rewrite of the sections that match the query (below) |
| **Competitor cited** | One or more competitor pages are cited, ours is not | Compare the cited passage with ours: does theirs give a direct definition, a number with a source, fresher data, a clearer step list? Close that gap with better-sourced content of our own; never copy wording |
| **Intent shift** | The results page now serves a different need (tools, video, local, product listings) | Refreshing text will not help. Re-target the page to the intent it still matches, or create the format the results now reward; consider consolidating |

Tag the segment per query as CONFIRMED (observed in a dated SERP check) and
any explanation of why as INFERRED.

## Step 3: Answer-first rewrite (Not cited / Competitor cited)

Make the relevant sections easy to quote accurately:

1. Put the direct answer first: the first 1-3 sentences under the heading
   answer the query on their own, without "as mentioned above".
2. Phrase the heading as the question when the query is a question.
3. Name the subject explicitly in each self-contained passage (no orphan
   pronouns), so a quoted passage still makes sense.
4. Add specific, attributed facts: numbers with their source and date,
   quotes from named experts the client can stand behind. The Princeton GEO
   study (Aggarwal et al., KDD 2024) found adding citations, quotations and
   statistics raised visibility in generative-engine answers, while keyword
   stuffing did not; do not repeat the query to "match" the AI Overview.
5. Use lists or a table where the answer is a set of steps or options.
6. Keep the URL. Update `dateModified` only if the change is substantive
   (see [refresh-rules.md](refresh-rules.md)).

Score the rewritten sections with
`python3 scripts/content_export.py check page.md --aeo` (informational) and
present the change as a section-level diff for approval (skill Step 5).

## Step 4: Snippet

Rewrite the title and meta description for the top queries: say what the
page offers beyond the summary (a calculator, a template, current prices, a
comparison table). Never promise content the page does not have.

## Step 5: Measure at +7 / +14 / +28 days

| Day | Check | Healthy signal |
|---|---|---|
| +7 | Recrawl and indexing (`gsc_inspect.py`); repeat the SERP check | New version indexed; citation status recorded |
| +14 | GSC CTR and clicks on the top queries (`rank_tracker.py report`, or `content_decay.py analyze --as-of`) | CTR stops falling; any gain in citations |
| +28 | Same, plus AI visibility for the related prompts (`geo-share-of-voice`) | CTR or clicks above the post-drop level; page cited for more queries |

GSC data lags 2-3 days; read day +7 as "indexed?", not as a result.

Falsifiability: if by +28 days the page is indexed in its new form, still not
cited, and CTR on the top queries is unchanged or lower, the rewrite did not
work. Re-check the segment (it may be an intent shift) before trying again,
and do not stack further rewrites on the same page inside 28 days, or no
change can be attributed.

## What not to do

- Do not block Google's crawlers or add `nosnippet` to escape AI Overviews
  without the operator understanding the trade-off: it can remove the page's
  regular snippet and its eligibility to be cited.
- Do not bump dates, rewrite for "AI keywords", or split pages into thin
  chunks for AI parsing; this plugin treats those as neutral-to-negative.
- Do not attribute a CTR drop to AI Overviews in a report without the dated
  SERP evidence from Step 1.
