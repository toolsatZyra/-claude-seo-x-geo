#!/usr/bin/env python3
"""
KPI history for SEO + AEO + leads: dated snapshots, trend reports, CI gates.

One SQLite store (``kpi``) holds one row per (project, date, metric). Rows
arrive four ways:

    snapshot   collects GSC site totals (+ non-brand totals), GA4 organic and
               AI-assistant sessions/key events, and rank-tracker KPIs, and
               records them as one dated snapshot. A failing source never
               aborts the others; its failure is listed under ``errors``.
    ingest     stores KPI envelopes written by other scripts via
               ``--emit-kpis <path>`` (ai_visibility.py, aeo_score.py,
               rank_tracker.py, ai_referrals.py ...).
    record     stores one manual value (e.g. CRM leads for the month).

and leave through ``report`` (latest vs a comparison snapshot, direction-aware,
``--fail-on-drop`` exit code 3 for scheduled checks) and ``export`` (the JSON
contract that geo-compare and the PDF report read).

KPI envelope contract (version 1) -- the file every ``--emit-kpis`` writes:

    {"kpi_envelope": 1, "project": "example.com", "date": "2026-10-17",
     "source": "ai_visibility.py", "metrics": {"ai.mention_rate": 0.32},
     "meta": {"n": 60}}

Rules enforced on ingest: version must be 1; project and date required; metric
names match ``[a-z0-9_]+.[a-z0-9_]+``; values must be finite numbers (JSON
``null`` is skipped, never stored as 0; booleans and strings are rejected);
reserved metrics are range-checked (rates/shares are 0-1 fractions, scores
0-100, counts >= 0). An envelope with any invalid metric is rejected whole.
Producers can import ``write_envelope()`` from this module.

Usage:
    python performance_tracker.py snapshot --project example.com [--date 2026-10-17] [--days 28]
    python performance_tracker.py snapshot --project example.com --skip-ga4 --gsc-input gsc.json
    python performance_tracker.py ingest kpis-ai.json kpis-aeo.json
    python performance_tracker.py record --project example.com --metric leads.total --value 42
    python performance_tracker.py report --project example.com [--metrics gsc,ga4] [--compare 28d]
    python performance_tracker.py report --project example.com --fail-on-drop 20 --watch gsc.clicks
    python performance_tracker.py export --project example.com --json
    python performance_tracker.py history --project example.com --metric gsc.clicks

All commands accept --data-dir (storage root; default $CLAUDE_SEO_DATA_DIR or
~/.cache/claude-seo). Exit codes: 0 ok, 1 error/no data, 3 a watched metric
worsened more than --fail-on-drop percent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_metrics import pct_change  # noqa: E402
from seo_project import all_brand_terms, load_profile  # noqa: E402
from seo_store import connect, normalize_domain, today, utc_now  # noqa: E402
# The KPI envelope contract lives in seo_kpi.py; re-exported here because
# rank_tracker / ai_referrals / tests historically import it from this module.
from seo_kpi import (  # noqa: E402,F401
    ENVELOPE_VERSION,
    METRIC_NAME_RE,
    NEUTRAL_METRICS,
    RESERVED_METRICS,
    RESERVED_PREFIXES,
    EnvelopeError,
    brand_regex,
    build_envelope,
    lower_is_better,
    re2_escape,
    validate_envelope,
    write_envelope,
    _valid_date,
)

STORE = "kpi"
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    project     TEXT NOT NULL,
    date        TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL NOT NULL,
    source      TEXT NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}',
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (project, date, metric)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_metric ON snapshots(project, metric, date);
"""

GSC_LAG_DAYS = 3


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def open_store(data_dir: Optional[str] = None):
    return connect(STORE, SCHEMA, data_dir)


def store_envelope(conn, envelope: dict) -> int:
    """Upsert a cleaned envelope's metrics; returns the number stored.

    The primary key is (project, date, metric): re-ingesting the same file is
    idempotent, and a later value for the same metric and date replaces the
    earlier one (the report always shows which source wrote it).
    """
    now = utc_now()
    meta = json.dumps(envelope.get("meta") or {}, sort_keys=True)
    n = 0
    for name, value in envelope["metrics"].items():
        conn.execute(
            "INSERT INTO snapshots (project, date, metric, value, source, meta, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(project, date, metric) DO UPDATE SET value=excluded.value, "
            "source=excluded.source, meta=excluded.meta, recorded_at=excluded.recorded_at",
            (envelope["project"], envelope["date"], name, float(value), envelope["source"],
             meta, now),
        )
        n += 1
    conn.commit()
    return n


def ingest_files(conn, paths: Iterable[str]) -> dict:
    """Validate and store envelope files. Invalid files are reported, not stored."""
    results = []
    for path in paths:
        entry: dict[str, Any] = {"file": str(path)}
        try:
            with open(path, encoding="utf-8") as fh:
                env = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            entry.update({"ok": False, "errors": [f"cannot read JSON: {exc}"]})
            results.append(entry)
            continue
        check = validate_envelope(env)
        entry.update({"ok": check["ok"], "errors": check["errors"], "warnings": check["warnings"],
                      "skipped_null": check["skipped_null"]})
        if check["ok"]:
            clean = check["envelope"]
            entry.update({"project": clean["project"], "date": clean["date"],
                          "source": clean["source"], "stored": store_envelope(conn, clean)})
        results.append(entry)
    return {"files": results, "stored": sum(r.get("stored", 0) for r in results),
            "rejected": sum(1 for r in results if not r["ok"])}


def metric_rows(conn, project: str, metric: Optional[str] = None) -> list[dict]:
    sql = "SELECT date, metric, value, source, meta FROM snapshots WHERE project = ?"
    params: list[Any] = [project]
    if metric:
        sql += " AND metric = ?"
        params.append(metric)
    sql += " ORDER BY metric, date"
    out = []
    for r in conn.execute(sql, params):
        try:
            meta = json.loads(r["meta"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        out.append({"date": r["date"], "metric": r["metric"], "value": r["value"],
                    "source": r["source"], "meta": meta})
    return out


# ---------------------------------------------------------------------------
# Snapshot collectors (each injectable for offline tests)
# ---------------------------------------------------------------------------

def _import_quietly(module: str):
    """Import a Google-client script whose module body calls sys.exit on a
    missing dependency; turn that into an exception so one missing library
    cannot abort the whole snapshot."""
    try:
        return __import__(module)
    except SystemExit as exc:  # pragma: no cover - depends on installed libs
        raise RuntimeError(f"{module} unavailable (missing Google client library)") from exc


def _live_gsc_totals(prop: str, start: str, end: str, filters: Optional[list]) -> dict:
    gsc_query = _import_quietly("gsc_query")
    res = gsc_query.query_search_analytics(prop, start_date=start, end_date=end, dimensions=[],
                                           row_limit=10, filters=filters, data_state="final")
    if res.get("error"):
        raise RuntimeError(res["error"])
    if res.get("totals_complete") is False:
        return {}   # partial row-sum totals undercount; record "not measured" instead
    return res.get("totals") or {}


def _totals_metrics(totals: dict, suffix: str = "") -> dict:
    """GSC totals -> metrics. Missing totals are None ("not measured"), never 0."""
    if not totals or not any(k in totals for k in ("clicks", "impressions")):
        names = [f"gsc.clicks{suffix}", f"gsc.impressions{suffix}"]
        if not suffix:
            names += ["gsc.ctr", "gsc.position"]
        return {n: None for n in names}
    clicks = float(totals.get("clicks") or 0)
    imps = float(totals.get("impressions") or 0)
    out = {f"gsc.clicks{suffix}": clicks, f"gsc.impressions{suffix}": imps}
    if not suffix:
        out["gsc.ctr"] = round(clicks / imps, 6) if imps > 0 else None
        pos = totals.get("position")
        out["gsc.position"] = round(float(pos), 2) if pos not in (None, "", 0) else None
    return out


def collect_gsc(profile: Optional[dict], snap_date: date, days: int, prop: Optional[str] = None,
                gsc_input: Optional[str] = None,
                fetch_totals: Optional[Callable] = None) -> dict:
    """GSC site totals (dimensionless query) + non-brand totals for one window."""
    end = snap_date - timedelta(days=GSC_LAG_DAYS)
    start = end - timedelta(days=days - 1)
    window = {"start": start.isoformat(), "end": end.isoformat()}
    limitations = []
    if gsc_input:
        with open(gsc_input, encoding="utf-8") as fh:
            data = json.load(fh)
        totals = data.get("totals") or {}
        if data.get("totals_complete") is False or data.get("totals_source") == "partial_row_sum":
            limitations.append("GSC input totals are a partial row sum (anonymized queries "
                               "missing); site totals recorded as not measured")
            totals = {}
        elif not totals:
            limitations.append("GSC input has no totals; site totals recorded as not measured")
        nonbrand = data.get("nonbrand_totals") or data.get("totals_nonbrand")
        metrics = _totals_metrics(totals)
        if nonbrand:
            metrics.update(_totals_metrics(nonbrand, "_nonbrand"))
        else:
            limitations.append("GSC input has no nonbrand_totals; non-brand metrics not recorded")
        window = data.get("date_range") or window
        return {"metrics": metrics, "meta": {"window": window, "input": os.path.basename(gsc_input)},
                "limitations": limitations}

    prop = prop or (profile or {}).get("gsc_property")
    if not prop:
        raise LookupError("no GSC property: pass --gsc-property or set gsc_property in the project profile")
    fetch = fetch_totals or _live_gsc_totals
    metrics = _totals_metrics(fetch(prop, window["start"], window["end"], None))
    brands = all_brand_terms(profile) if profile else []
    if brands:
        flt = [{"dimension": "query", "operator": "excludingRegex", "expression": brand_regex(brands)}]
        metrics.update(_totals_metrics(fetch(prop, window["start"], window["end"], flt), "_nonbrand"))
        limitations.append("Non-brand totals use a query filter, which drops anonymized queries; "
                           "compare non-brand to non-brand over time, never to the site total")
    else:
        limitations.append("No brand terms in the project profile; non-brand metrics not recorded")
    return {"metrics": metrics, "meta": {"window": window, "property": prop, "data_state": "final"},
            "limitations": limitations}


def collect_ga4(profile: Optional[dict], snap_date: date, days: int, prop: Optional[str] = None,
                ga4_input: Optional[str] = None, client: Any = None) -> dict:
    import ai_referrals  # lazy: avoids a circular import (ai_referrals imports this module)

    events = list((profile or {}).get("conversion_events") or [])
    end = snap_date - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    if ga4_input:
        rows, landing = ai_referrals.load_rows(ga4_input), None
        notes: list[str] = []
        prop = "input:" + os.path.basename(ga4_input)
    else:
        prop = prop or (profile or {}).get("ga4_property")
        if not prop:
            raise LookupError("no GA4 property: pass --ga4-property or set ga4_property in the project profile")
        rows, landing, notes = ai_referrals.fetch_ga4_rows(prop, start.isoformat(), end.isoformat(),
                                                           events, client=client)
    summary = ai_referrals.summarize(rows, landing_rows=landing, conversion_events=events)
    return {"metrics": ai_referrals.kpis_from_summary(summary),
            "meta": {"window": {"start": start.isoformat(), "end": end.isoformat()},
                     "property": prop, "cvr_basis": summary["organic"]["cvr_basis"],
                     "classifier_version": ai_referrals.AI_SOURCES_VERSION},
            "limitations": notes + ["AI-assistant sessions are classified by a referrer-source "
                                    "heuristic and undercount (stripped referrers arrive as Direct)"]}


def collect_rank(project: str, snap_date: date, data_dir: Optional[str],
                 profile: Optional[dict]) -> dict:
    import rank_tracker  # lazy: rank_tracker imports this module for write_envelope

    conn = rank_tracker.open_store(data_dir)
    try:
        report = rank_tracker.build_report(
            conn, project, as_of=snap_date,
            brand_terms=all_brand_terms(profile) if profile else ())
    finally:
        conn.close()
    if not report["summary"]["tracked"]:
        raise LookupError("no tracked keywords (rank_tracker.py add ...)")
    if not report["summary"]["observations"]["current"]:
        raise LookupError("no rank observations in the current window (rank_tracker.py ingest-gsc)")
    return {"metrics": report["kpis"],
            "meta": {"window": report["windows"]["current"], "source": report["source"]},
            "limitations": ["rank.* counts use GSC average positions over a "
                            f"{report['windows']['window_days']}-day window, not SERP ranks"]}


def take_snapshot(project: str, snap_date: Optional[date] = None, days: int = 28,
                  data_dir: Optional[str] = None, skip: Iterable[str] = (),
                  gsc_property: Optional[str] = None, ga4_property: Optional[str] = None,
                  gsc_input: Optional[str] = None, ga4_input: Optional[str] = None,
                  gsc_fetch: Optional[Callable] = None, ga4_client: Any = None) -> dict:
    """Collect every available source and store one dated snapshot."""
    project = normalize_domain(project)
    snap_date = snap_date or date.fromisoformat(today())
    profile = load_profile(project, data_dir)
    skip = set(skip)
    out: dict[str, Any] = {"project": project, "date": snap_date.isoformat(), "days": days,
                           "recorded": {}, "errors": {}, "skipped": {}, "limitations": [],
                           "data_sources": []}
    if profile is None:
        out["limitations"].append(f"No project profile for {project}; properties and brand terms "
                                  "must come from flags (seo_project.py init)")

    collectors = {
        "gsc": (lambda: collect_gsc(profile, snap_date, days, gsc_property, gsc_input, gsc_fetch),
                "gsc_query.py", "Google Search Console Search Analytics (dimensionless totals)"),
        "ga4": (lambda: collect_ga4(profile, snap_date, days, ga4_property, ga4_input, ga4_client),
                "ai_referrals.py", "GA4 Data API (sessions, key events by source/medium)"),
        "rank": (lambda: collect_rank(project, snap_date, data_dir, profile),
                 "rank_tracker.py", "Local rank-tracking store (GSC history / SERP imports)"),
    }
    conn = open_store(data_dir)
    try:
        for name, (fn, source, label) in collectors.items():
            if name in skip:
                out["skipped"][name] = "skipped by flag"
                continue
            try:
                result = fn()
            except LookupError as exc:
                out["skipped"][name] = str(exc)
                continue
            except Exception as exc:  # noqa: BLE001 - one source must not abort the others
                out["errors"][name] = f"{type(exc).__name__}: {exc}"
                continue
            env = {"kpi_envelope": ENVELOPE_VERSION, "project": project,
                   "date": snap_date.isoformat(), "source": source,
                   "metrics": result["metrics"], "meta": result["meta"]}
            check = validate_envelope(env)
            if not check["ok"]:
                out["errors"][name] = "; ".join(check["errors"])
                continue
            store_envelope(conn, check["envelope"])
            out["recorded"].update({k: {"value": v, "source": source}
                                    for k, v in check["envelope"]["metrics"].items()})
            out["limitations"].extend(result.get("limitations", []))
            out["data_sources"].append(label)
    finally:
        conn.close()
    return out


# ---------------------------------------------------------------------------
# Report / export
# ---------------------------------------------------------------------------

def _match_prefixes(metric: str, prefixes: Optional[list[str]]) -> bool:
    if not prefixes:
        return True
    for p in prefixes:
        p = p.strip()
        if not p:
            continue
        if "." not in p:
            p += "."
        if metric.startswith(p) or metric == p.rstrip("."):
            return True
    return False


def _pick_comparison(rows: list[dict], compare: str) -> Optional[dict]:
    """rows ascending by date; returns the comparison row or None."""
    if len(rows) < 2:
        return None
    latest = date.fromisoformat(rows[-1]["date"])
    if compare == "previous":
        return rows[-2]
    m = re.fullmatch(r"(\d+)d", compare)
    if m:
        target = latest - timedelta(days=int(m.group(1)))
    else:
        target = date.fromisoformat(compare)
    earlier = [r for r in rows[:-1] if date.fromisoformat(r["date"]) <= target]
    return earlier[-1] if earlier else None


def build_kpi_report(conn, project: str, prefixes: Optional[list[str]] = None,
                     compare: str = "previous", watch: Optional[list[str]] = None,
                     fail_on_drop: Optional[float] = None) -> dict:
    """Latest value per metric vs a comparison snapshot, direction-aware."""
    if compare != "previous" and not re.fullmatch(r"\d+d", compare) and _valid_date(compare) is None:
        raise ValueError("--compare must be previous, Nd (e.g. 28d, 90d) or YYYY-MM-DD")
    by_metric: dict[str, list[dict]] = {}
    for r in metric_rows(conn, project):
        if _match_prefixes(r["metric"], prefixes):
            by_metric.setdefault(r["metric"], []).append(r)

    rows_out = []
    for metric in sorted(by_metric):
        series = by_metric[metric]
        latest = series[-1]
        comp = _pick_comparison(series, compare)
        lib = lower_is_better(metric)
        entry: dict[str, Any] = {
            "metric": metric,
            "latest": {"date": latest["date"], "value": latest["value"], "source": latest["source"]},
            "comparison": ({"date": comp["date"], "value": comp["value"], "source": comp["source"]}
                           if comp else None),
            "delta": None, "pct_change": None, "direction": "n/a", "assessment": "n/a",
            "lower_is_better": lib,
        }
        if comp:
            delta = latest["value"] - comp["value"]
            entry["delta"] = round(delta, 6)
            entry["pct_change"] = pct_change(comp["value"], latest["value"])
            entry["direction"] = "up" if delta > 0 else "down" if delta < 0 else "flat"
            if metric in NEUTRAL_METRICS:
                entry["assessment"] = "neutral"
            elif delta == 0:
                entry["assessment"] = "unchanged"
            else:
                entry["assessment"] = "better" if (delta < 0) == lib else "worse"
        rows_out.append(entry)

    report: dict[str, Any] = {
        "project": project, "generated_at": utc_now(), "compare": compare,
        "metrics": rows_out,
        "latest_date": max((r["latest"]["date"] for r in rows_out), default=None),
        "notes": ["pct_change is relative ((new-old)/|old|); for 0-1 rates read delta as "
                  "percentage points x 100",
                  "Snapshots are rolling-window totals; compare like with like (same --days)"],
    }

    if fail_on_drop is not None:
        known = {r["metric"]: r for r in rows_out}
        targets = watch or [m for m in known if m not in NEUTRAL_METRICS]
        failures, unevaluable, missing = [], [], []
        for m in targets:
            r = known.get(m)
            if r is None:
                missing.append(m)
                continue
            if r["pct_change"] is None:
                unevaluable.append(m)
                continue
            worsened = r["pct_change"] if r["lower_is_better"] else -r["pct_change"]
            if m not in NEUTRAL_METRICS and worsened > fail_on_drop:
                failures.append({"metric": m, "worsened_pct": round(worsened, 1),
                                 "from": r["comparison"]["value"], "to": r["latest"]["value"]})
        report["gate"] = {"fail_on_drop_pct": fail_on_drop, "watched": targets,
                          "failures": failures, "unevaluable": unevaluable, "missing": missing,
                          "status": "FAIL" if failures else "PASS"}
    return report


def export_snapshots(conn, project: str, prefixes: Optional[list[str]] = None) -> dict:
    """The export contract consumed by geo-compare and the PDF report."""
    by_date: dict[str, dict] = {}
    for r in metric_rows(conn, project):
        if _match_prefixes(r["metric"], prefixes):
            by_date.setdefault(r["date"], {})[r["metric"]] = {"value": r["value"], "source": r["source"]}
    return {"project": project, "generated_at": utc_now(),
            "snapshots": [{"date": d, "metrics": by_date[d]} for d in sorted(by_date)]}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _fmt(value: Optional[float]) -> str:
    if value is None:
        return "-"
    if float(value).is_integer() and abs(value) >= 1:
        return f"{int(value):,}"
    return f"{value:.4g}"


def _print_report(rep: dict) -> None:
    print(f"=== KPI report: {rep['project']} (latest {rep['latest_date']}, vs {rep['compare']}) ===")
    print(f"{'metric':<28} {'latest':>12} {'compare':>12} {'delta':>10} {'%':>8}  assessment")
    for r in rep["metrics"]:
        comp = r["comparison"]
        pct = "-" if r["pct_change"] is None else f"{r['pct_change']:+.1f}"
        print(f"{r['metric']:<28} {_fmt(r['latest']['value']):>12} "
              f"{_fmt(comp['value']) if comp else '-':>12} {_fmt(r['delta']):>10} {pct:>8}  "
              f"{r['assessment']}{' (lower is better)' if r['lower_is_better'] else ''}")
    for note in rep["notes"]:
        print(f"Note: {note}")
    gate = rep.get("gate")
    if gate:
        print(f"\nGate (--fail-on-drop {gate['fail_on_drop_pct']}%): {gate['status']}")
        for f in gate["failures"]:
            print(f"  [FAIL] {f['metric']} worsened {f['worsened_pct']}% ({_fmt(f['from'])} -> {_fmt(f['to'])})")
        for m in gate["missing"]:
            print(f"  [missing] {m} has no snapshots")
        for m in gate["unevaluable"]:
            print(f"  [n/a] {m}: no comparison value or comparison is 0")


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return n


def _parse_date_arg(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    parsed = _valid_date(value)
    if parsed is None:
        raise argparse.ArgumentTypeError(f"invalid date {value!r} (expected YYYY-MM-DD)")
    return date.fromisoformat(parsed)


def main(argv: Optional[list[str]] = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", help="Storage root (default $CLAUDE_SEO_DATA_DIR or ~/.cache/claude-seo)")
    common.add_argument("--json", action="store_true", help="Output JSON")

    parser = argparse.ArgumentParser(description="KPI snapshots, trend reports and CI gates")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("snapshot", parents=[common], help="Collect GSC/GA4/rank KPIs into one dated snapshot")
    p.add_argument("--project", required=True)
    p.add_argument("--date", type=_parse_date_arg, help="Snapshot date (default today, UTC)")
    p.add_argument("--days", type=_positive_int, default=28,
                   help="Rolling window for GSC/GA4 totals (default 28)")
    p.add_argument("--skip-gsc", action="store_true")
    p.add_argument("--skip-ga4", action="store_true")
    p.add_argument("--skip-rank", action="store_true")
    p.add_argument("--gsc-property", help="Override the profile's gsc_property")
    p.add_argument("--ga4-property", help="Override the profile's ga4_property")
    p.add_argument("--gsc-input", help="Offline GSC totals JSON ({totals, nonbrand_totals})")
    p.add_argument("--ga4-input", help="Offline GA4 rows (CSV/JSON, see ai_referrals.py)")

    p = sub.add_parser("ingest", parents=[common], help="Store KPI envelope files")
    p.add_argument("files", nargs="+")

    p = sub.add_parser("record", parents=[common], help="Record one manual metric value")
    p.add_argument("--project", required=True)
    p.add_argument("--metric", required=True)
    p.add_argument("--value", required=True, type=float)
    p.add_argument("--date", type=_parse_date_arg)
    p.add_argument("--source", default="manual")
    p.add_argument("--note", default="", help="Stored in meta (e.g. 'CRM export, October')")

    p = sub.add_parser("report", parents=[common], help="Latest vs comparison per metric")
    p.add_argument("--project", required=True)
    p.add_argument("--metrics", help="Comma-separated prefixes, e.g. gsc,ga4.ai_,aeo.score")
    p.add_argument("--compare", default="previous", help="previous | Nd (28d, 90d) | YYYY-MM-DD")
    p.add_argument("--fail-on-drop", type=float, help="Exit 3 if a watched metric worsens more than PCT")
    p.add_argument("--watch", help="Comma-separated metrics for the gate (default: all non-neutral)")

    p = sub.add_parser("export", parents=[common], help="Export all snapshots (JSON contract)")
    p.add_argument("project_pos", nargs="?", metavar="PROJECT", help=argparse.SUPPRESS)
    p.add_argument("--project")
    p.add_argument("--metrics", help="Comma-separated prefixes")

    p = sub.add_parser("history", parents=[common], help="One metric over time")
    p.add_argument("--project", required=True)
    p.add_argument("--metric", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "ingest":
        conn = open_store(args.data_dir)
        try:
            res = ingest_files(conn, args.files)
        finally:
            conn.close()
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            for f in res["files"]:
                status = f"stored {f.get('stored', 0)}" if f["ok"] else "REJECTED"
                print(f"{f['file']}: {status}")
                for e in f.get("errors", []):
                    print(f"  error: {e}")
                for w in f.get("warnings", []):
                    print(f"  warning: {w}")
                if f.get("skipped_null"):
                    print(f"  skipped (null): {', '.join(f['skipped_null'])}")
        return 1 if res["rejected"] else 0

    if args.cmd == "snapshot":
        skip = [n for n, flag in (("gsc", args.skip_gsc), ("ga4", args.skip_ga4),
                                  ("rank", args.skip_rank)) if flag]
        res = take_snapshot(args.project, args.date, args.days, args.data_dir, skip,
                            args.gsc_property, args.ga4_property, args.gsc_input, args.ga4_input)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"=== KPI snapshot: {res['project']} {res['date']} ({res['days']}-day windows) ===")
            for k, v in sorted(res["recorded"].items()):
                print(f"  {k:<28} {_fmt(v['value']):>12}  ({v['source']})")
            for k, v in res["skipped"].items():
                print(f"  [skipped] {k}: {v}")
            for k, v in res["errors"].items():
                print(f"  [error] {k}: {v}")
            for lim in res["limitations"]:
                print(f"  note: {lim}")
        return 0 if res["recorded"] else 1

    project_arg = args.project if args.cmd != "export" else (args.project or args.project_pos)
    if not project_arg:
        print("Error: --project is required", file=sys.stderr)
        return 1
    project = normalize_domain(project_arg)
    if not project:
        print(f"Error: cannot derive a domain from {project_arg!r}", file=sys.stderr)
        return 1

    conn = open_store(args.data_dir)
    try:
        if args.cmd == "record":
            day = (args.date or date.fromisoformat(today())).isoformat()
            meta = {"note": args.note} if args.note else {}
            check = validate_envelope({"kpi_envelope": ENVELOPE_VERSION, "project": project,
                                       "date": day, "source": args.source,
                                       "metrics": {args.metric: args.value}, "meta": meta})
            if not check["ok"]:
                print("Error: " + "; ".join(check["errors"]), file=sys.stderr)
                return 1
            store_envelope(conn, check["envelope"])
            res = {"project": project, "date": day, "metric": args.metric, "value": args.value,
                   "source": args.source, "warnings": check["warnings"]}
            print(json.dumps(res, indent=2) if args.json else
                  f"Recorded {args.metric}={_fmt(args.value)} for {project} on {day} ({args.source})")
            return 0

        if args.cmd == "export":
            prefixes = args.metrics.split(",") if args.metrics else None
            print(json.dumps(export_snapshots(conn, project, prefixes), indent=2))
            return 0

        if args.cmd == "history":
            rows = metric_rows(conn, project, args.metric)
            if args.json:
                print(json.dumps({"project": project, "metric": args.metric, "rows": rows}, indent=2))
            else:
                print(f"=== {args.metric} for {project} ===")
                for r in rows:
                    print(f"  {r['date']}  {_fmt(r['value']):>12}  ({r['source']})")
                if not rows:
                    print("  (no snapshots)")
            return 0 if rows else 1

        # report
        prefixes = args.metrics.split(",") if args.metrics else None
        watch = [w.strip() for w in args.watch.split(",") if w.strip()] if args.watch else None
        try:
            rep = build_kpi_report(conn, project, prefixes, args.compare, watch, args.fail_on_drop)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if not rep["metrics"]:
            msg = f"No snapshots for {project}. Run: performance_tracker.py snapshot --project {project}"
            if args.json:
                print(json.dumps(rep, indent=2))
            print(msg, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(rep, indent=2))
        else:
            _print_report(rep)
        return 3 if rep.get("gate", {}).get("status") == "FAIL" else 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
