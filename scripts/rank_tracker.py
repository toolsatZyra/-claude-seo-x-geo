#!/usr/bin/env python3
"""
Keyword rank tracking from Search Console history and SERP-tool imports.

Keeps a per-project list of tracked keywords (with tags such as
``treatment:faq`` / ``control:faq`` for holdout tests) and a daily
observation table filled from Google Search Console (``ingest-gsc``) or from
SERP-checker exports (``import``: DataForSEO, Ahrefs, Semrush, manual CSV).
``report`` turns that history into movers, position bands, a visibility index,
cannibalization, URL swaps and per-tag statistics; ``experiment`` applies the
pre-registered holdout decision rule (Promote / Keep-testing / Rollback /
Unproven) described in skills/seo-track/references/measurement-protocol.md.

What the numbers are -- and are not:
  * GSC "position" is an impression-weighted AVERAGE over every impression in
    the window, not the rank on any one SERP. Query-level positions here are
    averaged over the query's page rows, which reads slightly worse than
    GSC's own query-level figure when two of the site's pages appear together.
  * GSC data lags 2-3 days, so report windows end ``--lag`` days before
    ``--as-of``.
  * GSC anonymizes rare queries (a large share of clicks on most sites), so a
    tracked low-volume keyword can show no data even while it ranks.
  * SERP imports are single-location, single-device snapshots; they are kept
    apart from GSC rows by ``source`` and summarized with a median.

Usage:
    python rank_tracker.py add --project example.com "crm pricing" "best crm" --tag bofu
    python rank_tracker.py add --project example.com --file keywords.csv --tag treatment:faq
    python rank_tracker.py list --project example.com [--tag bofu] [--json]
    python rank_tracker.py remove --project example.com "best crm" [--purge-history]
    python rank_tracker.py ingest-gsc --project example.com [--property sc-domain:example.com] [--days 30]
    python rank_tracker.py ingest-gsc --project example.com --input gsc_rows.json
    python rank_tracker.py import --project example.com serp.csv --source dataforseo
    python rank_tracker.py report --project example.com [--window 7] [--lag 3] [--as-of 2026-10-17]
    python rank_tracker.py report --project example.com --emit-kpis kpis-rank.json --json
    python rank_tracker.py experiment --project example.com --treatment treatment:faq \
        --control control:faq --start 2026-09-01 --horizon 28
    python rank_tracker.py history --project example.com "crm pricing" [--json]

All commands accept --data-dir (storage root; default $CLAUDE_SEO_DATA_DIR or
~/.cache/claude-seo) and --json.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from performance_tracker import EnvelopeError, re2_escape, write_envelope  # noqa: E402
from seo_metrics import (  # noqa: E402
    CTR_CURVE_SOURCE,
    detect_cannibalization,
    expected_ctr,
    is_striking_distance,
    position_band,
    sign_test_p,
)
from seo_project import all_brand_terms, load_profile  # noqa: E402
from seo_store import connect, host_matches, normalize_domain, today, utc_now  # noqa: E402

STORE = "rankings"
SCHEMA = """
CREATE TABLE IF NOT EXISTS keywords (
    project    TEXT NOT NULL,
    keyword    TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT '[]',
    target_url TEXT,
    added_at   TEXT NOT NULL,
    PRIMARY KEY (project, keyword)
);
CREATE TABLE IF NOT EXISTS obs (
    project     TEXT NOT NULL,
    date        TEXT NOT NULL,
    keyword     TEXT NOT NULL,
    page        TEXT NOT NULL DEFAULT '',
    country     TEXT NOT NULL DEFAULT 'all',
    device      TEXT NOT NULL DEFAULT 'all',
    clicks      REAL,
    impressions REAL,
    ctr         REAL,
    position    REAL,
    source      TEXT NOT NULL,
    PRIMARY KEY (project, date, keyword, page, country, device, source)
);
CREATE INDEX IF NOT EXISTS idx_obs_keyword ON obs(project, keyword, source, date);
CREATE INDEX IF NOT EXISTS idx_obs_date ON obs(project, source, date);
"""

GSC_SOURCE = "gsc"
SERP_SOURCES = ("dataforseo", "ahrefs", "semrush", "manual")
ALL_SOURCES = (GSC_SOURCE,) + SERP_SOURCES

MOVER_MIN_DELTA = 3.0       # |delta| in positions to count as a mover
SIGN_TIE_EPS = 0.5          # |delta| below this is "unchanged" (noise in averages)
MIN_SIGN_TEST_N = 6         # smallest n where a two-sided sign test can reach p < 0.05
GSC_REGEX_MAX = 4000        # GSC caps regex filter expressions at 4096 characters
GSC_ROW_CAP = 100_000       # gsc_query.py stops paginating here

POSITION_NOTE = ("GSC position is an impression-weighted average over the window (and over "
                 "the query's ranking pages), not a rank on any single SERP.")
SERP_NOTE = ("SERP-import position is the median of daily snapshot ranks from one "
             "location/device; days where the domain was not found count as unranked.")


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def norm_keyword(keyword: str) -> str:
    """GSC reports queries lowercased with single spaces; match that form."""
    return " ".join((keyword or "").lower().split())


def norm_project(project: str) -> str:
    host = normalize_domain(project or "")
    if not host:
        raise ValueError(f"cannot derive a domain from {project!r}")
    return host


def parse_day(value: Any) -> Optional[str]:
    """Accept YYYY-MM-DD, YYYYMMDD or an ISO datetime; return YYYY-MM-DD or None."""
    s = str(value or "").strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    s = s[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "")
    if not s or s in ("-", "n/a", "na", "none", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _url_key(url: str) -> tuple[str, str]:
    u = (url or "").strip()
    if not u:
        return "", ""
    if u.startswith("/"):
        host, path = "", u.split("?")[0].split("#")[0]
    else:
        parsed = urlparse(u if "://" in u else "https://" + u)
        host, path = normalize_domain(parsed.hostname or ""), parsed.path or "/"
    return host, (path.rstrip("/") or "/")


def same_url(a: str, b: str) -> bool:
    """URL equality ignoring scheme, www, query, fragment and trailing slash.
    A path-only value matches any host."""
    ha, pa = _url_key(a)
    hb, pb = _url_key(b)
    return bool(pa) and pa == pb and (not ha or not hb or ha == hb)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def open_store(data_dir: Optional[str] = None):
    return connect(STORE, SCHEMA, data_dir)


def _tags(raw: Optional[str]) -> list[str]:
    try:
        val = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(t) for t in val] if isinstance(val, list) else []


def add_keywords(conn, project: str, keywords: Iterable[str], tags: Iterable[str] = (),
                 target_url: Optional[str] = None) -> dict:
    """Track keywords. Re-adding merges tags and updates target_url if given."""
    tags = sorted({t.strip() for t in tags if t and t.strip()})
    added, updated = [], []
    now = utc_now()
    for raw in keywords:
        kw = norm_keyword(raw)
        if not kw:
            continue
        row = conn.execute("SELECT tags, target_url FROM keywords WHERE project=? AND keyword=?",
                           (project, kw)).fetchone()
        if row is None:
            conn.execute("INSERT INTO keywords (project, keyword, tags, target_url, added_at) "
                         "VALUES (?, ?, ?, ?, ?)",
                         (project, kw, json.dumps(tags), target_url or None, now))
            added.append(kw)
        else:
            merged = sorted(set(_tags(row["tags"])) | set(tags))
            conn.execute("UPDATE keywords SET tags=?, target_url=? WHERE project=? AND keyword=?",
                         (json.dumps(merged), target_url or row["target_url"], project, kw))
            updated.append(kw)
    conn.commit()
    return {"added": added, "updated": updated}


def read_keyword_file(path: str) -> list[dict]:
    """CSV with a ``keyword`` column (optional ``tags`` separated by ; or |, and
    ``target_url``), or a plain list with one keyword per line."""
    text = Path(path).read_text(encoding="utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    header = [h.strip().lower() for h in next(csv.reader([lines[0]]))]
    if "keyword" not in header:
        return [{"keyword": ln.split(",")[0].strip(), "tags": [], "target_url": None} for ln in lines]
    out = []
    for row in csv.DictReader(io.StringIO("\n".join(lines))):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        tags = [t.strip() for t in re.split(r"[;|]", row.get("tags", "")) if t.strip()]
        out.append({"keyword": row.get("keyword", ""), "tags": tags,
                    "target_url": row.get("target_url") or None})
    return out


def remove_keywords(conn, project: str, keywords: Iterable[str], purge: bool = False) -> dict:
    removed, purged = [], 0
    for raw in keywords:
        kw = norm_keyword(raw)
        cur = conn.execute("DELETE FROM keywords WHERE project=? AND keyword=?", (project, kw))
        if cur.rowcount:
            removed.append(kw)
        if purge:
            purged += conn.execute("DELETE FROM obs WHERE project=? AND keyword=?",
                                   (project, kw)).rowcount
    conn.commit()
    return {"removed": removed, "observations_purged": purged}


def list_keywords(conn, project: str, tag: Optional[str] = None) -> list[dict]:
    out = []
    for r in conn.execute("SELECT keyword, tags, target_url, added_at FROM keywords "
                          "WHERE project=? ORDER BY keyword", (project,)):
        tags = _tags(r["tags"])
        if tag and tag not in tags:
            continue
        stats = conn.execute("SELECT COUNT(*) AS n, MAX(date) AS last FROM obs "
                             "WHERE project=? AND keyword=?", (project, r["keyword"])).fetchone()
        out.append({"keyword": r["keyword"], "tags": tags, "target_url": r["target_url"],
                    "added_at": r["added_at"], "observations": stats["n"],
                    "last_observed": stats["last"]})
    return out


def upsert_obs(conn, rows: Iterable[dict]) -> int:
    n = 0
    for r in rows:
        conn.execute(
            "INSERT INTO obs (project, date, keyword, page, country, device, clicks, impressions, "
            "ctr, position, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(project, date, keyword, page, country, device, source) DO UPDATE SET "
            "clicks=excluded.clicks, impressions=excluded.impressions, ctr=excluded.ctr, "
            "position=excluded.position",
            (r["project"], r["date"], r["keyword"], r.get("page") or "",
             r.get("country") or "all", r.get("device") or "all", r.get("clicks"),
             r.get("impressions"), r.get("ctr"), r.get("position"), r["source"]))
        n += 1
    conn.commit()
    return n


# ---------------------------------------------------------------------------
# GSC ingest
# ---------------------------------------------------------------------------

def keyword_filter_chunks(keywords: Iterable[str], max_len: int = GSC_REGEX_MAX) -> list[str]:
    """Split tracked keywords into ``^(a|b|c)$`` RE2 expressions under max_len."""
    chunks, current = [], []
    for kw in sorted({norm_keyword(k) for k in keywords if norm_keyword(k)}):
        esc = re2_escape(kw)
        if current and len("^(" + "|".join(current + [esc]) + ")$") > max_len:
            chunks.append("^(" + "|".join(current) + ")$")
            current = []
        current.append(esc)
    if current:
        chunks.append("^(" + "|".join(current) + ")$")
    return chunks


def _live_gsc_fetch(prop: str, start: str, end: str, dimensions: list, filters: Optional[list]) -> dict:
    try:
        import gsc_query
    except SystemExit as exc:  # gsc_query exits when google-api-python-client is missing
        raise RuntimeError("google-api-python-client is not installed") from exc
    return gsc_query.query_search_analytics(prop, start_date=start, end_date=end,
                                            dimensions=dimensions, row_limit=GSC_ROW_CAP,
                                            filters=filters, data_state="final")


def fetch_gsc_rows(prop: str, start: str, end: str, keywords: Optional[list[str]],
                   fetch: Optional[Callable] = None) -> dict:
    """Fetch [date, query, page] rows; one call per keyword-regex chunk.

    ``keywords=None`` fetches every query (``--all-queries``). Filtering on the
    server keeps tracked keywords from being cut off by the row cap.
    """
    fetch = fetch or _live_gsc_fetch
    dims = ["date", "query", "page"]
    filter_sets: list[Optional[list]] = (
        [None] if keywords is None else
        [[{"dimension": "query", "operator": "includingRegex", "expression": expr}]
         for expr in keyword_filter_chunks(keywords)])
    rows, truncated = [], False
    for flt in filter_sets:
        res = fetch(prop, start, end, dims, flt)
        if res.get("error"):
            raise RuntimeError(res["error"])
        rows.extend(res.get("rows") or [])
        # Truncated when a call returned as many rows as it was allowed to:
        # gsc_query stops paginating at GSC_ROW_CAP and drops the rest.
        truncated = truncated or max(res.get("row_count") or 0, len(res.get("rows") or [])) >= GSC_ROW_CAP
    return {"rows": rows, "calls": len(filter_sets), "truncated": truncated}


def gsc_rows_to_obs(rows: Iterable[dict], project: str) -> list[dict]:
    """Convert gsc_query-style rows (keys or named dims) to observations.

    CTR is recomputed as clicks/impressions (a 0-1 fraction); gsc_query.py
    reports it as a percent.
    """
    out = []
    for r in rows:
        keys = r.get("keys") or []
        day = parse_day(r.get("date") or (keys[0] if len(keys) > 0 else ""))
        query = norm_keyword(r.get("query") or (keys[1] if len(keys) > 1 else ""))
        page = r.get("page") or (keys[2] if len(keys) > 2 else "")
        if not day or not query:
            continue
        clicks = _num(r.get("clicks")) or 0.0
        imps = _num(r.get("impressions")) or 0.0
        pos = _num(r.get("position"))
        out.append({"project": project, "date": day, "keyword": query, "page": page,
                    "country": r.get("country") or "all", "device": r.get("device") or "all",
                    "clicks": clicks, "impressions": imps,
                    "ctr": round(clicks / imps, 6) if imps > 0 else None,
                    "position": pos if pos and pos > 0 else None, "source": GSC_SOURCE})
    return out


def ingest_gsc(conn, project: str, rows: Iterable[dict], all_queries: bool = False) -> dict:
    tracked = {k["keyword"] for k in list_keywords(conn, project)}
    obs = gsc_rows_to_obs(rows, project)
    keep = obs if all_queries else [o for o in obs if o["keyword"] in tracked]
    stored = upsert_obs(conn, keep)
    dates = sorted({o["date"] for o in keep})
    return {"rows_in": len(obs), "rows_stored": stored,
            "untracked_skipped": len(obs) - len(keep),
            "keywords_seen": len({o["keyword"] for o in keep}),
            "tracked_without_data": sorted(tracked - {o["keyword"] for o in keep}),
            "date_range": {"start": dates[0], "end": dates[-1]} if dates else None}


# ---------------------------------------------------------------------------
# SERP imports
# ---------------------------------------------------------------------------

_COLUMN_ALIASES = {
    "keyword": ("keyword", "query", "search term", "keyphrase", "term"),
    "position": ("position", "rank", "current position", "rank_group", "rank group",
                 "organic position", "google position", "rank_absolute", "pos"),
    "url": ("url", "current url", "ranking url", "page", "landing page", "result url"),
    "date": ("date", "current date", "check date", "checked at", "last update", "updated",
             "datetime", "timestamp"),
    "country": ("country", "country code", "location"),
    "device": ("device",),
}


def load_structured(path: str) -> Any:
    """Load JSON, JSON Lines or CSV (comma/semicolon/tab; '#' comment lines skipped)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    stripped = text.lstrip()
    if path.lower().endswith(".jsonl"):
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(text)
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    try:
        dialect = csv.Sniffer().sniff(lines[0], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO("\n".join(lines)), dialect=dialect))


def _pick(row: dict, field: str) -> Any:
    lowered = {(k or "").strip().lower(): v for k, v in row.items()}
    for alias in _COLUMN_ALIASES[field]:
        if alias in lowered and lowered[alias] not in (None, ""):
            return lowered[alias]
    return None


def _flatten_dataforseo(data: dict, project: str, default_day: str) -> list[dict]:
    """DataForSEO SERP API response -> one row per keyword (best organic hit)."""
    out = []
    for task in data.get("tasks") or []:
        if task.get("status_code") not in (None, 20000):
            continue
        for res in task.get("result") or []:
            best = None
            for item in res.get("items") or []:
                if item.get("type") != "organic":
                    continue
                if not host_matches(item.get("url") or item.get("domain") or "", project):
                    continue
                pos = _num(item.get("rank_group") or item.get("rank_absolute"))
                if pos and (best is None or pos < best[0]):
                    best = (pos, item.get("url") or "")
            out.append({"keyword": res.get("keyword"),
                        "date": parse_day(res.get("datetime")) or default_day,
                        "position": best[0] if best else None, "url": best[1] if best else ""})
    return out


def normalize_serp_rows(data: Any, project: str, source: str, default_day: str) -> dict:
    """Normalize an export to observations. Rows for other domains are skipped
    (competitor rows in a shared export); missing/0/'-' positions = not ranking."""
    if isinstance(data, dict) and "tasks" in data:
        raw = _flatten_dataforseo(data, project, default_day)
    elif isinstance(data, dict):
        raw = next((data[k] for k in ("rows", "items", "data", "keywords")
                    if isinstance(data.get(k), list)), [])
    else:
        raw = data or []
    obs, skipped_domain, skipped_invalid, defaulted_date = [], 0, 0, 0
    for row in raw:
        if not isinstance(row, dict):
            skipped_invalid += 1
            continue
        kw = norm_keyword(str(_pick(row, "keyword") or ""))
        if not kw:
            skipped_invalid += 1
            continue
        url = str(_pick(row, "url") or "").strip()
        if url and not url.startswith("/") and not host_matches(url, project):
            skipped_domain += 1
            continue
        raw_day = _pick(row, "date")
        day = parse_day(raw_day) if raw_day else None
        if raw_day and not day:
            skipped_invalid += 1
            continue
        if not day:
            day, defaulted_date = default_day, defaulted_date + 1
        pos = _num(_pick(row, "position"))
        obs.append({"project": project, "date": day, "keyword": kw, "page": url,
                    "country": str(_pick(row, "country") or "all").lower(),
                    "device": str(_pick(row, "device") or "all").lower(),
                    "clicks": None, "impressions": None, "ctr": None,
                    "position": pos if pos and pos > 0 else None, "source": source})
    return {"obs": obs, "skipped_other_domain": skipped_domain,
            "skipped_invalid": skipped_invalid, "defaulted_date": defaulted_date}


def import_serp(conn, project: str, path: str, source: str, default_day: str) -> dict:
    if source not in SERP_SOURCES:
        raise ValueError(f"source must be one of {', '.join(SERP_SOURCES)}")
    norm = normalize_serp_rows(load_structured(path), project, source, default_day)
    stored = upsert_obs(conn, norm["obs"])
    tracked = {k["keyword"] for k in list_keywords(conn, project)}
    seen = {o["keyword"] for o in norm["obs"]}
    return {"source": source, "rows_stored": stored,
            "skipped_other_domain": norm["skipped_other_domain"],
            "skipped_invalid": norm["skipped_invalid"],
            "rows_without_date_used": default_day if norm["defaulted_date"] else None,
            "untracked_keywords_stored": sorted(seen - tracked)}


# ---------------------------------------------------------------------------
# Window aggregation
# ---------------------------------------------------------------------------

def window_bounds(as_of: date, window: int, lag: int) -> dict:
    cur_end = as_of - timedelta(days=lag)
    cur_start = cur_end - timedelta(days=window - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=window - 1)
    return {"current": (cur_start, cur_end), "previous": (prev_start, prev_end)}


def fetch_obs(conn, project: str, source: str, start: date, end: date,
              country: Optional[str] = None, device: Optional[str] = None) -> list[dict]:
    sql = ("SELECT date, keyword, page, country, device, clicks, impressions, position "
           "FROM obs WHERE project=? AND source=? AND date BETWEEN ? AND ?")
    params: list[Any] = [project, source, start.isoformat(), end.isoformat()]
    if country:
        sql += " AND country=?"
        params.append(country.lower())
    if device:
        sql += " AND device=?"
        params.append(device.lower())
    return [dict(r) for r in conn.execute(sql + " ORDER BY date, keyword, page", params)]


def _median_with_unranked(values: list[Optional[float]]) -> Optional[float]:
    """Median where None (not found in the checked depth) sorts as worst."""
    if not values:
        return None
    ordered = sorted(values, key=lambda v: float("inf") if v is None else v)
    n = len(ordered)
    mid = ordered[n // 2] if n % 2 else None
    if n % 2 == 0:
        a, b = ordered[n // 2 - 1], ordered[n // 2]
        mid = None if a is None or b is None else (a + b) / 2
    return mid


def aggregate(rows: list[dict], source: str) -> dict:
    """Summarize one keyword's rows for one window."""
    if not rows:
        return {"position": None, "clicks": None, "impressions": None, "ctr": None,
                "top_page": None, "days": 0}
    pages: dict[str, dict] = {}
    for r in rows:
        p = pages.setdefault(r["page"] or "", {"imps": 0.0, "clicks": 0.0, "wpos": 0.0, "obs": 0,
                                               "ranks": []})
        p["obs"] += 1
        if source == GSC_SOURCE:
            imps = r["impressions"] or 0.0
            p["imps"] += imps
            p["clicks"] += r["clicks"] or 0.0
            if r["position"]:
                p["wpos"] += r["position"] * imps
        elif r["position"]:
            p["ranks"].append(r["position"])
    days = len({r["date"] for r in rows})
    if source == GSC_SOURCE:
        imps = sum(p["imps"] for p in pages.values())
        clicks = sum(p["clicks"] for p in pages.values())
        position = sum(p["wpos"] for p in pages.values()) / imps if imps > 0 else None
        top = sorted(((pg, p) for pg, p in pages.items() if p["imps"] > 0),
                     key=lambda kv: (-kv[1]["imps"], -kv[1]["clicks"], kv[0]))
        return {"position": round(position, 2) if position else None, "clicks": clicks,
                "impressions": imps, "ctr": round(clicks / imps, 4) if imps > 0 else None,
                "top_page": top[0][0] if top else None, "days": days}
    by_day: dict[str, Optional[float]] = {}
    for r in rows:
        cur = by_day.get(r["date"])
        if r["position"] and (cur is None or r["position"] < cur):
            by_day[r["date"]] = r["position"]
        else:
            by_day.setdefault(r["date"], cur)
    position = _median_with_unranked(list(by_day.values()))
    top = sorted(((pg, p) for pg, p in pages.items() if p["ranks"] and pg),
                 key=lambda kv: (-len(kv[1]["ranks"]), statistics.median(kv[1]["ranks"]), kv[0]))
    return {"position": round(position, 2) if position else None, "clicks": None,
            "impressions": None, "ctr": None, "top_page": top[0][0] if top else None,
            "days": days, "days_ranked": sum(1 for v in by_day.values() if v)}


def _by_keyword(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["keyword"], []).append(r)
    return out


def visibility_index(positions: Iterable[Optional[float]]) -> Optional[float]:
    """100 x mean(expected_ctr(pos) / expected_ctr(1)); unranked counts as 0."""
    vals = list(positions)
    if not vals:
        return None
    top = expected_ctr(1)
    return round(100 * sum(expected_ctr(p) / top if p else 0.0 for p in vals) / len(vals), 1)


def delta_stats(deltas: list[float]) -> dict:
    improved = sum(1 for d in deltas if d >= SIGN_TIE_EPS)
    declined = sum(1 for d in deltas if d <= -SIGN_TIE_EPS)
    return {"measured": len(deltas),
            "median_delta": round(statistics.median(deltas), 2) if deltas else None,
            "improved": improved, "declined": declined,
            "unchanged": len(deltas) - improved - declined,
            "sign_test_p": sign_test_p(improved, declined)}


def _status(prev: Optional[float], cur: Optional[float], delta: Optional[float]) -> str:
    if prev and cur:
        return "improved" if delta >= SIGN_TIE_EPS else "declined" if delta <= -SIGN_TIE_EPS else "stable"
    if cur:
        return "entered"
    if prev:
        return "dropped"
    return "no_data"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(conn, project: str, as_of: Optional[date] = None, window: int = 7, lag: int = 3,
                 min_impressions: float = 10, tag: Optional[str] = None, source: str = GSC_SOURCE,
                 brand_terms: Iterable[str] = (), country: Optional[str] = None,
                 device: Optional[str] = None) -> dict:
    """Movers, bands, visibility, cannibalization, URL swaps and per-tag stats."""
    if window < 1 or lag < 0:
        raise ValueError("window must be >= 1 and lag >= 0")
    as_of = as_of or date.fromisoformat(today())
    bounds = window_bounds(as_of, window, lag)
    (cs, ce), (ps, pe) = bounds["current"], bounds["previous"]
    tracked = list_keywords(conn, project, tag)
    is_gsc = source == GSC_SOURCE
    cur_rows = fetch_obs(conn, project, source, cs, ce, country, device)
    prev_rows = fetch_obs(conn, project, source, ps, pe, country, device)
    cur_by, prev_by = _by_keyword(cur_rows), _by_keyword(prev_rows)

    keywords = []
    for k in tracked:
        cur = aggregate(cur_by.get(k["keyword"], []), source)
        prev = aggregate(prev_by.get(k["keyword"], []), source)
        delta = (round(prev["position"] - cur["position"], 2)
                 if prev["position"] and cur["position"] else None)
        floor_ok = (not is_gsc) or ((cur["impressions"] or 0) >= min_impressions
                                    and (prev["impressions"] or 0) >= min_impressions)
        swap = None
        if cur["top_page"] and prev["top_page"] and not same_url(cur["top_page"], prev["top_page"]):
            swap = {"from": prev["top_page"], "to": cur["top_page"]}
        keywords.append({
            "keyword": k["keyword"], "tags": k["tags"], "target_url": k["target_url"],
            "current": cur, "previous": prev, "delta": delta,
            "band": position_band(cur["position"]), "previous_band": position_band(prev["position"]),
            "status": _status(prev["position"], cur["position"], delta),
            "mover": delta is not None and abs(delta) >= MOVER_MIN_DELTA and floor_ok,
            "url_swap": swap,
            "target_match": (same_url(cur["top_page"], k["target_url"])
                             if k["target_url"] and cur["top_page"] else None),
        })

    bands = ("top3", "page1", "striking", "deep", "far", "unranked")
    band_counts = {b: sum(1 for k in keywords if k["band"] == b) for b in bands}
    band_prev = {b: sum(1 for k in keywords if k["previous_band"] == b) for b in bands}
    cur_positions = [k["current"]["position"] for k in keywords]
    # No observations at all in a window means "not measured", not "unranked":
    # report null rather than zeros so a missed ingest cannot look like a collapse.
    vis_cur = visibility_index(cur_positions) if cur_rows else None
    vis_prev = visibility_index(k["previous"]["position"] for k in keywords) if prev_rows else None

    kpis = {
        "rank.tracked": len(keywords),
        "rank.top3": sum(1 for p in cur_positions if p and p <= 3) if cur_rows else None,
        "rank.top10": sum(1 for p in cur_positions if p and p <= 10) if cur_rows else None,
        "rank.striking": sum(1 for p in cur_positions if is_striking_distance(p)) if cur_rows else None,
        "rank.visibility": vis_cur,
    }

    movers = [k for k in keywords if k["mover"]]
    gainers = sorted((k for k in movers if k["delta"] > 0), key=lambda k: (-k["delta"], k["keyword"]))
    losers = sorted((k for k in movers if k["delta"] < 0), key=lambda k: (k["delta"], k["keyword"]))

    def brief(k: dict) -> dict:
        return {"keyword": k["keyword"], "previous": k["previous"]["position"],
                "current": k["current"]["position"], "delta": k["delta"],
                "impressions": k["current"]["impressions"], "page": k["current"]["top_page"]}

    tracked_set = {k["keyword"] for k in keywords}
    limitations = []
    cannibal: list[dict] = []
    if is_gsc:
        pair: dict[tuple, dict] = {}
        for r in cur_rows:  # all stored queries, so page totals are as complete as the store
            a = pair.setdefault((r["keyword"], r["page"]),
                                {"query": r["keyword"], "page": r["page"], "clicks": 0.0,
                                 "impressions": 0.0, "_w": 0.0})
            a["clicks"] += r["clicks"] or 0.0
            a["impressions"] += r["impressions"] or 0.0
            a["_w"] += (r["position"] or 0.0) * (r["impressions"] or 0.0)
        cann_rows = [{**a, "position": round(a["_w"] / a["impressions"], 2) if a["impressions"] else None}
                     for a in pair.values()]
        cannibal = [c for c in detect_cannibalization(cann_rows, brand_terms)
                    if c["query"] in tracked_set]
        limitations.append("Cannibalization page shares are computed over stored rows only; ingest "
                           "with --all-queries for the strict page-share test")
    else:
        limitations.append("Cannibalization needs click data and is computed for GSC only")

    tag_names = sorted({t for k in keywords for t in k["tags"]})
    tag_stats = {}
    for t in tag_names:
        group = [k for k in keywords if t in k["tags"]]
        stats = delta_stats([k["delta"] for k in group if k["delta"] is not None])
        stats.update({"keywords": len(group),
                      "visibility": visibility_index(k["current"]["position"] for k in group)})
        tag_stats[t] = stats

    if not cur_rows:
        limitations.append(f"No {source} observations in the current window; rank KPIs are null "
                           "(run ingest-gsc / import first)")
    if not tracked:
        limitations.append("No tracked keywords" + (f" with tag {tag!r}" if tag else "")
                           + "; add some with: rank_tracker.py add")
    distinct = {(r["country"], r["device"]) for r in cur_rows}
    if len(distinct) > 1:
        limitations.append(f"Rows span {len(distinct)} country/device combinations and were "
                           "combined; pass --country/--device to separate them")
    if is_gsc:
        limitations += [
            "GSC data lags 2-3 days; windows end --lag days before --as-of",
            "GSC anonymizes rare queries; a low-volume tracked keyword can show no data while ranking",
        ]
    if tag:
        limitations.append(f"Filtered to tag {tag!r}: rank.* KPIs describe that subset only")

    return {
        "project": project, "generated_at": utc_now(), "as_of": as_of.isoformat(), "source": source,
        "windows": {"current": {"start": cs.isoformat(), "end": ce.isoformat()},
                    "previous": {"start": ps.isoformat(), "end": pe.isoformat()},
                    "window_days": window, "lag_days": lag},
        "parameters": {"min_impressions": min_impressions, "mover_min_delta": MOVER_MIN_DELTA,
                       "unchanged_below": SIGN_TIE_EPS, "tag": tag, "country": country,
                       "device": device},
        "summary": {
            "tracked": len(keywords),
            "observations": {"current": len(cur_rows), "previous": len(prev_rows)},
            "ranked_current": sum(1 for p in cur_positions if p),
            **{s: sum(1 for k in keywords if k["status"] == s)
               for s in ("improved", "declined", "stable", "entered", "dropped", "no_data")},
            "visibility": {"current": vis_cur, "previous": vis_prev,
                           "delta": (round(vis_cur - vis_prev, 1)
                                     if vis_cur is not None and vis_prev is not None else None)},
            "bands": band_counts, "bands_previous": band_prev,
        },
        "kpis": kpis,
        "movers": {"gainers": [brief(k) for k in gainers], "losers": [brief(k) for k in losers]},
        "entered": [brief(k) for k in keywords if k["status"] == "entered"],
        "dropped": [brief(k) for k in keywords if k["status"] == "dropped"],
        "url_swaps": [{"keyword": k["keyword"], **k["url_swap"], "delta": k["delta"]}
                      for k in keywords if k["url_swap"]],
        "target_mismatches": [{"keyword": k["keyword"], "target_url": k["target_url"],
                               "ranking_url": k["current"]["top_page"]}
                              for k in keywords if k["target_match"] is False],
        "cannibalization": cannibal,
        "tags": tag_stats,
        "keywords": keywords,
        "notes": {"position": POSITION_NOTE if is_gsc else SERP_NOTE,
                  "visibility": "100 x mean(expected CTR at position / expected CTR at #1) over "
                                f"tracked keywords, unranked = 0; curve: {CTR_CURVE_SOURCE}",
                  "delta": "previous - current position; positive = improved"},
        "data_sources": ["Google Search Console Search Analytics (date x query x page)" if is_gsc
                         else f"SERP import ({source})", "Local rank store (seo_store 'rankings')"],
        "limitations": limitations,
    }


# ---------------------------------------------------------------------------
# Holdout experiment
# ---------------------------------------------------------------------------

def holdout_verdict(treatment: dict, control: dict, horizon_complete: bool,
                    alpha: float = 0.05, min_effect: float = 1.0) -> dict:
    """Pre-registered decision rule (see references/measurement-protocol.md).

    ``treatment`` must carry ``adjusted`` stats: each treatment keyword's delta
    minus the control group's median delta, so site-wide or algorithm movement
    that hits both groups cancels out.
    """
    adj = treatment.get("adjusted") or {}
    if not horizon_complete:
        return {"verdict": "Keep-testing", "reason": "pre-registered horizon not reached; "
                "interim numbers are shown but no decision is made on them"}
    if not control.get("measured"):
        return {"verdict": "Unproven", "reason": "no measurable control keywords; the change "
                "cannot be separated from site-wide or algorithm movement"}
    if (adj.get("measured") or 0) < MIN_SIGN_TEST_N:
        return {"verdict": "Unproven", "reason": f"fewer than {MIN_SIGN_TEST_N} measurable "
                "treatment keywords; a two-sided sign test cannot reach p < 0.05"}
    med, p = adj.get("median_delta"), adj.get("sign_test_p", 1.0)
    if med is not None and med >= min_effect and p < alpha:
        return {"verdict": "Promote", "reason": f"control-adjusted median gain {med:+.2f} positions "
                f"(>= {min_effect}), sign test p={p:.4f} < {alpha}"}
    if med is not None and med <= -min_effect and p < alpha:
        return {"verdict": "Rollback", "reason": f"control-adjusted median loss {med:+.2f} positions "
                f"(<= -{min_effect}), sign test p={p:.4f} < {alpha}"}
    return {"verdict": "Unproven", "reason": f"horizon reached without a significant control-adjusted "
            f"effect of at least {min_effect} position (median {med}, p={p}); re-register a larger "
            "or longer test rather than extending this one"}


def run_experiment(conn, project: str, treatment_tag: str, control_tag: str, start: date,
                   horizon: int = 28, as_of: Optional[date] = None, lag: int = 3,
                   source: str = GSC_SOURCE, min_impressions: float = 10,
                   alpha: float = 0.05, min_effect: float = 1.0) -> dict:
    """Compare equal-length pre/post windows around ``start`` for two tag groups."""
    as_of = as_of or date.fromisoformat(today())
    data_end = as_of - timedelta(days=lag)
    post_end_planned = start + timedelta(days=horizon - 1)
    horizon_complete = data_end >= post_end_planned
    post = (start, min(post_end_planned, data_end))
    pre = (start - timedelta(days=horizon), start - timedelta(days=1))
    if post[1] < post[0]:
        raise ValueError(f"no post-start data yet: data runs to {data_end}, test starts {start}")
    is_gsc = source == GSC_SOURCE
    pre_by = _by_keyword(fetch_obs(conn, project, source, *pre))
    post_by = _by_keyword(fetch_obs(conn, project, source, *post))

    def group(tag: str) -> dict:
        members = list_keywords(conn, project, tag)
        rows, deltas, excluded = [], [], []
        for k in members:
            a = aggregate(pre_by.get(k["keyword"], []), source)
            b = aggregate(post_by.get(k["keyword"], []), source)
            enough = (not is_gsc) or ((a["impressions"] or 0) >= min_impressions
                                      and (b["impressions"] or 0) >= min_impressions)
            d = round(a["position"] - b["position"], 2) if a["position"] and b["position"] else None
            if d is None or not enough:
                excluded.append(k["keyword"])
            else:
                deltas.append(d)
            rows.append({"keyword": k["keyword"], "pre": a["position"], "post": b["position"],
                         "delta": d if enough else None})
        stats = delta_stats(deltas)
        stats.update({"tag": tag, "keywords": len(members), "excluded_insufficient_data": excluded,
                      "rows": rows, "_deltas": deltas})
        return stats

    t, c = group(treatment_tag), group(control_tag)
    overlap = sorted({r["keyword"] for r in t["rows"]} & {r["keyword"] for r in c["rows"]})
    c_med = c["median_delta"]
    t["adjusted"] = (delta_stats([d - c_med for d in t["_deltas"]]) if c_med is not None
                     else {"measured": 0})
    t.pop("_deltas")
    c.pop("_deltas")
    decision = holdout_verdict(t, c, horizon_complete, alpha, min_effect)
    caveats = []
    if overlap:
        caveats.append(f"{len(overlap)} keyword(s) carry both tags; they contaminate the comparison")
    if c.get("measured") and c["sign_test_p"] < alpha:
        caveats.append("the control group itself moved significantly: site-wide or algorithm "
                       "movement during the test; the adjusted effect accounts for its median only")
    if c.get("measured", 0) < t.get("measured", 0):
        caveats.append("control group is smaller than treatment; its median is noisier")
    return {
        "project": project, "as_of": as_of.isoformat(), "source": source,
        "design": {"treatment_tag": treatment_tag, "control_tag": control_tag,
                   "start": start.isoformat(), "horizon_days": horizon,
                   "pre_window": {"start": pre[0].isoformat(), "end": pre[1].isoformat()},
                   "post_window": {"start": post[0].isoformat(), "end": post[1].isoformat()},
                   "horizon_complete": horizon_complete, "alpha": alpha,
                   "min_effect_positions": min_effect, "min_impressions": min_impressions},
        "treatment": t, "control": c, **decision, "caveats": caveats,
        "notes": {"delta": "pre - post position; positive = improved",
                  "position": POSITION_NOTE if is_gsc else SERP_NOTE},
        "limitations": ["Sign test on control-adjusted deltas treats the control median as fixed; "
                        "small control groups make it noisy",
                        "Rankings are a lagging outcome; see the measurement protocol for "
                        "leading indicators to watch during the horizon"],
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def keyword_history(conn, project: str, keyword: str) -> list[dict]:
    kw = norm_keyword(keyword)
    rows = [dict(r) for r in conn.execute(
        "SELECT date, source, page, country, device, clicks, impressions, position FROM obs "
        "WHERE project=? AND keyword=? ORDER BY date, source", (project, kw))]
    grouped: dict[tuple, list[dict]] = {}
    for r in rows:
        grouped.setdefault((r["date"], r["source"]), []).append(r)
    out = []
    for (day, src), rs in sorted(grouped.items()):
        agg = aggregate(rs, src)
        out.append({"date": day, "source": src, "position": agg["position"],
                    "clicks": agg["clicks"], "impressions": agg["impressions"],
                    "page": agg["top_page"], "pages": len({r["page"] for r in rs})})
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _date_arg(value: str) -> date:
    day = parse_day(value)
    if not day or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        raise argparse.ArgumentTypeError(f"invalid date {value!r} (expected YYYY-MM-DD)")
    return date.fromisoformat(day)


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return n


def _fmt_pos(p: Optional[float]) -> str:
    return "-" if not p else f"{p:.1f}"


def _print_report(rep: dict) -> None:
    w = rep["windows"]
    s = rep["summary"]
    print(f"=== Rank report: {rep['project']} ({rep['source']}) ===")
    print(f"Current {w['current']['start']}..{w['current']['end']} vs previous "
          f"{w['previous']['start']}..{w['previous']['end']}  (lag {w['lag_days']}d)")
    print(f"Note: {rep['notes']['position']}")
    vis = s["visibility"]
    print(f"Tracked {s['tracked']} | ranked {s['ranked_current']} | improved {s['improved']} | "
          f"declined {s['declined']} | entered {s['entered']} | dropped {s['dropped']} | "
          f"no data {s['no_data']}")
    print(f"Visibility index {vis['current']} (prev {vis['previous']}, delta {vis['delta']})")
    print("Bands: " + ", ".join(f"{b} {n}" for b, n in s["bands"].items()))
    for label, items in (("Gainers", rep["movers"]["gainers"]), ("Losers", rep["movers"]["losers"])):
        if items:
            print(f"\n{label} (|delta| >= {MOVER_MIN_DELTA}):")
            for m in items[:15]:
                print(f"  {m['keyword']:<40} {_fmt_pos(m['previous']):>6} -> {_fmt_pos(m['current']):>6}"
                      f"  ({m['delta']:+.1f})")
    for sw in rep["url_swaps"][:10]:
        print(f"URL swap: {sw['keyword']}: {sw['from']} -> {sw['to']}")
    for mm in rep["target_mismatches"][:10]:
        print(f"Target mismatch: {mm['keyword']}: ranks {mm['ranking_url']}, target {mm['target_url']}")
    for c in rep["cannibalization"][:10]:
        print(f"Cannibalization: {c['query']}: " + ", ".join(
            f"{p['page']} ({p['query_share']:.0%})" for p in c["pages"]))
    if rep["tags"]:
        print("\nTags:")
        for t, st in rep["tags"].items():
            print(f"  {t:<24} n={st['keywords']} measured={st['measured']} median delta="
                  f"{st['median_delta']} up={st['improved']} down={st['declined']} "
                  f"p={st['sign_test_p']} visibility={st['visibility']}")
    for lim in rep["limitations"]:
        print(f"  limitation: {lim}")


def main(argv: Optional[list[str]] = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", help="Storage root (default $CLAUDE_SEO_DATA_DIR or ~/.cache/claude-seo)")
    common.add_argument("--json", action="store_true", help="Output JSON")
    common.add_argument("--project", required=True, help="Project domain (keys every stored row)")

    parser = argparse.ArgumentParser(description="Keyword rank tracking (GSC history + SERP imports)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", parents=[common], help="Track keywords")
    p.add_argument("keywords", nargs="*")
    p.add_argument("--file", help="CSV with a keyword column (tags, target_url optional) or one per line")
    p.add_argument("--tag", action="append", default=[], help="Tag (repeatable), e.g. control:faq")
    p.add_argument("--target-url", help="URL that should rank for these keywords")

    p = sub.add_parser("remove", parents=[common], help="Stop tracking keywords")
    p.add_argument("keywords", nargs="+")
    p.add_argument("--purge-history", action="store_true", help="Also delete stored observations")

    p = sub.add_parser("list", parents=[common], help="List tracked keywords")
    p.add_argument("--tag")

    p = sub.add_parser("ingest-gsc", parents=[common], help="Store daily GSC rows")
    p.add_argument("--property", help="GSC property (default: profile gsc_property)")
    p.add_argument("--days", type=_positive_int, default=30)
    p.add_argument("--as-of", type=_date_arg, help="Treat this date as today (default today, UTC)")
    p.add_argument("--all-queries", action="store_true", help="Store every query, not only tracked ones")
    p.add_argument("--input", help="Offline gsc_query-style JSON rows instead of the API")

    p = sub.add_parser("import", parents=[common], help="Import SERP-tool rankings")
    p.add_argument("file")
    p.add_argument("--source", required=True, choices=SERP_SOURCES)
    p.add_argument("--date", type=_date_arg, help="Date for rows without one (default today)")

    p = sub.add_parser("report", parents=[common], help="Movers, bands, visibility, cannibalization, tags")
    p.add_argument("--window", type=_positive_int, default=7, help="Days per comparison window (default 7)")
    p.add_argument("--lag", type=int, default=3, help="Days of GSC lag to exclude (default 3)")
    p.add_argument("--min-impressions", type=float, default=10,
                   help="GSC impressions needed in BOTH windows to count as a mover")
    p.add_argument("--tag", help="Only keywords with this tag")
    p.add_argument("--source", default=GSC_SOURCE, choices=ALL_SOURCES)
    p.add_argument("--country", help="Only rows for this country code")
    p.add_argument("--device", help="Only rows for this device")
    p.add_argument("--as-of", type=_date_arg, help="Treat this date as today (default today, UTC)")
    p.add_argument("--emit-kpis", help="Write rank.* metrics as a KPI envelope to this path")

    p = sub.add_parser("experiment", parents=[common], help="Holdout verdict for a treatment vs control tag")
    p.add_argument("--treatment", required=True)
    p.add_argument("--control", required=True)
    p.add_argument("--start", required=True, type=_date_arg, help="Date the change shipped")
    p.add_argument("--horizon", type=_positive_int, default=28, help="Pre-registered post-period length in days")
    p.add_argument("--lag", type=int, default=3)
    p.add_argument("--min-impressions", type=float, default=10)
    p.add_argument("--min-effect", type=float, default=1.0, help="Minimum adjusted gain in positions")
    p.add_argument("--alpha", type=float, default=0.05)
    p.add_argument("--source", default=GSC_SOURCE, choices=ALL_SOURCES)
    p.add_argument("--as-of", type=_date_arg)

    p = sub.add_parser("history", parents=[common], help="Daily history for one keyword")
    p.add_argument("keyword")

    args = parser.parse_args(argv)
    try:
        project = norm_project(args.project)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    conn = open_store(args.data_dir)
    try:
        return _dispatch(args, conn, project)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError, EnvelopeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def _emit(args, payload: dict, text: Callable[[], None]) -> None:
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        text()


def _dispatch(args, conn, project: str) -> int:
    if args.cmd == "add":
        entries = [{"keyword": k, "tags": [], "target_url": None} for k in args.keywords]
        if args.file:
            entries += read_keyword_file(args.file)
        if not entries:
            raise ValueError("give keywords or --file")
        res = {"added": [], "updated": []}
        for e in entries:
            r = add_keywords(conn, project, [e["keyword"]], list(args.tag) + e["tags"],
                             args.target_url or e["target_url"])
            res["added"] += r["added"]
            res["updated"] += r["updated"]
        _emit(args, res, lambda: print(f"Added {len(res['added'])}, updated {len(res['updated'])} "
                                       f"keyword(s) for {project}"))
        return 0

    if args.cmd == "remove":
        res = remove_keywords(conn, project, args.keywords, args.purge_history)
        _emit(args, res, lambda: print(f"Removed {len(res['removed'])} keyword(s); "
                                       f"purged {res['observations_purged']} observation(s)"))
        return 0

    if args.cmd == "list":
        rows = list_keywords(conn, project, args.tag)

        def text() -> None:
            for r in rows:
                print(f"  {r['keyword']:<45} tags={','.join(r['tags']) or '-'} "
                      f"obs={r['observations']} last={r['last_observed'] or '-'}")
            print(f"{len(rows)} tracked keyword(s)")
        _emit(args, {"project": project, "keywords": rows}, text)
        return 0

    if args.cmd == "ingest-gsc":
        as_of = args.as_of or date.fromisoformat(today())
        end = as_of - timedelta(days=1)
        start = end - timedelta(days=args.days - 1)
        meta: dict[str, Any] = {"project": project, "source": GSC_SOURCE}
        if args.input:
            data = load_structured(args.input)
            rows = data.get("rows", []) if isinstance(data, dict) else data
            meta["input"] = os.path.basename(args.input)
        else:
            profile = load_profile(project, args.data_dir) or {}
            prop = args.property or profile.get("gsc_property")
            if not prop:
                raise ValueError("no GSC property: pass --property or set gsc_property in the profile")
            tracked = [k["keyword"] for k in list_keywords(conn, project)]
            if not tracked and not args.all_queries:
                raise ValueError("no tracked keywords; add some first or pass --all-queries")
            fetched = fetch_gsc_rows(prop, start.isoformat(), end.isoformat(),
                                     None if args.all_queries else tracked)
            rows = fetched["rows"]
            meta.update({"property": prop, "requested": {"start": start.isoformat(),
                                                         "end": end.isoformat()},
                         "api_calls": fetched["calls"], "truncated": fetched["truncated"]})
            if fetched["truncated"]:
                meta["warning"] = (f"hit the {GSC_ROW_CAP:,}-row cap; older or rarer rows may be "
                                   "missing (drop --all-queries or shorten --days)")
        res = {**meta, **ingest_gsc(conn, project, rows, args.all_queries),
               "notes": ["Unfinalized days are not returned (dataState=final); re-ingesting is "
                         "idempotent", POSITION_NOTE]}
        _emit(args, res, lambda: print(
            f"Stored {res['rows_stored']} GSC row(s) for {res['keywords_seen']} keyword(s) "
            f"({res['untracked_skipped']} untracked skipped); range {res['date_range']}"
            + (f"\n  no data for: {', '.join(res['tracked_without_data'][:20])}"
               if res["tracked_without_data"] else "")))
        return 0

    if args.cmd == "import":
        default_day = (args.date or date.fromisoformat(today())).isoformat()
        res = import_serp(conn, project, args.file, args.source, default_day)
        _emit(args, res, lambda: print(
            f"Imported {res['rows_stored']} {res['source']} row(s); skipped "
            f"{res['skipped_other_domain']} other-domain, {res['skipped_invalid']} invalid"
            + (f"; {len(res['untracked_keywords_stored'])} untracked keyword(s) stored "
               "(add them to report on them)" if res["untracked_keywords_stored"] else "")))
        return 0

    profile = load_profile(project, args.data_dir)
    brands = all_brand_terms(profile) if profile else []

    if args.cmd == "report":
        # rank.* KPIs describe the whole tracked set from Search Console. A
        # filtered report (one tag, one country/device, a SERP source) written
        # to the same (project, date, metric) keys would silently overwrite
        # the project-wide history, so it is refused instead.
        if args.emit_kpis:
            narrowed = [flag for flag, val in (("--tag", args.tag), ("--country", args.country),
                                               ("--device", args.device))
                        if val not in (None, "", "all")]
            if args.source not in (None, "gsc"):
                narrowed.append(f"--source {args.source}")
            if narrowed:
                print("Error: --emit-kpis records project-wide rank.* KPIs; it cannot be combined "
                      f"with {', '.join(narrowed)}. Run the filtered report without --emit-kpis.",
                      file=sys.stderr)
                return 2
        rep = build_report(conn, project, args.as_of, args.window, args.lag, args.min_impressions,
                           args.tag, args.source, brands, args.country, args.device)
        if args.emit_kpis:
            write_envelope(args.emit_kpis, project, "rank_tracker.py", rep["kpis"], rep["as_of"],
                           {"source": rep["source"], "window": rep["windows"]["current"],
                            "tag": args.tag, "curve": CTR_CURVE_SOURCE})
            rep["kpi_envelope_path"] = args.emit_kpis
        _emit(args, rep, lambda: _print_report(rep))
        return 0

    if args.cmd == "experiment":
        res = run_experiment(conn, project, args.treatment, args.control, args.start, args.horizon,
                             args.as_of, args.lag, args.source, args.min_impressions, args.alpha,
                             args.min_effect)

        def text() -> None:
            d = res["design"]
            print(f"=== Holdout: {d['treatment_tag']} vs {d['control_tag']} (start {d['start']}, "
                  f"horizon {d['horizon_days']}d) ===")
            for label in ("treatment", "control"):
                g = res[label]
                print(f"  {label:<9} n={g['keywords']} measured={g['measured']} median delta="
                      f"{g['median_delta']} up={g['improved']} down={g['declined']} p={g['sign_test_p']}")
            adj = res["treatment"].get("adjusted") or {}
            print(f"  adjusted  median={adj.get('median_delta')} p={adj.get('sign_test_p')}")
            print(f"Verdict: {res['verdict']} -- {res['reason']}")
            for c in res["caveats"]:
                print(f"  caveat: {c}")
        _emit(args, res, text)
        return 0

    # history
    rows = keyword_history(conn, project, args.keyword)

    def text() -> None:
        print(f"=== History: {norm_keyword(args.keyword)} ({project}) ===")
        for r in rows:
            imp = "" if r["impressions"] is None else f" imps={int(r['impressions'])} clicks={int(r['clicks'])}"
            print(f"  {r['date']} {r['source']:<10} pos={_fmt_pos(r['position'])}{imp} page={r['page'] or '-'}")
        if not rows:
            print("  (no observations)")
    _emit(args, {"project": project, "keyword": norm_keyword(args.keyword), "rows": rows,
                 "note": POSITION_NOTE}, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
