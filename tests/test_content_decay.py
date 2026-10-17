"""
Tests for scripts/content_decay.py — GSC content decay tiers, cause diagnosis,
action rules, decay score and Outrank-style improvement candidates.

Offline only: live GSC access is replaced by an injected query function, and
project profiles live under tmp_path via --data-dir.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import content_decay as cd  # noqa: E402
import seo_project  # noqa: E402

PY = sys.executable
SCRIPT = str(SCRIPTS / "content_decay.py")


def row(page, clicks, impressions, position, **extra):
    return {"page": page, "clicks": clicks, "impressions": impressions, "position": position, **extra}


def page_of(result, page):
    return next(p for p in result["pages"] if p["page"] == page)


FIXTURE = {
    "current": [
        row("https://ex.com/rank-loss", 50, 4000, 9.5, ctr=1.25),
        row("https://ex.com/aio", 60, 10000, 3.1),
        row("https://ex.com/demand", 30, 1500, 4.0),
        row("https://ex.com/pricing", 30, 1500, 4.0),
        row("https://ex.com/cannibal-a", 40, 2000, 6.0),
        row("https://ex.com/cannibal-b", 35, 1800, 7.0),
        row("https://ex.com/stable", 100, 3000, 5.0),
        row("https://ex.com/tiny", 1, 50, 30.0),
        row("https://ex.com/candidate", 10, 2000, 6.0),
    ],
    "previous": [
        row("https://ex.com/rank-loss", 140, 6000, 5.0),
        row("https://ex.com/aio", 200, 10000, 3.0),
        row("https://ex.com/stable", 105, 3000, 5.0),
        row("https://ex.com/tiny", 5, 60, 25.0),
        row("https://ex.com/candidate", 30, 2100, 6.1),
        row("https://ex.com/gone", 80, 900, 4.0),
    ],
    "yoy": [
        row("https://ex.com/rank-loss", 160, 6500, 4.8),
        row("https://ex.com/aio", 210, 9800, 3.0),
        row("https://ex.com/demand", 120, 6000, 4.1),
        row("https://ex.com/pricing", 120, 6000, 4.1),
        row("https://ex.com/cannibal-a", 90, 2500, 5.0),
        row("https://ex.com/stable", 95, 2900, 5.1),
        row("https://ex.com/gone", 100, 1000, 4.0),
    ],
    "query_page": [
        {"query": "crm pricing", "page": "https://ex.com/cannibal-a", "clicks": 20, "impressions": 900, "position": 6},
        {"query": "crm pricing", "page": "https://ex.com/cannibal-b", "clicks": 18, "impressions": 800, "position": 7},
        {"query": "best crm", "page": "https://ex.com/candidate", "clicks": 5, "impressions": 1200, "position": 6},
        {"query": "crm tools", "page": "https://ex.com/candidate", "clicks": 5, "impressions": 800, "position": 6},
        {"keys": ["acme login", "https://ex.com/stable"], "clicks": 50, "impressions": 100, "position": 1},
    ],
}


@pytest.fixture
def result():
    return cd.analyze_pages(FIXTURE, min_baseline_clicks=20, money_pages=["/pricing"],
                            brand_terms=["acme"], calibrate=False)


# ---------------------------------------------------------------------------
# Tiers and baselines
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pct,tier", [
    (-19.9, "stable"), (-20.0, "warning"), (-39.9, "warning"), (-40.0, "high"),
    (-59.9, "high"), (-60.0, "critical"), (-100.0, "critical"), (15.0, "stable"), (None, "stable"),
])
def test_tier_thresholds(pct, tier):
    assert cd.tier_for(pct) == tier


def test_yoy_baseline_preferred_when_available(result):
    p = page_of(result, "https://ex.com/rank-loss")
    assert p["baseline"] == "yoy"
    assert "seasonality-safe" in p["baseline_reason"]
    assert p["delta"]["clicks_pct"] == pytest.approx(-68.8)


def test_page_without_yoy_row_falls_back_to_previous_and_says_so(result):
    p = page_of(result, "https://ex.com/candidate")
    assert p["baseline"] == "previous"
    assert "seasonality NOT controlled" in p["baseline_reason"]


def test_property_without_yoy_data_falls_back_for_every_page():
    data = {k: v for k, v in FIXTURE.items() if k != "yoy"}
    res = cd.analyze_pages(data, calibrate=False)
    assert res["summary"]["yoy_available"] is False
    p = page_of(res, "https://ex.com/rank-loss")
    assert p["baseline"] == "previous"
    assert "no year-earlier data" in p["baseline_reason"]


def test_below_floor_baseline_is_insufficient_and_monitored(result):
    p = page_of(result, "https://ex.com/tiny")
    assert p["tier"] == "insufficient_data"
    assert p["decay_score"] is None
    assert p["action"]["action"] == "monitor"


def test_new_page_has_no_baseline(result):
    p = page_of(result, "https://ex.com/cannibal-b")
    assert p["tier"] == "insufficient_data"
    assert "no baseline data" in p["baseline_reason"]


def test_ctr_is_recomputed_not_taken_from_rows(result):
    cur = page_of(result, "https://ex.com/rank-loss")["windows"]["current"]
    assert cur["ctr"] == pytest.approx(50 / 4000, abs=1e-4)


# ---------------------------------------------------------------------------
# Causes and actions
# ---------------------------------------------------------------------------

def test_ranking_loss_critical_recommends_rewrite(result):
    p = page_of(result, "https://ex.com/rank-loss")
    assert p["tier"] == "critical"
    assert p["cause"]["primary"] == "ranking_loss"
    assert p["cause"]["basis"].startswith("INFERRED")
    assert (p["action"]["action"], p["action"]["rule"]) == ("rewrite", "R4b")


def test_moderate_ranking_loss_recommends_refresh():
    data = {"current": [row("/a", 70, 4500, 7.0)], "yoy": [row("/a", 100, 5500, 5.5)]}
    p = cd.analyze_pages(data, calibrate=False)["pages"][0]
    assert p["tier"] == "warning"
    assert p["cause"]["primary"] == "ranking_loss"
    assert (p["action"]["action"], p["action"]["rule"]) == ("refresh", "R4a")


def test_serp_feature_when_impressions_and_position_flat_but_ctr_down(result):
    p = page_of(result, "https://ex.com/aio")
    assert p["cause"]["primary"] == "serp_feature_or_ai_overview"
    assert p["action"]["action"] == "refresh"
    assert any("aio-recovery" in v for v in p["action"]["verify_first"])


def test_demand_drop_critical_is_review_only_for_non_money_page(result):
    p = page_of(result, "https://ex.com/demand")
    assert p["cause"]["primary"] == "demand_drop"
    assert p["action"]["action"] == "redirect_or_retire_review"
    assert "Review only" in p["action"]["why"]


def test_money_page_is_never_suggested_for_retirement(result):
    p = page_of(result, "https://ex.com/pricing")
    assert p["money_page"] is True
    assert p["cause"]["primary"] == "demand_drop"
    assert p["action"]["action"] == "monitor"
    assert "money page" in p["action"]["why"]


def test_cannibalization_recommends_consolidate(result):
    p = page_of(result, "https://ex.com/cannibal-a")
    assert p["cause"]["primary"] == "cannibalization"
    assert p["action"]["action"] == "consolidate"
    assert p["cannibalization"][0]["others"] == ["https://ex.com/cannibal-b"]


def test_branded_queries_do_not_count_as_cannibalization(result):
    assert all(rec["query"] != "acme login" for rec in result["cannibalization"])


def test_page_missing_from_current_is_lost_visibility(result):
    p = page_of(result, "https://ex.com/gone")
    assert p["cause"]["primary"] == "lost_visibility"
    assert p["action"]["action"] == "redirect_or_retire_review"
    assert p["decay_score"]["components"]["position_loss"] == 1.0


def test_no_action_ever_deletes():
    allowed = {"refresh", "rewrite", "consolidate", "redirect_or_retire_review", "monitor"}
    for tier in ("warning", "high", "critical", "stable", "insufficient_data"):
        for cause in list(cd.VERIFY_FIRST) + [None]:
            for money in (True, False):
                act = cd.recommend(tier, cause, {"position": 25.0}, money)
                assert act["action"] in allowed
                if money:
                    assert not (act["action"] == "redirect_or_retire_review" and cause == "demand_drop")


# ---------------------------------------------------------------------------
# Score and ordering
# ---------------------------------------------------------------------------

def test_decay_score_is_deterministic_and_bounded(result):
    again = cd.analyze_pages(FIXTURE, min_baseline_clicks=20, money_pages=["/pricing"],
                             brand_terms=["acme"], calibrate=False)
    for a, b in zip(result["pages"], again["pages"]):
        assert a["page"] == b["page"]
        assert a["decay_score"] == b["decay_score"]
        if a["decay_score"]:
            assert 0 <= a["decay_score"]["score"] <= 100


def test_decay_score_components_and_renormalization():
    delta = {"clicks_pct": -50.0, "position_change": 2.5, "ctr_pct": None, "impressions_pct": -10.0,
             "lost_clicks": 50}
    s = cd.decay_score(delta, ctr_ratio=None, cannibalized=None, lost_visibility=False)
    # click_loss 0.5 (w45) + position_loss 0.5 (w20), ctr/cannibal N/A -> renormalized over 65
    assert s["score"] == round(100 * (45 * 0.5 + 20 * 0.5) / 65)
    assert set(s["excluded_as_na"]) == {"ctr_shortfall", "cannibalization"}
    assert "/ 65" in s["expression"]


@pytest.mark.parametrize("clicks_pct", [-12.5, -20.5, -32.5, -60.5, -2.5, -87.5, -0.5])
def test_decay_expression_reproduces_score_on_ties(clicks_pct):
    s = cd.decay_score({"clicks_pct": clicks_pct, "position_change": None}, None, None, False)
    assert eval(s["expression"], {"__builtins__": {"round": round}}) == s["score"]


def test_decay_expression_always_matches_score():
    rng = random.Random(4321)
    for _ in range(3000):
        delta = {"clicks_pct": rng.choice([None, round(rng.uniform(-100, 50), rng.randint(0, 3)),
                                           rng.uniform(-120, 0), -12.5, -37.5]),
                 "position_change": rng.choice([None, round(rng.uniform(-3, 8), 1), rng.uniform(0, 6)])}
        ratio = rng.choice([None, rng.uniform(0, 1.5), round(rng.uniform(0, 1), 2), 0.875])
        s = cd.decay_score(delta, ratio, rng.choice([None, True, False]), rng.random() < 0.1)
        assert eval(s["expression"], {"__builtins__": {"round": round}}) == s["score"], s
        assert 0 <= s["score"] <= 100


# ---------------------------------------------------------------------------
# Row limits and truncated windows
# ---------------------------------------------------------------------------

def _truncating_gsc(limit_seen, victim_clicks=40):
    """Fake GSC: every page window returns exactly row_limit rows (the API's cut)."""
    def fake(site_url, start_date=None, end_date=None, dimensions=None, row_limit=1000, **kw):
        limit_seen.append(row_limit)
        if dimensions == ["page"]:
            rows = [{"keys": [f"https://ex.com/p{i}"], "clicks": 1000 - i, "impressions": 5000,
                     "ctr": 1.0, "position": 5.0} for i in range(row_limit)]
            if start_date == "2026-04-18":   # previous window: the victim made the cut
                rows[-1] = {"keys": ["https://ex.com/pricing"], "clicks": victim_clicks, "impressions": 900,
                            "ctr": 4.4, "position": 7.0}
            return {"rows": rows, "row_count": len(rows), "error": None}
        return {"rows": [], "row_count": 0, "error": None}
    return fake


def test_live_fetch_requests_100k_rows_and_flags_truncated_windows(monkeypatch):
    assert cd.GSC_ROW_LIMIT == 100_000                  # gsc_query pages through up to 100,000 rows
    seen = []
    windows = cd.compute_windows(date(2026, 10, 17), 90, 3)
    cd.fetch_live("sc-domain:ex.com", windows, lambda *a, **kw: (seen.append(kw["row_limit"]) or
                                                                 {"rows": [], "error": None}))
    assert set(seen) == {100_000}
    monkeypatch.setattr(cd, "GSC_ROW_LIMIT", 50)        # keep the fake small; same code path as 100,000
    data, _ = cd.fetch_live("sc-domain:ex.com", windows, _truncating_gsc(seen))
    assert data["truncated"] == {"current": True, "previous": True, "yoy": True, "query_page": False}
    assert data["row_limit"] == 50


def test_row_count_from_gsc_counts_toward_truncation():
    assert cd._is_truncated({"row_count": 100_000}, [], 100_000)
    assert cd._is_truncated({}, [{}] * 10, 10)
    assert not cd._is_truncated({"row_count": 9}, [{}] * 9, 10)


def test_page_cut_from_truncated_current_window_is_never_lost_or_retired(tmp_path, capsys, monkeypatch):
    seo_project.save_profile(seo_project.new_profile("ex.com", money_pages=["/pricing"],
                                                     gsc_property="sc-domain:ex.com"), str(tmp_path))
    monkeypatch.setattr(cd, "GSC_ROW_LIMIT", 40)
    rc = cd.main(["analyze", "--project", "ex.com", "--as-of", "2026-10-17", "--show", "all",
                  "--json", "--data-dir", str(tmp_path)], query_fn=_truncating_gsc([]))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    p = next(p for p in out["pages"] if p["page"] == "https://ex.com/pricing")
    assert p["money_page"] is True
    assert p["tier"] == "insufficient_data" and p["cause"] is None and p["decay_score"] is None
    assert (p["action"]["action"], p["action"]["rule"], p["action"]["urgent"]) == ("monitor", "R0c", False)
    assert p["delta"] is None and p["absent_from_truncated_window"] == "current"
    assert "row limit" in p["action"]["why"] and "40-row" in p["baseline_reason"]
    assert out["summary"]["truncated_windows"] == ["current", "previous", "yoy"]
    assert out["summary"]["absent_from_truncated_current"] == 1
    assert any("current window hit" in n and "R0c" in n for n in out["notes"])
    assert not any(q["action"]["action"] == "redirect_or_retire_review" for q in out["pages"])


def test_money_page_missing_from_untruncated_window_is_still_lost_visibility():
    data = {"current": [row("https://ex.com/a", 50, 1000, 5.0)],
            "previous": [row("https://ex.com/pricing", 100, 2000, 3.0), row("https://ex.com/a", 50, 1000, 5.0)],
            "yoy": [], "truncated": {"current": False}}
    p = page_of(cd.analyze_pages(data, money_pages=["/pricing"], calibrate=False), "https://ex.com/pricing")
    assert p["cause"]["primary"] == "lost_visibility" and p["action"]["urgent"] is True


def test_input_truncated_flag_is_honored(tmp_path):
    data = {"current": [row("https://ex.com/a", 50, 1000, 5.0)],
            "previous": [row("https://ex.com/gone", 100, 2000, 3.0), row("https://ex.com/a", 50, 1000, 5.0)],
            "yoy": [], "truncated": {"current": True}}
    path = tmp_path / "in.json"
    path.write_text(json.dumps(data))
    r = subprocess.run([PY, SCRIPT, "analyze", "--input", str(path), "--show", "all", "--json"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    p = next(p for p in out["pages"] if p["page"] == "https://ex.com/gone")
    assert p["tier"] == "insufficient_data" and p["action"]["rule"] == "R0c"
    assert any("export's row limit" in n for n in out["notes"])


def test_money_pages_sort_first_within_a_tier(result):
    critical = [p for p in result["pages"] if p["tier"] == "critical"]
    assert critical[0]["page"] == "https://ex.com/pricing"
    tiers = [cd.TIER_RANK[p["tier"]] for p in result["pages"]]
    assert tiers == sorted(tiers)


@pytest.mark.parametrize("page,entries,expected", [
    ("https://ex.com/pricing/", ["/pricing"], True),
    ("https://ex.com/pricing-old", ["/pricing"], False),
    ("https://ex.com/demo/book", ["/demo/*"], True),
    ("https://ex.com/contact", ["https://ex.com/contact/"], True),
])
def test_money_page_matching(page, entries, expected):
    assert cd.is_money_page(page, entries) is expected


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

def test_candidates_apply_impression_floor_band_and_signal(result):
    cands = cd.improvement_candidates(result, min_impressions=500, min_pos=4, max_pos=25)
    pages = [c["page"] for c in cands]
    assert "https://ex.com/aio" not in pages          # position 3.1 is outside 4-25
    assert "https://ex.com/tiny" not in pages         # below the impression floor
    cand = next(c for c in cands if c["page"] == "https://ex.com/candidate")
    assert "declining" in cand["reasons"]
    assert [q["query"] for q in cand["top_queries"]] == ["best crm", "crm tools"]
    assert cand["brief_focus"]


def test_candidates_put_money_pages_first(result):
    cands = cd.improvement_candidates(result, min_impressions=500)
    assert cands[0]["money_page"] is True


def test_candidate_requires_ctr_gap_or_decline():
    data = {"current": [row("/ok", 400, 5000, 5.0)], "previous": [row("/ok", 390, 5000, 5.0)]}
    res = cd.analyze_pages(data, calibrate=False)
    assert cd.improvement_candidates(res) == []


# ---------------------------------------------------------------------------
# Live path with an injected GSC function
# ---------------------------------------------------------------------------

def test_compute_windows_uses_lag_and_52_week_offset():
    w = cd.compute_windows(date(2026, 10, 17), days=90, lag=3)
    assert w["current"] == {"start": "2026-07-17", "end": "2026-10-14"}
    assert w["previous"]["end"] == "2026-07-16"
    assert w["yoy"] == {"start": "2025-07-18", "end": "2025-10-15"}
    assert date.fromisoformat(w["yoy"]["start"]).weekday() == date.fromisoformat(w["current"]["start"]).weekday()


def test_live_fetch_with_injected_query_fn_and_percent_ctr(tmp_path, capsys):
    calls = []

    def fake_gsc(site_url, start_date=None, end_date=None, dimensions=None, row_limit=1000, **kw):
        calls.append((start_date, end_date, tuple(dimensions)))
        if start_date.startswith("2025"):
            return {"rows": [], "error": "no data"}
        if dimensions == ["query", "page"]:
            return {"rows": [{"keys": ["crm", "https://ex.com/a"], "clicks": 5, "impressions": 100,
                              "ctr": 5.0, "position": 4.0}], "error": None}
        if start_date == "2026-07-17":
            return {"rows": [{"keys": ["https://ex.com/a"], "clicks": 30, "impressions": 1000,
                              "ctr": 3.0, "position": 4.0}], "error": None}
        return {"rows": [{"keys": ["https://ex.com/a"], "clicks": 100, "impressions": 1100,
                          "ctr": 9.09, "position": 4.1}], "error": None}

    rc = cd.main(["analyze", "--property", "sc-domain:ex.com", "--as-of", "2026-10-17", "--json",
                  "--data-dir", str(tmp_path)], query_fn=fake_gsc)
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(calls) == 4
    p = out["pages"][0]
    assert p["baseline"] == "previous"                      # YoY window errored -> fallback
    assert p["windows"]["current"]["ctr"] == pytest.approx(0.03)  # recomputed, not 3.0
    assert any("yoy window unavailable" in n for n in out["notes"])
    assert out["windows"]["current"]["end"] == "2026-10-14"
    assert out["data_sources"] and out["limitations"]


def test_live_current_window_error_is_fatal(tmp_path, capsys):
    def failing(*a, **k):
        return {"rows": [], "error": "Permission denied"}
    rc = cd.main(["analyze", "--property", "sc-domain:ex.com", "--json", "--data-dir", str(tmp_path)],
                 query_fn=failing)
    assert rc == 1
    assert "Permission denied" in json.loads(capsys.readouterr().out)["error"]


# ---------------------------------------------------------------------------
# CLI smoke tests (subprocess, offline --input)
# ---------------------------------------------------------------------------

@pytest.fixture
def input_file(tmp_path):
    path = tmp_path / "windows.json"
    path.write_text(json.dumps(FIXTURE), encoding="utf-8")
    # Create the profile through seo_project so the file name follows its naming scheme.
    profile = seo_project.new_profile("ex.com", brand_terms=["acme"], money_pages=["/pricing"])
    saved = seo_project.save_profile(profile, str(tmp_path / "data"))
    assert saved == seo_project.profile_path("ex.com", str(tmp_path / "data"))
    return path


def test_cli_analyze_json(input_file, tmp_path):
    r = subprocess.run([PY, SCRIPT, "analyze", "--input", str(input_file), "--project", "ex.com",
                        "--data-dir", str(tmp_path / "data"), "--json"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["project"] == "ex.com"
    assert all(p["tier"] in ("warning", "high", "critical") for p in out["pages"])
    assert out["pages"][0]["money_page"] is True
    assert out["data_sources"] and out["limitations"]
    assert "ctr_curve" in out


def test_cli_candidates_text(input_file, tmp_path):
    r = subprocess.run([PY, SCRIPT, "candidates", "--input", str(input_file), "--project", "ex.com",
                        "--data-dir", str(tmp_path / "data")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "improvement candidates" in r.stdout


def test_cli_missing_profile_errors(input_file, tmp_path):
    r = subprocess.run([PY, SCRIPT, "analyze", "--input", str(input_file), "--project", "nope.com",
                        "--data-dir", str(tmp_path / "empty"), "--json"], capture_output=True, text=True)
    assert r.returncode == 1
    assert "no project profile" in json.loads(r.stdout)["error"]
