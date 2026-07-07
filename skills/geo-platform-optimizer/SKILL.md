---
name: geo-platform-optimizer
description: Platform-specific AI search optimization — audit and optimize for Google AI Overviews, ChatGPT, Perplexity, Gemini, and Bing Copilot individually
tags: [geo, ai-search, platform-optimization, chatgpt, perplexity, gemini, aio]
allowed-tools: Read, Grep, Glob, Bash, WebFetch, Write
metadata:
  version: "3.0.0"
  author: geo-seo-claude (grafted)
---

# GEO Platform Optimizer

## Core Insight

Cross-platform citation overlap is low: only a minority of domains (commonly cited as ~11%, though this figure has not been independently re-verified -- treat as directional, see [[evidence-registry]]) are cited by BOTH ChatGPT and Google AI Overviews for the same query. Each AI search platform uses different indexes, ranking logic, and source preferences. A page optimized for Google AI Overviews may be invisible to ChatGPT, and vice versa. Platform-specific optimization is not optional — it is the foundation of any serious GEO strategy.

## How to Use This Skill

1. Collect the target URL and the site's primary topic/industry
2. Run each platform checklist below against the site
3. Score each platform on the 0-100 rubric
4. Generate GEO-PLATFORM-OPTIMIZATION.md with per-platform scores, gaps, and action items

## Scoring discipline (mandatory — apply to every criterion below)

Every row in the 5 scoring rubrics below is anchored to a countable fact
(a number of threads/videos/properties found, a date threshold, a binary
presence check) per `skills/seo/references/scoring-rubric.md` Rule 3 —
none should be scored from a bare adjective or general impression anymore.
Apply this discipline when running the rubrics:

1. **Cite the actual evidence per criterion** — the specific search you
   ran, the count you found, the URL you checked, the date you observed —
   before picking a point value. If you didn't run the check, say so.
2. **"No evidence found" scores the criterion's lowest listed value**,
   never a middle value assumed out of politeness or general impression of
   brand quality. If a row's top tier requires ">=3 threads found," you
   must be able to name those 3 threads, not estimate that there are
   "probably several."
3. **If you find a row phrased with a bare adjective and no attached
   count** (this should not happen anymore, but flag it if you find one),
   treat it as scoring 0 unless you can name specific instances that
   satisfy it — do not award partial credit for an impression.
4. **Do not let one platform's score influence another's.** A brand
   strong on YouTube is not thereby more likely to be strong on Reddit —
   score each platform from that platform's own evidence only.
5. **Compute every platform total with an actual tool call, not prose
   arithmetic** (`skills/seo/references/scoring-rubric.md` Rule 4). A live
   test found both independent runs' reported totals didn't match their
   own itemized scores (one summed to 23 but reported 38; the other summed
   to 10 but reported 24) — good criteria and cited evidence were not
   enough on their own. Run e.g. `python3 -c "print(20+0+15+...)"` with the
   exact scores just assigned, and show that expression in the output next
   to the total.
6. **N/A criteria renormalize, per Rule 4** — a criterion marked N/A
   (GitHub for non-technical brands, Bing Places for non-local businesses,
   Google Merchant Center for non-e-commerce sites) is excluded from both
   the earned-points sum and the max-points denominator, then the result is
   rescaled to /100. Do not silently score an N/A criterion as 0 out of
   the full possible total.

---

## Platform 1: Google AI Overviews (AIO)

### How AIO Selects Sources
- A large majority of AIO citations come from pages already ranking in the **top 10 organic results** — traditional SEO is the gateway. The exact share moves quickly: Ahrefs reported 38% in one study and 76% in a later one within the same research year. Don't quote a fixed percentage without checking [[evidence-registry]] for the current figure first.
- AIO also has its own selection logic independent of raw rank -- some citations come from pages outside the top 5, favoring clarity and directness over position alone
- AIO strongly favors pages with **clean structure, direct answers, and scannable formatting**
- Featured snippet optimization has ~70% overlap with AIO optimization
- AIO prefers **concise, factual, unambiguous answers** — hedging and filler reduce citation probability

### Optimization Checklist

1. **Question-Based Headings**: Use H2/H3 headings phrased as questions matching real user queries. Check Google's "People Also Ask" for the target topic and mirror those exact phrasings.
2. **Direct Answer in First Paragraph**: After each question heading, provide a clear 1-2 sentence answer immediately. Then expand with supporting detail. The first sentence should be a standalone citation candidate.
3. **Tables and Structured Comparisons**: AIO heavily cites tables. Convert any comparison, pricing, specification, or feature data into HTML tables. Use clear column headers.
4. **Ordered and Unordered Lists**: Step-by-step processes should use ordered lists. Feature lists should use unordered lists. AIO extracts these directly.
5. **FAQ Sections**: Add a dedicated FAQ section with 5-10 real questions. Use proper H3 headings for each question. Google retired FAQ rich results for ALL sites on May 7, 2026 (superseding the Aug 2023 gov/health-only restriction) -- there is no SERP rich-result benefit anymore. Keep the FAQ content pattern anyway: it still aids AIO/AI Mode extraction and entity resolution as a supporting signal, not a ranking feature. See `seo-schema/SKILL.md` for the canonical position.
6. **Definitions and Glossary Boxes**: For any industry-specific term, provide a clear definition. Format: "**[Term]** is [concise definition]." AIO frequently cites definitions.
7. **Statistics with Sources**: Include specific numbers with attribution. "According to [Source], [statistic]." AIO prefers citeable, specific claims over vague assertions.
8. **Publication Date**: Include a visible publication date and last-updated date. AIO deprioritizes undated content for time-sensitive queries.
9. **Author Byline**: Display author name with credentials. Link to an author page with bio, credentials, and sameAs links.
10. **Page Depth**: Keep target pages within 3 clicks of homepage. AIO rarely cites deep, orphaned content.

### Scoring Rubric (0-100)

| Criterion | Points | How to Score |
|---|---|---|
| Ranks in top 10 for target queries | 20 | 20 if yes, 10 if top 20, 0 if beyond |
| Question-based headings present | 10 | 2 points per question heading, max 10 |
| Direct answers after headings | 15 | 3 points per direct answer, max 15 |
| Tables present for comparison data | 10 | 10 if >=1 HTML table covers comparison/pricing/spec data with labeled column headers, 5 if a table exists but lacks labeled headers or covers only some of the comparable data, 0 if no table exists despite comparable data being present in prose |
| Lists for processes/features | 10 | 10 if step-by-step processes use ordered lists AND feature lists use unordered lists, 5 if only one of those two applicable patterns is followed, 0 if neither is used despite list-worthy content existing |
| FAQ section with 5+ questions | 10 | 10 if 5+, 5 if 1-4, 0 if none |
| Statistics with citations | 10 | 2 points per cited stat, max 10 |
| Publication/updated date visible | 5 | 5 if both dates, 3 if one, 0 if none |
| Author byline with credentials | 5 | 5 if a named author with a linked bio/credentials page is shown, 3 if a name is shown with no bio/credentials link, 0 if no author is named |
| Clean URL + heading hierarchy | 5 | 5 if exactly one H1 and zero skipped heading levels, 3 if one skipped level or 2 H1s, 0 if 2+ skipped levels or no discernible heading structure |

---

## Platform 2: ChatGPT Web Search

### How ChatGPT Selects Sources
- Uses **Bing's search index** as its foundation (not Google)
- Top citation sources by domain share: Wikipedia is the most-cited domain across all major AI assistants; Ahrefs' Dec 2025 study (75K brands) put ChatGPT's Wikipedia citation rate at ~16.3%, ahead of Perplexity (~12.5%) and Google AI Overviews (~8.4%) -- see [[evidence-registry]] for the source and re-check before quoting an exact number, as these shift between studies. Reddit, YouTube, and major news outlets round out the top sources.
- ChatGPT heavily weights **entity recognition** — if your brand exists as a structured entity (Wikipedia, Wikidata, Crunchbase), it is far more likely to be cited
- Prefers **authoritative, well-established sources** over new or niche sites
- Longer, more comprehensive articles get cited more often than short pieces
- ChatGPT tends to cite **the most canonical source** for a claim rather than the original

### Optimization Checklist

1. **Wikipedia Presence**: Check if the brand/person/product has a Wikipedia article. If not, assess notability criteria. If notable, create a draft. If an article exists, ensure it is accurate and current.
2. **Wikidata Entity**: Verify the entity exists on Wikidata (wikidata.org). If not, create a Wikidata item with key properties: instance of, official website, social media links, founding date, headquarters location.
3. **Bing Webmaster Tools**: Verify the site is registered in Bing Webmaster Tools. Submit sitemap. Check for crawl errors.
4. **Bing Index Coverage**: Use `site:domain.com` on Bing to verify key pages are indexed. Bing may have different indexed pages than Google.
5. **Reddit Authority**: Check for brand mentions on Reddit. Identify relevant subreddits. Assess whether the brand participates authentically in discussions.
6. **YouTube Presence**: Verify YouTube channel exists with relevant content. Video descriptions should contain full URLs and entity information.
7. **Authoritative Backlinks**: ChatGPT/Bing weight .edu, .gov, and major publication backlinks heavily. Audit backlink profile for these sources.
8. **Entity Consistency**: Brand name, founding date, leadership, and key facts must be consistent across Wikipedia, Crunchbase, LinkedIn, and the official website.
9. **Comprehensive Content**: Pages targeting ChatGPT citation should be **2000+ words** with thorough topic coverage. ChatGPT prefers single authoritative sources over combining multiple thin pages.
10. **Clear Attribution**: Include "About" sections, company descriptions, and founding stories. ChatGPT uses these for entity grounding.

### Scoring Rubric (0-100)

| Criterion | Points | How to Score |
|---|---|---|
| Wikipedia article exists and is accurate | 20 | 20 if exists, 10 if stub, 0 if none |
| Wikidata entity with 5+ properties | 10 | 10 if >=5 properties present on the Wikidata item, 5 if 1-4 properties present, 0 if no Wikidata item found |
| Bing index coverage of key pages | 10 | 10 if a `site:domain.com` Bing search returns all checked key pages, 5 if some but not all are returned, 0 if none are returned or not checked |
| Reddit brand mentions (positive) | 10 | 10 if >=3 threads found via search with net-positive sentiment, 5 if 1-2 threads found or sentiment is mixed, 0 if none found or not checked |
| YouTube channel with relevant content | 10 | 10 if a channel exists with a video published in the last 90 days, 5 if a channel exists but the most recent video is 90+ days old, 0 if no channel found |
| Authoritative backlinks (.edu, .gov, press) | 15 | 3 points per authoritative backlink category, max 15 |
| Entity consistency across platforms | 10 | 10 if brand name, founding date, and leadership match exactly across all checked sources (Wikipedia, Crunchbase, LinkedIn, official site), 5 if exactly 1 fact differs across sources, 0 if 2+ facts differ or sources could not be cross-checked |
| Content comprehensiveness | 10 | 10 if >=2000 words with every subtopic in the target's "People Also Ask"/competitor coverage addressed, 5 if 800-1999 words or missing 1+ major subtopic, 0 if <800 words |
| Bing Webmaster Tools configured | 5 | 5 if verified, 0 if not |

---

## Platform 3: Perplexity AI

### How Perplexity Selects Sources
- Top citation sources: Reddit, Wikipedia, YouTube, and major publications all feature prominently; the specific per-domain share figure previously here could not be independently verified and has been removed rather than left uncorrected -- check [[evidence-registry]] before citing an exact number to a client
- Perplexity places the **heaviest emphasis on community validation** of all AI search platforms
- Strongly favors **discussion threads** where claims are debated, validated, or expanded by multiple participants
- Prefers recent content — publication date is a strong ranking signal
- Cites **multiple sources per answer** (typically 5-15), so there is more opportunity for mid-authority sites to appear
- Uses its own crawling infrastructure in addition to search APIs

### Optimization Checklist

1. **Active Reddit Presence**: The brand or its representatives should participate authentically in relevant subreddit discussions. Not promotional — helpful, specific, and community-oriented.
2. **Reddit AMAs and Threads**: Encourage or participate in AMAs, detailed discussion threads, and community Q&As. Perplexity treats these as high-signal content.
3. **Forum and Community Presence**: Beyond Reddit, check Hacker News, Stack Overflow, Quora, and niche industry forums. Perplexity indexes these heavily.
4. **Discussion-Friendly Content**: Publish content that invites discussion — opinion pieces, research findings, contrarian takes, original data. Content that gets shared and debated in communities ranks higher.
5. **Freshness Signals**: Publish content with clear dates. Update content regularly. Perplexity deprioritizes stale content more aggressively than other platforms.
6. **Multiple Source Validation**: Claims in your content should be supported by other sources. Perplexity cross-references and prefers claims it can verify from multiple origins.
7. **YouTube Video Content**: Create video content that Perplexity can reference. Ensure video titles, descriptions, and transcripts contain target information.
8. **Direct, Quotable Passages**: Write paragraphs that can stand alone as citations. Each paragraph should make one clear point with supporting evidence.
9. **Original Data and Research**: Publish original surveys, benchmarks, case studies, or datasets. Perplexity heavily favors primary sources.
10. **Perplexity Pages**: Check if Perplexity has created a "Page" about your topic/brand. These are curated summaries that influence future citations.

### Scoring Rubric (0-100)

| Criterion | Points | How to Score |
|---|---|---|
| Active Reddit presence in relevant subreddits | 20 | 20 if the brand/representatives posted or commented in a relevant subreddit within the last 90 days (name the thread), 10 if the brand is mentioned by others with no active participation found, 0 if no mentions found |
| Forum/community mentions (HN, SO, Quora) | 10 | 10 if mentions found on 2+ of {Hacker News, Stack Overflow, Quora}, 5 if found on exactly 1, 0 if none found |
| Content freshness (updated within 6 months) | 10 | 10 if the visible last-updated date is within 6 months, 5 if 6-12 months, 0 if >12 months or no date shown |
| Original research/data published | 15 | 15 if an original survey/benchmark/dataset with stated methodology is published, 10 if named case studies with specific client results are published, 5 if at least one first-party statistic is cited without full methodology, 0 if no first-party data appears |
| YouTube content with transcripts | 10 | 10 if a channel exists with >=1 video in the last 90 days that has captions/transcript available, 5 if a channel exists with videos but none in the last 90 days or none captioned, 0 if no channel found |
| Quotable, standalone paragraphs | 10 | 2 points per paragraph that states one specific claim/fact in its first sentence and reads standalone without surrounding context, max 10 |
| Multi-source claim validation | 10 | 10 if every major factual claim on the page links to or names an external source, 5 if some but not all major claims are sourced, 0 if no claims are sourced |
| Discussion-generating content | 10 | 10 if >=3 verifiable off-site discussion threads found via search that reference the content, 5 if 1-2 found, 0 if none found or not checked |
| Wikipedia/Wikidata presence | 5 | 5 if present, 0 if absent |

---

## Platform 4: Google Gemini

### How Gemini Selects Sources
- Uses **Google's search index** plus strong weighting toward **Google-owned properties**
- YouTube content is weighted significantly more heavily than in standard Google Search
- Google Business Profile data is directly accessible to Gemini
- Gemini uses Google's Knowledge Graph directly — entity presence in Knowledge Graph is a major advantage
- Structured data (Schema.org) is consumed directly by Gemini for entity understanding
- Gemini multi-modal: can reference images, videos, and text together

### Optimization Checklist

1. **Google Knowledge Panel**: Check if the brand has a Google Knowledge Panel. If not, claim it through Google Business Profile or structured data. Ensure all information is accurate.
2. **Google Business Profile**: Complete and optimize GBP with all fields: hours, services, photos, posts, Q&A. Gemini pulls directly from GBP for local queries.
3. **YouTube Strategy**: Create YouTube content for every key topic. Optimize titles, descriptions, timestamps, and closed captions. Gemini cites YouTube more than any other AI platform.
4. **YouTube Chapters and Timestamps**: Use chapters (timestamps in description) so Gemini can reference specific segments of videos.
5. **Google Merchant Center**: For e-commerce, ensure products are in Google Merchant Center. Gemini references product data directly.
6. **Structured Data (Schema.org)**: Implement comprehensive Schema.org markup. Gemini uses this for entity understanding more aggressively than other platforms.
7. **Google Sites Ecosystem**: Ensure presence across Google ecosystem: Google Scholar (for research), Google News (for publishers), Google Maps (for local).
8. **Image Optimization**: Gemini is multi-modal. Use descriptive alt text, structured image filenames, and high-quality images. Include relevant images with every piece of content.
9. **Google E-E-A-T Signals**: All standard Google E-E-A-T signals apply with extra weight. Author pages, about pages, editorial policies, and expertise demonstrations.
10. **Chrome Web Store / Google Workspace Marketplace**: For software companies, presence on Google platforms adds entity signals.

### Scoring Rubric (0-100)

| Criterion | Points | How to Score |
|---|---|---|
| Google Knowledge Panel exists | 15 | 15 if a panel appears for a brand-name search with logo, description, and social links all populated, 10 if a panel appears but is missing 1+ of those fields, 0 if no panel appears |
| Google Business Profile complete | 10 | 10 if GBP exists with hours, services, photos, and a post within the last 90 days all present, 5 if a GBP exists but is missing 1+ of those, 0 if no GBP found |
| YouTube channel with topic-relevant content | 20 | 20 if a channel exists with a video in the last 90 days using chapters/timestamps, 10 if a channel exists but lacks a recent video or chapters, 0 if no channel found |
| Schema.org structured data implemented | 15 | 15 if entity schema (Organization/Person) AND a page-type schema (Product/Article/LocalBusiness) are both present with required properties, 10 if only one of those two is present, 5 if only a minimal/incomplete schema block exists, 0 if no schema present |
| Google ecosystem presence (Scholar, News, Maps) | 10 | 10 if 3+, 5 if 1-2, 0 if none |
| Image optimization (alt text, filenames) | 10 | 10 if 100% of checked images have descriptive alt text and non-generic filenames, 5 if 50-99% do, 0 if <50% do |
| E-E-A-T signals (author pages, about, editorial) | 10 | 10 if all 3 present (author bio page with credentials, About page, stated editorial/review policy), 5 if 1-2 present, 0 if none present |
| Google Merchant Center (if e-commerce) | 5 | 5 if products are found listed in Google Merchant Center / Shopping results, 0 if e-commerce but no listings found, N/A if not an e-commerce site |
| Multi-modal content (text + images + video) | 5 | 5 if the page includes text, at least 1 relevant image, and at least 1 embedded/linked video, 3 if it includes text plus only one of image or video, 0 if text-only |

---

## Platform 5: Bing Copilot

### How Copilot Selects Sources
- Uses **Bing's search index** (shared infrastructure with ChatGPT but different ranking/selection)
- Supports **IndexNow protocol** for near-instant indexing of new and updated content
- Copilot tends to cite **fewer sources per answer** (typically 3-5) but gives more prominent attribution
- Microsoft ecosystem integration: LinkedIn, GitHub, Microsoft Learn content is weighted
- Copilot prefers pages with clear, structured markup and fast load times

### Optimization Checklist

1. **Bing Webmaster Tools**: Register and verify site. Submit XML sitemap. Review and fix any crawl issues.
2. **IndexNow Implementation**: Implement the IndexNow protocol to notify Bing of content changes in real-time. Submit a key file at `/.well-known/indexnow-key.txt` and ping the IndexNow API on content publish/update.
3. **LinkedIn Company Page**: Ensure the company LinkedIn page is complete with accurate description, employee connections, and regular posts. Copilot indexes LinkedIn content.
4. **GitHub Presence**: For tech companies, maintain an active GitHub presence. Copilot references GitHub repos, documentation, and README files.
5. **Microsoft Learn / Documentation**: If relevant, contribute to Microsoft Learn or ensure documentation is compatible with Microsoft's documentation standards.
6. **Bing Places for Business**: Equivalent to Google Business Profile. Complete all fields for local search visibility in Copilot.
7. **Clear Meta Descriptions**: Bing/Copilot weights meta descriptions more heavily than Google does. Write compelling, keyword-rich meta descriptions for every page.
8. **Social Signals**: Bing has historically weighted social signals (shares, likes, engagement) more than Google. Maintain active social media presence.
9. **Exact-Match Keywords**: Bing's algorithm is more literal about keyword matching than Google. Include exact target phrases in titles, headings, and body content.
10. **Fast Page Load**: Copilot deprioritizes slow pages. Target sub-2-second load time. Optimize images, enable compression, minimize render-blocking resources.

### Scoring Rubric (0-100)

| Criterion | Points | How to Score |
|---|---|---|
| Bing Webmaster Tools verified + sitemap | 15 | 15 if the site is verified in Bing Webmaster Tools AND a sitemap is submitted, 5 if only one of the two is confirmed, 0 if neither is confirmed or not checked |
| IndexNow protocol implemented | 15 | 15 if a key file is found at `/.well-known/indexnow-key.txt` (or equivalent documented location), 0 if not found |
| Bing index coverage of key pages | 10 | 10 if a `site:domain.com` Bing search returns all checked key pages, 5 if some but not all are returned, 0 if none are returned or not checked |
| LinkedIn company page (complete) | 10 | 10 if a company page exists with description, logo, and a post within the last 90 days, 5 if a page exists but is missing 1+ of those, 0 if no company page found |
| GitHub presence (if applicable) | 5 | 5 if a GitHub org/repo exists with a commit within the last 90 days, 0 if a GitHub presence exists but the last commit is 90+ days old, N/A if not applicable (non-technical brand) |
| Meta descriptions optimized | 10 | 10 if 100% of checked key pages have a unique meta description 150-160 characters, 5 if 50-99% do, 0 if <50% do |
| Social media engagement signals | 10 | 10 if a company social profile is found with visible posts within the last 30 days, 5 if a profile exists but the most recent post is 30+ days old, 0 if no profile found or not checked |
| Exact-match keywords in titles/headings | 10 | 10 if the exact target phrase appears in the title tag AND at least one heading, 5 if it appears in only one of the two, 0 if it appears in neither |
| Page load speed < 2 seconds | 10 | 10 if < 2s, 5 if < 4s, 0 if > 4s |
| Bing Places configured (if local) | 5 | 5 if a Bing Places listing exists with hours, address, and category all populated, 0 if a listing exists but is missing 1+ of those, N/A if not a local business |

---

## Cross-Platform Summary

### Universal Optimization Actions (help ALL platforms)
1. Wikipedia/Wikidata entity presence
2. YouTube channel with relevant content
3. Comprehensive, well-structured content with clear headings
4. Schema.org structured data (especially Organization + sameAs)
5. Fast page load and clean HTML
6. Author pages with credentials and sameAs links
7. Regular content updates with visible dates

### Platform-Specific Priorities
| Priority | Google AIO | ChatGPT | Perplexity | Gemini | Copilot |
|---|---|---|---|---|---|
| #1 | Top-10 ranking | Wikipedia | Reddit presence | YouTube | IndexNow |
| #2 | Q&A structure | Entity graph | Original research | Knowledge Panel | Bing WMT |
| #3 | Tables/lists | Bing SEO | Freshness | Schema.org | LinkedIn |
| #4 | Featured snippets | Reddit | Community forums | GBP | Meta descriptions |

---

## Output Format

Generate **GEO-PLATFORM-OPTIMIZATION.md** with the following structure.
Per Rule 4, each platform score and the Combined GEO Score must show the
actual computed expression, not just the resulting number — e.g.
`python3 -c "print(20+0+15+5+10+0+3+0+5)"` alongside its output — so a
reader can re-verify the sum against the itemized criteria table.

```markdown
# GEO Platform Optimization Report — [Domain]
Date: [Date]

## Overall Platform Readiness
- Combined GEO Score: XX/100 — computed as
  `round((AIO + ChatGPT + Perplexity + Gemini + Copilot) / 5)`; show the
  actual tool call with the 5 real numbers substituted in, not just the
  final figure

## Platform Scores
| Platform | Score | Computation shown | Status |
|---|---|---|---|
| Google AI Overviews | XX/100 | `python3 -c "print(...)"` -> XX | [Strong/Moderate/Weak] |
| ChatGPT Web Search | XX/100 | `python3 -c "print(...)"` -> XX | [Strong/Moderate/Weak] |
| Perplexity AI | XX/100 | `python3 -c "print(...)"` -> XX | [Strong/Moderate/Weak] |
| Google Gemini | XX/100 | `python3 -c "print(...)"` -> XX | [Strong/Moderate/Weak] |
| Bing Copilot | XX/100 | `python3 -c "print(...)"` -> XX | [Strong/Moderate/Weak] |

If any platform excluded an N/A criterion, state which one and show the
renormalized computation (Rule 4) instead of the plain sum.

Status thresholds: Strong = 70+, Moderate = 40-69, Weak = 0-39

## Platform Details

For each platform, the per-criterion breakdown is a table with a
mandatory Evidence column (Rule 6) — not scores listed in prose with
evidence folded elsewhere. A controlled two-run test found the run using
exactly this table shape caught its own unjustified scores (a criterion
that would otherwise be scored full marks with no stated basis) and
produced a more accurate total than the run that scored in loose prose:

| Criterion | Points possible | Score | Evidence |
|---|---|---|---|
| [criterion name] | XX | XX | [what you found, quoted/cited] or "No evidence found" |

Follow each platform's table with its Rule-4 tool-call computation (see
Platform Scores above) and a gaps/specific-actions summary.

## Prioritized Action Plan
### Quick Wins (this week)
[Actions that improve multiple platform scores with minimal effort]

### Medium-Term (this month)
[Actions requiring content creation or technical changes]

### Strategic (this quarter)
[Actions requiring entity building, community development, or platform presence]
```
