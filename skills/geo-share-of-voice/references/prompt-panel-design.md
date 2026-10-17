# Prompt panel design for AI share of voice

A share-of-voice number is only as good as the questions behind it. The
panel is a fixed, documented sample of the questions the client's buyers
ask AI assistants. Design it once, freeze it, and change it only by adding
new groups.

## Size and composition

| Item | Guidance | Why |
|---|---|---|
| Panel size | 20-50 prompts | Fewer than about 20 unbranded answers per engine is flagged thin; more than 50 adds cost faster than precision |
| Runs per prompt (k) | 5 or more per engine per measurement | Answers are non-deterministic; brand lists rarely repeat exactly, while mention frequency is steadier |
| Unbranded share | at least 80% | Only unbranded prompts count in the headline |
| Branded prompts | 3-5 | A knowledge check ("what is <client>", "<client> pricing"); reported separately, never in the headline |
| Competitor comparisons | 3-8 | "<client> vs <rival>", "<rival> alternatives"; these are BOFU and unbranded for the headline unless they name the client |

A prompt is branded when it names the client (any brand term, the profile
name or the domain, matched case- and accent-insensitively on word
boundaries). "rival alternatives" is unbranded; "client vs rival" is branded.

## Funnel coverage

Spread prompts across funnel stages in roughly the proportion that matters
for the client's pipeline. Tag each prompt with `--funnel`; untagged prompts
are classified by `seo_metrics.classify_intent()`.

| Stage | Example shapes | Share of panel |
|---|---|---|
| TOFU | "how do agencies forecast cash flow", "what is revenue operations" | 20-30% |
| MOFU | "best tools for agency resource planning", "crm features for consultancies" | 30-40% |
| BOFU | "<rival> alternatives", "pricing of agency crms", "<rival> vs <rival2>" | 30-40% |

Write prompts the way a buyer types or speaks them: full questions, no
keyword strings, no leading phrasing ("why is <client> the best ..."), and no
instructions to the model ("list 5 tools"), which change answer shape.

## Sources for prompts

1. Search Console queries phrased as questions (striking-distance and
   question-shaped queries from `seo-keywords`).
2. Sales and support call notes: the questions prospects ask before buying.
3. Community threads (Reddit, forums) in the client's category.
4. `seo-cluster` topic hubs: one or two prompts per hub the client wants to
   own.

Record the source of each prompt in the profile notes
(`seo_project.py note ... --approved-by user`) so a later reviewer can see
why it is in the panel.

## Treatment and control groups

Use groups whenever the client plans AEO changes and wants to know whether
they worked.

- **treatment**: prompts whose answers the planned work should move (the
  topics of the pages being rewritten, the comparisons being published).
- **control**: similar prompts on topics nobody will touch during the test.
  Control absorbs engine-wide drift (model updates, retrieval changes,
  seasonality); without it every change is "Unproven".
- Aim for 10 or more prompts per group. With Holm adjustment over treatment
  and control, at least 7 prompts must move in the same direction before a
  verdict can be significant, and a few ties are normal.
- Assign groups before the baseline window and never move a prompt between
  groups mid-test. Randomize assignment among comparable prompts when
  possible; if not, write down why each prompt is in its group.

## Cadence

| Purpose | Cadence |
|---|---|
| Monitoring | Monthly batch, same day-of-month, k = 5 |
| Experiment | Baseline window before the change; outcome window starting 2-4 weeks after the change ships (time to be crawled and retrieved) |
| After a known model launch | One extra batch, labelled in the profile notes, before comparing with earlier windows |

Keep everything else constant across windows: model id, engine, surface,
`--country`, and the panel.

## Engines and surfaces

| Engine | How | Surface |
|---|---|---|
| Claude (Messages API + web search) | `ai_visibility.py run --engine anthropic` | api |
| ChatGPT app | DataForSEO `ai_optimization_chat_gpt_scraper` via `seo-dataforseo`, then `ingest --engine chatgpt` | ui |
| AI Overviews / AI Mode, Copilot, Perplexity | licensed provider or manual capture, then `ingest` | ui |
| Gemini API grounded with Google Search | **excluded** (terms forbid caching and analysing grounded results) | n/a |

Never average across surfaces. Report each engine/surface as its own row and
let the reader compare them.

## Cost control

- Run `plan` first and confirm the call count with the operator in chat.
- `--max-calls` equal to the confirmed count; a paused search turn consumes
  extra calls and can end a batch early, which keeps what it collected.
- `--group` measures one group only, for example to re-check treatment.
- Token spend depends on answer length and search usage; quote call counts,
  never invented dollar figures.

## Manual capture protocol (ui surfaces)

1. Logged-out or fresh session, no custom instructions, memory off.
2. One prompt per new conversation; paste the prompt exactly.
3. Copy the full answer text and every source link shown.
4. Record time (UTC), product/model label and locale.
5. Repeat k times per prompt, in separate conversations.
6. Save as JSONL in the format shown in the skill and ingest with
   `--surface ui`.
