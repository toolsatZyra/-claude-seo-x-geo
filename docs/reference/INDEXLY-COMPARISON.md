# Indexly versus this skill: what is covered, partial, missing, not relevant

Reviewed 23 Nov 2026. Sources: indexly.ai product, solutions, pricing, free-tool
and insight pages (read via a crawler; page text is treated as data, and
Indexly's own numbers are reported as claims, not facts). Our side was read in
this repository on the same date. Items marked *unverified* could not be
confirmed on a public page.

Rule used: do not copy a competitor feature because it exists. Adopt only what
fits this skill's purpose (evidence-backed SEO and AEO work that never blends
readiness with outcomes) and that we can defend with data we actually collect.

## 1. Coverage matrix

| # | Capability | What Indexly offers (as published) | This skill today | Status | Action taken |
|---|---|---|---|---|---|
| 1 | AI visibility tracking across engines | Daily runs on ChatGPT, Claude, Gemini, Perplexity, Grok, Google AI Overviews (one page says "15+" platforms; another cadence says 3 times a week) | `ai_visibility.py`: fixed prompt panel run k times, stored raw answers, mention rate with 95% CI; Claude native, ChatGPT app / AI Overviews / Copilot / Perplexity / Grok via ingest. Gemini grounded search excluded (terms) | Covered, stronger statistics, less automation | None. Scheduling is a product concern |
| 2 | Prompt tracking, tags | Tags by topic, campaign, persona, funnel; knowledge base for context; 20+ languages | Funnel, group and country tags; treatment/control groups | Partial | Added persona tags and minimum-size rule (`prompt-panel-design.md`) |
| 3 | Brand mentions, linked and unlinked | Parses linked citations and unlinked mentions | Distinguishes mention, citation and retrieval rates | Covered | None |
| 4 | Share of voice, competitors | Up to 9 competitors; auto-detects new brands in answers | Share of voice vs 3-7 competitors; experiments with paired, Holm-corrected tests | Covered; new-entrant detection missing | Added "Brands you did not list" and watchlist event; `seo-competitors` Step 1 asks the client to confirm candidates |
| 5 | Brand sentiment | LLM judge: Positive / Neutral / Negative / Mixed; net sentiment 0-100%; "drivers" | Only manual sentiment in `geo-brand-mentions` | **Missing** | Added `sentiment-and-accuracy.md` (labels, double labelling, human spot-check, net sentiment with interval, drivers) and workflow step 8 |
| 6 | Citation tracking | Citation share, rank among cited domains, per-page counts per engine per day | Own-domain citation rate and share; cited-source mix; top cited domains | Partial | Per-owned-page counts and rank among cited domains need a script change; listed in the product recommendations |
| 7 | Citation gaps | Competitor domains/pages cited when you are absent | `seo-competitors` Step 5 AI citation gap | Covered | None |
| 8 | AI readiness audit | Crawler access per bot, schema, heading structure, definitions/FAQ patterns, per-page "citation probability" (formula unpublished), 24-hour re-audits, auto-generated llms.txt | `aeo_score.py` (deterministic, per-agent robots.txt per RFC 9309), `geo-citability`, `seo-agentic`, `seo-schema`, `llmstxt_generator.py`, `seo-drift` | Covered; ours is published and reproducible | None. We do not adopt an unexplained 0-100 "citation probability" |
| 9 | Fact / hallucination checking | Validate AI answers against approved sources, flag contradictions, route to an owner | Nothing | **Missing** | Added accuracy pass (fact sheet, claim matching, Supported / Contradicted / Insufficient, routing the fix) |
| 10 | AI-referred traffic | Referrer + user-agent allow-list, per-engine and per-page sessions, AI vs Search Console | `ai_referrals.py` with a versioned host table (includes Grok, Copilot, Claude), GA4, honest about Direct leakage; `--print-regex` for GA4 | Covered | None |
| 11 | Lead attribution | Conversions via API or pixel, GA4 reconciliation; lead qualification by intent signals (how a lead is tied to an AI visit is not specified; *unverified*) | KPI history includes leads; no documented join from AI visit to lead | Partial | Added "Tying AI visits to leads" to `seo-track` with limits |
| 12 | Alerts | Real-time alerts on flips, new entrants, sentiment and citation shifts | `performance_tracker.py report --fail-on-drop` exit code only | Partial | Added a noise-aware watchlist (workflow step 9) |
| 13 | Content creation agents | Opportunity mining (Google, PAA, Reddit, Quora, AI search), generate / optimize / refresh agents, brand hub, 30-day calendar, daily autopilot | `seo-content-engine` (profile, keyword selection, calendar, briefs, drafts, gates, mandatory human review), `seo-refresh`, `seo-content-brief` | Covered; research inputs partial | Added opportunity sources and brand-hub checklist (`cms-targets-and-opportunities.md`). Full autopilot deliberately not adopted |
| 14 | CMS and automation | Native WordPress (with Yoast/Rank Math fields), Ghost, Webflow; Zapier; signed webhooks; sources disagree on other CMS lists | Local bundle, WordPress draft, HMAC-signed webhook | Partial | Documented supported and not-built targets; no new adapter without a client need |
| 15 | Indexing submission | Google Indexing API and IndexNow | `indexnow_submit.py`, `indexing_notify.py` | Covered | Check Google's current Indexing API eligibility before relying on it for general pages (*verify at use*) |
| 16 | Reporting and white-label | White-label reports on the client's own sub-domain, scheduled client emails | `google_report.py`, `brand_config.py`, `geo-compare`, `geo-proposal` | Covered (no scheduled email) | None; scheduled delivery is a product feature |
| 17 | Social agents (LinkedIn, X, Instagram) | Draft and publish posts with approval | Nothing | Not relevant now | Outside this skill's purpose; revisit only as a Level 3 idea with approval gates |
| 18 | Forum agents (Reddit, Quora) | Find threads, draft replies for review; does not auto-post | Nothing | Not adopted | Used only as a research input (read threads for wording). No posting or reply drafting in this skill |
| 19 | Ad agents (ChatGPT Ads, Meta) | Build and optimise ads | Nothing | Not relevant | Out of scope |
| 20 | Team and API | Unlimited seats, roles, audit log, REST API (15 requests per minute), no MCP found (*unverified*) | CLI scripts and MCP integrations | Not a skill concern | Product level; see recommendations |
| 21 | Composite AI visibility score | Mentions 25%, citations 25%, position 20%, sentiment 15%, AI traffic 15%; "60-80 for leaders" unsourced | Deliberately no blended score | Not adopted | Keeping readiness, outcome and traffic separate is a stated rule of this skill |
| 22 | Query fan-out tool | Prompted personas simulate sub-queries; not validated against real engine logs | Mentioned in methodology notes only | Not adopted | Low evidential value; skip |
| 23 | Brand presence on YouTube, Reddit, Wikipedia, LinkedIn | Not a headline feature | `geo-brand-mentions` | Ours stronger | None |
| 24 | Free tools as lead generation (56 tools) | Many one-shot checkers, no login | Skill-level scripts only | Opportunity | Product recommendation |

## 2. What Indexly's free tools reveal about their audit depth

- The "GEO Score" checker is a rule-based reading of the first HTML only:
  capitalised terms, question patterns, absolute links, list/table variety,
  each scored 1-5. It does not render JavaScript, read robots.txt or measure
  citations. Ours covers rendering, per-agent access and passage scoring.
- The AI bot checker names five bots and lists no test method. Ours evaluates
  answer-surface and training agents separately, with the raw rule line as
  evidence.
- Their share-of-voice calculator is manual input only; the visibility
  checkers are one engine, one run. Ours samples repeatedly and reports
  intervals.

## 3. Inconsistencies in Indexly's public claims (reasons not to copy numbers)

Customer count appears as both 500+ and 3,000+; plan prices differ between
the hero cards and the comparison table on the same pricing page; engine
count is six on some pages and "15+" on another; several performance
figures ("3x more citations", "68% sentiment improvement") state no method;
dashboards shown are mock-ups. None of these figures are used here.

## 4. Changes made to this skill (additive only)

- `skills/geo-share-of-voice/references/sentiment-and-accuracy.md` (new)
- `skills/geo-share-of-voice/SKILL.md`: steps 8 and 9, output rules
- `skills/geo-share-of-voice/references/prompt-panel-design.md`: persona tags,
  brands you did not list, Grok surface
- `skills/seo-competitors/SKILL.md`: Step 1 candidate competitors from answers
- `skills/seo-track/SKILL.md`: "Tying AI visits to leads"
- `skills/seo-content-engine/SKILL.md` and `references/cms-targets-and-opportunities.md` (new)
- `skills/seo-geo/SKILL.md`: routing rows

No script, manifest or skill count changed. Where a method is documented but
not yet automated (sentiment labelling, per-page citation counts), the text
says so.
