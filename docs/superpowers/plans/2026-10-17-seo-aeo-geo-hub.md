# Implementation plan: SEO × AEO × GEO hub (v3.1.0)

Spec: [`../specs/2026-10-17-seo-aeo-geo-hub-design.md`](../specs/2026-10-17-seo-aeo-geo-hub-design.md)

Branch: `claude/aeo-seo-geo-consolidation-272910`. No pushes to `origin/main`.

## Phase 0 — Shared core (done before fan-out)

- [x] `scripts/seo_store.py`, `scripts/seo_metrics.py`, `scripts/seo_project.py`
- [x] `tests/test_seo_core.py` (43 tests)
- Rule for all workstreams: **import** the shared core; do not modify it. If a
  workstream needs a change, it reports the need and the integrator makes it.

## Phase 1 — Parallel workstreams (disjoint file ownership)

Every workstream: scripts follow repo conventions (docstring with usage,
argparse, `--json`, `sys.path` insert of `scripts/`, SSRF-safe fetching via
`fetch_page`/`url_safety`), ships offline tests, keeps new SKILL.md files under
500 lines with frontmatter `metadata.version: "3.0.0"` (the integrator bumps
all versions together), reference files under 200 lines and linked from their
SKILL.md. Workstreams do **not** edit the hub (`skills/seo/SKILL.md`),
manifests, README, CLAUDE.md, AGENTS.md, CHANGELOG or `docs/` — the integrator
owns those. Workstreams do not commit.

### W1 — Upstream port (security + fixes + seo-agentic)

Owns: `scripts/{url_safety,fetch_page,render_page,parse_html,commoncrawl_graph,domain_history,dataforseo_costs,bing_webmaster,gsc_query,pagespeed_check,preload_check,ucp_check,unlighthouse_run,gbp_deprecation_lint,content_humanize,content_quality,seo_updates}.py`, `data/google-updates.json`, `hooks/`, `extensions/*/install*`, `extensions/*/uninstall*`, `requirements.txt`, new `scripts/{metadata_template,sitemap_discovery,consistency_check,agentic_check,agentic_fix,lighthouse_agentic}.py`, `skills/seo-agentic/`, `agents/seo-agentic.md`, prompt-injection guidance in agents **except** `agents/geo-*.md` and `agents/seo-geo.md` (W5), `skills/seo-page` + `skills/seo-programmatic` wiring for `metadata_template`.

Acceptance: every ported change reviewed line by line against the upstream
diff; upstream tests ported; full suite green; no fork-specific behaviour lost
(ZYRA branding, client preflight, AEO wiring).

### W2 — Research: keywords + competitors

Owns: `scripts/keyword_research.py`, `scripts/competitor_gap.py`,
`skills/seo-keywords/`, `skills/seo-competitors/`, tests; one-line cross-links
in `seo-cluster`, `seo-plan`, `seo-content-brief`, `seo-competitor-pages`.

Acceptance: `suggest` rate-limited + cached + fail-soft and labelled
unofficial; `gsc` works live (via `gsc_query.query_search_analytics`) and from
`--input`; `score` accepts suggest/gsc/Keyword Planner/DataForSEO/Ahrefs/Semrush
shapes; outputs JSON + CSV; content gap works from sitemaps with caps.

### W3 — Measure: rank tracking + KPIs + AI referrals

Owns: `scripts/rank_tracker.py`, `scripts/performance_tracker.py`,
`scripts/ai_referrals.py`, `skills/seo-track/` (+ `references/measurement-protocol.md`,
`references/kpi-definitions.md`), tests; cross-link lines in `seo-google`, `seo-drift`.

Acceptance: SQLite history via `seo_store`; GSC lag exclusion; movement rule;
visibility index; cannibalization + URL swaps; KPI envelope ingest/export per
spec §4.3; `--fail-on-drop` exit code; GA4 AI-referral regex documented.

### W4 — Create/optimize: content engine + refresh + optimizer + export

Owns: `scripts/content_decay.py`, `scripts/content_optimizer.py`,
`scripts/content_export.py`, `skills/seo-content-engine/`, `skills/seo-refresh/`
(+ `references/aio-recovery.md`), new "Optimize mode" section in
`skills/seo-content/SKILL.md`, tests.

Acceptance: decay tiers + cause diagnosis + action rule; optimizer score is
deterministic and phrased as correlation; export defaults to draft, enforces
review gates, HMAC-signs webhooks, never sends without `--confirm`.

### W5 — AEO: share of voice + single AEO score + AEO fixes

Owns: `scripts/ai_visibility.py`, `scripts/aeo_score.py`,
`skills/geo-share-of-voice/`, edits to `skills/{geo-crawlers,geo-compare,geo-proposal,geo-prospect,geo-platform-optimizer,geo-citability,geo-brand-mentions,seo-geo,seo-audit}/`,
`agents/{geo-ai-visibility,geo-platform-analysis,seo-geo}.md`, tests.

Acceptance: Anthropic engine via optional `anthropic` SDK (lazy import,
web search tool `web_search_20260209`, `claude-opus-5-5` default, refusal and
`pause_turn` handled); ingest path for other engines; branded prompts excluded
from headline; n < 20 flagged thin; paired compare with Holm; spend caps +
dry-run; one AEO score everywhere; AI-crawler facts corrected; dead commands
removed; `geo-compare` reads `performance_tracker.py export`.

## Phase 2 — Integration (integrator)

1. Review each workstream's diff; run its tests; fix contract mismatches.
2. Hub: rewrite `skills/seo/SKILL.md` Quick Reference as a jobs-to-be-done map
   (Research / Audit / Create & Optimize / AEO-GEO / Measure / Local / Data),
   add data-tier matrix and `/seo project` commands; keep Sub-Skills and
   Subagents lists in sync with disk.
3. Version bump 3.0.0 → 3.1.0 everywhere the manifest tests check.
4. Counts: plugin.json, marketplace.json, README, CLAUDE.md, AGENTS.md.
5. Docs: CHANGELOG, README (what's new, commands, limitations), docs/COMMANDS.md,
   docs/ARCHITECTURE.md, CONTRIBUTORS.md / NOTICE.md attribution.
6. Full test suite; code review pass; commit per workstream.

## Deferred (documented follow-ups)

- Managed runtime launcher (`${CLAUDE_PLUGIN_ROOT}` anchoring, upstream v2.2.4/2.2.6).
- gcloud ADC sign-in (upstream v2.4.2); seo-cockpit companion; Matomo extension.
- Native OpenAI / Perplexity engines in `ai_visibility.py` (verify current APIs first).
- Bing Webmaster `GetKeywordStats` as a free volume source.
- Verify the Ahrefs MCP extension (`@ahrefs/mcp@0.0.11` reportedly archived Feb 2026).
- Entity profile (`data/entities/<slug>.json`) and content-type-weighted quality aggregator.
