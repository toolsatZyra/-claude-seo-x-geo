# Publishing gates

Every gate `scripts/content_export.py` enforces, and why. `check --for draft`
runs the draft gates; `check --for publish` runs draft + publish gates.
Errors block (exit code 2); warnings are shown and do not block. `bundle`,
`webhook` and `wordpress` run the same gates automatically before writing or
sending anything.

## Which gate set applies

| Export | Gate set |
|---|---|
| status `draft` or `pending`, event `save_draft` (the default for these statuses) | draft |
| status `publish` (default event `publish_articles`) | publish |
| event `publish_articles` or `update_article`, any status | publish: a receiver keyed on `event_type` may publish (or overwrite a live article) without reading `status` |
| WordPress update of a post that is already `publish` or `future` | refused unless `--status publish`, which applies the publish gates |

The effective status comes from `--status` on the command line (default
`draft`). A `status: publish` in front matter alone never publishes; the tool
exports a draft and says how to apply the requested status. `--event` is
optional: drafts get `save_draft`, a non-publishing event, unless the operator
asks for a publishing event, which then needs the publish gates.

Front matter types are checked on load: `title`, `slug`, `meta_description`,
`image_url`, `status` and `reviewed_by` must be text (quote values such as
`title: "1984"`), `tags` a list or comma-separated string. A `false`, number
or list there is an error with a fix hint, never silently turned into text.

## Draft gates

| Gate | Level | Rule | Why |
|---|---|---|---|
| `required_field` | error | `title`, `slug`, `meta_description` present | A CMS post without them gets auto-generated values nobody reviewed |
| `required_field` | warning | `primary_keyword` present | The optimizer and placement checks need it |
| `slug_format` | error | kebab-case: `a-z`, `0-9`, single hyphens | Stable, readable URLs; also makes the slug safe as an output filename (no `../`) |
| `slug_format` | warning | 75 characters or fewer | Long slugs get truncated in results and are hard to share |
| `meta_description_length` | error | 70-160 characters | Very short descriptions say little and are often rewritten by Google; longer ones get truncated in results |
| `title_length` | warning | 60 characters or fewer | Longer titles are often truncated in results (display is width-based) |
| `status_value` | error | `draft`, `pending` or `publish` | Anything else is ambiguous to the CMS |
| `single_h1` | error | Exactly one H1; the title counts as the H1 when the body has none | One clear page topic; CMS themes render the title as H1, so the body's leading H1 is stripped from CMS payloads |
| `image_alt` | error | Every body image has alt text; `image_url` needs `image_alt` | Accessibility, and image search understands the image |
| `url_format` | error | `image_url` and `canonical` are absolute http(s) URLs | Relative values break once the content leaves this file |
| `schema_json` | error | `schema` (inline JSON-LD or a path next to the file) parses as JSON | Unparsable JSON-LD cannot be used for rich results (Search Console reports it as unparsable structured data) |
| `schema_json` | error | A `schema` path is relative, stays inside the Markdown file's folder (no `..` or symlinks out), ends in `.json`/`.jsonld`, is not hidden, under `~/.config` or named like a credential (secret, token, credentials, service account, `.env`), is at most 256 KiB, and holds JSON-LD (`@context` or `@type`) | The file's JSON is embedded in signed webhook payloads and bundle HTML; front matter may be drafted from untrusted research, so a path must not be able to ship a local secret |
| `schema_json` | warning | Every JSON-LD block has `@type` | A block without a type describes nothing |
| `unsafe_url` | error | No `javascript:`, `data:`, `vbscript:` or `file:` links, images or other URL attributes, including entity-encoded forms (`&#106;avascript:`, `javascript&colon;`) | Script injection through content |
| `unsafe_html` | error | No `on*` event handlers or `srcdoc`; removed from the final HTML of every engine, `--allow-html` included | Script injection through pasted HTML |
| `raw_html` | warning | Raw HTML is escaped unless `--allow-html` | Pasted HTML from AI tools or other sites can carry scripts and broken markup |

## Publish gates (in addition to the draft gates)

| Gate | Level | Rule | Why |
|---|---|---|---|
| `human_review` | error | `reviewed_by` is text containing a letter and is not a placeholder (TODO, TBD, n/a, none, pending, reviewer, name and similar; case and surrounding punctuation ignored, so `tbd.` is refused) | Google's guidance on generative-AI content asks publishers to review and fact-check AI-assisted content before publishing; the name makes the review accountable |
| `unresolved_marker` | error | No `[needs source]`, `[citation needed]`, `TODO`, `TK` or `{{` in the rendered page text (code blocks and code spans excluded; link targets, alt and title text included; any spacing inside brackets) or in any text or list front-matter value | These mark unverified claims and unfinished text; publishing them ships guesses as facts. The check reads the rendered page, so a malformed code span that displays as text cannot hide a marker |
| `word_floor` | error | At least `--min-words` words (default 300) | Catches empty or placeholder drafts. It is a floor, not a target: word count is not a ranking factor |

## Not gates, but required steps (Step 6 of the skill)

`content_verify.py` (claim citations), `content_quality.py` (filler and
AI-pattern signals), `content_optimizer.py` (coverage, density above 3%
flagged) and `check --aeo` (per-section citability) are run and reported by
the skill. They inform the reviewer; they do not replace review.

## Network safety

| Control | Behaviour |
|---|---|
| Dry run by default | `webhook` and `wordpress` make no network request without `--confirm`; the dry run prints the payload or request plan |
| HTTPS only | Webhook URLs and WordPress sites must use `https://` |
| Public hosts only | URLs go through `url_safety` (parse-time check, then DNS-pinned connection); private, loopback, link-local and cloud-metadata addresses are refused unless the operator listed the host in `CLAUDE_SEO_LOCAL_TARGETS` |
| No redirects | Requests never follow redirects, so signed content or credentials cannot be bounced to another host |
| Secrets from env vars | `--secret-env` and `--app-password-env` take the *name* of an environment variable; a value that looks like a secret instead of a name is refused |
| Signed webhooks | `X-Signature-SHA256` is the hex HMAC-SHA256 of the exact body bytes; sending unsigned needs `--allow-unsigned` |
| Password never printed | WordPress errors are scrubbed of the Application Password |
| Idempotent WordPress export | Looks up the slug (`status=any`) and updates only a post whose `slug` matches exactly (others in the response are ignored and reported); refuses when several posts share the slug |
| Live posts | A published or scheduled WordPress post is never downgraded or silently edited |
| Draft bundles | `<slug>.html` carries `noindex` until the export status is `publish` |

## Verifying the webhook signature (receiver side)

```python
import hashlib, hmac, json, time

def verify(raw_body: bytes, header_sig: str, secret: str, max_age_s: int = 300) -> dict:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header_sig or ""):
        raise ValueError("bad signature")
    payload = json.loads(raw_body)
    # payload["timestamp"] is ISO-8601 UTC and signed with the body: reject stale
    # deliveries to limit replay (parse and compare against max_age_s).
    return payload
```

Compute the HMAC over the raw request bytes, before any JSON parsing. The
envelope is `{"event_type", "timestamp", "data": {"articles": [...]}}`; each
article carries `id` (first 16 hex characters of sha256(slug), stable across
updates), `title`, `content_markdown`, `content_html`, `meta_description`,
`image_url`, `image_alt`, `slug`, `tags`, `created_at`, `status`,
`reviewed_by`, `primary_keyword`, `canonical` and `schema_jsonld`.

`event_type` is one of:

| Event | Sent by default for | Meaning for the receiver |
|---|---|---|
| `save_draft` | `--status draft` / `pending` | Store or update as a draft; never publish |
| `publish_articles` | `--status publish` | Outrank's publish event: may go live (publish gates passed) |
| `update_article` | only when asked for | Outrank's update event: may overwrite a live article (publish gates passed) |

A receiver built for Outrank only knows the last two; make it ignore or
draft-store `save_draft` rather than treat unknown events as publish.

## WordPress specifics

- Uses the REST API at `<site>/wp-json/wp/v2/posts` with an Application
  Password (Users → Profile → Application Passwords) over HTTPS.
- `meta_description` is sent as the excerpt. SEO-plugin fields (Yoast, Rank
  Math), the canonical and JSON-LD are not REST-writable by default: set
  them in the plugin after export.
- Tags are matched to existing WordPress tags by slug; missing tags are
  reported, not created. Featured images are not uploaded.
