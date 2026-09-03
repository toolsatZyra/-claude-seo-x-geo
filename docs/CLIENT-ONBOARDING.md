# Client Onboarding Runbook

Google Search Console and GA4 are the highest-value inputs this plugin has, and
the only ones that cannot be obtained by crawling. They require the client to
grant access to our Google account. **That request belongs on day one, not
halfway through the audit** — a client who grants access in week three has paid
for two weeks of crawl-only reporting.

This runbook exists so no engagement starts without it.

---

## The operator account

All Google access is held by a single Google account, authorized via OAuth
(there is no service account configured). Clients grant access to that account.

Default: `hello@growthzyra.com`

Confirm the live value before sending anything to a client:

```bash
~/.claude/skills/seo/.venv/bin/python ~/.claude/skills/seo/scripts/gsc_query.py sites
```

Every property that account can read is listed. Override the address in the
preflight with `--operator-email` or the `ZYRA_SEO_OPERATOR_EMAIL` env var.

---

## Step 1 — Run the preflight before you quote

```bash
~/.claude/skills/seo/.venv/bin/python ~/.claude/skills/seo/scripts/client_preflight.py <domain>
```

It reports what will actually return data for this client and exits with a
status you can branch on:

| Exit | Verdict | Meaning |
|-----:|---------|---------|
| 0 | GO | Search Console access confirmed. Full-depth audit available. |
| 1 | PARTIAL | Crawl-only audit. Google access still needed. |
| 2 | BLOCKED | Site unreachable. Confirm the domain before anything else. |

The preflight also surfaces two things worth knowing before a sales call:

- **Blocked AI crawlers.** If GPTBot, ClaudeBot, PerplexityBot or
  Google-Extended are disallowed, the client cannot appear in AI answers at
  all. This is common, usually accidental, and it is the single most
  compelling finding to lead a pitch with.
- **CrUX field data.** Absent means the site lacks the traffic for real-user
  Core Web Vitals. Lab data via PageSpeed still works, but do not promise
  field-data reporting to a site that has none.

## Step 2 — Send the access request

```bash
~/.claude/skills/seo/.venv/bin/python ~/.claude/skills/seo/scripts/client_preflight.py <domain> --request-email
```

Prints a copy-pasteable request covering both properties. Send it with the
proposal, not after it is signed.

What to ask for, and why that level:

| Property | Path | Level | Why |
|---|---|---|---|
| Search Console | Settings → Users and permissions → Add user | Restricted is sufficient; Full is needed only to submit sitemaps or use the Indexing API on their behalf | Query, page, indexation and CWV field data |
| GA4 | Admin → Property access management → + | Viewer | Organic traffic, conversions, landing-page performance |

Never ask for, and never accept, the client's own password. Property-level
access grants are the only correct mechanism, they are revocable, and they
leave an audit trail on the client's side.

## Step 3 — Record the property string

Search Console access is granted **per property form**. A client may own any of:

- `sc-domain:example.com` — domain property, covers every subdomain and protocol
- `https://www.example.com/` — URL-prefix property
- `https://example.com/` — a different URL-prefix property

Being added to one grants nothing on the others. The preflight prints the exact
form we hold; store that string on the client record in `geo-prospect`, and pass
it as `--property` for every subsequent query.

This is the single most common source of a mid-engagement `Permission denied`
error. Our own site is the cautionary example: the correct property is
`sc-domain:thezyra.studio`, and passing the URL form fails outright.

Also confirm the GA4 property ID. `ga4_property_id` in
`~/.config/claude-seo/google-api.json` is a single global value, so a
multi-client setup must pass the right ID per run rather than relying on the
default.

## Step 4 — Baseline before you change anything

Capture a drift baseline on day one so every later change is provable:

```bash
/seo drift baseline <url>
```

Then run the audit. For a retainer, the month-two deliverable is
`/seo drift compare` plus `geo-compare` — that pairing is the retainer
product, and it only works if the baseline was captured before the first fix
shipped.

---

## Verdict → what you can honestly sell

| Verdict | Sell | Do not sell |
|---|---|---|
| GO | Ranking analysis, indexation, traffic attribution, field CWV, full retainer reporting | — |
| PARTIAL | Technical audit, schema, AEO/citability, content quality, competitor SERP analysis (via DataForSEO) | Anything phrased in terms of *their* rankings, traffic or indexation |
| BLOCKED | Nothing yet | Everything |

A PARTIAL engagement is still a real engagement — the AEO side needs no client
credentials at all. Just do not quote on traffic outcomes you cannot measure.
