"""Known-wrong statements that must not come back.

Ported from AgriciDaniel/claude-seo (MIT) tests/test_canonical_facts.py (audits of
2026-09-23 and 2026-09-28). Each entry pairs a phrase that was found in shipped
instruction text with the primary source that disproved it.

SCOPE (deliberately narrow for now): upstream scans every skill, agent, extension
and script. In this fork the skill text is owned by several parallel workstreams
and still carries some of these phrases, so this module scans only the files the
upstream-port workstream (W6) owns: the Google updates ledger, its query script,
and the core agents other than ``seo-geo``/``seo-agentic``/``geo-*``. Once the
skill-text corrections land, widen ``FILES`` to upstream's full glob set::

    [*ROOT.glob("skills/**/*.md"), *ROOT.glob("agents/*.md"),
     *ROOT.glob("extensions/*/skills/**/*.md"), *ROOT.glob("extensions/*/agents/*.md"),
     *ROOT.glob("scripts/*.py")]
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Agents maintained by other workstreams until integration (W5: seo-geo, geo-*;
# W1: seo-agentic). Remove this exclusion when widening FILES.
_OTHER_OWNERS = {"seo-geo.md", "seo-agentic.md"}
FILES = [
    ROOT / "data" / "google-updates.json",
    ROOT / "scripts" / "seo_updates.py",
    *(p for p in sorted(ROOT.glob("agents/seo-*.md")) if p.name not in _OTHER_OWNERS),
]

WRONG = [
    # (regex, why it is wrong, primary source)
    (r"\|\s*Book Actions\s*\|\s*Deprecated", "Book actions banner removed 2025-11-05",
     "developers.google.com/search/updates"),
    (r"LCP [Ss]ubparts \(February 2025", "January 2025 CrUX release, published 2025-02-11",
     "developer.chrome.com/docs/crux/release-notes"),
    (r"(?i)resource load time", "the subpart is 'resource load duration'",
     "web.dev/articles/optimize-lcp"),
    (r"GA4 4\.x", "GA4 has no 4.x version", "developers.google.com/tag-platform"),
    (r"eu_data_collection_disabled", "no such GA4 field", "GA4 Admin API reference"),
    (r"Sept 2025 QRG addition", "generative-AI guidance predates the Sept 2025 QRG",
     "guidelines.raterhub.com"),
    (r"Rolling out to a subset of properties", "gen-AI report reached all sites 2026-08-31",
     "developers.google.com/search/blog/2026/06/gen-ai-performance-reports"),
    (r"AEO and GEO are rebranded labels", "not a quote from Google's guide",
     "developers.google.com/search/docs/fundamentals/ai-optimization-guide"),
    (r"The guide also covers \*\*WebMCP", "the AI optimization guide never mentions WebMCP",
     "developers.google.com/search/docs/fundamentals/ai-optimization-guide"),
    (r"Privacy Sandbox APIs are still available", "most were retired 2025-10-17",
     "privacysandbox.google.com/blog"),
    (r"GBP Q&A is active where available", "Q&A API discontinued 2025-11-03",
     "developers.google.com/my-business/content/sunset-dates"),
    (r"Q&A gap analysis via Questions and Answers API",
     "Google's Q&A API was discontinued 2025-11-03",
     "developers.google.com/my-business/content/sunset-dates"),
    (r"Content API for Shopping sunsets August 18, 2026", "it was sunset; requests now fail",
     "developers.google.com/merchant/api/guides/compatibility/overview"),
    (r"custom version of Gemini 2\.5", "AI Mode default is Gemini 3.5 Flash since 2026-05-19",
     "blog.google/products-and-platforms/products/search/search-io-2026"),
    (r"(?i)optimal passage length", "a third-party heuristic, not a Google rule",
     "developers.google.com/search/docs/fundamentals/ai-optimization-guide"),
    (r"AI crawlers do NOT execute JavaScript", "Googlebot renders JS and feeds AI features",
     "developers.google.com/search/docs/crawling-indexing/javascript"),
    (r"(?i)(aggregator|supplier) units?[^.;|]*(South Africa|Turkiye|Türkiye)|(South Africa|Turkiye|Türkiye)[^.;|]*(aggregator|supplier) units?",
     "aggregator and supplier units are EEA-only",
     "developers.google.com/search/docs/appearance/aggregator-features"),
    (r"ignore robots\.txt by design", "Google's docs say 'generally ignore robots.txt rules'",
     "developers.google.com/crawling/docs/crawlers-fetchers/google-user-triggered-fetchers"),
    (r"(?i)M157|milestone 157", "no WebMCP ship milestone is announced", "chromestatus 5117755740913664"),
    (r"Google (has said it )?does not act on (Content-Signal|it)", "no Google statement exists",
     "developers.google.com/crawling/docs/robots-txt/robots-txt-spec"),
    (r"ucp\.dev lists (\*\*)?2026-04-08(\*\*)? as the latest", "ucp.dev latest is 2026-08-25",
     "ucp.dev/versions.json"),
    (r"GBP Q&A remains available", "Q&A API discontinued 2025-11-03",
     "developers.google.com/my-business/content/sunset-dates"),
    (r"Project Mariner\)", "Mariner's status is secondary-only; describe Google-Agent by function",
     "developers.google.com/crawling"),
    # Review of 2026-09-28.
    (r"(?i)(site reputation|searcher region|EEA)[^\n]{0,400}since 2026-08-28",
     "regional site reputation enforcement took effect 2026-08-30",
     "developers.google.com/search/blog/2026/08/update-site-reputation-policy"),
    (r"Gemini training \(NOT search\)|Optional block \(training only\)[^\n]*Google-Extended",
     "Google-Extended covers Gemini training and grounding",
     "developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers"),
    (r"August 2026 Spam \| Aug 18-20", "the August 2026 spam rollout completed August 21",
     "status.search.google.com/incidents/LEubPCm2octf2uMqCFKE"),
    (r"^\|[^|]*\d{4} (Core|Spam)[^|]*\|[^|]*\|[^|]*\|\s*Confirmed\s*\|\s*$",
     "Google confirms rollout dates, not impact descriptions; label rows 'Dates confirmed'",
     "status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history"),
    (r"(?i)Google-Extended[^\n]{0,80}grounding( use)? only|training (&|and) grounding only\*\*",
     "Google-Extended also limits training of the models behind Search gen-AI features",
     "support.google.com/webmasters/answer/16908024"),
    (r"canonical selection, mobile usability", "URL Inspection mobileUsabilityResult is deprecated",
     "developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult"),
    (r"Nano Banana 2 \(Flash, previous gen\)", "gemini-2.5-flash-image is the original Nano Banana",
     "ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-image"),
    (r"\*\*18-day rule\*\*", "a single Sterling Sky case example, not a rule",
     "sterlingsky.ca/what-gets-you-ranking-for-near-me-2025"),
    (r"December 2025 JS SEO guidance, structured data injected via JavaScript may face delayed",
     "the guide warns about Shopping crawl frequency for dynamic Product markup",
     "developers.google.com/search/docs/appearance/structured-data/generate-structured-data-with-javascript"),
    # Fork additions (this port, 2026-10-17).
    (r"FID was fully removed from all Chrome tools \(CrUX API, PageSpeed Insights, Lighthouse\)",
     "Lighthouse is a lab tool that never reported FID",
     "web.dev/blog/inp-cwv-launch"),
    (r"Lighthouse 13\.0[^\n]*updated scoring weights",
     "Lighthouse 13 restructured audits; the performance score was not re-weighted",
     "developer.chrome.com/blog/lighthouse-13-0"),
    (r"`local_business_data`|`google_local_pack_serp`",
     "not DataForSEO MCP tool names (use business_data_business_listings_search, serp_organic_live_advanced)",
     "tests/fixtures/dataforseo_mcp_2_8_10_tools.txt"),
]


def test_scope_covers_the_ledger_script_and_owned_agents() -> None:
    names = {p.name for p in FILES}
    assert {"google-updates.json", "seo_updates.py", "seo-technical.md", "seo-local.md"} <= names
    assert all(p.is_file() for p in FILES)


@pytest.mark.parametrize("pattern,why,source", WRONG)
def test_known_wrong_statement_is_absent(pattern: str, why: str, source: str) -> None:
    rx = re.compile(pattern)
    hits = [f"{p.relative_to(ROOT)}:{n}"
            for p in FILES
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if rx.search(line)]
    assert not hits, f"{why} ({source}): {hits}"


def test_notebooklm_is_only_named_as_the_former_token() -> None:
    hits = [f"{p.relative_to(ROOT)}:{n}"
            for p in FILES
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "Google-NotebookLM" in line and not re.search(r"formerly|replaced|former", line)]
    assert not hits, f"use Google-GeminiNotebook (renamed 2026-07-16): {hits}"
