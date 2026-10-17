"""
Regression tests for defects found in the v3.1 pre-merge code review.

Each test reproduces a confirmed finding against the original code and pins
the fixed behaviour. (Core-module findings — brand intent, cannibalization
aggregation, profile filename collisions, malformed hosts — are covered in
tests/test_seo_core.py.)
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ai_referrals  # noqa: E402
import competitor_gap as cg  # noqa: E402
import keyword_research as kr  # noqa: E402
import performance_tracker as pt  # noqa: E402
import rank_tracker as rt  # noqa: E402


# --- GSC rows silently cut at 25,000 ------------------------------------------

def test_rank_tracker_requests_full_cap_and_flags_truncation():
    seen = {}

    def fetch(prop, start, end, dims, flt):
        seen["called"] = True
        return {"rows": [{}] * rt.GSC_ROW_CAP, "row_count": rt.GSC_ROW_CAP}

    res = rt.fetch_gsc_rows("p", "a", "b", None, fetch=fetch)
    assert res["truncated"] is True
    import inspect
    assert "row_limit=GSC_ROW_CAP" in inspect.getsource(rt._live_gsc_fetch)


def test_keyword_research_surfaces_row_cap():
    calls = {}

    def query_fn(site_url, **kw):
        calls.update(kw)
        return {"rows": [{"keys": ["q", "/p"], "clicks": 1, "impressions": 10, "position": 5}],
                "row_count": kr.GSC_ROW_LIMIT}

    rows, date_range, err = kr.fetch_gsc_rows("sc-domain:x.com", 90, query_fn=query_fn)
    assert err is None and calls["row_limit"] == kr.GSC_ROW_LIMIT == 100_000
    assert date_range["row_cap_hit"] == kr.GSC_ROW_LIMIT


# --- sitemap crawl: failed fetches must count, 403/429/503 stop the site ------

class _Site:
    def __init__(self, pages: dict, default=None):
        self.pages, self.default, self.calls = pages, default, []

    def __call__(self, url, cap, from_content):
        self.calls.append(url)
        status, body = self.pages.get(url, self.default or (404, b""))
        return cg.FetchResult(url=url, final_url=url, status=status, body=body,
                              truncated=False, error=None)


def _index(children):
    locs = "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
    return f'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</sitemapindex>'.encode()


def test_dead_children_cannot_multiply_requests():
    children = [f"https://a.com/s{i}.xml" for i in range(2000)]
    site = _Site({"https://a.com/robots.txt": (200, b"Sitemap: https://a.com/index.xml\n"),
                  "https://a.com/index.xml": (200, _index(children))})
    info = cg.crawl_domain("a.com", fetch=site, max_sitemaps=20, delay=0)
    sitemap_calls = [u for u in site.calls if not u.endswith("robots.txt")]
    assert len(sitemap_calls) <= 20 and info["sitemap_attempts"] <= 20
    assert info["truncated"] is True


def test_offsite_children_are_never_fetched():
    site = _Site({"https://a.com/robots.txt": (200, b"Sitemap: https://a.com/index.xml\n"),
                  "https://a.com/index.xml": (200, _index(["https://evil.example/s.xml",
                                                           "https://cdn.a.com/s.xml"]))})
    info = cg.crawl_domain("a.com", fetch=site, max_sitemaps=20, delay=0)
    assert "https://evil.example/s.xml" not in site.calls
    assert "https://cdn.a.com/s.xml" in site.calls          # subdomain of the site is fine
    assert info["offsite_sitemaps_ignored"] == 1


@pytest.mark.parametrize("status", [403, 429, 503])
def test_rate_limit_or_block_stops_the_crawl(status):
    children = [f"https://a.com/s{i}.xml" for i in range(10)]
    site = _Site({"https://a.com/robots.txt": (200, b"Sitemap: https://a.com/index.xml\n"),
                  "https://a.com/index.xml": (200, _index(children))}, default=(status, b""))
    info = cg.crawl_domain("a.com", fetch=site, max_sitemaps=20, delay=0)
    assert len([u for u in site.calls if u.endswith(".xml") and "/s" in u]) == 1
    assert info["stopped"] and str(status) in info["stopped"]


# --- unrecognised inputs must be "not measured", never 0 ---------------------

def test_unrecognised_ga4_file_is_rejected_not_zeroed(tmp_path):
    f = tmp_path / "ga4_report.json"
    f.write_text(json.dumps({"daily_data": [{"date": "2026-10-01", "sessions": 120}]}))
    with pytest.raises(ValueError):
        ai_referrals.load_rows(str(f))


def test_gsc_input_without_totals_records_nulls(tmp_path):
    f = tmp_path / "gsc.json"
    f.write_text(json.dumps({"rows": []}))
    from datetime import date
    res = pt.collect_gsc(None, date(2026, 10, 17), 28, gsc_input=str(f))
    assert res["metrics"]["gsc.clicks"] is None and res["metrics"]["gsc.impressions"] is None
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"totals": {"clicks": 5, "impressions": 50},
                                   "totals_source": "partial_row_sum", "totals_complete": False}))
    res2 = pt.collect_gsc(None, date(2026, 10, 17), 28, gsc_input=str(partial))
    assert res2["metrics"]["gsc.clicks"] is None
    assert any("partial row sum" in lim for lim in res2["limitations"])


# --- filtered rank report must not overwrite project-wide rank.* KPIs ---------

@pytest.mark.parametrize("extra", [["--tag", "bofu"], ["--country", "gbr"], ["--device", "mobile"],
                                   ["--source", "dataforseo"]])
def test_filtered_rank_report_cannot_emit_kpis(tmp_path, extra):
    out = tmp_path / "k.json"
    proc = subprocess.run([sys.executable, str(SCRIPTS / "rank_tracker.py"), "report",
                           "--project", "example.com", "--data-dir", str(tmp_path),
                           "--emit-kpis", str(out), *extra], capture_output=True, text=True)
    assert proc.returncode == 2 and "--emit-kpis" in proc.stderr
    assert not out.exists()


# --- reviewer 2: AEO / AI visibility -----------------------------------------

import aeo_score  # noqa: E402
import ai_visibility as av  # noqa: E402
import seo_project as proj  # noqa: E402


def test_bom_does_not_invert_robots_result(tmp_path):
    f = tmp_path / "robots.txt"
    f.write_bytes("﻿User-agent: *\r\nDisallow: /\r\n".encode("utf-8"))
    res = aeo_score.check_crawlers("https://example.com", robots_file=str(f))
    assert res["score"] == 0                                   # everything is blocked
    assert aeo_score.analyze_robots("﻿User-agent: *\nDisallow: /\n", 200)["score"] == 0


def test_trademark_signs_do_not_hide_mentions():
    folded = av.fold("Try Acme™ or Acme® today")
    assert av.first_mention(folded, ["acme"]) is not None
    assert "acmetm" not in folded


@pytest.mark.parametrize("host,label", [
    ("shop.globex.com", "globex"), ("globex.co.uk", "globex"), ("app.acme.io", "acme"),
    ("acme.com", "acme"), ("www.shop.com", ""),            # "shop" itself is generic
])
def test_registrable_label(host, label):
    assert proj.registrable_label(host) == label


def test_subdomain_competitor_does_not_match_generic_words():
    profile = proj.new_profile("acme.io", brand_terms=["acme"], competitors=["shop.globex.com"])
    terms = [t for e in av.build_entities(profile) for t in e["terms"]]
    assert "shop" not in terms and "globex" in terms
    assert "shop" not in proj.competitor_terms(profile)


@pytest.mark.parametrize("field,value", [("funnel", 1), ("model", {"x": 1}), ("group", ["a"]),
                                         ("error", {"code": 1}), ("locale", 5)])
def test_bad_ingest_field_marks_row_invalid_not_crash(field, value):
    with pytest.raises(ValueError):
        av.parse_ingest_row({"prompt": "best crm", "answer": "Acme.", field: value})


def test_anthropic_client_has_retries_disabled():
    import inspect
    assert "Anthropic(max_retries=0)" in inspect.getsource(av)


# --- live-run finding: raw API responses contain datetimes -------------------

def test_raw_response_with_datetimes_is_stored(tmp_path):
    """Regression from the first live pilot: SDK to_dict() (python mode) returns
    datetime objects for web-search results; storing the run crashed after the
    API call had already been billed."""
    from datetime import datetime, timezone

    class FakeMessage:
        def to_dict(self, mode="python"):
            when = datetime(2026, 10, 1, tzinfo=timezone.utc)
            return {"content": [{"type": "web_search_tool_result",
                                 "content": [{"url": "https://a.com", "page_age": when if mode == "python" else when.isoformat()}]}],
                    "mode": mode}

    raw = av._to_raw(FakeMessage())
    assert raw["mode"] == "json"                         # asks the SDK for JSON-safe output
    conn = av.open_store(str(tmp_path))
    rid = av.insert_run(conn, {"project": "acme.io", "batch_id": "b", "run_at": "2026-10-17T00:00:00Z",
                               "prompt": "p", "engine": "anthropic", "surface": "api", "status": "ok",
                               "answer": "x", "raw": {"when": datetime(2026, 10, 1)}})  # still stored
    assert rid
    class OldSDK:
        def to_dict(self):
            return {"ok": True}
    assert av._to_raw(OldSDK()) == {"ok": True}


# --- live-run finding: dynamic web search returns uncited answers -----------

def test_retrieval_rate_measured_when_citations_are_absent():
    profile = proj.new_profile("acme.io", brand_terms=["acme"], competitors=["rival.com"])
    entities = av.build_entities(profile)
    a1 = av.analyze_answer("Acme and Rival make CRMs.", [], entities,
                           [{"url": "https://www.acme.io/pricing"}, {"url": "https://rival.com/"}])
    a2 = av.analyze_answer("Rival is popular.", [], entities, [{"url": "https://rival.com/"}])
    for a in (a1, a2):
        a["_row"] = {"branded": False, "prompt": "p"}
    s = av.summarize([a1, a2], entities)
    assert s["retrieval_rate"] == 0.5 and s["answers_retrieving_own"] == 1
    assert s["citation_rate"] is None            # no structured citations: not measured, never 0
    none = av.summarize([av.analyze_answer("x", [], entities, [])], entities)
    assert none["retrieval_rate"] is None        # no search results reported: not measured


def test_search_tool_option_selects_the_tool_type():
    class FakeSDK:
        class Anthropic:
            def __init__(self, **kw):
                pass
    basic = av.AnthropicEngine(sdk=FakeSDK, search_tool="basic")
    assert basic.request_kwargs("claude-opus-5-5", [])["tools"][0]["type"] == "web_search_20250305"
    dyn = av.AnthropicEngine(sdk=FakeSDK)
    assert dyn.request_kwargs("claude-opus-5-5", [])["tools"][0]["type"] == "web_search_20260209"
    with pytest.raises(av.EngineFatalError):
        av.AnthropicEngine(sdk=FakeSDK, search_tool="other")


def test_retrieval_rate_is_a_reserved_fraction_metric():
    import seo_kpi
    assert seo_kpi.RESERVED_METRICS["ai.retrieval_rate"] == "fraction"
