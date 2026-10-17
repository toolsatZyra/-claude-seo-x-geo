"""
Tests for scripts/rank_tracker.py — tracked keywords, GSC/SERP ingest, the
report (lag-excluded windows, movers, bands, visibility, cannibalization,
URL swaps, per-tag stats) and the holdout experiment verdicts.

Offline only: GSC fetches are injected, storage lives under tmp_path.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import performance_tracker as pt  # noqa: E402
import rank_tracker as rt  # noqa: E402
import seo_metrics as m  # noqa: E402

PROJECT = "example.com"
AS_OF = date(2026, 10, 17)        # lag 3, window 7 -> current 10-08..10-14, previous 10-01..10-07
CUR_START, PREV_START = date(2026, 10, 8), date(2026, 10, 1)
SCRIPT = str(REPO_ROOT / "scripts" / "rank_tracker.py")


def days(start: date, n: int) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def gsc(kw: str, page: str, start: date, n: int, pos: float, imps: float, clicks: float) -> list[dict]:
    """gsc_query.py-shaped rows (ctr is a PERCENT there, like the real script)."""
    return [{"keys": [d, kw, page], "clicks": clicks, "impressions": imps,
             "ctr": round(100 * clicks / imps, 2) if imps else 0, "position": pos}
            for d in days(start, n)]


@pytest.fixture()
def conn(tmp_path):
    c = rt.open_store(str(tmp_path))
    yield c
    c.close()


def seed(conn) -> None:
    rt.add_keywords(conn, PROJECT, ["CRM Pricing", "best crm", "crm demo"], tags=["bofu"])
    rt.add_keywords(conn, PROJECT, ["crm guide", "crm api"], tags=["tofu"])
    rt.add_keywords(conn, PROJECT, ["acme crm"], tags=["brand"])
    rows = []
    # Gainer: 8 -> 4 with enough impressions; split across two pages now (cannibalization).
    rows += gsc("crm pricing", "https://example.com/pricing", PREV_START, 7, 8.0, 100, 3)
    rows += gsc("crm pricing", "https://example.com/pricing", CUR_START, 7, 4.0, 60, 5)
    rows += gsc("crm pricing", "https://example.com/plans", CUR_START, 7, 4.0, 40, 3)
    # Loser 5 -> 9 with a URL swap.
    rows += gsc("best crm", "https://example.com/best", PREV_START, 7, 5.0, 80, 4)
    rows += gsc("best crm", "https://example.com/blog/best", CUR_START, 7, 9.0, 80, 1)
    # Small improvement, not a mover.
    rows += gsc("crm demo", "https://example.com/demo", PREV_START, 7, 12.0, 30, 0)
    rows += gsc("crm demo", "https://example.com/demo", CUR_START, 7, 11.0, 30, 0)
    # Big move on a trickle of impressions: below the floor, so not a mover.
    rows += gsc("crm guide", "https://example.com/guide", PREV_START, 7, 15.0, 1, 0)
    rows += gsc("crm guide", "https://example.com/guide", CUR_START, 7, 10.0, 1, 0)
    # Brand query split across pages — must not be flagged as cannibalization.
    rows += gsc("acme crm", "https://example.com/", CUR_START, 7, 1.0, 50, 20)
    rows += gsc("acme crm", "https://example.com/about", CUR_START, 7, 2.0, 50, 15)
    # Inside the lag (10-15..10-17): must be ignored by the report.
    rows += gsc("crm pricing", "https://example.com/pricing", date(2026, 10, 15), 3, 1.0, 1000, 500)
    # Untracked query.
    rows += gsc("random query", "https://example.com/x", CUR_START, 7, 3.0, 10, 1)
    rt.ingest_gsc(conn, PROJECT, rows)


def report(conn, **kw):
    kw.setdefault("brand_terms", ["acme"])
    return rt.build_report(conn, PROJECT, as_of=AS_OF, **kw)


# ---------------------------------------------------------------------------
# Keyword management
# ---------------------------------------------------------------------------

def test_add_merges_tags_and_normalizes(conn):
    rt.add_keywords(conn, PROJECT, ["  CRM   Pricing "], tags=["bofu"])
    res = rt.add_keywords(conn, PROJECT, ["crm pricing"], tags=["treatment:faq"], target_url="/pricing")
    assert res == {"added": [], "updated": ["crm pricing"]}
    kws = rt.list_keywords(conn, PROJECT)
    assert kws[0]["keyword"] == "crm pricing"
    assert kws[0]["tags"] == ["bofu", "treatment:faq"]
    assert kws[0]["target_url"] == "/pricing"
    assert [k["keyword"] for k in rt.list_keywords(conn, PROJECT, tag="bofu")] == ["crm pricing"]
    assert rt.list_keywords(conn, PROJECT, tag="nope") == []


def test_remove_keeps_history_unless_purged(conn):
    seed(conn)
    res = rt.remove_keywords(conn, PROJECT, ["crm demo"])
    assert res == {"removed": ["crm demo"], "observations_purged": 0}
    assert rt.keyword_history(conn, PROJECT, "crm demo")
    res = rt.remove_keywords(conn, PROJECT, ["best crm"], purge=True)
    assert res["observations_purged"] == 14
    assert rt.keyword_history(conn, PROJECT, "best crm") == []


def test_keyword_file_csv_and_plain(tmp_path):
    csv_path = tmp_path / "kw.csv"
    csv_path.write_text("keyword,tags,target_url\ncrm pricing,bofu;control:x,/pricing\nbest crm,,\n")
    rows = rt.read_keyword_file(str(csv_path))
    assert rows[0] == {"keyword": "crm pricing", "tags": ["bofu", "control:x"], "target_url": "/pricing"}
    assert rows[1]["tags"] == [] and rows[1]["target_url"] is None
    plain = tmp_path / "kw.txt"
    plain.write_text("# comment\ncrm pricing\nbest crm\n")
    assert [r["keyword"] for r in rt.read_keyword_file(str(plain))] == ["crm pricing", "best crm"]


# ---------------------------------------------------------------------------
# GSC ingest
# ---------------------------------------------------------------------------

def test_keyword_filter_chunks_escape_and_respect_limit():
    chunks = rt.keyword_filter_chunks(["c++ tutorial", "what is crm?", "a.b"], max_len=4000)
    assert chunks == [r"^(a\.b|c\+\+ tutorial|what is crm\?)$"]
    many = [f"keyword number {i}" for i in range(400)]
    chunks = rt.keyword_filter_chunks(many, max_len=200)
    assert len(chunks) > 1 and all(len(c) <= 200 for c in chunks)
    covered = set()
    for c in chunks:
        covered |= set(c[2:-2].split("|"))
    assert covered == set(many)
    for c in chunks:  # each chunk is a valid regex that fully matches its members only
        assert re.fullmatch(c, "keyword number 1") or "keyword number 1" not in c[2:-2].split("|")


def test_fetch_gsc_rows_one_call_per_chunk_with_date_query_page():
    calls = []

    def fake(prop, start, end, dims, filters):
        calls.append((prop, start, end, dims, filters))
        return {"rows": [{"keys": ["2026-10-01", "x", "/p"], "clicks": 1, "impressions": 2,
                          "position": 3}], "row_count": 1, "error": None}

    res = rt.fetch_gsc_rows("sc-domain:example.com", "2026-09-01", "2026-09-30",
                            ["crm pricing", "best crm"], fetch=fake)
    assert res["calls"] == 1 and len(res["rows"]) == 1 and not res["truncated"]
    prop, start, end, dims, filters = calls[0]
    assert dims == ["date", "query", "page"]
    assert filters == [{"dimension": "query", "operator": "includingRegex",
                        "expression": "^(best crm|crm pricing)$"}]
    rt.fetch_gsc_rows("p", "a", "b", None, fetch=fake)
    assert calls[-1][4] is None  # --all-queries: no filter


def test_fetch_gsc_rows_surfaces_errors_and_truncation():
    def failing(*_a):
        return {"rows": [], "error": "Permission denied"}

    with pytest.raises(RuntimeError, match="Permission denied"):
        rt.fetch_gsc_rows("p", "a", "b", ["x"], fetch=failing)

    def capped(*_a):
        return {"rows": [], "row_count": rt.GSC_ROW_CAP, "error": None}

    assert rt.fetch_gsc_rows("p", "a", "b", None, fetch=capped)["truncated"] is True


def test_ingest_keeps_tracked_only_recomputes_ctr_and_is_idempotent(conn):
    rt.add_keywords(conn, PROJECT, ["crm pricing"])
    rows = gsc("crm pricing", "https://example.com/pricing", PREV_START, 2, 5.0, 80, 10)
    rows += gsc("other", "https://example.com/o", PREV_START, 2, 5.0, 80, 10)
    first = rt.ingest_gsc(conn, PROJECT, rows)
    assert first["rows_stored"] == 2 and first["untracked_skipped"] == 2
    stored = conn.execute("SELECT ctr, country, device, source FROM obs").fetchall()
    assert {tuple(r) for r in stored} == {(0.125, "all", "all", "gsc")}  # fraction, not 12.5
    rows[0]["clicks"] = 20
    rt.ingest_gsc(conn, PROJECT, rows)
    assert conn.execute("SELECT COUNT(*) FROM obs").fetchone()[0] == 2
    assert conn.execute("SELECT MAX(clicks) FROM obs").fetchone()[0] == 20
    all_q = rt.ingest_gsc(conn, PROJECT, rows, all_queries=True)
    assert all_q["untracked_skipped"] == 0
    assert conn.execute("SELECT COUNT(*) FROM obs").fetchone()[0] == 4


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def test_windows_exclude_lag(conn):
    seed(conn)
    rep = report(conn)
    assert rep["windows"]["current"] == {"start": "2026-10-08", "end": "2026-10-14"}
    assert rep["windows"]["previous"] == {"start": "2026-10-01", "end": "2026-10-07"}
    pricing = next(k for k in rep["keywords"] if k["keyword"] == "crm pricing")
    # The 10-15..10-17 rows (pos 1, 1000 imps) would dominate if the lag were ignored.
    assert pricing["current"]["position"] == 4.0
    assert pricing["current"]["impressions"] == 700


def test_movers_require_delta_and_impression_floor(conn):
    seed(conn)
    rep = report(conn)
    assert [g["keyword"] for g in rep["movers"]["gainers"]] == ["crm pricing"]
    assert rep["movers"]["gainers"][0]["delta"] == 4.0
    assert [lo["keyword"] for lo in rep["movers"]["losers"]] == ["best crm"]
    guide = next(k for k in rep["keywords"] if k["keyword"] == "crm guide")
    assert guide["delta"] == 5.0 and guide["mover"] is False   # below 10 impressions
    demo = next(k for k in rep["keywords"] if k["keyword"] == "crm demo")
    assert demo["status"] == "improved" and demo["mover"] is False
    assert rep["summary"]["no_data"] == 1                       # crm api
    assert rep["summary"]["entered"] == 1                       # acme crm (current only)
    lowered = report(conn, min_impressions=1)
    assert "crm guide" in [g["keyword"] for g in lowered["movers"]["gainers"]]


def test_bands_visibility_and_kpis(conn):
    seed(conn)
    rep = report(conn)
    pos = {k["keyword"]: k["current"]["position"] for k in rep["keywords"]}
    assert pos["acme crm"] == 1.5 and pos["crm api"] is None
    assert rep["summary"]["bands"] == {"top3": 1, "page1": 3, "striking": 1, "deep": 0, "far": 0,
                                       "unranked": 1}
    expected = round(100 * sum(m.expected_ctr(p) / m.expected_ctr(1) if p else 0
                               for p in pos.values()) / len(pos), 1)
    assert rep["summary"]["visibility"]["current"] == expected
    assert rep["kpis"] == {"rank.tracked": 6, "rank.top3": 1, "rank.top10": 4,
                           "rank.striking": 4, "rank.visibility": expected}
    assert "average" in rep["notes"]["position"] and "not a rank" in rep["notes"]["position"]
    pt.build_envelope(PROJECT, "rank_tracker.py", rep["kpis"])  # KPIs satisfy the envelope contract


def test_no_observations_yield_null_kpis_not_zeros(conn):
    rt.add_keywords(conn, PROJECT, ["crm pricing"])
    rep = report(conn)
    assert rep["kpis"] == {"rank.tracked": 1, "rank.top3": None, "rank.top10": None,
                           "rank.striking": None, "rank.visibility": None}
    assert rep["summary"]["observations"] == {"current": 0, "previous": 0}
    assert any("No gsc observations" in lim for lim in rep["limitations"])
    check = pt.validate_envelope({"kpi_envelope": 1, "project": PROJECT, "date": "2026-10-17",
                                  "source": "rank_tracker.py", "metrics": rep["kpis"]})
    assert check["ok"] and len(check["skipped_null"]) == 4


def test_url_swap_target_mismatch_and_cannibalization(conn):
    seed(conn)
    rt.add_keywords(conn, PROJECT, ["crm pricing"], target_url="https://www.example.com/pricing/")
    rt.add_keywords(conn, PROJECT, ["best crm"], target_url="/best")
    rep = report(conn)
    assert rep["url_swaps"] == [{"keyword": "best crm", "from": "https://example.com/best",
                                 "to": "https://example.com/blog/best", "delta": -4.0}]
    assert rep["target_mismatches"] == [{"keyword": "best crm", "target_url": "/best",
                                         "ranking_url": "https://example.com/blog/best"}]
    assert [c["query"] for c in rep["cannibalization"]] == ["crm pricing"]
    pages = [p["page"] for p in rep["cannibalization"][0]["pages"]]
    assert pages == ["https://example.com/pricing", "https://example.com/plans"]
    unbranded = rt.build_report(conn, PROJECT, as_of=AS_OF, brand_terms=[])
    assert "acme crm" in [c["query"] for c in unbranded["cannibalization"]]


def test_per_tag_stats_and_tag_filter(conn):
    seed(conn)
    rep = report(conn)
    bofu = rep["tags"]["bofu"]
    assert bofu["keywords"] == 3 and bofu["measured"] == 3
    assert (bofu["improved"], bofu["declined"]) == (2, 1)
    assert bofu["median_delta"] == 1.0
    assert bofu["sign_test_p"] == m.sign_test_p(2, 1)
    only = report(conn, tag="tofu")
    assert only["kpis"]["rank.tracked"] == 2
    assert any("tag 'tofu'" in lim for lim in only["limitations"])


def test_serp_import_csv_median_and_domain_filter(conn, tmp_path):
    rt.add_keywords(conn, PROJECT, ["crm pricing"])
    path = tmp_path / "serp.csv"
    lines = ["Keyword,Position,URL,Date"]
    for i, pos in enumerate([3, 5, 4, "", 6, 4, 4]):   # one day not found
        lines.append(f"crm pricing,{pos},https://example.com/pricing,{days(CUR_START, 7)[i]}")
    lines.append(f"crm pricing,1,https://rival.com/pricing,{CUR_START.isoformat()}")
    path.write_text("\n".join(lines) + "\n")
    res = rt.import_serp(conn, PROJECT, str(path), "ahrefs", "2026-10-17")
    assert res["rows_stored"] == 7 and res["skipped_other_domain"] == 1
    rep = report(conn, source="ahrefs")
    k = rep["keywords"][0]
    assert k["current"]["position"] == 4.0          # median with unranked as worst
    assert k["current"]["days_ranked"] == 6
    assert "median" in rep["notes"]["position"]
    gsc_rep = report(conn)                          # SERP rows never leak into GSC reports
    assert gsc_rep["keywords"][0]["current"]["position"] is None


def test_median_with_unranked_majority_is_unranked():
    assert rt._median_with_unranked([3, None, None]) is None
    assert rt._median_with_unranked([3, 5, None]) == 5
    assert rt._median_with_unranked([2, 4]) == 3
    assert rt._median_with_unranked([2, None]) is None


def test_dataforseo_response_flattened_to_best_own_result(conn, tmp_path):
    payload = {"tasks": [{"status_code": 20000, "result": [{
        "keyword": "crm pricing", "datetime": "2026-10-10 08:00:00 +00:00",
        "items": [
            {"type": "organic", "rank_group": 1, "url": "https://rival.com/"},
            {"type": "paid", "rank_group": 1, "url": "https://example.com/ad"},
            {"type": "organic", "rank_group": 7, "url": "https://example.com/plans"},
            {"type": "organic", "rank_group": 4, "url": "https://www.example.com/pricing"},
        ]}, {"keyword": "best crm", "datetime": "2026-10-10 08:00:00 +00:00", "items": [
            {"type": "organic", "rank_group": 1, "url": "https://rival.com/"}]}]}]}
    path = tmp_path / "d4s.json"
    path.write_text(json.dumps(payload))
    rt.import_serp(conn, PROJECT, str(path), "dataforseo", "2026-10-17")
    hist = rt.keyword_history(conn, PROJECT, "crm pricing")
    assert hist == [{"date": "2026-10-10", "source": "dataforseo", "position": 4.0, "clicks": None,
                     "impressions": None, "page": "https://www.example.com/pricing", "pages": 1}]
    assert rt.keyword_history(conn, PROJECT, "best crm")[0]["position"] is None


def test_import_rejects_unknown_source(conn, tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("keyword,position\na,1\n")
    with pytest.raises(ValueError):
        rt.import_serp(conn, PROJECT, str(p), "gsc", "2026-10-17")


# ---------------------------------------------------------------------------
# Holdout experiment
# ---------------------------------------------------------------------------

START = date(2026, 9, 1)


def seed_experiment(conn, treat_gain: float, control_gain: float, n_treat: int = 8,
                    n_control: int = 8) -> None:
    rows = []
    for i in range(n_treat):
        kw = f"treated {i}"
        rt.add_keywords(conn, PROJECT, [kw], tags=["treatment:faq"])
        rows += gsc(kw, f"https://example.com/t{i}", START - timedelta(days=28), 28, 10.0 + i * 0.1, 20, 1)
        rows += gsc(kw, f"https://example.com/t{i}", START, 28, 10.0 + i * 0.1 - treat_gain - i * 0.05, 20, 1)
    for i in range(n_control):
        kw = f"control {i}"
        rt.add_keywords(conn, PROJECT, [kw], tags=["control:faq"])
        rows += gsc(kw, f"https://example.com/c{i}", START - timedelta(days=28), 28, 10.0 + i * 0.1, 20, 1)
        rows += gsc(kw, f"https://example.com/c{i}", START, 28, 10.0 + i * 0.1 - control_gain, 20, 1)
    rt.ingest_gsc(conn, PROJECT, rows)


def run(conn, as_of=date(2026, 10, 15), **kw):
    return rt.run_experiment(conn, PROJECT, "treatment:faq", "control:faq", START, 28, as_of, **kw)


def test_experiment_promote_with_control_adjustment(conn):
    seed_experiment(conn, treat_gain=3.0, control_gain=0.5)
    res = run(conn)
    assert res["design"]["horizon_complete"] is True
    assert res["design"]["pre_window"] == {"start": "2026-08-04", "end": "2026-08-31"}
    assert res["design"]["post_window"] == {"start": "2026-09-01", "end": "2026-09-28"}
    assert res["verdict"] == "Promote", res["reason"]
    assert res["treatment"]["adjusted"]["median_delta"] >= 1.0


def test_experiment_sitewide_lift_is_not_promoted(conn):
    seed_experiment(conn, treat_gain=3.0, control_gain=3.0)
    res = run(conn)
    assert res["verdict"] == "Unproven"
    assert any("control group itself moved" in c for c in res["caveats"])


def test_experiment_rollback(conn):
    seed_experiment(conn, treat_gain=-3.0, control_gain=0.0)
    assert run(conn)["verdict"] == "Rollback"


def test_experiment_keep_testing_before_horizon(conn):
    seed_experiment(conn, treat_gain=3.0, control_gain=0.0)
    res = run(conn, as_of=date(2026, 9, 20))
    assert res["verdict"] == "Keep-testing"
    assert res["design"]["post_window"]["end"] == "2026-09-17"


def test_experiment_unproven_without_control_or_with_small_n(conn):
    seed_experiment(conn, treat_gain=3.0, control_gain=0.0, n_treat=5, n_control=4)
    assert "fewer than 6" in run(conn)["reason"]
    res = rt.run_experiment(conn, PROJECT, "treatment:faq", "control:none", START, 28,
                            date(2026, 10, 15))
    assert res["verdict"] == "Unproven" and "control" in res["reason"]


def test_holdout_verdict_rule_table():
    big = {"adjusted": {"measured": 10, "median_delta": 2.0, "sign_test_p": 0.01}}
    ctl = {"measured": 10}
    assert rt.holdout_verdict(big, ctl, False)["verdict"] == "Keep-testing"
    assert rt.holdout_verdict(big, ctl, True)["verdict"] == "Promote"
    weak = {"adjusted": {"measured": 10, "median_delta": 2.0, "sign_test_p": 0.2}}
    assert rt.holdout_verdict(weak, ctl, True)["verdict"] == "Unproven"
    small = {"adjusted": {"measured": 10, "median_delta": 0.5, "sign_test_p": 0.01}}
    assert rt.holdout_verdict(small, ctl, True)["verdict"] == "Unproven"
    assert rt.holdout_verdict(big, {"measured": 0}, True)["verdict"] == "Unproven"


# ---------------------------------------------------------------------------
# CLI smoke tests (subprocess, --input fixtures, tmp data dir)
# ---------------------------------------------------------------------------

def cli(tmp_path, *args):
    return subprocess.run([sys.executable, SCRIPT, *args, "--project", PROJECT,
                           "--data-dir", str(tmp_path)], capture_output=True, text=True)


def test_cli_end_to_end(tmp_path):
    rows = (gsc("crm pricing", "https://example.com/pricing", PREV_START, 7, 8.0, 100, 3)
            + gsc("crm pricing", "https://example.com/pricing", CUR_START, 7, 4.0, 100, 8))
    inp = tmp_path / "gsc.json"
    inp.write_text(json.dumps({"rows": rows}))

    r = cli(tmp_path, "add", "crm pricing", "best crm", "--tag", "bofu")
    assert r.returncode == 0, r.stderr
    r = cli(tmp_path, "ingest-gsc", "--input", str(inp), "--json")
    assert r.returncode == 0, r.stderr
    ing = json.loads(r.stdout)
    assert ing["rows_stored"] == 14 and ing["tracked_without_data"] == ["best crm"]

    kpi_path = tmp_path / "kpis.json"
    r = cli(tmp_path, "report", "--as-of", "2026-10-17", "--emit-kpis", str(kpi_path), "--json")
    assert r.returncode == 0, r.stderr
    rep = json.loads(r.stdout)
    assert rep["movers"]["gainers"][0]["keyword"] == "crm pricing"
    env = json.loads(kpi_path.read_text())
    check = pt.validate_envelope(env)
    assert check["ok"], check["errors"]
    assert env["source"] == "rank_tracker.py" and env["date"] == "2026-10-17"
    assert env["metrics"]["rank.tracked"] == 2 and env["metrics"]["rank.top10"] == 1

    r = cli(tmp_path, "report", "--as-of", "2026-10-17")
    assert r.returncode == 0 and "not a rank" in r.stdout

    r = cli(tmp_path, "history", "crm pricing", "--json")
    hist = json.loads(r.stdout)
    assert len(hist["rows"]) == 14 and hist["rows"][0]["position"] == 8.0

    r = cli(tmp_path, "list", "--json")
    assert [k["keyword"] for k in json.loads(r.stdout)["keywords"]] == ["best crm", "crm pricing"]


def test_cli_errors_are_clean(tmp_path):
    r = cli(tmp_path, "ingest-gsc")            # no profile, no --property, no keywords
    assert r.returncode == 1 and "Error:" in r.stderr and "Traceback" not in r.stderr
    r = cli(tmp_path, "report", "--as-of", "17-10-2026")
    assert r.returncode == 2                   # argparse rejects the date
    r = cli(tmp_path, "report", "--window", "0")
    assert r.returncode == 2 and "positive integer" in r.stderr
