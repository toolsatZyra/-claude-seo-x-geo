#!/usr/bin/env python3
"""
AI-assistant referral traffic vs organic search, from GA4.

Answers: how many sessions (and key events) arrive from AI assistants such as
ChatGPT, Perplexity, Gemini, Copilot and Claude, which landing pages they hit,
and how they convert compared with organic search.

Classification is a HEURISTIC: a session counts as AI when its GA4
``sessionSource`` matches the versioned host table below (AI_SOURCES). It
undercounts, because many AI apps strip the referrer (those visits arrive as
Direct) and some assistants send no identifiable source at all. It is a
floor, not a census. Organic = ``sessionDefaultChannelGroup`` "Organic Search"
(or medium "organic" when an export has no channel column); a session that
matches the AI table is never also counted as organic.

Data: GA4 Data API (dimensions sessionSource, sessionMedium,
sessionDefaultChannelGroup, landingPage; metrics sessions, keyEvents,
sessionKeyEventRate, and ``keyEvents:<eventName>`` for each profile
conversion event). If the property rejects the per-event metrics the script
falls back to total keyEvents and says so. Offline: ``--input`` takes a CSV or
JSON export with the same columns (GA4 UI CSV, API JSON, or a plain row list).

Usage:
    python ai_referrals.py --project example.com [--property 123456789] [--days 28]
    python ai_referrals.py --project example.com --input ga4_export.csv --json
    python ai_referrals.py --project example.com --emit-kpis kpis-ga4.json
    python ai_referrals.py --print-regex        # GA4 custom channel group regex

Output includes AI sessions + share of all sessions, a per-assistant table,
top AI landing pages, organic sessions, key events and conversion rate for AI
vs organic, ``data_sources`` and ``limitations``. Credentials are read by
google_auth.py and never printed.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from performance_tracker import EnvelopeError, re2_escape, write_envelope  # noqa: E402
from seo_project import load_profile  # noqa: E402
from seo_store import normalize_domain, today, utc_now  # noqa: E402

# ---------------------------------------------------------------------------
# Versioned AI-assistant source table. A source matches when it equals one of
# the hosts or is a subdomain of it ("www.perplexity.ai"). Bump the version
# whenever the table changes so stored KPIs can be traced to the rules used.
# ---------------------------------------------------------------------------

AI_SOURCES_VERSION = "2026-10-17"
AI_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ChatGPT", ("chatgpt.com", "chat.openai.com")),
    ("Perplexity", ("perplexity.ai",)),
    ("Gemini", ("gemini.google.com", "bard.google.com")),
    ("Microsoft Copilot", ("copilot.microsoft.com", "copilot.cloud.microsoft",
                           "edgeservices.bing.com")),
    ("Claude", ("claude.ai",)),
    ("You.com", ("you.com",)),
    ("Phind", ("phind.com",)),
    ("Meta AI", ("meta.ai",)),
    ("DeepSeek", ("chat.deepseek.com",)),
    ("Grok", ("grok.com",)),
    ("Mistral Le Chat", ("chat.mistral.ai",)),
)
# Substrings that suggest an AI source the table does not cover yet; matching
# sources are listed for human review, never counted as AI automatically.
_AI_HINTS = ("gpt", "openai", "perplexity", "copilot", "gemini", "claude", "anthropic",
             "deepseek", "mistral", "grok", "llm", "chatbot")

MAX_EVENT_METRICS = 7          # GA4 allows 10 metrics per request; 3 are always used
_EVENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
PAGE_SIZE = 10_000
MAX_ROWS = 100_000


def _host(source: str) -> str:
    s = (source or "").strip().lower()
    if not s or s in ("(direct)", "(not set)", "(none)"):
        return ""
    if "://" in s:
        s = urlparse(s).hostname or ""
    s = s.split("/")[0].split(":")[0].rstrip(".")
    for prefix in ("www.", "m."):
        if s.startswith(prefix):
            s = s[len(prefix):]
    return s


def classify_source(source: str) -> Optional[str]:
    """Return the assistant name for a GA4 sessionSource, or None."""
    host = _host(source)
    if not host:
        return None
    for name, hosts in AI_SOURCES:
        for h in hosts:
            if host == h or host.endswith("." + h):
                return name
    return None


def ai_source_regex() -> str:
    """RE2 regex for a GA4 custom channel group ('Source matches regex')."""
    hosts = sorted({h for _, hs in AI_SOURCES for h in hs})
    return r"^(.+\.)?(" + "|".join(re2_escape(h) for h in hosts) + r")$"


# ---------------------------------------------------------------------------
# Row normalization (shared by live API rows and offline exports)
# ---------------------------------------------------------------------------

_FIELD_ALIASES = {
    "source": ("sessionsource", "source"),
    "medium": ("sessionmedium", "medium"),
    "source_medium": ("sessionsource/medium", "source/medium", "sessionsourcemedium"),
    "landing_page": ("landingpage", "landingpageplusquerystring", "landingpage+querystring",
                     "page"),
    "channel_group": ("sessiondefaultchannelgroup", "defaultchannelgroup",
                      "sessionprimarychannelgroup", "channelgroup", "channel"),
    "sessions": ("sessions",),
    "key_events": ("keyevents", "conversions"),
    "key_event_rate": ("sessionkeyeventrate", "keyeventrate", "sessionconversionrate"),
}


def _compress(key: str) -> str:
    return re.sub(r"[\s_]+", "", (key or "").strip().lower())


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    pct = s.endswith("%")
    s = s.rstrip("%").strip()
    if not s or s in ("-", "(not set)"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100 if pct else v


def normalize_row(raw: dict) -> Optional[dict]:
    """Map one export/API row to {source, medium, landing_page, channel_group,
    sessions, key_events, key_event_rate, events}. Returns None for rows
    without a sessions value (e.g. GA4 'Grand total' lines)."""
    fields: dict[str, Any] = {}
    events: dict[str, float] = {}
    for key, value in raw.items():
        if key is None:
            continue
        k = str(key).strip()
        if k.lower().startswith("keyevents:"):
            n = _num(value)
            if n is not None:
                events[k.split(":", 1)[1].strip()] = n
            continue
        ck = _compress(k)
        for field, aliases in _FIELD_ALIASES.items():
            if ck in aliases and field not in fields:
                fields[field] = value
    sessions = _num(fields.get("sessions"))
    if sessions is None:
        return None
    source = str(fields.get("source") or "").strip()
    medium = str(fields.get("medium") or "").strip()
    if not source and fields.get("source_medium"):
        parts = str(fields["source_medium"]).split(" / ", 1)
        source = parts[0].strip()
        medium = medium or (parts[1].strip() if len(parts) > 1 else "")
    rate = _num(fields.get("key_event_rate"))
    if rate is not None and rate > 1:      # a percent that lost its % sign
        rate = rate / 100
    return {
        "source": source, "medium": medium,
        "landing_page": str(fields.get("landing_page") or "").strip(),
        "channel_group": str(fields.get("channel_group") or "").strip(),
        "sessions": sessions, "key_events": _num(fields.get("key_events")) or 0.0,
        "key_event_rate": rate, "events": events,
    }


def _rows_from_api_json(data: dict) -> list[dict]:
    dims = [h.get("name") for h in data.get("dimensionHeaders") or []]
    mets = [h.get("name") for h in data.get("metricHeaders") or []]
    out = []
    for row in data.get("rows") or []:
        rec = {dims[i]: v.get("value") for i, v in enumerate(row.get("dimensionValues") or [])}
        rec.update({mets[i]: v.get("value") for i, v in enumerate(row.get("metricValues") or [])})
        out.append(rec)
    return out


def load_rows(path: str) -> list[dict]:
    """Load GA4 rows from a CSV export, GA4 API JSON, or a JSON row list."""
    text = Path(path).read_text(encoding="utf-8-sig")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(text)
        if isinstance(data, dict) and "dimensionHeaders" in data:
            raw = _rows_from_api_json(data)
        elif isinstance(data, dict):
            raw = data.get("rows") or []
        else:
            raw = data
    else:
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        raw = list(csv.DictReader(io.StringIO("\n".join(lines))))
    rows = [r for r in (normalize_row(x) for x in raw if isinstance(x, dict)) if r]
    if not rows:
        # An unrecognised file (e.g. a ga4_report.py daily_data export) must not
        # become "0 sessions": a real zero and "not measured" are different facts.
        raise ValueError(f"{path}: no GA4 rows recognised (expected session source/medium rows "
                         "as CSV, a JSON row list, or GA4 Data API JSON)")
    return rows


# ---------------------------------------------------------------------------
# Live GA4 fetch
# ---------------------------------------------------------------------------

def _valid_events(conversion_events: Iterable[str]) -> tuple[list[str], list[str]]:
    ok, bad = [], []
    for e in conversion_events or []:
        (ok if _EVENT_NAME_RE.match(e or "") else bad).append(e)
    return ok[:MAX_EVENT_METRICS], bad + ok[MAX_EVENT_METRICS:]


def _response_rows(resp) -> list[dict]:
    dims = [h.name for h in resp.dimension_headers]
    mets = [h.name for h in resp.metric_headers]
    out = []
    for row in resp.rows:
        rec = {dims[i]: v.value for i, v in enumerate(row.dimension_values)}
        rec.update({mets[i]: v.value for i, v in enumerate(row.metric_values)})
        out.append(rec)
    return out


def _explain_ga4_error(exc: Exception, prop: str) -> str:
    msg = str(exc)
    if "403" in msg or "PERMISSION_DENIED" in msg:
        return (f"Permission denied for GA4 property '{prop}'. Add the service account / OAuth "
                "user as Viewer in GA4 Admin > Property access management.")
    if "404" in msg or "NOT_FOUND" in msg:
        return f"GA4 property '{prop}' not found. Use the numeric ID from GA4 Admin > Property details."
    return f"GA4 API error: {msg}"


def fetch_ga4_rows(property_id: str, start: str, end: str, conversion_events: Iterable[str] = (),
                   client: Any = None) -> tuple[list[dict], list[dict], list[str]]:
    """Run the two GA4 reports; returns (traffic_rows, ai_landing_rows, notes).

    ``client`` is injectable (anything with ``run_report(request)``); by
    default ga4_report._build_ga4_client() supplies it.
    """
    from google.analytics.data_v1beta.types import (  # lazy: optional dependency
        DateRange, Dimension, Filter, FilterExpression, Metric, OrderBy, RunReportRequest)

    try:
        import ga4_report
    except SystemExit as exc:  # ga4_report exits when google-analytics-data is missing
        raise RuntimeError("google-analytics-data is not installed") from exc
    prop = ga4_report._resolve_property(str(property_id))
    if client is None:
        client = ga4_report._build_ga4_client()
        if client is None:
            raise RuntimeError("Could not build GA4 client; run google_auth.py --check")

    notes: list[str] = []
    events, rejected = _valid_events(conversion_events)
    if rejected:
        notes.append(f"Conversion events not requested per-event (invalid name or over the "
                     f"{MAX_EVENT_METRICS}-event cap): {', '.join(rejected)}")
    dranges = [DateRange(start_date=start, end_date=end)]

    def traffic_request(event_metrics: list[str], offset: int) -> Any:
        return RunReportRequest(
            property=prop,
            dimensions=[Dimension(name=n) for n in
                        ("sessionSource", "sessionMedium", "sessionDefaultChannelGroup")],
            metrics=[Metric(name=n) for n in
                     ["sessions", "keyEvents", "sessionKeyEventRate"] + event_metrics],
            date_ranges=dranges, limit=PAGE_SIZE, offset=offset)

    def run_traffic(event_metrics: list[str]) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        while True:
            resp = client.run_report(traffic_request(event_metrics, offset))
            batch = _response_rows(resp)
            rows.extend(batch)
            offset += len(batch)
            total = getattr(resp, "row_count", 0) or 0
            if not batch or offset >= total or offset >= MAX_ROWS:
                if total > MAX_ROWS:
                    notes.append(f"GA4 returned {total:,} rows; only the first {MAX_ROWS:,} were read")
                return rows

    event_metrics = [f"keyEvents:{e}" for e in events]
    try:
        traffic = run_traffic(event_metrics)
    except Exception as exc:  # noqa: BLE001
        if not event_metrics:
            raise RuntimeError(_explain_ga4_error(exc, str(property_id))) from exc
        notes.append(f"GA4 rejected the per-event metrics ({', '.join(event_metrics)}): "
                     f"{type(exc).__name__}; reported total keyEvents only")
        try:
            traffic = run_traffic([])
        except Exception as exc2:  # noqa: BLE001
            raise RuntimeError(_explain_ga4_error(exc2, str(property_id))) from exc2

    landing_req = RunReportRequest(
        property=prop,
        dimensions=[Dimension(name="sessionSource"), Dimension(name="landingPage")],
        metrics=[Metric(name="sessions"), Metric(name="keyEvents")],
        date_ranges=dranges,
        dimension_filter=FilterExpression(filter=Filter(
            field_name="sessionSource",
            string_filter=Filter.StringFilter(match_type=Filter.StringFilter.MatchType.FULL_REGEXP,
                                              value=ai_source_regex(), case_sensitive=False))),
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=250)
    try:
        landing = _response_rows(client.run_report(landing_req))
    except Exception as exc:  # noqa: BLE001 - totals are still valid without pages
        landing = []
        notes.append(f"AI landing-page report failed ({type(exc).__name__}); totals unaffected")

    return ([r for r in map(normalize_row, traffic) if r],
            [r for r in map(normalize_row, landing) if r], notes)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _is_organic(row: dict) -> bool:
    if row["channel_group"]:
        return row["channel_group"].strip().lower() == "organic search"
    return row["medium"].strip().lower() == "organic"


def _ratio(num: float, den: float, digits: int = 4) -> Optional[float]:
    return round(num / den, digits) if den else None


class _Bucket:
    def __init__(self) -> None:
        self.sessions = 0.0
        self.key_events = 0.0
        self.converting = 0.0
        self.events: dict[str, float] = {}

    def add(self, row: dict) -> None:
        self.sessions += row["sessions"]
        self.key_events += row["key_events"]
        if row["key_event_rate"] is not None:
            self.converting += row["key_event_rate"] * row["sessions"]
        for e, n in row["events"].items():
            self.events[e] = self.events.get(e, 0.0) + n

    def cvr(self, session_basis: bool) -> Optional[float]:
        return _ratio(self.converting if session_basis else self.key_events, self.sessions)


def summarize(rows: list[dict], landing_rows: Optional[list[dict]] = None,
              conversion_events: Iterable[str] = (), top_n: int = 20) -> dict:
    """Classify rows and aggregate AI vs organic. Pure and deterministic."""
    total, ai, organic = _Bucket(), _Bucket(), _Bucket()
    by_assistant: dict[str, _Bucket] = {}
    possible: dict[str, float] = {}
    for r in rows:
        total.add(r)
        name = classify_source(r["source"])
        if name:
            ai.add(r)
            by_assistant.setdefault(name, _Bucket()).add(r)
        elif _is_organic(r):
            organic.add(r)
        host = _host(r["source"])
        if not name and host and any(h in host for h in _AI_HINTS):
            possible[r["source"]] = possible.get(r["source"], 0.0) + r["sessions"]

    session_basis = bool(rows) and all(r["key_event_rate"] is not None for r in rows if r["sessions"])
    basis = "sessions_with_key_event" if session_basis else "key_events_per_session"

    pages: dict[str, dict] = {}
    source_rows = landing_rows if landing_rows is not None else rows
    for r in source_rows:
        name = classify_source(r["source"])
        if not name or not r["landing_page"]:
            continue
        p = pages.setdefault(r["landing_page"], {"landing_page": r["landing_page"], "sessions": 0.0,
                                                 "key_events": 0.0, "assistants": set()})
        p["sessions"] += r["sessions"]
        p["key_events"] += r["key_events"]
        p["assistants"].add(name)
    top_pages = sorted(pages.values(), key=lambda p: (-p["sessions"], p["landing_page"]))[:top_n]
    for p in top_pages:
        p["assistants"] = sorted(p["assistants"])

    events_out = None
    wanted = list(conversion_events or [])
    if any(r["events"] for r in rows):
        names = sorted(set(total.events) | set(wanted))
        events_out = {e: {"ai": ai.events.get(e, 0.0), "organic": organic.events.get(e, 0.0),
                          "total": total.events.get(e, 0.0)} for e in names}

    ai_cvr, org_cvr = ai.cvr(session_basis), organic.cvr(session_basis)
    limitations = [
        "AI classification is a referrer-source heuristic (table version "
        f"{AI_SOURCES_VERSION}); AI traffic is undercounted because many assistants and apps "
        "strip the referrer, so those visits arrive as Direct",
        "Conversion rate basis: " + ("share of sessions with at least one key event"
                                     if session_basis else
                                     "key events per session (can exceed the share of converting "
                                     "sessions; no sessionKeyEventRate in the data)"),
        "Small AI session counts make CVR comparisons unstable; read them as directional",
        "GA4 may apply data thresholding or an '(other)' row on high-cardinality reports",
    ]
    if wanted and events_out is None:
        limitations.append("Profile conversion events were not broken out (no keyEvents:<event> "
                           "data); totals use all key events")
    return {
        "totals": {"sessions": total.sessions, "key_events": total.key_events},
        "ai": {
            "sessions": ai.sessions, "share_of_total": _ratio(ai.sessions, total.sessions),
            "key_events": ai.key_events, "cvr": ai_cvr, "cvr_basis": basis,
            "by_assistant": [
                {"assistant": n, "sessions": b.sessions,
                 "share_of_ai": _ratio(b.sessions, ai.sessions), "key_events": b.key_events,
                 "cvr": b.cvr(session_basis)}
                for n, b in sorted(by_assistant.items(), key=lambda kv: (-kv[1].sessions, kv[0]))],
            "top_landing_pages": top_pages,
        },
        "organic": {"sessions": organic.sessions,
                    "share_of_total": _ratio(organic.sessions, total.sessions),
                    "key_events": organic.key_events, "cvr": org_cvr, "cvr_basis": basis},
        "ai_vs_organic": {"session_ratio": _ratio(ai.sessions, organic.sessions),
                          "cvr_ratio": _ratio(ai_cvr, org_cvr, 2) if ai_cvr is not None and org_cvr else None},
        "conversion_events": events_out,
        "possible_unclassified_ai_sources": [
            {"source": s, "sessions": n} for s, n in sorted(possible.items(), key=lambda kv: -kv[1])],
        "classification": {"version": AI_SOURCES_VERSION,
                           "assistants": [{"assistant": n, "hosts": list(h)} for n, h in AI_SOURCES],
                           "ga4_regex": ai_source_regex(), "heuristic": True},
        "limitations": limitations,
    }


def kpis_from_summary(summary: dict) -> dict:
    """KPI-envelope metrics (ga4.ai_* and ga4.organic_*). CVR may be None."""
    return {
        "ga4.ai_sessions": summary["ai"]["sessions"],
        "ga4.ai_key_events": summary["ai"]["key_events"],
        "ga4.ai_cvr": summary["ai"]["cvr"],
        "ga4.organic_sessions": summary["organic"]["sessions"],
        "ga4.organic_key_events": summary["organic"]["key_events"],
        "ga4.organic_cvr": summary["organic"]["cvr"],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _pct(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.1%}"


def _print(rep: dict) -> None:
    dr = rep["date_range"]
    print(f"=== AI referrals vs organic: {rep['project']} ({dr['start']}..{dr['end']}) ===")
    ai, org = rep["ai"], rep["organic"]
    print(f"All sessions {rep['totals']['sessions']:,.0f} | key events {rep['totals']['key_events']:,.0f}")
    print(f"AI assistants: {ai['sessions']:,.0f} sessions ({_pct(ai['share_of_total'])} of all), "
          f"{ai['key_events']:,.0f} key events, CVR {_pct(ai['cvr'])}")
    print(f"Organic search: {org['sessions']:,.0f} sessions ({_pct(org['share_of_total'])} of all), "
          f"{org['key_events']:,.0f} key events, CVR {_pct(org['cvr'])}")
    for a in ai["by_assistant"]:
        print(f"  {a['assistant']:<20} {a['sessions']:>9,.0f} sessions  {_pct(a['share_of_ai']):>7} of AI"
              f"  CVR {_pct(a['cvr'])}")
    if ai["top_landing_pages"]:
        print("Top AI landing pages:")
        for p in ai["top_landing_pages"][:10]:
            print(f"  {p['sessions']:>7,.0f}  {p['landing_page']}  ({', '.join(p['assistants'])})")
    for s in rep["possible_unclassified_ai_sources"][:10]:
        print(f"  review: '{s['source']}' ({s['sessions']:,.0f} sessions) looks AI-related but is "
              "not in the table")
    for lim in rep["limitations"]:
        print(f"  limitation: {lim}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GA4 AI-assistant referrals vs organic search")
    parser.add_argument("--project", help="Project domain (profile supplies GA4 property + conversion events)")
    parser.add_argument("--property", help="GA4 property ID (default: profile ga4_property)")
    parser.add_argument("--days", type=int, default=28, help="Window length ending yesterday (default 28)")
    parser.add_argument("--as-of", help="Treat this date as today, YYYY-MM-DD (default today, UTC)")
    parser.add_argument("--input", help="Offline GA4 export (CSV / API JSON / JSON rows)")
    parser.add_argument("--top", type=int, default=20, help="Top AI landing pages to list")
    parser.add_argument("--emit-kpis", help="Write ga4.ai_* / ga4.organic_* as a KPI envelope")
    parser.add_argument("--print-regex", action="store_true",
                        help="Print the GA4 custom-channel-group regex and exit")
    parser.add_argument("--data-dir", help="Storage root for the project profile")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.print_regex:
        out = {"version": AI_SOURCES_VERSION, "regex": ai_source_regex(),
               "usage": "GA4 Admin > Data display > Channel groups > new channel 'AI assistants': "
                        "Source matches regex <regex>; place it above Referral"}
        print(json.dumps(out, indent=2) if args.json else out["regex"])
        return 0
    if not args.project:
        parser.error("--project is required")
    if args.days < 1:
        parser.error("--days must be a positive integer")
    project = normalize_domain(args.project)
    if not project:
        parser.error(f"cannot derive a domain from --project {args.project!r}")
    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.fromisoformat(today())
    except ValueError:
        parser.error(f"invalid --as-of {args.as_of!r}")
    end = as_of - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)
    profile = load_profile(project, args.data_dir) or {}
    events = list(profile.get("conversion_events") or [])

    notes: list[str] = []
    try:
        if args.input:
            rows, landing = load_rows(args.input), None
            prop = "input:" + os.path.basename(args.input)
            source_label = f"GA4 export file ({os.path.basename(args.input)})"
            date_range = {"start": "as exported", "end": "as exported"}
        else:
            prop = args.property or profile.get("ga4_property")
            if not prop:
                print("Error: no GA4 property: pass --property or set ga4_property in the project "
                      "profile (seo_project.py set <domain> ga4_property <id>)", file=sys.stderr)
                return 1
            rows, landing, notes = fetch_ga4_rows(prop, start.isoformat(), end.isoformat(), events)
            source_label = "GA4 Data API v1beta (runReport)"
            date_range = {"start": start.isoformat(), "end": end.isoformat()}
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    summary = summarize(rows, landing, events, args.top)
    rep = {"project": project, "property": prop, "generated_at": utc_now(),
           "date_range": date_range, **summary,
           "kpis": kpis_from_summary(summary),
           "data_sources": [source_label, f"AI source table v{AI_SOURCES_VERSION} (heuristic)"],
           "limitations": notes + summary["limitations"]}
    if args.emit_kpis:
        try:
            write_envelope(args.emit_kpis, project, "ai_referrals.py", rep["kpis"], as_of.isoformat(),
                           {"window": {"start": start.isoformat(), "end": end.isoformat()}
                            if not args.input else "as exported",
                            "cvr_basis": summary["organic"]["cvr_basis"],
                            "classifier_version": AI_SOURCES_VERSION})
        except EnvelopeError as exc:
            print(f"Error: KPI envelope invalid: {exc}", file=sys.stderr)
            return 1
        rep["kpi_envelope_path"] = args.emit_kpis
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        _print(rep)
    return 0


if __name__ == "__main__":
    sys.exit(main())
