---
name: geo-prospect
description: >
  CRM-lite for managing AEO/GEO agency prospects and clients (AEO Score from scripts/aeo_score.py). Track leads through
  the full sales pipeline: Lead → Qualified → Proposal Sent → Won → Lost.
  Store audit history, notes, deal values, and generate pipeline summaries.
  Use when user says "prospect", "lead", "client", "pipeline", "crm", "nuovo prospect",
  "aggiungi cliente", or when managing the business side of GEO services.
tags: [geo, business, crm, prospect, pipeline, sales]
allowed-tools: Read, Write, Bash, Glob
metadata:
  version: "3.1.0"
  author: geo-seo-claude (grafted)
---

# GEO Prospect Manager

## Purpose

Manage GEO agency prospects and clients through the full sales lifecycle.
All data is stored in `~/.geo-prospects/prospects.json` (persistent across sessions).

---

## Commands

| Command | What It Does |
|---------|-------------|
| `/geo prospect new <domain>` | Create new prospect (interactive prompts) |
| `/geo prospect list` | Show all prospects with pipeline status |
| `/geo prospect list <status>` | Filter: lead, qualified, proposal, won, lost |
| `/geo prospect show <id-or-domain>` | Full prospect detail with history |
| `/geo prospect audit <id-or-domain>` | Run an AEO audit (`/seo geo` + `aeo_score.py compute`) and save the AEO Score to the prospect record |
| `/geo prospect note <id-or-domain> "<text>"` | Add interaction note with timestamp |
| `/geo prospect status <id-or-domain> <new-status>` | Move through pipeline |
| `/geo prospect won <id-or-domain> <monthly-value>` | Mark as won, set contract value |
| `/geo prospect lost <id-or-domain> "<reason>"` | Mark as lost with reason |
| `/geo prospect pipeline` | Visual pipeline summary with revenue forecast |

---

## Data Structure

Each prospect is stored as a JSON record:

```json
{
  "id": "PRO-001",
  "company": "Electron Srl",
  "domain": "electron-srl.com",
  "contact_email": "info@electron-srl.com",
  "contact_name": "",
  "industry": "Educational Equipment Manufacturing",
  "country": "Italy",
  "status": "qualified",
  "aeo_score": 38,
  "aeo_completeness": 0.75,
  "aeo_rating": "Critical",
  "audit_date": "2026-03-12",
  "audit_file": "~/.geo-prospects/audits/electron-srl.com-2026-03-12.md",
  "proposal_file": "~/.geo-prospects/proposals/electron-srl.com-proposal.md",
  "monthly_value": 0,
  "contract_start": null,
  "contract_months": 0,
  "notes": [
    {
      "date": "2026-03-12",
      "text": "Initial AEO audit. AEO Score 38/100 (Critical, completeness 0.75). Strong candidate for AEO services."
    }
  ],
  "created_at": "2026-03-12",
  "updated_at": "2026-03-12"
}
```

---

## Orchestration Instructions

### `/geo prospect new <domain>`

1. Check if `~/.geo-prospects/prospects.json` exists, create if not (empty array)
2. Auto-detect company name from domain (e.g., `electron-srl.com` → `Electron Srl`)
3. Assign next sequential ID: `PRO-001`, `PRO-002`, etc.
4. Ask user for:
   - Contact name (optional)
   - Contact email
   - Monthly contract value estimate (optional)
5. Set status to `lead`
6. Save to JSON file
7. Suggest next step: "Run `/geo prospect audit electron-srl.com` to score this prospect"

### `/geo prospect list`

Read `~/.geo-prospects/prospects.json` and render a summary table:

```
GEO Prospect Pipeline — March 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ID       Domain                  Company           Status      AEO     Value
───────  ──────────────────────  ────────────────  ──────────  ──────  ──────
PRO-001  electron-srl.com        Electron Srl      Qualified   38/100  €4.5K
PRO-002  acme.com                ACME Corp         Lead        —       —
PRO-003  bigshop.it              BigShop           Won         41/100  €6.0K

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Pipeline: 1 lead | 1 qualified | 0 proposals | 1 won | 0 lost
Committed MRR: €6,000 | Pipeline Value: €4,500
```

### `/geo prospect audit <id-or-domain>`

1. Run `/seo geo <url>` to measure the AEO components (citability, crawler
   access, brand authority, platform readiness, plus content E-E-A-T and
   schema when available), then
   `python3 scripts/aeo_score.py compute ... --json` for the one AEO Score.
2. Save to the prospect record: `aeo_score`, `aeo_completeness`,
   `aeo_rating`, `audit_date`. Never fill a missing component by estimate.
3. Save audit output to `~/.geo-prospects/audits/<domain>-<date>.md`, with
   the line `AEO Score: NN/100` so `geo-compare` can read it as a legacy
   baseline if needed.
4. Update `audit_file` path in prospect record
5. Add auto-note: "AEO audit run. AEO Score: XX/100 (rating, completeness C)."
6. If score < 55 and completeness >= 0.6: suggest "Score indicates strong sales opportunity. Run `/geo proposal <domain>` to generate proposal."

Older records may carry `geo_score` from the retired pre-v3.1 formula. Show
it as "legacy, not comparable" and re-audit before quoting a score to the
prospect.

### `/geo prospect note <id-or-domain> "<text>"`

1. Find prospect by ID or domain
2. Append note with current ISO date
3. Save back to JSON
4. Confirm: "Note added to Electron Srl (PRO-001)"

### `/geo prospect status <id-or-domain> <status>`

Valid statuses: `lead`, `qualified`, `proposal`, `won`, `lost`

1. Update status field
2. Add auto-note: "Status changed to <status>"
3. Save and confirm

### `/geo prospect pipeline`

Visual revenue-focused pipeline summary:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GEO AGENCY PIPELINE SUMMARY — March 2026
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STAGE          COUNT   POTENTIAL VALUE   NOTES
─────────────  ─────   ───────────────   ─────────────────────
Lead             2      €8,000/mo        New discoveries
Qualified        1      €4,500/mo        Ready for proposal
Proposal Sent    1      €6,000/mo        Awaiting signature
Won              3      €18,500/mo       Active clients (MRR)
Lost             1      —                Budget freeze

COMMITTED MRR:        €18,500
PIPELINE (qualified+): €10,500
TOTAL POTENTIAL:      €29,000/mo → €348,000/yr

Next actions:
→ PRO-003 (acme.com): Send proposal — AEO score 38/100 (strong case)
→ PRO-007 (shop.it): Follow up — proposal sent 8 days ago
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Storage Location

All data stored in `~/.geo-prospects/`:
```
~/.geo-prospects/
├── prospects.json          # Main CRM database
├── audits/                 # AEO audit snapshots
│   └── electron-srl.com-2026-03-12.md
└── proposals/              # Generated proposals
    └── electron-srl.com-proposal.md
```

Create directory if it does not exist: `mkdir -p ~/.geo-prospects/audits ~/.geo-prospects/proposals`

---

## Pipeline Stage Definitions

| Status | Meaning | Typical Next Action |
|--------|---------|---------------------|
| `lead` | Discovered, not yet contacted | Run an AEO audit, assess opportunity |
| `qualified` | Audit done, confirmed pain points | Generate proposal |
| `proposal` | Proposal sent, awaiting decision | Follow up, answer questions |
| `won` | Contract signed, active client | Run full audit, start onboarding |
| `lost` | Deal closed lost | Log reason for future reference |

---

## Output

- All commands print confirmation + current prospect status to terminal
- No external files unless explicitly saving audits/proposals
- JSON database is the single source of truth
