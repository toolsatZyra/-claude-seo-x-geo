#!/usr/bin/env python3
"""
Content decay detection and refresh candidates from Google Search Console.

Compares each page's clicks in the latest window with the same window a year
earlier (52 weeks back, so weekdays line up and seasonality cancels out). When
no year-earlier data exists, it falls back to the immediately preceding window
and says so, because that comparison does NOT control for seasonality.

For every page it reports the metrics per window, which baseline was used and
why, the change in clicks / impressions / position / CTR, CTR against the
expected CTR for its position, a decay tier, a rule-based cause diagnosis
(tagged INFERRED, per scoring-rubric Rule 9), a deterministic 0-100 decay
score and a recommended action with the rule that produced it.

Tiers (only when baseline clicks >= --min-baseline-clicks, default 20):
    warning <= -20% clicks, high <= -40%, critical <= -60%

Causes (first match wins; all matches are listed as secondary):
    lost_visibility             0 impressions now (left the index, redirected, URL changed)
    cannibalization             page splits non-branded queries with another page of the site
    ranking_loss                avg position worse by >= 1.0
    serp_feature_or_ai_overview impressions not down (> -15%), position flat (< 1.0 change),
                                CTR down >= 20%: something on the SERP takes the clicks
    demand_drop                 impressions down >= 15% with position flat or better
    unclear                     none of the above

Actions: refresh | rewrite | consolidate | redirect_or_retire_review | monitor.
Retirement is only ever a *review* item, never an automatic deletion, and is
never suggested for money pages. Rules and decay-score weights are documented
in skills/seo-refresh/references/refresh-rules.md.

``candidates`` lists Outrank-style improvement candidates: current impressions
>= --min-impressions (500), average position within --min-pos..--max-pos
(4-25), and CTR ratio vs expected < 0.7 OR clicks down >= 10% vs the previous
window. Each comes with its top queries as input for a refresh brief.

Usage:
    python content_decay.py analyze --project example.com [--json]
    python content_decay.py analyze --property sc-domain:example.com --days 90 --lag 3 \
        [--as-of 2026-10-17] [--min-baseline-clicks 20] [--json]
    python content_decay.py analyze --input windows.json --json
    python content_decay.py candidates --project example.com [--min-impressions 500] \
        [--min-pos 4] [--max-pos 25] [--json]

``--input`` JSON: {"current": [...], "previous": [...], "yoy": [...], "query_page": [...],
"windows": {...optional dates...}, "truncated": {"current": false, ...optional}}.
Rows: page, clicks, impressions, position (+ query for query_page). GSC-style
rows with "keys" are accepted; any "ctr" field is ignored and recomputed as
clicks / impressions. Set "truncated" for a window whose export hit a row cap.

Row limits: live queries ask GSC for up to 100,000 rows per window (the most
gsc_query.py pages through). A window that returns that many rows is
TRUNCATED: GSC drops the lowest-click pages, so a page missing from a
truncated current window is ``insufficient_data`` (rule R0c), never
``lost_visibility``, and is never routed to retirement.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_metrics import (CTR_CURVE_SOURCE, calibrate_ctr_curve, ctr_gap,  # noqa: E402
                         detect_cannibalization, pct_change)
from seo_project import all_brand_terms, load_profile  # noqa: E402
from seo_store import today, utc_now  # noqa: E402

TIERS = (("critical", -60.0), ("high", -40.0), ("warning", -20.0))
TIER_RANK = {"critical": 0, "high": 1, "warning": 2, "stable": 3, "insufficient_data": 4}
DECAYING = frozenset({"critical", "high", "warning"})
FLAT_IMPRESSIONS_PCT = 15.0
CTR_DROP_PCT = 20.0
POSITION_WORSE = 1.0
DEEP_POSITION = 20.0
POSITION_LOSS_FULL = 5.0
DECAY_WEIGHTS = {"click_loss": 45, "position_loss": 20, "ctr_shortfall": 20, "cannibalization": 15}
YOY_OFFSET_DAYS = 364
CANDIDATE_CTR_RATIO = 0.7
CANDIDATE_DECLINE_PCT = -10.0
TOP_QUERIES = 10
GSC_ROW_LIMIT = 100_000   # gsc_query.query_search_analytics pages through up to 100,000 rows
WINDOW_NAMES = ("current", "previous", "yoy", "query_page")

VERIFY_FIRST = {
    "lost_visibility": ["URL Inspection (gsc_inspect.py): indexed? canonical? noindex? HTTP status?",
                        "seo-drift compare if a baseline exists for this URL"],
    "cannibalization": ["choose one page per query (best intent match, links, conversions)",
                        "merge into it with a 301, or re-target the weaker page to a different intent"],
    "ranking_loss": ["seo-drift compare: did the title, H1, content or schema change?",
                     "check who now outranks the page for its top queries"],
    "serp_feature_or_ai_overview": ["look at the top queries' SERPs for an AI Overview or other features "
                                    "(manual check or DataForSEO)",
                                    "follow skills/seo-refresh/references/aio-recovery.md"],
    "demand_drop": ["check search interest for the top queries (Keyword Planner, Trends)",
                    "if the baseline was the previous window, rule out seasonality"],
    "unclear": ["compare query-level clicks for this page between the two windows"],
}


class DecayError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Rows and windows
# ---------------------------------------------------------------------------

def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_rows(rows, with_query: bool = False) -> list[dict]:
    """Coerce GSC rows into {page, clicks, impressions, position[, query]}; CTR is never trusted."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        keys = r.get("keys") or []
        page = r.get("page")
        query = r.get("query")
        if with_query:
            if query is None and len(keys) >= 2:
                query, page = keys[0], keys[1] if page is None else page
        elif page is None and keys:
            page = keys[0]
        if not page or (with_query and not query):
            continue
        pos = r.get("position")
        row = {"page": str(page).strip(), "clicks": _num(r.get("clicks")),
               "impressions": _num(r.get("impressions")),
               "position": _num(pos, None) if pos not in (None, "") else None}
        if with_query:
            row["query"] = str(query).strip()
        out.append(row)
    return out


def aggregate_pages(rows: list[dict]) -> dict[str, dict]:
    """Sum clicks/impressions per page; position is impression-weighted."""
    acc: dict[str, dict] = {}
    for r in rows:
        a = acc.setdefault(r["page"], {"clicks": 0.0, "impressions": 0.0, "_pos_w": 0.0, "_pos_imp": 0.0})
        a["clicks"] += r["clicks"]
        a["impressions"] += r["impressions"]
        if r.get("position") is not None and r["impressions"] > 0:
            a["_pos_w"] += r["position"] * r["impressions"]
            a["_pos_imp"] += r["impressions"]
    out = {}
    for page, a in acc.items():
        imps = a["impressions"]
        out[page] = {
            "clicks": round(a["clicks"], 2),
            "impressions": round(imps, 2),
            "ctr": round(a["clicks"] / imps, 4) if imps > 0 else 0.0,
            "position": round(a["_pos_w"] / a["_pos_imp"], 1) if a["_pos_imp"] > 0 else None,
        }
    return out


def compute_windows(as_of: date, days: int, lag: int) -> dict:
    """Current, previous and year-earlier (52 weeks back) windows of ``days`` days."""
    if days < 7:
        raise DecayError("--days must be at least 7")
    end = as_of - timedelta(days=lag)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    def win(s: date, e: date) -> dict:
        return {"start": s.isoformat(), "end": e.isoformat()}

    return {"current": win(start, end), "previous": win(prev_start, prev_end),
            "yoy": win(start - timedelta(days=YOY_OFFSET_DAYS), end - timedelta(days=YOY_OFFSET_DAYS))}


def _default_query_fn() -> Callable:
    try:
        from gsc_query import query_search_analytics
    except SystemExit as exc:  # gsc_query exits when google-api-python-client is missing
        raise DecayError("google-api-python-client is required for live GSC data "
                         "(or pass --input with exported rows)") from exc
    return query_search_analytics


def _is_truncated(res: dict, rows: list, limit: int) -> bool:
    """A window that returned as many rows as were requested may have been cut off."""
    try:
        reported = int(res.get("row_count") or 0)
    except (TypeError, ValueError):
        reported = 0
    return max(reported, len(rows)) >= limit


def fetch_live(prop: str, windows: dict, query_fn: Optional[Callable] = None,
               row_limit: Optional[int] = None) -> tuple[dict, list[str]]:
    """Pull page rows for each window and query x page rows for the current window.

    ``data["truncated"]`` flags every window whose result reached ``row_limit``
    (default GSC_ROW_LIMIT): GSC returned its top rows only, so pages can be
    missing from it although they had impressions.
    """
    query_fn = query_fn or _default_query_fn()
    limit = row_limit or GSC_ROW_LIMIT
    data: dict = {"truncated": {}}
    notes: list[str] = []
    for name in ("current", "previous", "yoy"):
        w = windows[name]
        res = query_fn(prop, start_date=w["start"], end_date=w["end"], dimensions=["page"],
                       row_limit=limit)
        if res.get("error"):
            if name == "current":
                raise DecayError(f"GSC query failed for the current window: {res['error']}")
            notes.append(f"{name} window unavailable: {res['error']}")
            data[name] = None
            continue
        data[name] = res.get("rows") or []
        data["truncated"][name] = _is_truncated(res, data[name], limit)
    w = windows["current"]
    res = query_fn(prop, start_date=w["start"], end_date=w["end"], dimensions=["query", "page"],
                   row_limit=limit)
    if res.get("error"):
        notes.append(f"query x page rows unavailable (no cannibalization or top queries): {res['error']}")
        data["query_page"] = None
    else:
        data["query_page"] = res.get("rows") or []
        data["truncated"]["query_page"] = _is_truncated(res, data["query_page"], limit)
    data["row_limit"] = limit
    return data, notes


# ---------------------------------------------------------------------------
# Per-page analysis
# ---------------------------------------------------------------------------

def _url_path(url: str) -> str:
    path = urlparse(url).path if "://" in url else url
    path = "/" + path.lstrip("/")
    return path.rstrip("/") or "/"


def is_money_page(page: str, money_pages: list[str]) -> bool:
    """Exact URL or path match (trailing slash ignored); entries ending in '*' match a prefix."""
    path = _url_path(page)
    for entry in money_pages or []:
        entry = str(entry).strip()
        if not entry:
            continue
        if entry.endswith("*"):
            if path.startswith(_url_path(entry[:-1]).rstrip("/") or "/"):
                return True
            continue
        if "://" in entry and entry.rstrip("/") == page.rstrip("/"):
            return True
        if _url_path(entry) == path:
            return True
    return False


def tier_for(clicks_pct: Optional[float]) -> str:
    if clicks_pct is None:
        return "stable"
    for name, threshold in TIERS:
        if clicks_pct <= threshold:
            return name
    return "stable"


def _deltas(base: Optional[dict], cur: dict) -> Optional[dict]:
    if not base:
        return None
    pos_change = (round(cur["position"] - base["position"], 1)
                  if cur.get("position") is not None and base.get("position") is not None else None)
    return {"clicks_pct": pct_change(base["clicks"], cur["clicks"]),
            "impressions_pct": pct_change(base["impressions"], cur["impressions"]),
            "position_change": pos_change,
            "ctr_pct": pct_change(base["ctr"], cur["ctr"]) if base["ctr"] > 0 else None,
            "lost_clicks": round(base["clicks"] - cur["clicks"], 1)}


def diagnose(cur: dict, base: dict, delta: dict, cannibal: list[dict], baseline_kind: str) -> dict:
    """Rule-based cause diagnosis. Returns {primary, secondary, evidence, basis}."""
    imp_pct, pos_chg, ctr_pct = delta["impressions_pct"], delta["position_change"], delta["ctr_pct"]
    matched: list[str] = []
    evidence: list[str] = []
    if cur["impressions"] <= 0 < base["impressions"]:
        matched.append("lost_visibility")
        evidence.append(f"0 impressions in the current window (baseline {int(base['impressions'])})")
    if cannibal:
        matched.append("cannibalization")
        sample = "; ".join(f"'{c['query']}' with {', '.join(o for o in c['others'][:2])}" for c in cannibal[:3])
        evidence.append(f"splits {len(cannibal)} non-branded quer{'y' if len(cannibal) == 1 else 'ies'} "
                        f"with other pages: {sample}")
    if pos_chg is not None and pos_chg >= POSITION_WORSE:
        matched.append("ranking_loss")
        evidence.append(f"avg position {base['position']} -> {cur['position']} (+{pos_chg}); "
                        f"impressions {imp_pct:+}%" if imp_pct is not None else
                        f"avg position {base['position']} -> {cur['position']} (+{pos_chg})")
    pos_flat = pos_chg is not None and abs(pos_chg) < POSITION_WORSE
    if (imp_pct is not None and imp_pct > -FLAT_IMPRESSIONS_PCT and pos_flat
            and ctr_pct is not None and ctr_pct <= -CTR_DROP_PCT):
        matched.append("serp_feature_or_ai_overview")
        note = (" (impressions rose: new low-CTR queries are an alternative explanation)"
                if imp_pct >= FLAT_IMPRESSIONS_PCT else "")
        evidence.append(f"impressions {imp_pct:+}%, position flat ({base['position']} -> {cur['position']}), "
                        f"CTR {base['ctr']:.2%} -> {cur['ctr']:.2%} ({ctr_pct:+}%){note}")
    if (imp_pct is not None and imp_pct <= -FLAT_IMPRESSIONS_PCT and pos_chg is not None
            and pos_chg < POSITION_WORSE and cur["impressions"] > 0):
        matched.append("demand_drop")
        season = ("; baseline is the previous window, so this may be seasonal"
                  if baseline_kind == "previous" else "")
        evidence.append(f"impressions {imp_pct:+}% with position flat or better "
                        f"({base['position']} -> {cur['position']}){season}")
    primary = matched[0] if matched else "unclear"
    if not matched:
        evidence.append("no single pattern matched; inspect query-level changes")
    return {"primary": primary, "secondary": matched[1:], "evidence": evidence,
            "basis": "INFERRED (rule-based pattern over CONFIRMED GSC metrics)"}


def _fmt_num(value: float) -> str:
    """Render a number so the expression string round-trips exactly (repr of the float)."""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def weighted_score(values: dict, weights: dict) -> tuple[Optional[int], Optional[str], int]:
    """(score, expression, total weight) for the available (non-None) components.

    The score is computed by the same arithmetic, in the same order, as the
    expression string shows, from the exact component values, so
    ``eval(expression) == score`` always holds. Rounding is Python ``round()``
    (ties to even), as in aeo_score.py.
    """
    terms = [(weights[k], values[k]) for k in weights if values.get(k) is not None]
    total_w = sum(w for w, _ in terms)
    if not total_w:
        return None, None, 0
    numerator = 0
    for w, v in terms:
        numerator = numerator + w * v
    expr = " + ".join(f"{w}*{_fmt_num(v)}" for w, v in terms)
    return round(100 * numerator / total_w), f"round(100 * ({expr}) / {total_w})", total_w


def decay_score(delta: dict, ctr_ratio: Optional[float], cannibalized: Optional[bool],
                lost_visibility: bool) -> dict:
    """0-100 decay severity; N/A components are excluded and weights renormalized."""
    comps: dict[str, Optional[float]] = {
        "click_loss": min(1.0, max(0.0, -(delta["clicks_pct"] or 0.0)) / 100.0),
        "position_loss": (1.0 if lost_visibility else
                          (min(1.0, max(0.0, delta["position_change"]) / POSITION_LOSS_FULL)
                           if delta["position_change"] is not None else None)),
        "ctr_shortfall": (min(1.0, max(0.0, 1.0 - ctr_ratio)) if ctr_ratio is not None else None),
        "cannibalization": (None if cannibalized is None else (1.0 if cannibalized else 0.0)),
    }
    score, expression, _ = weighted_score(comps, DECAY_WEIGHTS)
    return {"score": score if score is not None else 0,
            "components": {k: (round(v, 3) if v is not None else None) for k, v in comps.items()},
            "expression": expression,
            "excluded_as_na": [k for k in DECAY_WEIGHTS if comps[k] is None]}


def recommend(tier: str, cause: Optional[str], cur: dict, money: bool,
              absent_from_truncated: bool = False) -> dict:
    """Deterministic action rule. Returns {action, rule, why, verify_first, urgent}."""
    if absent_from_truncated:
        return {"action": "monitor", "rule": "R0c",
                "why": "missing from a current window that hit the GSC row limit: the page may still have "
                       "impressions below the cut, so a decline or lost visibility cannot be concluded",
                "verify_first": ["query GSC for this page alone (gsc_query.py with a page filter) for the "
                                 "current window",
                                 "URL Inspection (gsc_inspect.py) if that query returns nothing"],
                "urgent": False}
    if tier == "insufficient_data":
        return {"action": "monitor", "rule": "R0a", "why": "baseline clicks below the floor: too little data "
                "to call a decline", "verify_first": [], "urgent": False}
    if tier == "stable":
        return {"action": "monitor", "rule": "R0b", "why": "clicks not down by 20% or more",
                "verify_first": [], "urgent": False}
    verify = list(VERIFY_FIRST.get(cause or "unclear", []))
    if cause == "lost_visibility":
        return {"action": "redirect_or_retire_review", "rule": "R1",
                "why": "no impressions now: confirm whether the URL left the index by accident (fix it) or "
                       "on purpose (make sure a 301 points to the closest live page). Review only.",
                "verify_first": verify, "urgent": money}
    if cause == "cannibalization":
        return {"action": "consolidate", "rule": "R2",
                "why": "two or more pages split the same queries; pick one and merge or re-target the other",
                "verify_first": verify, "urgent": False}
    if cause == "serp_feature_or_ai_overview":
        return {"action": "refresh", "rule": "R3",
                "why": "rankings held but CTR fell: refresh for answer-first, quotable sections and a "
                       "stronger snippet (AI Overview recovery playbook)",
                "verify_first": verify, "urgent": False}
    if cause == "ranking_loss":
        deep = cur.get("position") is not None and cur["position"] > DEEP_POSITION
        if tier == "critical" or deep:
            return {"action": "rewrite", "rule": "R4b",
                    "why": "severe ranking loss (critical tier or now beyond position 20): rework structure "
                           "and depth against what ranks now, not a light touch-up",
                    "verify_first": verify, "urgent": money}
        return {"action": "refresh", "rule": "R4a",
                "why": "moderate ranking loss while still in reach: update facts, fill subtopic gaps, "
                       "strengthen internal links",
                "verify_first": verify, "urgent": money}
    if cause == "demand_drop":
        if tier == "critical" and not money:
            return {"action": "redirect_or_retire_review", "rule": "R5b",
                    "why": "search demand for this topic collapsed: review whether the page still serves the "
                           "business before keeping, merging or redirecting it. Review only.",
                    "verify_first": verify, "urgent": False}
        return {"action": "monitor", "rule": "R5a",
                "why": "fewer searches, not a weaker page: refreshing cannot restore demand"
                       + (" (money page: retirement is never suggested)" if money else ""),
                "verify_first": verify, "urgent": False}
    if tier in ("high", "critical"):
        return {"action": "refresh", "rule": "R6b",
                "why": "material decline with no clear single cause: refresh and inspect query-level data",
                "verify_first": verify, "urgent": money}
    return {"action": "monitor", "rule": "R6a",
            "why": "mild decline with no clear cause: re-check next period",
            "verify_first": verify, "urgent": False}


def _cannibal_index(qp_rows: Optional[list[dict]], brand_terms: list[str]) -> tuple[Optional[dict], list]:
    if qp_rows is None:
        return None, []
    records = detect_cannibalization(qp_rows, brand_terms=brand_terms)
    index: dict[str, list[dict]] = {}
    for rec in records:
        pages = [p["page"] for p in rec["pages"]]
        for p in pages:
            index.setdefault(p, []).append({"query": rec["query"], "basis": rec["basis"],
                                            "others": [o for o in pages if o != p]})
    return index, records


def _is_branded(query: str, brand_terms: list[str]) -> bool:
    q = f" {query.lower()} "
    return any(re.search(r"(?<![a-z0-9])" + re.escape(b) + r"(?![a-z0-9])", q) for b in brand_terms if b)


def _ctr_curve(qp_rows: Optional[list[dict]], brand_terms: list[str], calibrate: bool) -> tuple[Optional[dict], dict]:
    if calibrate and qp_rows:
        nonbrand = [r for r in qp_rows if not _is_branded(r["query"], brand_terms)]
        cal = calibrate_ctr_curve(nonbrand)
        if cal["curve"]:
            return cal["curve"], {"source": cal["source"] + " (current window, non-branded; positions "
                                  "without enough data fall back to the default curve)",
                                  "points": cal["curve"]}
    return None, {"source": CTR_CURVE_SOURCE, "points": None}


def analyze_pages(data: dict, min_baseline_clicks: float = 20, money_pages: Optional[list] = None,
                  brand_terms: Optional[list] = None, calibrate: bool = True, days: int = 90) -> dict:
    """Pure analysis over normalized window data (see module docstring for the input shape)."""
    brand_terms = [b.lower() for b in (brand_terms or []) if b]
    cur_pages = aggregate_pages(normalize_rows(data.get("current")))
    prev_rows = data.get("previous")
    yoy_rows = data.get("yoy")
    prev_pages = aggregate_pages(normalize_rows(prev_rows)) if prev_rows is not None else {}
    yoy_pages = aggregate_pages(normalize_rows(yoy_rows)) if yoy_rows else {}
    yoy_available = bool(yoy_pages)
    qp_raw = data.get("query_page")
    qp_rows = normalize_rows(qp_raw, with_query=True) if qp_raw is not None else None
    curve, curve_info = _ctr_curve(qp_rows, brand_terms, calibrate)
    cannibal_idx, cannibal_records = _cannibal_index(qp_rows, brand_terms)
    truncated = {k: bool(v) for k, v in (data.get("truncated") or {}).items() if k in WINDOW_NAMES and v}
    cut = (f"the {int(data['row_limit']):,}-row GSC limit" if data.get("row_limit")
           else "the export's row limit")

    empty = {"clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": None}
    pages_out = []
    for page in sorted(set(cur_pages) | set(prev_pages) | set(yoy_pages)):
        cur = cur_pages.get(page, dict(empty))
        prev = prev_pages.get(page)
        yoy = yoy_pages.get(page)
        money = is_money_page(page, money_pages or [])
        # GSC returns the top rows by clicks; a page cut from a truncated current
        # window may still have impressions, so its absence proves nothing.
        absent_truncated = page not in cur_pages and truncated.get("current", False)
        if yoy_available and yoy and yoy["clicks"] >= min_baseline_clicks:
            kind, base = "yoy", yoy
            reason = f"same {days} days a year earlier (52 weeks back; seasonality-safe)"
        elif prev and prev["clicks"] >= min_baseline_clicks:
            kind, base = "previous", prev
            if not yoy_available:
                reason = (f"no year-earlier data for the property: compared with the previous {days} days; "
                          "seasonality NOT controlled")
            elif yoy is None and truncated.get("yoy"):
                reason = (f"page absent from the year-earlier rows, which hit {cut} (low-click pages were "
                          f"cut): compared with the previous {days} days; seasonality NOT controlled")
            else:
                reason = (f"page had {int(yoy['clicks']) if yoy else 0} clicks a year earlier (below the "
                          f"{int(min_baseline_clicks)}-click floor, e.g. a newer page): compared with the "
                          f"previous {days} days; seasonality NOT controlled")
        else:
            kind = "yoy" if (yoy_available and yoy) else ("previous" if prev else None)
            base = yoy if kind == "yoy" else prev
            reason = ("no baseline data (new page or not ranking before)" if base is None else
                      f"baseline clicks {int(base['clicks'])} below the {int(min_baseline_clicks)}-click floor")
            if base is None and (truncated.get("yoy") or truncated.get("previous")):
                reason += f"; a baseline window hit {cut}, so low-click rows are missing from it"
        if absent_truncated:
            reason = (f"absent from the current window, which hit {cut}: current clicks are unknown "
                      f"(below the cut), not zero; baseline would have been {kind or 'none'}")
        delta = None if absent_truncated else _deltas(base, cur)
        sufficient = base is not None and base["clicks"] >= min_baseline_clicks and not absent_truncated
        tier = tier_for(delta["clicks_pct"]) if sufficient else "insufficient_data"
        gap = (ctr_gap(cur["position"], cur["ctr"], cur["impressions"], curve)
               if cur.get("position") and cur["impressions"] > 0 else None)
        page_cannibal = (cannibal_idx or {}).get(page, []) if cannibal_idx is not None else []
        cause = (diagnose(cur, base, delta, page_cannibal, kind) if tier in DECAYING else None)
        lost_vis = bool(cause and cause["primary"] == "lost_visibility")
        score = (decay_score(delta, gap["ctr_ratio"] if gap else None,
                             (bool(page_cannibal) if cannibal_idx is not None else None), lost_vis)
                 if sufficient else None)
        action = recommend(tier, cause["primary"] if cause else None, cur, money,
                           absent_from_truncated=absent_truncated)
        entry = {
            "page": page, "money_page": money,
            "windows": {"current": cur, "previous": prev, "yoy": yoy},
            "baseline": kind if sufficient else (kind and f"{kind} (below floor)"),
            "baseline_reason": reason,
            "delta": delta,
            "delta_vs_previous": None if absent_truncated else _deltas(prev, cur),
            "ctr_vs_expected": gap,
            "tier": tier,
            "cause": cause,
            "decay_score": score,
            "action": action,
            "cannibalization": page_cannibal,
        }
        if absent_truncated:
            entry["baseline"] = "unknown (current window truncated)"
            entry["absent_from_truncated_window"] = "current"
        pages_out.append(entry)

    pages_out.sort(key=lambda p: (TIER_RANK[p["tier"]], 0 if p["money_page"] else 1,
                                  -((p["decay_score"] or {}).get("score") or 0),
                                  -((p["delta"] or {}).get("lost_clicks") or 0), p["page"]))
    summary = {
        "pages_analyzed": len(pages_out),
        "by_tier": _count(pages_out, lambda p: p["tier"]),
        "by_cause": _count([p for p in pages_out if p["cause"]], lambda p: p["cause"]["primary"]),
        "by_action": _count([p for p in pages_out if p["tier"] in DECAYING], lambda p: p["action"]["action"]),
        "baseline_used": _count(pages_out, lambda p: p["baseline"] or "none"),
        "lost_clicks_decaying": round(sum((p["delta"] or {}).get("lost_clicks") or 0
                                          for p in pages_out if p["tier"] in DECAYING), 1),
        "yoy_available": yoy_available,
        "truncated_windows": sorted(truncated),
        "absent_from_truncated_current": sum(1 for p in pages_out if p.get("absent_from_truncated_window")),
    }
    return {"summary": summary, "pages": pages_out, "ctr_curve": curve_info,
            "cannibalization": cannibal_records if cannibal_idx is not None else None,
            "notes": truncation_notes(truncated, cut, summary["absent_from_truncated_current"]),
            "_curve": curve, "_qp_rows": qp_rows, "_brand_terms": brand_terms}


def truncation_notes(truncated: dict, cut: str, absent_current: int) -> list[str]:
    """Limitation notes for windows whose rows hit the row limit."""
    notes = []
    if truncated.get("current"):
        notes.append(f"current window hit {cut}: {absent_current} page(s) absent from it but present in a "
                     "baseline are reported as insufficient_data (R0c), never as lost visibility or for "
                     "retirement; query them individually before acting")
    for name in ("previous", "yoy"):
        if truncated.get(name):
            notes.append(f"{name} window hit {cut}: pages absent from it have no {name} baseline "
                         "(their low-click rows were cut), so they cannot be called declining against it")
    if truncated.get("query_page"):
        notes.append(f"query x page rows hit {cut}: cannibalization, CTR calibration and top queries cover "
                     "only the highest-click rows")
    return notes


def _count(items, key) -> dict:
    out: dict = {}
    for it in items:
        k = key(it)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def improvement_candidates(analysis: dict, min_impressions: float = 500, min_pos: float = 4,
                           max_pos: float = 25) -> list[dict]:
    """Outrank-style candidates from an analyze_pages() result."""
    curve = analysis["_curve"]
    qp_rows = analysis["_qp_rows"] or []
    brand = analysis["_brand_terms"]
    by_page: dict[str, list[dict]] = {}
    for r in qp_rows:
        by_page.setdefault(r["page"], []).append(r)
    out = []
    for p in analysis["pages"]:
        cur = p["windows"]["current"]
        if cur["impressions"] < min_impressions or cur.get("position") is None:
            continue
        if not min_pos <= cur["position"] <= max_pos:
            continue
        gap = p["ctr_vs_expected"]
        decline = (p["delta_vs_previous"] or {}).get("clicks_pct")
        reasons = []
        if gap and gap["ctr_ratio"] is not None and gap["ctr_ratio"] < CANDIDATE_CTR_RATIO:
            reasons.append("ctr_gap")
        if decline is not None and decline <= CANDIDATE_DECLINE_PCT:
            reasons.append("declining")
        if not reasons:
            continue
        queries = []
        for r in sorted(by_page.get(p["page"], []), key=lambda r: (-r["impressions"], r["query"]))[:TOP_QUERIES]:
            ctr = r["clicks"] / r["impressions"] if r["impressions"] > 0 else 0.0
            qgap = ctr_gap(r["position"], ctr, r["impressions"], curve) if r.get("position") else None
            queries.append({"query": r["query"], "clicks": r["clicks"], "impressions": r["impressions"],
                            "ctr": round(ctr, 4), "position": r.get("position"),
                            "expected_ctr": qgap["expected_ctr"] if qgap else None,
                            "ctr_ratio": qgap["ctr_ratio"] if qgap else None,
                            "branded": _is_branded(r["query"], brand)})
        focus = []
        if "ctr_gap" in reasons:
            focus.append("snippet: rewrite title and meta description for the top queries; open the page with "
                         "a direct, self-contained answer")
        if "declining" in reasons:
            focus.append("refresh: update facts and dates that changed, cover subtopics the top queries imply, "
                         "add internal links from related pages")
        out.append({"page": p["page"], "money_page": p["money_page"], "reasons": reasons,
                    "current": cur, "ctr_vs_expected": gap, "clicks_pct_vs_previous": decline,
                    "click_shortfall": gap["click_shortfall"] if gap else 0.0,
                    "tier": p["tier"], "top_queries": queries, "brief_focus": focus})
    out.sort(key=lambda c: (0 if c["money_page"] else 1, -c["click_shortfall"],
                            -c["current"]["impressions"], c["page"]))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

LIMITATIONS = [
    "GSC position is an impression-weighted average across all of a page's queries, not a SERP rank.",
    "GSC hides anonymized low-volume queries, so query x page rows (cannibalization, top queries) "
    "undercount clicks; page-level totals are complete.",
    "GSC data lags 2-3 days (--lag) and is kept for 16 months; year-earlier windows need ~15 months of data.",
    "GSC returns at most 100,000 rows per query (requested here). A window that reaches the limit is "
    "truncated: pages missing from it are insufficient_data (R0c), never lost visibility.",
    "Causes are rule-based inferences from aggregates (Rule 9: INFERRED). Confirm with query-level data, "
    "seo-drift history and a SERP check before acting.",
    "Expected CTR comes from a curve (site-calibrated when enough non-branded rows exist, else a "
    "pre-AI-Overview population curve that overstates CTR); treat CTR ratios as relative signals.",
]


def _load_input(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DecayError(f"cannot read --input {path}: {exc}") from exc
    if not isinstance(data, dict) or "current" not in data:
        raise DecayError("--input must be a JSON object with at least a 'current' list")
    return data


def collect(args, query_fn: Optional[Callable] = None) -> tuple[dict, dict]:
    """Resolve profile, data and metadata for analyze/candidates."""
    profile = None
    if args.project:
        try:
            profile = load_profile(args.project, args.data_dir)
        except ValueError as exc:   # not a domain, or a profile file that belongs to another domain
            raise DecayError(str(exc)) from exc
        if profile is None:
            raise DecayError(f"no project profile for {args.project}; create one with "
                             f"seo_project.py init {args.project}")
    brand = list(args.brand or [])
    money: list = []
    if profile:
        brand += all_brand_terms(profile)
        money = profile.get("money_pages") or []
    meta: dict = {"project": profile["domain"] if profile else None, "notes": []}
    if args.input:
        data = _load_input(args.input)
        meta.update({"property": data.get("property"), "windows": data.get("windows"),
                     "data_sources": [f"input file: {args.input} (GSC rows exported earlier)"]})
    else:
        prop = args.property or (profile or {}).get("gsc_property")
        if not prop:
            raise DecayError("no GSC property: pass --property, set gsc_property in the project profile, "
                             "or use --input")
        try:
            as_of = date.fromisoformat(args.as_of) if args.as_of else date.fromisoformat(today())
        except ValueError as exc:
            raise DecayError(f"--as-of must be YYYY-MM-DD: {exc}") from exc
        windows = compute_windows(as_of, args.days, args.lag)
        data, notes = fetch_live(prop, windows, query_fn)
        meta.update({"property": prop, "windows": windows, "notes": notes,
                     "data_sources": ["Google Search Console Search Analytics API: page rows for the current, "
                                      "previous and year-earlier windows; query x page rows for the current "
                                      "window (dataState=final)"]})
    analysis = analyze_pages(data, args.min_baseline_clicks, money, brand, not args.no_calibrate, args.days)
    meta["notes"] = list(meta.get("notes") or []) + list(analysis.get("notes") or [])
    return analysis, meta


def _public(analysis: dict) -> dict:
    return {k: v for k, v in analysis.items() if not k.startswith("_")}


def main(argv: Optional[list[str]] = None, query_fn: Optional[Callable] = None) -> int:
    parser = argparse.ArgumentParser(description="GSC content decay detection and refresh candidates")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--project", help="Project profile domain (seo_project.py)")
        p.add_argument("--property", help="GSC property, e.g. sc-domain:example.com")
        p.add_argument("--days", type=int, default=90, help="Window length in days (default 90)")
        p.add_argument("--lag", type=int, default=3, help="Days excluded at the end for GSC lag (default 3)")
        p.add_argument("--min-baseline-clicks", type=float, default=20)
        p.add_argument("--as-of", help="Reference date YYYY-MM-DD (default today, UTC)")
        p.add_argument("--input", help="Offline JSON with current/previous/yoy/query_page rows")
        p.add_argument("--brand", action="append", default=[], help="Extra brand term (repeatable)")
        p.add_argument("--no-calibrate", action="store_true", help="Use the default CTR curve")
        p.add_argument("--data-dir", help="Storage root for project profiles (see seo_store.py)")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("analyze", help="Decay tiers, causes and actions per page")
    common(p)
    p.add_argument("--show", choices=("decaying", "all"), default="decaying")
    p.add_argument("--limit", type=int, default=200)

    p = sub.add_parser("candidates", help="Improvement candidates (impressions + position band + CTR gap/decline)")
    common(p)
    p.add_argument("--min-impressions", type=float, default=500)
    p.add_argument("--min-pos", type=float, default=4)
    p.add_argument("--max-pos", type=float, default=25)
    p.add_argument("--limit", type=int, default=50)

    args = parser.parse_args(argv)
    try:
        analysis, meta = collect(args, query_fn)
    except DecayError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1

    params = {k: getattr(args, k) for k in ("days", "lag", "min_baseline_clicks", "as_of")}
    base = {"command": args.cmd, "generated_at": utc_now(), **meta, "parameters": params}
    if args.cmd == "analyze":
        pub = _public(analysis)
        pages = pub["pages"] if args.show == "all" else [p for p in pub["pages"] if p["tier"] in DECAYING]
        out = {**base, "summary": pub["summary"], "ctr_curve": pub["ctr_curve"],
               "pages": pages[:args.limit], "pages_truncated": max(0, len(pages) - args.limit),
               "cannibalization": (pub["cannibalization"] or [])[:50] if pub["cannibalization"] is not None else None,
               "limitations": LIMITATIONS}
        if args.json:
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            s = out["summary"]
            print(f"{s['pages_analyzed']} pages | tiers {s['by_tier']} | baselines {s['baseline_used']} | "
                  f"YoY available: {s['yoy_available']}")
            for p in out["pages"]:
                d = p["delta"] or {}
                print(f"  [{p['tier']:<8}] {'$ ' if p['money_page'] else ''}{p['page']}  clicks {d.get('clicks_pct')}% "
                      f"vs {p['baseline']} | cause {(p['cause'] or {}).get('primary')} | "
                      f"{p['action']['action']} ({p['action']['rule']}) | score "
                      f"{(p['decay_score'] or {}).get('score')}")
            for n in meta.get("notes") or []:
                print(f"  note: {n}")
        return 0

    cands = improvement_candidates(analysis, args.min_impressions, args.min_pos, args.max_pos)
    out = {**base, "parameters": {**params, "min_impressions": args.min_impressions,
                                  "min_pos": args.min_pos, "max_pos": args.max_pos,
                                  "ctr_ratio_below": CANDIDATE_CTR_RATIO,
                                  "decline_pct_at_most": CANDIDATE_DECLINE_PCT},
           "ctr_curve": analysis["ctr_curve"], "count": len(cands), "candidates": cands[:args.limit],
           "limitations": LIMITATIONS}
    if analysis["_qp_rows"] is None:
        out["notes"] = list(out.get("notes") or []) + ["no query x page rows: top queries unavailable"]
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"{len(cands)} improvement candidates")
        for c in out["candidates"]:
            g = c["ctr_vs_expected"] or {}
            print(f"  {'$ ' if c['money_page'] else ''}{c['page']}  pos {c['current']['position']} "
                  f"imp {int(c['current']['impressions'])} ctr-ratio {g.get('ctr_ratio')} "
                  f"Δclicks {c['clicks_pct_vs_previous']}% -> {', '.join(c['reasons'])}")
        for n in out.get("notes") or []:
            print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
