"""
Tests for scripts/competitor_gap.py (seo-competitors skill).

Offline only: ranking exports are fixtures, sitemap discovery runs against an
injected fake fetcher, and the url_safety-backed fetcher is exercised with a
monkeypatched transport (plus one SSRF refusal that never leaves the process).
"""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS / "competitor_gap.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import competitor_gap as cg  # noqa: E402
import keyword_research as kr  # noqa: E402
import seo_metrics as m  # noqa: E402

SM_NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def _rec(kw, pos=None, volume=None, difficulty=None, url=None):
    return {"keyword": kw, "volume": volume, "volume_range": None, "difficulty": difficulty,
            "position": pos, "url": url, "cpc": None, "impressions": None, "clicks": None,
            "opp_clicks_monthly": None, "provider_intent": None, "source": "t"}


def _merged(*recs):
    return kr.merge_records(list(recs))


def _write(tmp_path: Path, name: str, content) -> str:
    p = tmp_path / name
    p.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return str(p)


def _run(*argv: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("CLAUDE_SEO_DATA_DIR", None)
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True,
                          timeout=60, env=env)


# ---------------------------------------------------------------------------
# keywords: segmentation
# ---------------------------------------------------------------------------

OWN = _merged(_rec("crm pricing", 5, 2400, 35), _rec("crm reports", 3, 500, 20),
              _rec("crm api", 34, 300, 30), _rec("acme login", 1, 900, 5))
RIVAL = _merged(_rec("crm pricing", 2, 2400, 35, "https://rival.com/pricing"),
                _rec("crm api", 4, 300, 30, "https://rival.com/api"),
                _rec("crm demo", 6, 800, 25, "https://rival.com/demo"),
                _rec("rival login", 1, 5000, 10),
                _rec("rival alternatives", 9, 700, 30, "https://other.io/rival-alt"))
OTHER = _merged(_rec("crm api", 8, 300, 30), _rec("crm demo", 3, 800, 25),
                _rec("what is a crm", 7, 9000, 70), _rec("crm reports", 25, 500, 20))
UNIVERSE = _merged(_rec("crm onboarding checklist", None, 200, 15), _rec("crm pricing"))


def _segment(**kw):
    return cg.segment_keywords(OWN, {"rival": RIVAL, "other.io": OTHER}, UNIVERSE,
                               brand_terms=["acme"], **kw)


def _by_kw(rows):
    return {r["keyword"]: r for r in rows}


def test_four_way_segmentation():
    res = _segment()
    seg = res["segments"]
    assert set(_by_kw(seg["moat"])) == {"crm reports"}          # other.io ranks 25 > threshold
    assert set(_by_kw(seg["battleground"])) == {"crm pricing"}
    assert set(_by_kw(seg["gap"])) == {"crm api", "crm demo", "what is a crm", "rival alternatives"}
    assert set(_by_kw(seg["pioneer"])) == {"crm onboarding checklist"}
    assert res["summary"]["excluded"] == {"competitor_navigational": 1, "own_brand": 1}
    assert sum(res["summary"]["counts"].values()) == 7


def test_brand_comparison_gap_is_kept_but_brand_navigational_is_not():
    own = _merged(_rec("acme", 1, 3000), _rec("crm", 9, 100))
    rival = _merged(_rec("rival vs acme", 2, 400, 20, "https://rival.com/rival-vs-acme"),
                    _rec("acme", 5, 3000))
    res = cg.segment_keywords(own, {"rival": rival}, brand_terms=["acme"])
    gap = _by_kw(res["segments"]["gap"])
    assert gap["rival vs acme"]["route"] == "seo-competitor-pages"
    assert res["summary"]["excluded"] == {"own_brand": 1}


def test_battleground_leader_and_delta():
    bg = _by_kw(_segment()["segments"]["battleground"])["crm pricing"]
    assert bg["leader"] == "rival" and bg["best_competitor_position"] == 2
    assert bg["position_delta"] == 3.0                           # we are 3 places behind
    assert bg["competitors"] == {"rival": 2}


def test_gap_priority_routes_and_tiebreaks():
    gaps = _segment()["segments"]["gap"]
    g = _by_kw(gaps)
    api = g["crm api"]
    intent = m.classify_intent("crm api", ["acme"], ["rival", "other.io", "other"])
    assert api["gap_priority"] == m.opportunity_score(300, 30, 34, intent["lead_value"])["score"]
    assert api["own_position"] == 34 and api["n_competitors"] == 2
    assert api["best_competitor"] == "rival" and api["best_competitor_url"] == "https://rival.com/api"
    assert g["rival alternatives"]["route"] == "seo-competitor-pages"
    assert g["rival alternatives"]["bofu"] is True
    assert g["what is a crm"]["route"] == "seo-content-brief" and g["what is a crm"]["bofu"] is False
    keys = [(-x["gap_priority"], -x["n_competitors"], x["best_competitor_position"]) for x in gaps]
    assert keys == sorted(keys)


def test_gap_tiebreak_by_competitor_count_then_best_position():
    own = _merged(_rec("seed", 1))
    a = _merged(_rec("alpha widget", 9, 100, 40), _rec("beta widget", 4, 100, 40),
                _rec("gamma widget", 9, 100, 40))
    b = _merged(_rec("gamma widget", 12, 100, 40))
    gaps = cg.segment_keywords(own, {"a": a, "b": b})["segments"]["gap"]
    assert [x["keyword"] for x in gaps] == ["gamma widget", "beta widget", "alpha widget"]


def test_threshold_min_volume_and_include_brand():
    tight = _segment(threshold=5)
    assert "crm pricing" in _by_kw(tight["segments"]["battleground"])     # 5 <= 5
    assert "crm demo" in _by_kw(tight["segments"]["gap"])                 # other.io at 3
    assert "rival alternatives" not in _by_kw(tight["segments"]["gap"])   # 9 > 5
    hv = _segment(min_volume=1000)
    assert hv["summary"]["excluded"]["below_min_volume"] >= 4
    assert "crm api" not in _by_kw(hv["segments"]["gap"])
    inc = _segment(include_brand=True)
    assert "acme login" in _by_kw(inc["segments"]["moat"])
    assert "rival login" in _by_kw(inc["segments"]["gap"])


def test_competitor_stats_overlap():
    stats = {c["name"]: c for c in _segment()["competitors"]}
    assert stats["rival"]["leads_battlegrounds"] == 1
    assert stats["rival"]["overlap_with_own"] == 0.5     # shares crm pricing of {pricing, reports}
    assert stats["other.io"]["in_gaps"] == 3


def test_parse_competitor_arg():
    assert cg.parse_competitor_arg("rival=/x/r.csv") == ("rival", "/x/r.csv")
    assert cg.parse_competitor_arg("/x/rival.com.csv") == ("rival.com", "/x/rival.com.csv")
    with pytest.raises(kr.InputError):
        cg.parse_competitor_arg("=x.csv")


# ---------------------------------------------------------------------------
# content: page types and slugs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,ptype", [
    ("https://a.com/", "home"),
    ("https://a.com/blog/hubspot-vs-salesforce", "comparison"),
    ("https://a.com/compare/a-b", "comparison"),
    ("https://a.com/hubspot-alternatives", "alternatives"),
    ("https://a.com/pricing", "pricing"),
    ("https://a.com/pricing/compare-plans", "pricing"),
    ("https://a.com/en/blog/what-is-crm", "blog"),
    ("https://a.com/integrations/slack", "integrations"),
    ("https://a.com/docs/integrations/slack", "docs"),
    ("https://a.com/features/reporting", "features"),
    ("https://a.com/solutions/sales-teams", "solutions"),
    ("https://a.com/industries/real-estate", "industries"),
    ("https://a.com/customers/acme", "customers"),
    ("https://a.com/templates/sales-plan", "templates"),
    ("https://a.com/sales-email-templates", "templates"),
    ("https://a.com/glossary/pipeline", "glossary"),
    ("https://a.com/roi-calculator", "tools"),
    ("https://a.com/locations/austin", "locations"),
    ("https://a.com/careers/engineer", "careers"),
    ("https://a.com/legal/privacy", "legal"),
    ("https://a.com/products/shoe-123", "other"),
    ("https://a.com/work/brand-film-for-acme", "customers"),
    ("https://a.com/services/ai-video", "services"),
    ("https://a.com/about", "company"),
])
def test_classify_page_type(url, ptype):
    assert cg.classify_page_type(url) == ptype


def test_slug_tokens():
    assert cg.slug_tokens("https://a.com/blog/best-crm-tools-for-agencies/") == ["best", "crm", "tool", "agency"]
    assert cg.slug_tokens("https://a.com/blog/2024/05/crm-guide.html") == ["crm", "guide"]
    assert cg.slug_tokens("https://a.com/p/123456") == []        # ID-only URL: no topic
    assert cg.slug_tokens("https://a.com/item/9f8e7d6c5b4a") == ["item"]
    assert cg.slug_tokens("https://a.com/") == []


# ---------------------------------------------------------------------------
# content: safe sitemap parsing
# ---------------------------------------------------------------------------

def _urlset(urls, extra=""):
    body = "".join(f"<url><loc>{u}</loc>{extra}</url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset {SM_NS}>{body}</urlset>'.encode()


def _index(urls):
    body = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in urls)
    return f'<?xml version="1.0"?><sitemapindex {SM_NS}>{body}</sitemapindex>'.encode()


def test_parse_sitemap_urlset_ignores_image_locs_and_caps():
    img = ('<image:image xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
           '<image:loc>https://a.com/i.png</image:loc></image:image>')
    data = _urlset(["https://a.com/x", "https://a.com/y", "https://a.com/z"], extra=img)
    r = cg.parse_sitemap(data)
    assert r == {"kind": "urlset", "locs": ["https://a.com/x", "https://a.com/y", "https://a.com/z"],
                 "truncated": False, "error": None}
    capped = cg.parse_sitemap(data, max_urls=2)
    assert capped["locs"] == ["https://a.com/x", "https://a.com/y"] and capped["truncated"]


def test_parse_sitemap_refuses_entities_and_keeps_partial_reads():
    bomb = (b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
            b'<urlset><url><loc>&b;</loc></url></urlset>')
    r = cg.parse_sitemap(bomb)
    assert r["locs"] == [] and "entities" in r["error"]
    cut = _urlset(["https://a.com/x", "https://a.com/y"])[:-30]
    r = cg.parse_sitemap(cut)
    assert r["locs"] == ["https://a.com/x"] and r["truncated"] and r["error"]


def test_parse_sitemap_index_text_html_and_bom():
    r = cg.parse_sitemap(_index(["https://a.com/s1.xml"]))
    assert r["kind"] == "sitemapindex" and r["locs"] == ["https://a.com/s1.xml"]
    assert cg.parse_sitemap(b"https://a.com/a\nhttps://a.com/b\n")["locs"] == ["https://a.com/a",
                                                                              "https://a.com/b"]
    assert cg.parse_sitemap(b"<html><body>404</body></html>")["error"]
    assert cg.parse_sitemap(b"Not Found")["error"]
    assert cg.parse_sitemap(b"\xef\xbb\xbf" + _urlset(["https://a.com/q"]))["locs"] == ["https://a.com/q"]


def test_maybe_gunzip_caps_decompressed_size():
    data = gzip.compress(b"<" + b"a" * 5_000_000)
    out, truncated = cg.maybe_gunzip(data, max_bytes=1000)
    assert len(out) == 1000 and truncated
    out, truncated = cg.maybe_gunzip(gzip.compress(b"hello"), 1000)
    assert out == b"hello" and not truncated
    assert cg.maybe_gunzip(b"plain", 10) == (b"plain", False)


def test_robots_sitemap_lines_and_diversify():
    robots = "User-agent: *\nDisallow: /x\nSitemap: https://a.com/s.xml\nsitemap: /rel.xml # c\n"
    assert cg.parse_robots_sitemaps(robots, "https://a.com/robots.txt") == [
        "https://a.com/s.xml", "https://a.com/rel.xml"]
    urls = ["https://a.com/post-sitemap1.xml", "https://a.com/post-sitemap2.xml",
            "https://a.com/page-sitemap.xml"]
    assert cg.diversify(urls) == [urls[0], urls[2], urls[1]]


# ---------------------------------------------------------------------------
# content: discovery with a fake fetcher
# ---------------------------------------------------------------------------

class FakeSite:
    def __init__(self, pages: dict):
        self.pages = pages
        self.calls: list[tuple[str, int]] = []
        self.from_content: dict[str, bool] = {}

    def __call__(self, url, cap, from_content=False):
        self.calls.append((url, cap))
        self.from_content[url] = from_content
        if url not in self.pages:
            return cg.FetchResult(url=url, status=404, body=b"", final_url=url)
        body = self.pages[url]
        return cg.FetchResult(url=url, status=200, body=body[:cap], final_url=url,
                              truncated=len(body) > cap)


def test_crawl_domain_robots_index_gz_offsite_and_caps():
    site = FakeSite({
        "https://a.com/robots.txt": b"Sitemap: https://a.com/index.xml\n",
        "https://a.com/index.xml": _index(["https://a.com/post-sitemap1.xml",
                                           "https://a.com/post-sitemap2.xml",
                                           "https://a.com/page-sitemap.xml.gz"]),
        "https://a.com/post-sitemap1.xml": _urlset([f"https://a.com/blog/p{i}" for i in range(5)]),
        "https://a.com/post-sitemap2.xml": _urlset([f"https://a.com/blog/q{i}" for i in range(5)]),
        "https://a.com/page-sitemap.xml.gz": gzip.compress(_urlset(
            ["https://a.com/pricing", "https://www.a.com/features", "https://evil.com/x"])),
    })
    sleeps = []
    info = cg.crawl_domain("https://www.a.com/", fetch=site, max_urls=6, max_sitemaps=3,
                           delay=0.25, sleep=sleeps.append)
    fetched = info["sitemaps_fetched"]
    assert fetched == ["https://a.com/index.xml", "https://a.com/post-sitemap1.xml",
                       "https://a.com/page-sitemap.xml.gz"]               # diversified order
    assert info["sitemaps_skipped"] == 1 and info["truncated"]
    assert info["offsite_ignored"] == 1
    assert len(info["urls"]) == 6
    assert info["urls"][:4] == ["https://a.com/blog/p0", "https://a.com/pricing",
                                "https://a.com/blog/p1", "https://www.a.com/features"]
    assert sleeps == [0.25] * (len(site.calls) - 1)
    assert site.calls[0] == ("https://a.com/robots.txt", cg.ROBOTS_MAX_BYTES)
    # robots.txt is built from the operator's domain; everything read out of it is content.
    assert site.from_content["https://a.com/robots.txt"] is False
    assert site.from_content["https://a.com/index.xml"] is True
    assert site.from_content["https://a.com/post-sitemap1.xml"] is True


def test_crawl_domain_falls_back_to_sitemap_xml():
    site = FakeSite({"https://a.com/robots.txt": b"User-agent: *\nDisallow:\n",
                     "https://a.com/sitemap.xml": _urlset(["https://a.com/x"])})
    info = cg.crawl_domain("a.com", fetch=site, delay=0)
    assert info["urls"] == ["https://a.com/x"]
    assert site.from_content["https://a.com/sitemap.xml"] is False      # operator-derived fallback
    assert "https://a.com/sitemap_index.xml" not in [u for u, _ in site.calls]
    site2 = FakeSite({"https://a.com/robots.txt": b"",
                      "https://a.com/sitemap_index.xml": _index(["https://a.com/s.xml"]),
                      "https://a.com/s.xml": _urlset(["https://a.com/y"])})
    info2 = cg.crawl_domain("a.com", fetch=site2, delay=0)
    assert info2["urls"] == ["https://a.com/y"]
    assert any("HTTP 404" in e["error"] for e in info2["errors"])


def test_crawl_domain_follows_a_moved_site():
    class Moved(FakeSite):
        def __call__(self, url, cap, from_content=False):
            r = super().__call__(url, cap, from_content)
            if url == "https://old.in/robots.txt":
                return cg.FetchResult(url=url, status=200, final_url="https://www.new.studio/robots.txt",
                                      body=b"Sitemap: https://www.new.studio/sitemap.xml\n")
            return r
    site = Moved({"https://www.new.studio/sitemap.xml": _urlset(
        ["https://www.new.studio/pricing", "https://evil.com/x"])})
    info = cg.crawl_domain("old.in", fetch=site, delay=0)
    assert info["redirected_to"] == "new.studio"
    assert info["urls"] == ["https://www.new.studio/pricing"] and info["offsite_ignored"] == 1
    lims = cg.content_limitations({"old.in": info}, [])
    assert any("old.in -> new.studio" in x for x in lims)


def test_crawl_domain_unreachable():
    def down(url, cap, from_content=False):
        return cg.FetchResult(url=url, error="ConnectionError: refused")
    info = cg.crawl_domain("a.com", fetch=down, delay=0)
    assert info["urls"] == [] and info["errors"][-1]["error"] == "site unreachable over https"


def test_bounded_fetch_blocks_ssrf_without_network():
    r = cg.bounded_fetch("http://127.0.0.1/sitemap.xml")
    assert r.error and r.error.startswith("url_safety") and r.body == b""


def test_bounded_fetch_streams_with_cap(monkeypatch):
    import url_safety

    class Resp:
        status_code = 200
        url = "https://a.com/sitemap.xml"
        closed = False

        def iter_content(self, n):
            for _ in range(100):
                yield b"x" * 1000

        def close(self):
            Resp.closed = True

    seen = {}

    def fake_get(url, **kw):
        seen.update(kw)
        return Resp()

    monkeypatch.setattr(url_safety, "safe_requests_get", fake_get)
    r = cg.bounded_fetch("https://a.com/sitemap.xml", max_bytes=2500)
    assert len(r.body) == 2500 and r.truncated and Resp.closed
    assert seen["stream"] is True
    assert "allow_local_targets" not in seen          # fake has no such parameter


def test_bounded_fetch_disables_local_targets_for_content_urls(monkeypatch):
    import url_safety

    class Resp:
        status_code, url = 200, "https://a.com/s.xml"

        def iter_content(self, n):
            yield b"<urlset/>"

        def close(self):
            pass

    seen = []

    def fake_get(url, *, timeout=30, allow_local_targets=True, **kw):
        seen.append(allow_local_targets)
        return Resp()

    monkeypatch.setattr(url_safety, "safe_requests_get", fake_get)
    cg.bounded_fetch("https://a.com/s.xml")
    cg.bounded_fetch("https://a.com/s.xml", from_content=True)
    assert seen == [True, False]


# ---------------------------------------------------------------------------
# content: gap analysis
# ---------------------------------------------------------------------------

INVENTORY = {
    "acme.com": ["https://acme.com/", "https://acme.com/pricing", "https://acme.com/blog/what-is-a-crm",
                 "https://acme.com/blog/crm-for-agencies", "https://acme.com/features/reports"],
    "rival.com": ["https://rival.com/pricing", "https://rival.com/rival-vs-acme",
                  "https://rival.com/acme-alternatives", "https://rival.com/blog/what-is-crm",
                  "https://rival.com/blog/sales-pipeline-stages",
                  "https://rival.com/integrations/slack", "https://rival.com/careers/dev"]
    + [f"https://rival.com/templates/t{i}-plan" for i in range(6)],
    "other.io": ["https://other.io/blog/sales-pipeline-stage", "https://other.io/compare/other-vs-acme",
                 "https://other.io/integrations/hubspot"]
    + [f"https://other.io/features/f{i}" for i in range(30)],
}


def test_analyze_content_format_and_topic_gaps():
    res = cg.analyze_content(INVENTORY, "acme.com", ["rival.com", "other.io"])
    fg = {g["page_type"]: g for g in res["format_gaps"]}
    assert fg["comparison"]["severity"] == "missing" and fg["comparison"]["competitors_with"] == 2
    assert fg["comparison"]["route"] == "seo-competitor-pages"
    assert fg["alternatives"]["severity"] == "missing"
    assert fg["integrations"]["route"] == "seo-programmatic"
    assert fg["features"]["severity"] == "thin"          # 1 vs median 30
    assert "careers" not in fg and "pricing" not in fg
    order = [g["page_type"] for g in res["format_gaps"]]
    assert order.index("comparison") < order.index("integrations") < order.index("features")
    topics = {t["topic"]: t for t in res["topic_gaps"]}
    pipeline = topics["sale pipeline stage"]
    assert pipeline["n_competitors"] == 2 and pipeline["competitors"] == ["other.io", "rival.com"]
    assert "crm" not in topics                            # what-is-crm covered by our what-is-a-crm
    assert res["topic_gaps"][0]["n_competitors"] == 2
    assert res["topic_gaps_total"] == len(res["topic_gaps"])


def test_topic_groups_do_not_mix_page_types():
    inv = {"acme.com": ["https://acme.com/blog/crm"],
           "rival.com": ["https://rival.com/hubspot-alternatives"],
           "other.io": ["https://other.io/integrations/hubspot"]}
    res = cg.analyze_content(inv, "acme.com", ["rival.com", "other.io"])
    kinds = sorted((t["topic"], t["page_type"], t["route"]) for t in res["topic_gaps"])
    assert kinds == [("hubspot", "integrations", "seo-programmatic"),
                     ("hubspot alternative", "alternatives", "seo-competitor-pages")]


def test_analyze_content_competitor_without_urls():
    res = cg.analyze_content({"acme.com": ["https://acme.com/x"], "rival.com": []}, "acme.com",
                             ["rival.com"])
    assert res["competitors_without_urls"] == ["rival.com"] and res["format_gaps"] == []


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

def test_cli_keywords_with_fixtures(tmp_path):
    own = _write(tmp_path, "own.csv", "Keyword,Volume,KD,Current position,Current URL\n"
                 "crm pricing,2400,35,5,https://acme.com/pricing\ncrm reports,500,20,3,\n")
    rival = _write(tmp_path, "rival.csv", "Keyword,Position,Search Volume,Keyword Difficulty,URL\n"
                   "crm pricing,2,2400,35,https://rival.com/pricing\n"
                   "rival alternatives,9,700,30,https://rival.com/x\n"
                   "crm demo,6,800,25,https://rival.com/demo\n")
    universe = _write(tmp_path, "universe.json", ["crm onboarding checklist"])
    r = _run("keywords", "--own", own, "--competitor", f"rival={rival}", "--universe", universe,
             "--brand", "acme", "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["summary"]["counts"] == {"moat": 1, "battleground": 1, "gap": 2, "pioneer": 1}
    assert out["data_sources"] and out["limitations"]
    csv_out = tmp_path / "gap.csv"
    r = _run("keywords", "--own", own, "--competitor", f"rival={rival}", "--output", str(csv_out))
    assert r.returncode == 0, r.stderr
    assert csv_out.read_text().splitlines()[0].split(",") == list(cg.GAP_CSV_COLUMNS)


def test_cli_content_offline_inventory(tmp_path):
    inv = _write(tmp_path, "inventory.json", {"domains": INVENTORY})
    r = _run("content", "--own", "acme.com", "--input", inv, "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["competitors"] == ["rival.com", "other.io"]
    assert out["format_gaps"][0]["severity"] == "missing"
    assert out["domains"]["rival.com"]["page_types"]["templates"] == 6
    assert out["data_sources"] and out["limitations"]
    r = _run("content", "--own", "nobody.com", "--input", inv, "--competitor", "rival.com")
    assert r.returncode == 1 and "no URLs discovered" in r.stderr


def test_cli_rejects_bad_caps_and_missing_competitor(tmp_path):
    r = _run("content", "--own", "acme.com", "--max-urls", "0")
    assert r.returncode == 1 and "--max-urls" in r.stderr
    own = _write(tmp_path, "own.csv", "Keyword,Position\ncrm,3\n")
    r = _run("keywords", "--own", own)
    assert r.returncode == 1 and "--competitor" in r.stderr
