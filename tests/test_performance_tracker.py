"""
Tests for scripts/performance_tracker.py — the KPI envelope contract
(validation, ingest, null handling), snapshots with per-source failure
isolation, direction-aware reports, the --fail-on-drop gate and the export
contract consumed by geo-compare.

Offline only: GSC/GA4 are injected or read from --input files; storage under tmp_path.
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
import seo_project as proj  # noqa: E402

PROJECT = "example.com"
SCRIPT = str(REPO_ROOT / "scripts" / "performance_tracker.py")


def env(**over):
    base = {"kpi_envelope": 1, "project": PROJECT, "date": "2026-10-17",
            "source": "ai_visibility.py", "metrics": {"ai.mention_rate": 0.32}, "meta": {"n": 60}}
    base.update(over)
    return base


@pytest.fixture()
def conn(tmp_path):
    c = pt.open_store(str(tmp_path))
    yield c
    c.close()


def store(conn, day, metrics, source="test.py"):
    check = pt.validate_envelope(env(date=day, metrics=metrics, source=source))
    assert check["ok"], check["errors"]
    pt.store_envelope(conn, check["envelope"])


# ---------------------------------------------------------------------------
# Envelope contract
# ---------------------------------------------------------------------------

def test_valid_envelope_is_cleaned():
    res = pt.validate_envelope(env(project="https://www.Example.com/x"))
    assert res["ok"] and res["errors"] == []
    assert res["envelope"]["project"] == "example.com"
    assert res["envelope"]["metrics"] == {"ai.mention_rate": 0.32}


@pytest.mark.parametrize("bad,needle", [
    ({"kpi_envelope": 2}, "kpi_envelope"),
    ({"kpi_envelope": "1"}, "kpi_envelope"),
    ({"kpi_envelope": True}, "kpi_envelope"),
    ({"project": ""}, "project"),
    ({"project": None}, "project"),
    ({"date": "17/10/2026"}, "date"),
    ({"date": "2026-02-30"}, "date"),
    ({"metrics": {}}, "metrics"),
    ({"metrics": {"ai.mention_rate": "0.32"}}, "number"),
    ({"metrics": {"ai.mention_rate": True}}, "number"),
    ({"metrics": {"ai.mention_rate": float("nan")}}, "finite"),
    ({"metrics": {"MentionRate": 0.3}}, "invalid metric name"),
    ({"metrics": {"ai.mention.rate": 0.3}}, "invalid metric name"),
    ({"metrics": {"gsc.ctr": 12.5}}, "fraction"),
    ({"metrics": {"aeo.score": 140}}, "0-100"),
    ({"metrics": {"gsc.clicks": -1}}, ">= 0"),
    ({"metrics": {"gsc.position": 0}}, "position"),
    ({"meta": "n=60"}, "meta"),
])
def test_invalid_envelopes_rejected(bad, needle):
    res = pt.validate_envelope(env(**bad))
    assert not res["ok"] and res["envelope"] is None
    assert any(needle in e for e in res["errors"]), res["errors"]


def test_one_bad_metric_rejects_whole_envelope():
    res = pt.validate_envelope(env(metrics={"ai.mention_rate": 0.3, "ai.sov": "high"}))
    assert not res["ok"]


def test_null_metrics_are_skipped_not_zero(conn):
    res = pt.validate_envelope(env(metrics={"ai.mention_rate": None, "ai.n": 60}))
    assert res["ok"] and res["skipped_null"] == ["ai.mention_rate"]
    pt.store_envelope(conn, res["envelope"])
    assert pt.metric_rows(conn, PROJECT, "ai.mention_rate") == []
    assert pt.metric_rows(conn, PROJECT, "ai.n")[0]["value"] == 60


def test_custom_names_allowed_and_reserved_prefix_typos_warned():
    res = pt.validate_envelope(env(metrics={"crm.mql": 12, "ai.mention_rat": 0.3}))
    assert res["ok"]
    assert any("ai.mention_rat" in w for w in res["warnings"])
    assert not any("crm.mql" in w for w in res["warnings"])


def test_write_envelope_validates_and_round_trips(tmp_path):
    path = tmp_path / "out" / "k.json"
    written = pt.write_envelope(str(path), "www.example.com", "aeo_score.py",
                                {"aeo.score": 61.5, "aeo.schema": None}, "2026-10-17", {"x": 1})
    on_disk = json.loads(path.read_text())
    assert on_disk == written and on_disk["project"] == "example.com"
    assert on_disk["metrics"]["aeo.schema"] is None
    with pytest.raises(pt.EnvelopeError):
        pt.write_envelope(str(path), PROJECT, "x.py", {"gsc.ctr": 3.2})


def test_ingest_files_stores_valid_rejects_invalid_and_is_idempotent(conn, tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(env(metrics={"ai.mention_rate": 0.32, "ai.sov": None})))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(env(kpi_envelope=2)))
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    res = pt.ingest_files(conn, [str(good), str(bad), str(broken)])
    assert res["stored"] == 1 and res["rejected"] == 2
    pt.ingest_files(conn, [str(good)])
    assert len(pt.metric_rows(conn, PROJECT)) == 1


# ---------------------------------------------------------------------------
# Report + gate
# ---------------------------------------------------------------------------

def seed_series(conn):
    store(conn, "2026-07-01", {"gsc.clicks": 1000, "gsc.position": 12.0, "rank.tracked": 40})
    store(conn, "2026-09-19", {"gsc.clicks": 1200, "gsc.position": 11.0, "rank.tracked": 50})
    store(conn, "2026-10-10", {"gsc.clicks": 1250, "gsc.position": 10.0, "rank.tracked": 50})
    store(conn, "2026-10-17", {"gsc.clicks": 900, "gsc.position": 9.0, "rank.tracked": 60,
                               "leads.total": 12})


def by_metric(rep):
    return {r["metric"]: r for r in rep["metrics"]}


def test_report_previous_is_direction_aware(conn):
    seed_series(conn)
    rep = by_metric(pt.build_kpi_report(conn, PROJECT))
    clicks, pos, tracked = rep["gsc.clicks"], rep["gsc.position"], rep["rank.tracked"]
    assert clicks["comparison"]["date"] == "2026-10-10"
    assert clicks["pct_change"] == -28.0 and clicks["assessment"] == "worse"
    assert pos["direction"] == "down" and pos["assessment"] == "better" and pos["lower_is_better"]
    assert tracked["assessment"] == "neutral"
    assert rep["leads.total"]["comparison"] is None and rep["leads.total"]["assessment"] == "n/a"


def test_report_compare_windows_and_dates(conn):
    seed_series(conn)
    rep = by_metric(pt.build_kpi_report(conn, PROJECT, compare="28d"))
    assert rep["gsc.clicks"]["comparison"]["date"] == "2026-09-19"
    rep = by_metric(pt.build_kpi_report(conn, PROJECT, compare="90d"))
    assert rep["gsc.clicks"]["comparison"]["date"] == "2026-07-01"
    rep = by_metric(pt.build_kpi_report(conn, PROJECT, compare="2026-09-30"))
    assert rep["gsc.clicks"]["comparison"]["date"] == "2026-09-19"
    rep = by_metric(pt.build_kpi_report(conn, PROJECT, compare="365d"))
    assert rep["gsc.clicks"]["comparison"] is None
    with pytest.raises(ValueError):
        pt.build_kpi_report(conn, PROJECT, compare="last-month")


def test_report_prefix_filter(conn):
    seed_series(conn)
    rep = pt.build_kpi_report(conn, PROJECT, prefixes=["gsc"])
    assert {r["metric"] for r in rep["metrics"]} == {"gsc.clicks", "gsc.position"}
    rep = pt.build_kpi_report(conn, PROJECT, prefixes=["leads.total"])
    assert [r["metric"] for r in rep["metrics"]] == ["leads.total"]


def test_fail_on_drop_gate(conn):
    seed_series(conn)
    rep = pt.build_kpi_report(conn, PROJECT, fail_on_drop=20)
    gate = rep["gate"]
    assert gate["status"] == "FAIL"
    assert [f["metric"] for f in gate["failures"]] == ["gsc.clicks"]
    assert "rank.tracked" not in gate["watched"]       # neutral metrics never gate
    assert "leads.total" in gate["unevaluable"]
    rep = pt.build_kpi_report(conn, PROJECT, fail_on_drop=30)
    assert rep["gate"]["status"] == "PASS"
    rep = pt.build_kpi_report(conn, PROJECT, fail_on_drop=5, watch=["gsc.position", "ai.sov"])
    assert rep["gate"]["status"] == "PASS" and rep["gate"]["missing"] == ["ai.sov"]


def test_position_worsening_trips_gate(conn):
    store(conn, "2026-10-10", {"gsc.position": 8.0})
    store(conn, "2026-10-17", {"gsc.position": 12.0})
    rep = pt.build_kpi_report(conn, PROJECT, fail_on_drop=20, watch=["gsc.position"])
    assert rep["gate"]["failures"][0]["worsened_pct"] == 50.0


def test_export_contract(conn):
    seed_series(conn)
    out = pt.export_snapshots(conn, PROJECT)
    assert set(out) == {"project", "generated_at", "snapshots"}
    dates = [s["date"] for s in out["snapshots"]]
    assert dates == sorted(dates) and dates[0] == "2026-07-01"
    assert out["snapshots"][-1]["metrics"]["gsc.clicks"] == {"value": 900.0, "source": "test.py"}


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def make_profile(tmp_path, **fields):
    p = proj.new_profile(PROJECT, brand_terms=["acme", "acme.io crm"],
                         gsc_property="sc-domain:example.com", ga4_property="123", **fields)
    proj.save_profile(p, str(tmp_path))


GA4_CSV = """# GA4 export
Session source,Session medium,Session default channel group,Landing page,Sessions,Key events,Session key event rate
google,organic,Organic Search,/,800,40,4%
chatgpt.com,referral,Referral,/pricing,50,5,8%
(direct),(none),Direct,/,300,9,3%
"""


def test_brand_regex_escapes_re2_metacharacters():
    assert pt.brand_regex(["Acme", "acme.io crm", "a+b", ""]) == r"(?i)(acme\.io crm|acme|a\+b)"
    assert pt.brand_regex([]) == ""


def test_snapshot_collects_all_sources(tmp_path):
    make_profile(tmp_path, conversion_events=["generate_lead"])
    calls = []

    def fake_gsc(prop, start, end, filters):
        calls.append((prop, start, end, filters))
        if filters:
            return {"clicks": 600, "impressions": 30000, "ctr": 2.0, "position": 14.2}
        return {"clicks": 1000, "impressions": 40000, "ctr": 2.5, "position": 12.3}

    ga4 = tmp_path / "ga4.csv"
    ga4.write_text(GA4_CSV)
    conn = rt.open_store(str(tmp_path))
    rt.add_keywords(conn, PROJECT, ["crm pricing"])
    rt.ingest_gsc(conn, PROJECT, [{"keys": [d, "crm pricing", "https://example.com/p"],
                                   "clicks": 2, "impressions": 50, "position": 3.0}
                                  for d in ("2026-10-09", "2026-10-10")])
    conn.close()

    res = pt.take_snapshot(PROJECT, date(2026, 10, 17), 28, str(tmp_path),
                           ga4_input=str(ga4), gsc_fetch=fake_gsc)
    assert res["errors"] == {} and res["skipped"] == {}
    rec = {k: v["value"] for k, v in res["recorded"].items()}
    assert rec["gsc.clicks"] == 1000 and rec["gsc.ctr"] == 0.025          # fraction, not 2.5
    assert rec["gsc.clicks_nonbrand"] == 600 and rec["gsc.position"] == 12.3
    assert rec["ga4.organic_sessions"] == 800 and rec["ga4.ai_sessions"] == 50
    assert rec["ga4.ai_cvr"] == 0.08
    assert rec["rank.tracked"] == 1 and rec["rank.top3"] == 1
    prop, start, end, flt = calls[1]
    assert (start, end) == ("2026-09-17", "2026-10-14")                  # 28 days ending lag-3
    assert flt[0]["operator"] == "excludingRegex"
    assert flt[0]["expression"] == r"(?i)(acme\.io crm|example|acme)"
    assert any("anonymized" in lim for lim in res["limitations"])
    conn = pt.open_store(str(tmp_path))
    assert len(pt.metric_rows(conn, PROJECT)) == len(res["recorded"])
    conn.close()


def test_snapshot_isolates_failing_source(tmp_path):
    make_profile(tmp_path)

    def broken_gsc(*_a):
        raise RuntimeError("quota exceeded")

    ga4 = tmp_path / "ga4.csv"
    ga4.write_text(GA4_CSV)
    res = pt.take_snapshot(PROJECT, date(2026, 10, 17), 28, str(tmp_path), ga4_input=str(ga4),
                           gsc_fetch=broken_gsc)
    assert "quota exceeded" in res["errors"]["gsc"]
    assert "no tracked keywords" in res["skipped"]["rank"]
    assert "ga4.organic_sessions" in res["recorded"]
    assert not any(k.startswith("gsc.") for k in res["recorded"])


def test_snapshot_skips_rank_without_observations(tmp_path):
    conn = rt.open_store(str(tmp_path))
    rt.add_keywords(conn, PROJECT, ["crm pricing"])
    conn.close()
    res = pt.take_snapshot(PROJECT, date(2026, 10, 17), 28, str(tmp_path), skip=["gsc", "ga4"])
    assert "no rank observations" in res["skipped"]["rank"]
    assert res["recorded"] == {}


def test_snapshot_without_profile_skips_with_reason(tmp_path):
    res = pt.take_snapshot(PROJECT, date(2026, 10, 17), 28, str(tmp_path), skip=["rank"])
    assert "no GSC property" in res["skipped"]["gsc"]
    assert "no GA4 property" in res["skipped"]["ga4"]
    assert res["recorded"] == {}


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

def cli(tmp_path, *args):
    return subprocess.run([sys.executable, SCRIPT, *args, "--data-dir", str(tmp_path)],
                          capture_output=True, text=True)


def test_cli_ingest_record_report_export(tmp_path):
    e1 = tmp_path / "e1.json"
    e1.write_text(json.dumps(env(date="2026-10-10", metrics={"ai.mention_rate": 0.40,
                                                              "ai.n": 60})))
    e2 = tmp_path / "e2.json"
    e2.write_text(json.dumps(env(date="2026-10-17", metrics={"ai.mention_rate": 0.30,
                                                              "ai.n": 60, "ai.sov": None})))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(env(metrics={"ai.mention_rate": 32})))

    r = cli(tmp_path, "ingest", str(e1), str(e2), "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["stored"] == 4
    r = cli(tmp_path, "ingest", str(bad))
    assert r.returncode == 1 and "REJECTED" in r.stdout

    r = cli(tmp_path, "record", "--project", PROJECT, "--metric", "leads.total", "--value", "42",
            "--date", "2026-10-17", "--note", "CRM export")
    assert r.returncode == 0, r.stderr
    r = cli(tmp_path, "record", "--project", PROJECT, "--metric", "ai.sov", "--value", "45")
    assert r.returncode == 1 and "fraction" in r.stderr

    r = cli(tmp_path, "report", "--project", PROJECT, "--json")
    assert r.returncode == 0, r.stderr
    rows = {m["metric"]: m for m in json.loads(r.stdout)["metrics"]}
    assert rows["ai.mention_rate"]["pct_change"] == -25.0

    r = cli(tmp_path, "report", "--project", PROJECT, "--fail-on-drop", "20", "--watch",
            "ai.mention_rate")
    assert r.returncode == 3 and "FAIL" in r.stdout
    r = cli(tmp_path, "report", "--project", PROJECT, "--fail-on-drop", "30", "--watch",
            "ai.mention_rate")
    assert r.returncode == 0 and "PASS" in r.stdout

    r = cli(tmp_path, "export", "--project", PROJECT, "--json")
    out = json.loads(r.stdout)
    assert [s["date"] for s in out["snapshots"]] == ["2026-10-10", "2026-10-17"]
    assert out["snapshots"][1]["metrics"]["leads.total"] == {"value": 42.0, "source": "manual"}
    assert "ai.sov" not in out["snapshots"][1]["metrics"]
    r = cli(tmp_path, "export", PROJECT, "--json")       # positional form from the spec
    assert json.loads(r.stdout)["snapshots"] == out["snapshots"]

    r = cli(tmp_path, "history", "--project", PROJECT, "--metric", "ai.mention_rate", "--json")
    assert [x["value"] for x in json.loads(r.stdout)["rows"]] == [0.4, 0.3]


def test_cli_snapshot_offline_inputs(tmp_path):
    gsc_in = tmp_path / "gsc.json"
    gsc_in.write_text(json.dumps({"totals": {"clicks": 120, "impressions": 4000, "ctr": 3.0,
                                             "position": 18.4},
                                  "nonbrand_totals": {"clicks": 80, "impressions": 3500}}))
    ga4_in = tmp_path / "ga4.csv"
    ga4_in.write_text(GA4_CSV)
    r = cli(tmp_path, "snapshot", "--project", PROJECT, "--date", "2026-10-17", "--skip-rank",
            "--gsc-input", str(gsc_in), "--ga4-input", str(ga4_in), "--json")
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)
    assert res["recorded"]["gsc.ctr"]["value"] == 0.03
    assert res["recorded"]["gsc.impressions_nonbrand"]["value"] == 3500
    assert res["skipped"] == {"rank": "skipped by flag"}

    r = cli(tmp_path, "snapshot", "--project", PROJECT, "--skip-rank", "--skip-ga4", "--skip-gsc")
    assert r.returncode == 1


def test_cli_report_without_data_exits_1(tmp_path):
    r = cli(tmp_path, "report", "--project", PROJECT)
    assert r.returncode == 1 and "No snapshots" in r.stderr


def test_live_gsc_totals_uses_dimensionless_query_with_filter():
    """Contract with gsc_query.query_search_analytics: dimensions=[] returns the
    true site totals (anonymized clicks included) and passes filters through."""
    pytest.importorskip("googleapiclient")
    from unittest import mock

    import gsc_query

    bodies = []

    class _Exec:
        def __init__(self, resp):
            self.resp = resp

        def execute(self):
            return self.resp

    class _SA:
        def query(self, siteUrl=None, body=None):
            bodies.append(body)
            return _Exec({"rows": [{"keys": [], "clicks": 24, "impressions": 2734,
                                    "ctr": 0.0088, "position": 12.3}]})

    class _Svc:
        def searchanalytics(self):
            return _SA()

    flt = [{"dimension": "query", "operator": "excludingRegex", "expression": "(?i)(acme)"}]
    with mock.patch.object(gsc_query, "_build_gsc_service", return_value=_Svc()):
        totals = pt._live_gsc_totals("sc-domain:example.com", "2026-09-17", "2026-10-14", flt)
    assert totals["clicks"] == 24 and totals["impressions"] == 2734
    assert all(b["dimensions"] == [] for b in bodies)
    assert bodies[0]["dimensionFilterGroups"] == [{"filters": flt}]
    assert pt._totals_metrics(totals)["gsc.ctr"] == round(24 / 2734, 6)
