# CMS targets, opportunity sources and the brand hub

Reference for `seo-content-engine`. Nothing here changes the non-negotiables:
draft first, human review mandatory, publishing only after the gates.

## 1. Export targets

| Target | Status | Notes |
|---|---|---|
| Local bundle (HTML noindex, JSON-LD, Markdown) | Supported (`content_export.py bundle`) | Default; works for any site |
| WordPress draft, idempotent by slug | Supported (`content_export.py wordpress`) | Application Password in an environment variable |
| Signed webhook (HMAC-SHA256) | Supported (`content_export.py webhook`) | Reaches other CMSs and automation tools through the client's own receiver |
| Ghost | Not built | Admin API; would follow the same draft-first, dry-run-first pattern |
| Webflow | Not built | CMS Collections API; needs per-collection field mapping |
| Contentful and other headless CMSs | Not built | Field mapping differs per space; use the webhook until demand is shown |

A competitor (Indexly) lists WordPress, Ghost and Webflow natively and Zapier
for the rest, and says it can write Yoast and Rank Math fields. We add a
target only when a real client needs it; each new target must ship with the
same gates (draft default, dry run, explicit confirm, no secrets on the command
line).

## 2. Opportunity sources for Step 1 (keyword selection)

Use these as inputs to the existing scoring, not as separate lists:

- Search Console queries and "people also ask" questions (already used).
- Questions asked on forums and Q&A sites (Reddit, Quora): read threads as
  research to learn the real wording and objections. Cite the thread in the
  brief. This skill does **not** post or reply on any forum; replying is a
  human act the client does under their own account and the forum's rules.
- Questions the AI share-of-voice panel shows the client missing from
  (`geo-share-of-voice` per-prompt table): each prompt where competitors are
  cited and the client is not is a content candidate.
- Competitor content and format gaps (`seo-competitors` Step 3).

Rank by search demand, competition and citation opportunity, and show the
evidence behind each rank. No invented volumes.

## 3. Brand hub (the project profile fields the drafts read)

The drafts need the same facts every time. The project profile
(`seo_project.py`) should hold: business description, audience, tone of
voice with two or three approved sample paragraphs, products or services with
approved wording, competitors, banned claims, approved sources, and image
rules. A draft that needs a fact not in the profile stops and asks; it never
guesses.

## 4. Not adopted

- Fully automatic daily publishing without review (Indexly offers "full
  autopilot"). We keep mandatory human review; scaled unreviewed content is a
  quality and policy risk.
- Multi-model drafting and a per-article "GEO score" as a marketing figure.
  Our quality gates (claims, citability, optimizer, schema) already report
  specific checks, and we do not publish an unexplained score.
