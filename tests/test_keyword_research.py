"""
Tests for scripts/keyword_research.py (seo-keywords skill).

Offline only: the autocomplete fetcher, sleep and clock are injected; GSC
rows come from fixtures or an injected query function; every cache/profile
write goes under tmp_path via --data-dir / data_dir.
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
SCRIPT = SCRIPTS / "keyword_research.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import keyword_research as kr  # noqa: E402
import seo_metrics as m  # noqa: E402
import seo_project as proj  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AHREFS_CSV = (
    "Keyword,Country,Volume,KD,CPC,Current position,Current URL,Global volume\n"
    "CRM Pricing,us,2400,35,12.5,8,https://acme.com/pricing,9000\n"
    "best crm for startups,us,1300,52,9.1,,,4000\n"
    "hubspot alternatives,us,880,41,7.0,14,https://acme.com/blog/hubspot-alt,2100\n"
    "what is a crm,us,12000,78,2.1,25,https://acme.com/blog/what-is-crm,90000\n"
)

SEMRUSH_CSV = (
    "Keyword,Position,Previous position,Search Volume,Keyword Difficulty,CPC,URL,Traffic\n"
    "crm pricing,6,9,2900,38,11.0,https://acme.com/pricing,140\n"
    "crm software for small business,11,12,1600,60,14.2,https://acme.com/crm,30\n"
)


def _kp_utf16_tsv() -> bytes:
    text = ("Keyword Stats 2026-10-01 at 10_00_00\n"
            "October 1, 2025 - September 30, 2026\n"
            "Keyword\tCurrency\tAvg. monthly searches\tCompetition\tCompetition (indexed value)\n"
            "crm pricing\tUSD\t1K – 10K\tHigh\t88\n"
            "crm demo\tUSD\t100 – 1K\tHigh\t91\n")
    return text.encode("utf-16")


GSC_ROWS = [
    # query, page, clicks, impressions, position, ctr(percent, deliberately wrong)
    ("crm pricing", "https://acme.com/pricing", 20, 2000, 7.2, 99.0),
    ("crm pricing", "https://acme.com/blog/crm-cost", 18, 1500, 9.0, 99.0),
    ("hubspot vs acme", "https://acme.com/vs/hubspot", 4, 900, 12.0, 99.0),
    ("what is a crm", "https://acme.com/blog/what-is-crm", 1, 5000, 4.0, 99.0),
    ("acme login", "https://acme.com/login", 900, 1000, 1.0, 99.0),
    ("acme pricing", "https://acme.com/pricing", 40, 300, 5.0, 99.0),
    ("tiny query", "https://acme.com/x", 0, 10, 8.0, 0.0),
    ("crm for agencies", "https://acme.com/agencies", 30, 400, 2.0, 99.0),
    ("crm reports", "https://acme.com/reports", 25, 500, 3.0, 99.0),
    ("crm api", "https://acme.com/api", 8, 400, 6.0, 99.0),
]


def _gsc_query_output(rows=GSC_ROWS) -> dict:
    out = []
    for q, page, clicks, imps, pos, ctr_pct in rows:
        out.append({"keys": [q, page], "clicks": clicks, "impressions": imps,
                    "ctr": ctr_pct, "position": pos, "query": q, "page": page})
    return {"property": "sc-domain:acme.com", "rows": out,
            "date_range": {"start": "2026-07-17", "end": "2026-10-14"}, "error": None}


def _write(tmp_path: Path, name: str, content) -> str:
    p = tmp_path / name
    if isinstance(content, bytes):
        p.write_bytes(content)
    elif isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_text(json.dumps(content), encoding="utf-8")
    return str(p)


def _run(*argv: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("CLAUDE_SEO_DATA_DIR", None)
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True,
                          text=True, timeout=60, env=env)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1,200", 1200.0), ("1.2K", 1200.0), ("3m", 3_000_000.0), ("45%", 45.0), ("$1.20", 1.2),
    ("", None), ("-", None), ("n/a", None), (None, None), (12, 12.0), ("1,5", 1.5),
])
def test_parse_number_scalars(raw, expected):
    assert kr.parse_number(raw)[0] == expected


def test_parse_number_ranges_use_geometric_midpoint():
    val, rng = kr.parse_number("1K – 10K")
    assert rng == (1000.0, 10000.0)
    assert val == pytest.approx(3162.3, abs=0.1)
    assert kr.parse_number("0 - 10") == (5.0, (0.0, 10.0))


def test_normalize_keyword_case_whitespace_and_zero_width():
    assert kr.normalize_keyword("  CRM\u200b   Pricing ") == "crm pricing"
    assert kr.normalize_keyword("C++ Tutorial") == "c++ tutorial"


def test_detect_columns_common_exports():
    cmap, _ = kr.detect_columns(["Keyword", "Volume", "KD", "Current position", "Current URL",
                                 "Global volume"])
    assert cmap == {"keyword": "Keyword", "volume": "Volume", "difficulty": "KD",
                    "position": "Current position", "url": "Current URL"}
    cmap, _ = kr.detect_columns(["Keyword", "Position", "Previous position", "Search Volume",
                                 "Keyword Difficulty %", "CPC (USD)"])
    assert cmap["position"] == "Position"
    assert cmap["difficulty"] == "Keyword Difficulty %"
    assert cmap["cpc"] == "CPC (USD)"


def test_ads_competition_is_never_difficulty_unless_opted_in():
    headers = ["Keyword", "Avg. monthly searches", "Competition", "Competition (indexed value)"]
    cmap, notes = kr.detect_columns(headers)
    assert "difficulty" not in cmap
    assert any("paid-ad competition" in n for n in notes)
    cmap, notes = kr.detect_columns(headers, difficulty_column="Competition (indexed value)")
    assert cmap["difficulty"] == "Competition (indexed value)"
    _, notes = kr.detect_columns(headers, difficulty_column="nope")
    assert any("not found" in n for n in notes)


def test_greedy_jaccard_groups_best_fit_and_empty_sets():
    groups = kr.greedy_jaccard_groups([["crm", "pricing"], ["seo", "tool"], ["crm", "pricing", "plan"],
                                       [], ["seo", "tool", "free"]], 0.5)
    assert groups == [[0, 2], [1, 4], [3]]


def test_fold_token_and_group_label():
    assert kr.fold_token("agencies") == "agency"
    assert kr.fold_token("tools") == "tool"
    assert kr.fold_token("business") == "business"
    assert kr.group_label([["crm", "pricing"], ["crm", "pricing", "plan"]], "x") == "crm pricing"
    assert kr.group_label([["a", "b"], ["b", "c"], ["c", "d"]], "x") == "b c"


def test_csv_output_neutralizes_formula_injection():
    out = kr.rows_to_csv([{"keyword": "=HYPERLINK(\"x\")", "n": 1}], ["keyword", "n"])
    assert "'=HYPERLINK" in out


# ---------------------------------------------------------------------------
# Loading every supported shape
# ---------------------------------------------------------------------------

def test_load_ahrefs_csv(tmp_path):
    recs, meta = kr.load_records(_write(tmp_path, "ahrefs.csv", AHREFS_CSV))
    assert meta["format"] == "csv" and meta["records"] == 4
    first = recs[0]
    assert first["keyword"] == "crm pricing"
    assert (first["volume"], first["difficulty"], first["position"]) == (2400.0, 35.0, 8.0)
    assert first["url"] == "https://acme.com/pricing"
    assert recs[1]["position"] is None  # blank cell = unknown, not "position 0"


def test_load_keyword_planner_utf16_tsv_with_preamble(tmp_path):
    recs, meta = kr.load_records(_write(tmp_path, "kp.csv", _kp_utf16_tsv()))
    assert [r["keyword"] for r in recs] == ["crm pricing", "crm demo"]
    assert recs[0]["volume_range"] == [1000.0, 10000.0]
    assert recs[0]["difficulty"] is None
    assert any("paid-ad competition" in n for n in meta["notes"])


def test_load_keyword_planner_json(tmp_path):
    kp = {"seed_keywords": ["crm"], "ideas": [
        {"keyword": "crm pricing", "avg_monthly_searches": 2900, "competition": "HIGH",
         "competition_index": 88, "low_top_of_page_bid": 4.1, "high_top_of_page_bid": 15.0}],
        "error": None}
    recs, meta = kr.load_records(_write(tmp_path, "kp.json", kp))
    assert meta["source"] == "google_ads_keyword_planner"
    assert recs[0]["volume"] == 2900 and recs[0]["difficulty"] is None
    vol = {"keywords": [{"keyword": "crm demo", "avg_monthly_searches": 320, "competition": "LOW"}]}
    recs, meta = kr.load_records(_write(tmp_path, "kpv.json", vol))
    assert meta["source"] == "google_ads_keyword_planner" and recs[0]["volume"] == 320


def test_load_dataforseo_envelope_and_items(tmp_path):
    envelope = {"tasks": [{"status_code": 20000, "result": [{"items": [
        {"keyword_data": {"keyword": "crm pricing",
                          "keyword_info": {"search_volume": 2400, "cpc": 11.2, "competition": 0.9},
                          "keyword_properties": {"keyword_difficulty": 37},
                          "search_intent_info": {"main_intent": "transactional"}},
         "ranked_serp_element": {"serp_item": {"rank_group": 4, "rank_absolute": 6,
                                               "url": "https://rival.com/pricing"}}}]}]}]}
    recs, meta = kr.load_records(_write(tmp_path, "dfs.json", envelope))
    assert meta["source"] == "dataforseo"
    r = recs[0]
    assert (r["keyword"], r["volume"], r["difficulty"], r["position"]) == ("crm pricing", 2400, 37, 4)
    assert r["provider_intent"] == "transactional"
    ideas = [{"keyword": "crm demo", "keyword_info": {"search_volume": 500},
              "keyword_properties": {"keyword_difficulty": 22}}]
    recs, _ = kr.load_records(_write(tmp_path, "ideas.json", ideas))
    assert recs[0]["volume"] == 500 and recs[0]["difficulty"] == 22


def test_load_suggest_gsc_and_plain_lists(tmp_path):
    sugg = {"seeds": ["crm"], "suggestions": [{"keyword": "crm pricing", "seed": "crm",
                                               "source_query": "crm"}]}
    recs, meta = kr.load_records(_write(tmp_path, "s.json", sugg))
    assert meta["source"] == "google_suggest"
    assert {r["keyword"] for r in recs} == {"crm", "crm pricing"}
    recs, meta = kr.load_records(_write(tmp_path, "g.json", _gsc_query_output()))
    assert meta["source"] == "gsc" and recs[0]["url"].startswith("https://acme.com/")
    recs, _ = kr.load_records(_write(tmp_path, "list.json", ["CRM", "crm demo"]))
    assert [r["keyword"] for r in recs] == ["crm", "crm demo"]
    recs, _ = kr.load_records(_write(tmp_path, "plain.txt", "crm\ncrm demo\n"))
    assert len(recs) == 2


def test_unknown_csv_columns_raise(tmp_path):
    with pytest.raises(kr.InputError, match="no keyword column"):
        kr.load_records(_write(tmp_path, "bad.csv", "Term,Volume\ncrm,10\n"))
    with pytest.raises(kr.InputError, match="unrecognized JSON"):
        kr.load_records(_write(tmp_path, "bad.json", {"foo": 1}))


def test_merge_records_rules(tmp_path):
    a, _ = kr.load_records(_write(tmp_path, "ahrefs.csv", AHREFS_CSV))
    b, _ = kr.load_records(_write(tmp_path, "semrush.csv", SEMRUSH_CSV))
    merged = kr.merge_records(a + b)
    crm = merged["crm pricing"]
    assert crm["volume"] == 2900.0          # max volume
    assert crm["difficulty"] == 38.0        # max difficulty (conservative)
    assert crm["position"] == 6.0           # best position, with its URL
    assert crm["sources"] == {"ahrefs", "semrush"}


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

def test_score_keywords_matches_seo_metrics_and_sorts(tmp_path):
    a, _ = kr.load_records(_write(tmp_path, "ahrefs.csv", AHREFS_CSV))
    merged = kr.merge_records(a)
    res = kr.score_keywords(merged, brand_terms=["acme"], competitor_terms_=["hubspot"])
    rows = {r["keyword"]: r for r in res["keywords"]}
    r = rows["crm pricing"]
    intent = m.classify_intent("crm pricing", ["acme"], ["hubspot"])
    exp = m.opportunity_score(2400, 35, 8, intent["lead_value"])
    assert r["opportunity_score"] == exp["score"] and r["completeness"] == exp["completeness"]
    assert r["bucket"] == m.scenario_bucket(35, intent["lead_value"], 8)
    assert r["traffic_potential"] == m.traffic_potential(2400, 3.0)
    assert r["lead_priority_basis"] == "traffic_potential"
    assert r["lead_priority"] == round(m.traffic_potential(2400) * intent["lead_value"], 1)
    assert rows["hubspot alternatives"]["route"] == "seo-competitor-pages"
    scores = [x["opportunity_score"] for x in res["keywords"]]
    assert scores == sorted(scores, reverse=True)
    assert res["grouping"].startswith("lexical (approximate)")
    assert sum(res["summary"]["by_funnel"].values()) == res["summary"]["total"] == 4
    assert all("group_id" in x for x in res["keywords"])


def test_score_gsc_opp_clicks_basis_relevance_and_min_volume(tmp_path):
    merged = kr.merge_records([
        {"keyword": "crm pricing", "volume": 2400, "volume_range": None, "difficulty": 30,
         "position": 7, "url": None, "cpc": None, "impressions": 2000, "clicks": 20,
         "opp_clicks_monthly": 50.0, "provider_intent": None, "source": "gsc"},
        {"keyword": "crm history", "volume": 20, "volume_range": None, "difficulty": None,
         "position": None, "url": None, "cpc": None, "impressions": None, "clicks": None,
         "opp_clicks_monthly": None, "provider_intent": None, "source": "x"},
        {"keyword": "crm ideas", "volume": None, "volume_range": None, "difficulty": None,
         "position": None, "url": None, "cpc": None, "impressions": None, "clicks": None,
         "opp_clicks_monthly": None, "provider_intent": None, "source": "x"},
    ])
    res = kr.score_keywords(merged, relevance={"crm pricing": 0.5}, min_volume=100)
    rows = {r["keyword"]: r for r in res["keywords"]}
    assert "crm history" not in rows and res["summary"]["dropped_below_min_volume"] == 1
    assert "crm ideas" in rows and rows["crm ideas"]["lead_priority"] is None  # unknown volume kept
    p = rows["crm pricing"]
    assert p["lead_priority_basis"] == "gsc_opp_clicks"
    assert p["lead_priority"] == round(50.0 * 1.0 * 0.5, 1)
    assert p["relevance"] == 0.5


def test_score_is_deterministic(tmp_path):
    a, _ = kr.load_records(_write(tmp_path, "ahrefs.csv", AHREFS_CSV))
    one = kr.score_keywords(kr.merge_records(a))
    two = kr.score_keywords(kr.merge_records(list(a)))
    assert one == two


def test_relevance_file_clips(tmp_path):
    rel, notes = kr.load_relevance(_write(tmp_path, "rel.csv",
                                          "keyword,relevance\nCRM pricing,0.8\ncrm demo,3\n"))
    assert rel == {"crm pricing": 0.8, "crm demo": 1.0}
    assert notes


# ---------------------------------------------------------------------------
# suggest
# ---------------------------------------------------------------------------

class FakeFetch:
    def __init__(self, responses=None, default=None):
        self.calls: list[str] = []
        self.responses = responses or {}
        self.default = default

    def __call__(self, url):
        self.calls.append(url)
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)["q"][0]
        if q in self.responses:
            resp = self.responses[q]
        elif self.default is not None:
            resp = self.default(q)
        else:
            resp = (200, json.dumps([q, [f"{q} one", f"{q} two"]]).encode(), "text/javascript; charset=UTF-8")
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0
        self.sleeps: list[float] = []

    def time(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_build_and_plan_queries():
    basic = kr.build_queries("CRM", "basic")
    assert basic[0] == "crm" and "how crm" in basic and "crm near me" in basic
    assert len(basic) == 1 + len(kr.QUESTION_PREFIXES) + len(kr.MODIFIER_SUFFIXES)
    full = kr.build_queries("crm", "full")
    assert len(full) == len(basic) + 36 and full[-1] == "crm 9"
    plan = kr.plan_queries(["crm", "seo"], "basic")
    assert plan[:4] == [("crm", "crm"), ("seo", "seo"), ("crm", "how crm"), ("seo", "how seo")]


def test_suggest_url_encodes_locale_and_query():
    url = kr.build_suggest_url("crm vs hubspot", "de", "at")
    assert url.startswith("https://suggestqueries.google.com/complete/search?client=firefox")
    assert "hl=de" in url and "gl=at" in url and "q=crm+vs+hubspot" in url


def test_suggest_rate_limit_cap_and_dedupe(tmp_path):
    fetch, clock = FakeFetch(default=lambda q: (200, json.dumps([q, ["crm pricing", q + " x"]]).encode(), "")), FakeClock()
    res = kr.run_suggest(["crm"], max_requests=3, delay=1.0, data_dir=str(tmp_path),
                         fetch=fetch, sleep=clock.sleep, clock=clock.time)
    assert res["requests_made"] == 3 and len(fetch.calls) == 3
    assert res["queries_skipped"] == res["queries_planned"] - 3
    assert clock.sleeps == [1.0, 1.0]  # no sleep before the first request
    kws = [s["keyword"] for s in res["suggestions"]]
    assert kws.count("crm pricing") == 1
    assert res["provider"] == "google_suggest (unofficial, no volume data)"
    assert any("--max-requests" in lim for lim in res["limitations"])
    assert res["data_sources"] and res["limitations"]


def test_suggest_cache_hit_expiry_and_no_cache(tmp_path):
    clock = FakeClock()
    first = FakeFetch()
    r1 = kr.run_suggest(["crm"], max_requests=2, delay=0, data_dir=str(tmp_path),
                        fetch=first, sleep=clock.sleep, clock=clock.time)
    assert r1["requests_made"] == 2
    cache_files = list((tmp_path / "cache" / "suggest").glob("*.json"))
    assert len(cache_files) == 2
    assert oct(cache_files[0].stat().st_mode & 0o777) == "0o600"

    second = FakeFetch()
    r2 = kr.run_suggest(["crm"], max_requests=0, delay=0, data_dir=str(tmp_path),
                        fetch=second, sleep=clock.sleep, clock=clock.time)
    assert r2["cache_hits"] == 2 and second.calls == []
    assert [s["keyword"] for s in r2["suggestions"]] == [s["keyword"] for s in r1["suggestions"]]

    clock.t += 8 * 86400  # older than the 7-day default
    r3 = kr.run_suggest(["crm"], max_requests=0, delay=0, data_dir=str(tmp_path),
                        fetch=FakeFetch(), sleep=clock.sleep, clock=clock.time)
    assert r3["cache_hits"] == 0

    third = FakeFetch()
    r4 = kr.run_suggest(["crm"], max_requests=1, delay=0, data_dir=str(tmp_path / "other"),
                        use_cache=False, fetch=third, sleep=clock.sleep, clock=clock.time)
    assert r4["requests_made"] == 1 and not (tmp_path / "other" / "cache").exists()


def test_suggest_fail_soft_and_circuit_breaker(tmp_path):
    clock = FakeClock()
    fetch = FakeFetch(responses={
        "crm": ConnectionError("boom"),
        "how crm": (200, b"<html>not json</html>", "text/html"),
        "what crm": (429, b"", ""),
    })
    res = kr.run_suggest(["crm"], max_requests=50, delay=0, data_dir=str(tmp_path),
                         fetch=fetch, sleep=clock.sleep, clock=clock.time)
    assert res["requests_made"] == 3            # stopped after the 429
    assert [e["query"] for e in res["errors"]] == ["crm", "how crm", "what crm"]
    assert "ConnectionError" in res["errors"][0]["error"]
    assert res["queries_skipped"] == res["queries_planned"] - 3
    assert any("HTTP 429" in lim for lim in res["limitations"])
    assert res["suggestions"] == []


def test_parse_suggest_response_shapes():
    assert kr.parse_suggest_response(json.dumps(["q", ["a", "b", 3]]).encode()) == ["a", "b"]
    with pytest.raises(ValueError):
        kr.parse_suggest_response(b'{"a": 1}')
    latin = json.dumps(["q", ["café"]], ensure_ascii=False).encode("latin-1")
    assert kr.parse_suggest_response(latin, "text/javascript; charset=ISO-8859-1") == ["café"]


# ---------------------------------------------------------------------------
# gsc
# ---------------------------------------------------------------------------

def test_normalize_gsc_rows_recomputes_ctr_fraction():
    rows = kr.normalize_gsc_rows(_gsc_query_output()["rows"])
    crm = rows[0]
    assert crm["ctr"] == pytest.approx(20 / 2000)  # not the bogus 99% percent field
    assert all(0 <= r["ctr"] <= 1 for r in rows)


def test_gsc_analysis_brand_exclusion_striking_and_cannibalization():
    rows = kr.normalize_gsc_rows(_gsc_query_output()["rows"])
    res = kr.analyze_gsc_rows(rows, brand_terms=["acme"], min_impressions=50, period_days=90)
    queries = [s["query"] for s in res["striking"]]
    # Brand-navigational queries are excluded; brand + buying-modifier queries
    # ("acme pricing", "hubspot vs acme") are BOFU work and are kept + flagged.
    assert "acme login" not in queries
    assert "acme pricing" in queries
    assert next(s for s in res["striking"] if s["query"] == "acme pricing")["brand"] is True
    assert "tiny query" not in queries                         # below impression floor
    assert set(queries) == {"crm pricing", "hubspot vs acme", "acme pricing", "what is a crm", "crm api"}
    vs = next(x for x in res["striking"] if x["query"] == "hubspot vs acme")
    assert vs["brand"] is True and vs["funnel"] == "BOFU"
    assert res["totals"]["branded_navigational_rows"] == 1             # "acme login" only
    assert res["ctr_curve"]["calibrated"] is False             # 10 rows: no bucket has 5 rows
    s = next(x for x in res["striking"] if x["page"] == "https://acme.com/pricing")
    exp = m.striking_distance_opportunity(7.2, 20 / 2000, 2000, None)
    assert s["opp_clicks"] == exp["opp_clicks"]
    assert s["opp_clicks_monthly"] == round(exp["opp_clicks"] * 30 / 90, 1)
    assert s["lead_priority"] == round(s["opp_clicks_monthly"] * s["lead_value"], 1)
    assert s["cannibalized"] is True
    assert res["cannibalization"][0]["query"] == "crm pricing"
    lps = [x["lead_priority"] for x in res["striking"]]
    assert lps == sorted(lps, reverse=True)
    inc = kr.analyze_gsc_rows(rows, brand_terms=["acme"], include_brand=True)
    assert "acme pricing" in [x["query"] for x in inc["striking"]]


def _calibration_rows(positions=(2, 5, 8), per_bucket=5, branded_ctr=False):
    rows = []
    for pos in positions:
        for i in range(per_bucket):
            q = f"topic {pos} variant {i}"
            rows.append((q, f"https://acme.com/{pos}/{i}", 10, 200, float(pos), 0.0))
    # Brand rows with absurd CTR must not leak into the calibrated curve.
    rows += [(f"acme {w}", "https://acme.com/", 190, 200, 2.0, 0.0) for w in ("login", "app")]
    return kr.normalize_gsc_rows(_gsc_query_output(rows)["rows"])


def test_gsc_curve_calibrated_only_with_three_buckets_of_five_rows():
    res = kr.analyze_gsc_rows(_calibration_rows(), brand_terms=["acme"])
    assert res["ctr_curve"]["calibrated"] is True
    assert res["curve_source"].startswith("site-calibrated")
    assert res["ctr_curve"]["curve"] == {"2": 0.05, "5": 0.05, "8": 0.05}   # brand rows excluded
    thin = kr.analyze_gsc_rows(_calibration_rows(per_bucket=4), brand_terms=["acme"])
    assert thin["ctr_curve"]["calibrated"] is False
    two = kr.analyze_gsc_rows(_calibration_rows(positions=(2, 5)), brand_terms=["acme"])
    assert two["ctr_curve"]["calibrated"] is False
    assert two["curve_source"] == m.CTR_CURVE_SOURCE


def test_gsc_ctr_underperformers_rule():
    rows = kr.normalize_gsc_rows(_gsc_query_output()["rows"])
    res = kr.analyze_gsc_rows(rows, brand_terms=["acme"])
    for u in res["ctr_underperformers"]:
        assert u["position"] <= 10 and u["ctr_ratio"] < 0.5
    assert "what is a crm" in [u["query"] for u in res["ctr_underperformers"]]


def test_fetch_gsc_rows_uses_query_fn_contract():
    seen = {}

    def fake_query(site_url, **kw):
        seen.update(kw, site_url=site_url)
        return _gsc_query_output()

    rows, dr, err = kr.fetch_gsc_rows("sc-domain:acme.com", 90, query_fn=fake_query,
                                      today=date(2026, 10, 17))
    assert err is None and len(rows) == len(GSC_ROWS)
    assert seen["dimensions"] == ["query", "page"] and seen["data_state"] == "final"
    assert dr == {"start": "2026-07-17", "end": "2026-10-14"}   # 90 days inclusive, 3-day lag
    _, _, err = kr.fetch_gsc_rows("x", 90, query_fn=lambda *a, **k: {"error": "no creds"})
    assert err == "no creds"


# ---------------------------------------------------------------------------
# CLI smoke tests (subprocess, fixtures, isolated data dir)
# ---------------------------------------------------------------------------

def test_cli_gsc_from_input_with_project(tmp_path):
    data_dir = tmp_path / "data"
    profile = proj.new_profile("acme.com", brand_terms=["acme"], competitors=["hubspot.com"])
    proj.save_profile(profile, str(data_dir))
    rows = _write(tmp_path, "gsc.json", _gsc_query_output())
    r = _run("gsc", "--input", rows, "--project", "acme.com", "--data-dir", str(data_dir), "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["period_days"] == 90
    assert out["parameters"]["brand_terms"] == ["acme"]
    assert "acme login" not in [s["query"] for s in out["striking"]]
    assert out["data_sources"] and out["limitations"]
    csv_path = tmp_path / "gsc.csv"
    r = _run("gsc", "--input", rows, "--brand", "acme", "--output", str(csv_path))
    assert r.returncode == 0, r.stderr
    header = csv_path.read_text().splitlines()[0].split(",")
    assert header == list(kr.CSV_COLUMNS_GSC)


def test_cli_score_json_and_csv(tmp_path):
    a = _write(tmp_path, "ahrefs.csv", AHREFS_CSV)
    s = _write(tmp_path, "semrush.csv", SEMRUSH_CSV)
    sugg = _write(tmp_path, "suggest.json", {"seeds": ["crm"], "suggestions": [
        {"keyword": "crm demo", "seed": "crm", "source_query": "crm"}]})
    r = _run("score", "--input", a, "--input", s, "--input", sugg, "--brand", "acme",
             "--competitor", "hubspot", "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["summary"]["total"] == 7
    assert {i["source"] for i in out["inputs"]} == {"ahrefs", "semrush", "google_suggest"}
    assert out["data_sources"] and out["limitations"]
    r = _run("score", "--input", a, "--format", "csv")
    assert r.returncode == 0, r.stderr
    rows = list(csv.DictReader(io.StringIO(r.stdout)))
    assert list(rows[0].keys()) == list(kr.CSV_COLUMNS_SCORE)
    assert len(rows) == 4


def test_cli_suggest_served_from_cache_without_network(tmp_path):
    data_dir = tmp_path / "data"
    clock = FakeClock()
    kr.run_suggest(["crm"], max_requests=100, delay=0, data_dir=str(data_dir), fetch=FakeFetch(),
                   sleep=clock.sleep, clock=lambda: __import__("time").time())
    r = _run("suggest", "crm", "--max-requests", "0", "--data-dir", str(data_dir), "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["requests_made"] == 0 and out["cache_hits"] == out["queries_planned"]
    assert "crm one" in [s["keyword"] for s in out["suggestions"]]


def test_cli_errors_are_clean(tmp_path):
    r = _run("gsc", "--project", "nobody.com", "--data-dir", str(tmp_path))
    assert r.returncode == 1 and "no project profile" in r.stderr
    r = _run("score", "--input", str(tmp_path / "missing.csv"))
    assert r.returncode == 1 and "cannot read" in r.stderr
