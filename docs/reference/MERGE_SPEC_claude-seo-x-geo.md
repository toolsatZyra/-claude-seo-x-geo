# Merge Spec: claude-seo (engine) x geo-seo-claude (AEO depth)

**Handoff document for Claude Code. Self-contained - do not assume access to the conversation that produced it.**

Version: 1.0
Target base: `AgriciDaniel/claude-seo` v2.2.0 (MIT)
Grafted source: `zubair-trabzada/geo-seo-claude` (MIT)
Merge model: **supersede, not stack** (see Section 3)

---

## 0. Mission

Fork `claude-seo` as the base plugin and graft `geo-seo-claude`'s deterministic AEO/GEO modules into it, producing one Claude Code plugin that keeps claude-seo's breadth, orchestration, reporting, technical depth, and CI gate, while replacing claude-seo's single shallow `seo-geo` skill with a first-class, separately-scored AEO layer. Do not ship 40 overlapping skills. Deduplicate by function, preserve provenance and licenses, keep the CI gate green.

The end state treats Answer Engine Optimization as a tracked dimension of its own - overriding claude-seo's built-in "AEO and GEO are just SEO" default - while retaining claude-seo's evidence discipline.

---

## 1. Source repos and license compliance (non-negotiable)

Both repos are MIT.

- Base: `git clone https://github.com/AgriciDaniel/claude-seo.git` - Copyright (c) 2026 agricidaniel
- Graft: `git clone https://github.com/zubair-trabzada/geo-seo-claude.git` - Copyright (c) 2026 Zubair Trabzada

MIT requires the copyright notice and license text to travel with the copied code. Therefore:

1. Create `NOTICE.md` at repo root crediting both authors and both original repos.
2. Preserve `geo-seo-claude`'s `LICENSE` verbatim at `LICENSES/geo-seo-claude-LICENSE.txt`.
3. For every grafted skill folder, add a per-skill `LICENSE.txt` (claude-seo convention - each skill folder already carries one) whose header notes origin: "Portions derived from zubair-trabzada/geo-seo-claude (MIT)."
4. Append both authors to `CONTRIBUTORS.md`.
5. Keep the fork's own MIT `LICENSE` (claude-seo's) as the top-level license.

Do not remove or rewrite either original copyright line.

---

## 2. Prerequisites and environment

- Python 3.11+ (claude-seo uses `pyproject.toml`, `requirements.txt`).
- Node not required for the plugin itself.
- Playwright browsers must be installed for SPA rendering (`playwright install chromium`).
- Windows note: the operator runs Windows. All shell steps must be given in PowerShell/cmd form as well as bash; do not assume Linux/macOS paths. Use `~/.claude/skills/` equivalently as `%USERPROFILE%\.claude\skills\` on Windows.
- Work on a branch: `git checkout -b merge/aeo-depth`.

---

## 3. Target architecture (supersede model)

claude-seo auto-discovers skills from `skills/` and agents from `agents/` - `plugin.json` does **not** enumerate them, it only carries metadata and counts. So grafting = dropping valid skill folders in place + updating counts + wiring scripts.

Rules:

- **Keep** all 25 claude-seo skills.
- **Repurpose** `skills/seo-geo` from a scoring skill into the **AEO orchestrator/router**. Keep its two reference files (`references/llmstxt-evidence.md`, `references/google-ai-optimization-guide.md`) - they are the evidence base. Rewrite its `SKILL.md` to route into the grafted modules and to carry the reconciled llms.txt policy (Section 8).
- **Graft 7** geo modules as first-class skills (keep the `geo-` prefix; it namespaces the AEO cluster and avoids any collision with `seo-` skills).
- **Merge and drop 8** geo modules whose function already exists in claude-seo (fold their unique logic into the seo- equivalent, then delete the standalone geo skill).
- Promote geo's deterministic Python scorers into `claude-seo/scripts/`, rewired onto claude-seo's hardened fetcher (Section 6).
- Keep geo's Flask dashboard as an **optional extension**, not core (Section 13).

---

## 4. Final skill tree (post-merge)

`skills/` after merge - 32 skills total (25 existing + 7 grafted):

Existing (unchanged unless noted): `seo`, `seo-audit` (edited), `seo-backlinks`, `seo-cluster`, `seo-competitor-pages`, `seo-content` (edited), `seo-content-brief`, `seo-dataforseo`, `seo-drift`, `seo-ecommerce`, `seo-flow`, `seo-geo` (**rewritten to router**), `seo-google`, `seo-hreflang`, `seo-image-gen`, `seo-images`, `seo-local`, `seo-maps`, `seo-page`, `seo-plan`, `seo-programmatic`, `seo-schema` (edited), `seo-sitemap`, `seo-sxo`, `seo-technical` (edited).

Grafted from geo (keep as separate skills): `geo-citability`, `geo-platform-optimizer`, `geo-compare`, `geo-brand-mentions`, `geo-crawlers`, `geo-prospect`, `geo-proposal`.

`agents/` after merge - 20 agents (18 existing + 2 grafted): add `geo-ai-visibility.md`, `geo-platform-analysis.md`. Do **not** graft geo's `geo-content.md`, `geo-schema.md`, `geo-technical.md` agents - superseded by the seo- equivalents.

---

## 5. File migration map

| Source (geo-seo-claude) | Destination (fork) | Action | Notes |
|---|---|---|---|
| `skills/geo-citability/` | `skills/geo-citability/` | Graft | Wire its SKILL.md to call `scripts/citability_scorer.py`. Encode Princeton weights (Section 12). |
| `skills/geo-platform-optimizer/` | `skills/geo-platform-optimizer/` | Graft | 5-platform module (AIO, ChatGPT, Perplexity, Gemini, Bing Copilot). No claude-seo equivalent. |
| `skills/geo-compare/` | `skills/geo-compare/` | Graft **after check** | claude-seo already advertises "AI Share-of-Voice tracking." Diff against `seo-geo`/`seo-flow` share-of-voice; if duplicate, fold instead of grafting. |
| `skills/geo-brand-mentions/` | `skills/geo-brand-mentions/` | Graft | Free DIY complement to the paid `extensions/profound`. Wire to `scripts/brand_scanner.py`. |
| `skills/geo-crawlers/` | `skills/geo-crawlers/` | Graft | AI crawler-access analysis (GPTBot, ClaudeBot, PerplexityBot). Cross-link from `seo-technical`. |
| `skills/geo-prospect/` | `skills/geo-prospect/` | Graft | Agency prospecting workflow. Net-new. |
| `skills/geo-proposal/` | `skills/geo-proposal/` | Graft | Sales proposal generator. Net-new. |
| `skills/geo-audit/` | — | Merge then delete | Fold any unique checks into `seo-audit`; claude-seo's audit orchestrator wins. |
| `skills/geo-content/` | — | Merge then delete | Fold citability pass into `seo-content`. |
| `skills/geo-schema/` | — | Merge then delete | Fold AI-citation schema emphasis into `seo-schema`. |
| `skills/geo-technical/` | — | Merge then delete | Fold crawler-access checks into `seo-technical`. |
| `skills/geo-report/`, `skills/geo-report-pdf/` | — | Delete | claude-seo WeasyPrint/matplotlib/openpyxl engine wins. |
| `skills/geo-llmstxt/` | — | Delete as skill | Behavior becomes a policy in `seo-geo` (Section 8). Keep only `llmstxt_generator.py` as a gated script. |
| `skills/geo-update/` | — | Delete | claude-seo has its own update path. |
| `agents/geo-ai-visibility.md` | `agents/geo-ai-visibility.md` | Graft | |
| `agents/geo-platform-analysis.md` | `agents/geo-platform-analysis.md` | Graft | |
| `scripts/citability_scorer.py` | `scripts/citability_scorer.py` | Graft + rewire | See Section 6. |
| `scripts/brand_scanner.py` | `scripts/brand_scanner.py` | Graft + rewire | See Section 6. |
| `scripts/llmstxt_generator.py` | `scripts/llmstxt_generator.py` | Graft (gated) | Only runnable when llms.txt policy = generate (Section 8). |
| `scripts/fetch_page.py` | — | **Do not copy** | Would clobber claude-seo's SSRF-hardened fetcher. Rewire geo scorers to import claude-seo's. |
| `scripts/crm_dashboard.py`, `scripts/webapp/` | `extensions/geo-dashboard/` | Move to extension | Optional Flask dashboard (Section 13). |
| `white-label/brand_config.py`, `white-label/brand.example.json` | integrate into `scripts/google_report.py` | Merge | Adds client-branding to claude-seo's report engine. |
| `templates/geo-report-*.{css,html}` | `extensions/geo-dashboard/templates/` | Move | Only for the optional dashboard; core reports use claude-seo's engine. |
| `schema/*.json` (6 files) | `schema/` | Merge **selectively** | Only add types claude-seo lacks (likely `software-saas.json`, `article-author.json`). Do not duplicate existing generators. |
| `examples/*` | `docs/examples/geo/` | Reference only | Sample outputs; keep out of the runnable product. |

---

## 6. Deterministic scorers integration (security-critical)

geo's scorers currently fetch pages via geo's own `fetch_page.py`. claude-seo ships an SSRF + DNS-rebinding hardened fetcher (`scripts/fetch_page.py`, covered by `tests/test_url_safety.py` and `tests/test_fetch_page_decoding.py`). Do not regress this.

Steps:

1. Copy `citability_scorer.py`, `brand_scanner.py`, `llmstxt_generator.py` into `scripts/`.
2. In each, replace any import/use of geo's page fetch with claude-seo's `fetch_page` module (same directory). Match its function signature and its safe-fetch contract (allowlist, redirect handling, size caps).
3. Delete any geo fetch helper that shipped alongside the scorers.
4. Add unit tests mirroring `tests/test_url_safety.py` to prove the grafted scorers cannot fetch private/loopback/link-local hosts.
5. Confirm `flask` and `rich` (geo deps) are only imported by the optional dashboard, never by core scorers - core must stay import-light.

---

## 7. Conflict resolutions (concrete edits)

- `seo-schema`: add a section for AI-citation-oriented schema (author/Person, Organization, FAQPage-as-entity-signal). Reuse claude-seo's deprecation table. Import the two novel geo schema JSON templates if missing.
- `seo-technical`: add an "AI crawler accessibility" subsection - robots rules for GPTBot, ClaudeBot, PerplexityBot, Google-Extended, Bingbot/Copilot - sourced from geo-technical/geo-crawlers. Keep claude-seo's CWV/INP logic authoritative.
- `seo-content` / `seo-content-brief`: add a citability pass that calls `geo-citability`. Front-loading rule from Section 12 becomes a content check.
- `seo-audit`: extend the audit orchestrator so a full run fans out to the grafted AEO cluster as a distinct scored track, and the final report shows SEO and AEO as **separate** scores, not one blended number.

---

## 8. The llms.txt reconciliation (exact policy)

Conflict: claude-seo's `seo-geo/references/llmstxt-evidence.md` argues llms.txt is not consumed by any major AI system and lists it under Google's "Myths." geo-seo-claude ships a generator treating it as an emerging standard.

Encode a single policy in the rewritten `seo-geo/SKILL.md`, default = **generate-but-flag**:

> llms.txt is audited for presence and validity, and can be generated on request via `scripts/llmstxt_generator.py`. It is reported as a **forward-looking, low-confidence** signal, explicitly **not** a current ranking or citation lever. No audit score is gained or lost based on its presence. Rationale and evidence: `references/llmstxt-evidence.md`.

Make the stance a config flag (`aeo.llmstxt_mode: audit | generate | off`, default `generate`) so it can be flipped without editing prose. The generator script must never run under `off`.

---

## 9. Manifest updates (exact)

`test_manifest_consistency.py` will fail the build if the declared counts do not match the folders on disk. Update both manifest files.

`.claude-plugin/plugin.json`:
- Bump `version` to `3.0.0`.
- Replace the count phrase in `description` with: "32 sub-skills and 20 sub-agents cover technical SEO, content quality, schema, sitemaps, Core Web Vitals, local SEO, backlinks, first-class AEO/GEO (deterministic citability scoring, per-platform optimization, AI crawler access, brand-mention tracking), ecommerce, hreflang, SXO, clustering, drift monitoring, and Google APIs."
- Add keywords: `answer-engine-optimization`, `aeo`, `citability-scoring`, `platform-optimization`, `perplexity`, `chatgpt-search`, `gemini`, `ai-crawlers`, `brand-mentions`.

`.claude-plugin/marketplace.json`:
- Update `metadata.description` and the plugin `description` to the same 32/20 counts and AEO language.
- Keep `name: agricidaniel-claude-seo` or rename to your fork's slug if publishing under your account; if renamed, update all install docs accordingly.

Also update the counts in `README.md` and `CHANGELOG.md` (add a v3.0.0 entry summarizing the AEO merge and crediting geo-seo-claude).

---

## 10. requirements.txt (merged - zero version conflicts)

Base is claude-seo's file (higher CVE-patched floors win). Append geo's two unique deps. Final additions to the existing claude-seo `requirements.txt`:

```
# AEO dashboard (optional extension: extensions/geo-dashboard)
flask>=3.0.0,<4.0.0
rich>=13.0.0,<14.0.0
```

Do not downgrade any shared pin (lxml, playwright, urllib3, Pillow) to geo's lower floors. Keep claude-seo's.

---

## 11. CLAUDE.md - AEO override section (insert verbatim, then adapt tone)

Append this section to the fork's root `CLAUDE.md`. It reverses the built-in "AEO = SEO" default.

```
## Answer Engine Optimization (AEO) - stance override

This build treats AEO/GEO as a FIRST-CLASS, SEPARATELY-SCORED dimension, not a
relabeling of SEO. Audits must surface an AEO score distinct from the SEO score.
The eligibility floor is still normal indexation, but AEO adds citation-structure
signals that classic SEO does not measure.

Scoring weights (grounded in Princeton's 2024 GEO study and 2026 citation data):
- Cited sources / statistics with attribution: strongest positive lift.
- Front-loading: the first ~30% of a page carries a large share of AI citations;
  major sections must open with a direct, self-contained answer.
- Passage self-containment and question-phrased headings: positive.
- Keyword stuffing / AI-specific keyword rewriting: negative or neutral; do not
  recommend.

Determinism: citability is scored by scripts/citability_scorer.py (0-100), not by
free-form judgment. Brand/AI visibility is scored by scripts/brand_scanner.py.

llms.txt: audited and optionally generated, reported as forward-looking and
low-confidence, never as a ranking lever. See seo-geo/references/llmstxt-evidence.md
and the aeo.llmstxt_mode flag.

Evidence discipline retained: every AEO recommendation keeps a falsifiability check
(observation it rests on, dependency, "how would we know it failed", leading
indicator), consistent with the rest of this plugin.
```

---

## 12. Third-tier integrations

- **Princeton / citation weights**: encode as constants in `citability_scorer.py` and reflect them in `geo-citability/SKILL.md` and the `seo-content` citability pass. Reference figures: citations approx +40% visibility, statistics approx +37%, keyword stuffing approx -10%; front-load because a large share (approx 44%) of AI citations come from the first 30% of a page. Treat these as directional weights, not guarantees.
- **GSC live data**: **claude-seo already has native Google Search Console** via `google-api-python-client` (`scripts/gsc_query.py`, `gsc_inspect.py`, `seo-google` skill, `test_gsc_query.py`). The originally-planned Suganthan GSC-MCP is therefore largely redundant. Recommendation: rely on native GSC. Only add a GSC-MCP extension if you want an OAuth-free path for non-technical operators; if so, scaffold it under `extensions/gsc-mcp/` and document it as an alternative, not a requirement.
- **StudioHawk SOURC-E and citation-share frameworks**: incorporate as **methodology references only** (license unclear for redistribution). Create `skills/seo-geo/references/sourc-e-framework.md` and `.../aeo-scoring-weights.md` summarizing the framework in your own words, with attribution and no verbatim copying. These feed the AEO cluster's prioritization logic.

---

## 13. Optional dashboard extension

Move geo's `crm_dashboard.py`, `webapp/`, and report templates into `extensions/geo-dashboard/` following the pattern of existing extensions (each has `install.sh`, `install.ps1`, `skills/`, `docs/`, `uninstall.sh`). This is where `flask`/`rich` are used. It must be installable and uninstallable independently and must not be a runtime dependency of any core skill. Provide Windows (`install.ps1`) and bash installers.

---

## 14. CI / test gate (keep it green)

claude-seo enforces per-PR: full pytest suite (26 test files, incl. `test_manifest_consistency.py`, `test_portability.py`, `test_url_safety.py`, `test_schema_v2.py`), manifest assertions, and a security review. Workflows: `.github/workflows/ci.yml`, `v2.yml`.

Add before opening any PR:

1. `tests/test_geo_citability.py` - asserts `citability_scorer.py` returns a bounded 0-100 score and rejects unsafe URLs (mirror `test_url_safety.py`).
2. `tests/test_geo_brand_scanner.py` - same URL-safety assertion for `brand_scanner.py`.
3. Extend `test_manifest_consistency.py` expectations to 32 skills / 20 agents.
4. `tests/test_llmstxt_policy.py` - asserts the generator refuses to run when `aeo.llmstxt_mode = off`.
5. Run `test_portability.py` after grafting to confirm the new skills carry valid, portable frontmatter (each grafted `SKILL.md` must have `name`, `description`, `allowed-tools`).
6. Confirm the full suite passes locally before pushing.

---

## 15. Execution order

1. Branch `merge/aeo-depth` off forked claude-seo.
2. License compliance scaffolding (Section 1): `NOTICE.md`, `LICENSES/`, per-skill headers, `CONTRIBUTORS.md`.
3. Graft the 7 geo skill folders + 2 agents (Section 4/5).
4. Copy + rewire the 3 scorers onto claude-seo's fetcher (Section 6).
5. Rewrite `seo-geo/SKILL.md` into the AEO router + encode llms.txt policy (Section 8).
6. Merge-and-delete the 8 superseded geo skills; fold unique logic into `seo-schema`, `seo-technical`, `seo-content`, `seo-audit` (Section 7).
7. Move dashboard to `extensions/geo-dashboard/` (Section 13).
8. Integrate white-label branding into `google_report.py`; selectively merge schema JSON.
9. Update `requirements.txt` (Section 10), manifests (Section 9), `CLAUDE.md` (Section 11), README/CHANGELOG.
10. Add references (Section 12).
11. Add/extend tests; run full suite until green (Section 14).
12. `install.sh` / `install.ps1` on a scratch machine; run `/seo audit <url>` and confirm a report with **separate SEO and AEO scores** plus a deterministic citability number.
13. Open PR; pass the gate; merge.

---

## 16. Acceptance criteria

- Full pytest suite green, including new AEO tests and updated manifest counts (32/20).
- `/seo audit <url>` produces one report with **distinct** SEO and AEO scores, a 0-100 citability figure from `citability_scorer.py`, per-platform notes, and AI-crawler-access findings.
- No core skill imports `flask`/`rich`; dashboard installs and uninstalls cleanly on its own.
- Grafted scorers provably cannot fetch private/loopback hosts.
- Both original MIT copyrights preserved; `NOTICE.md` credits both repos.
- llms.txt reported as forward-looking only; generator refuses to run under `off`.
- No duplicate function: geo-audit/content/schema/technical/report/update no longer exist as standalone skills.

---

## 17. Out of scope / do-not-do

- Do not blend SEO and AEO into a single score.
- Do not overwrite claude-seo's `fetch_page.py`.
- Do not downgrade shared dependency floors.
- Do not copy StudioHawk files verbatim; methodology summaries only.
- Do not treat llms.txt as a ranking lever.
- Do not ship 40 skills; the target is 32 with function-level deduplication.
- Do not make the Flask dashboard a core dependency.
