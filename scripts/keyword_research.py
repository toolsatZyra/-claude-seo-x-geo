#!/usr/bin/env python3
"""
Keyword research for the seo-keywords skill: free discovery, Search Console
opportunity mining, and deterministic scoring of keywords from any source.

Subcommands (every JSON output carries ``data_sources`` and ``limitations``
so a report can disclose exactly what its numbers rest on):

  suggest  Expand seed keywords through Google's public autocomplete endpoint
           (seed, question prefixes, commercial modifiers; ``--depth full``
           adds a-z and 0-9 suffixes). Unofficial and volume-free, so it is
           rate-limited (1 request/s by default), cached on disk (7 days by
           default), hard-capped by --max-requests and fail-soft: an error
           or block is recorded and the run continues from cache.
  gsc      Mine the site's own Search Console query x page rows: striking
           distance (average position 4-20) with opportunity clicks, CTR
           underperformers (position <= 10, CTR below half of expected) and
           keyword cannibalization. Prefers a CTR curve calibrated on the
           site's own non-branded rows and reports which curve it used.
  score    Merge keyword lists from suggest / gsc / Keyword Planner /
           DataForSEO / Ahrefs / Semrush (JSON or CSV), then classify intent
           and funnel stage, flag answer-engine formats, and compute the
           0-100 opportunity score, scenario bucket, traffic potential, lead
           priority and an approximate lexical group per keyword.

All metric maths lives in seo_metrics.py. Formulas, weights, thresholds and
their sources: skills/seo-keywords/references/keyword-scoring.md. Data tiers
and terms-of-service notes: skills/seo-keywords/references/keyword-data-sources.md.

Never scrapes google.com/search (People Also Ask, related searches): that is
disallowed by Google's robots.txt and terms. SERP features come only through
the DataForSEO extension.

Usage:
    python keyword_research.py suggest "crm software" --json
    python keyword_research.py suggest "crm" "sales pipeline" --depth full \\
        --max-requests 60 --output suggestions.json
    python keyword_research.py gsc --project example.com --days 90 --json
    python keyword_research.py gsc --property sc-domain:example.com --brand acme --json
    python keyword_research.py gsc --input gsc_rows.json --brand acme --json
    python keyword_research.py score --input suggestions.json --input ahrefs.csv \\
        --project example.com --format csv --output scored.csv

Exit codes: 0 ok; 1 bad input, missing profile/credentials, or (suggest) no
suggestions at all because every request failed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urlencode

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_metrics import (  # noqa: E402
    CTR_CURVE_SOURCE,
    calibrate_ctr_curve,
    classify_intent,
    ctr_gap,
    detect_cannibalization,
    geo_flags,
    is_striking_distance,
    opportunity_score,
    scenario_bucket,
    striking_distance_opportunity,
    tokenize,
    traffic_potential,
)
from seo_project import all_brand_terms, competitor_terms, load_profile  # noqa: E402
from seo_store import data_root, utc_now  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUESTION_PREFIXES = ("how", "what", "why", "can", "is", "which", "when", "where", "who", "does")
MODIFIER_SUFFIXES = ("vs", "alternatives", "for", "near me", "best", "pricing", "cost",
                     "review", "examples", "template")
ALNUM_SUFFIXES = tuple("abcdefghijklmnopqrstuvwxyz0123456789")

SUGGEST_ENDPOINT = "https://suggestqueries.google.com/complete/search"
SUGGEST_PROVIDER = "google_suggest (unofficial, no volume data)"
DEFAULT_DELAY = 1.0
DEFAULT_CACHE_DAYS = 7
DEFAULT_MAX_REQUESTS = 60
MAX_SUGGEST_BYTES = 256_000
# Statuses that mean "stop asking": rate limited, forbidden, or unavailable.
# After one of these, no further network requests are sent in this run.
STOP_STATUSES = frozenset({403, 429, 503})

GROUPING_LABEL = "lexical (approximate) — use seo-cluster for SERP-overlap clustering"
GROUP_JACCARD = 0.5
UNDERPERFORMER_RATIO = 0.5
UNDERPERFORMER_MAX_POSITION = 10.0
MIN_CALIBRATION_BUCKETS = 3
MIN_BUCKET_ROWS = 5
GSC_ROW_LIMIT = 100_000   # gsc_query.py paginates up to this many rows, then stops
DAYS_PER_MONTH = 30.0
DEFAULT_GSC_DAYS = 90
DEFAULT_MIN_IMPRESSIONS = 50
DEFAULT_LIST_LIMIT = 200
GSC_LAG_DAYS = 3

ADS_COMPETITION_HEADERS = frozenset({"competition", "competition index", "competitive density"})

# Normalized header -> canonical field. First alias that exists in a file wins,
# so put the preferred column first (e.g. country "volume" before "global volume").
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "keyword": ("keyword", "keywords", "query", "queries", "top queries", "search term",
                "search terms", "keyphrase", "key phrase"),
    "volume": ("volume", "search volume", "avg monthly searches", "monthly searches",
               "global volume"),
    "difficulty": ("kd", "keyword difficulty", "difficulty", "keyword difficulty index"),
    "position": ("position", "current position", "rank", "average position", "avg position"),
    "url": ("url", "current url", "page", "landing page", "ranking url"),
    "cpc": ("cpc",),
    "impressions": ("impressions",),
    "clicks": ("clicks",),
    "opp_clicks_monthly": ("opp clicks monthly", "click shortfall monthly"),
    "intent": ("intent", "search intent", "main intent"),
}

CSV_COLUMNS_SCORE = (
    "keyword", "group_id", "group_label", "opportunity_score", "completeness", "intent",
    "funnel", "lead_value", "bucket", "volume", "difficulty", "position", "url", "cpc",
    "traffic_potential", "opp_clicks_monthly", "lead_priority", "lead_priority_basis",
    "relevance", "geo_flags", "local", "brand", "competitor", "route", "confidence",
    "provider_intent", "sources",
)
CSV_COLUMNS_SUGGEST = ("keyword", "seed", "source_query")
CSV_COLUMNS_GSC = (
    "list", "query", "page", "position", "impressions", "clicks", "ctr", "expected_ctr",
    "ctr_ratio", "opp_clicks", "opp_clicks_monthly", "click_shortfall",
    "click_shortfall_monthly", "target_position", "intent", "funnel", "lead_value",
    "lead_priority", "scenario", "geo_flags", "cannibalized",
)


class InputError(ValueError):
    """A user-supplied file or flag could not be used."""


# ---------------------------------------------------------------------------
# Normalization and parsing helpers (pure)
# ---------------------------------------------------------------------------

_ZERO_WIDTH_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")


def normalize_keyword(text: Any) -> str:
    """Case/whitespace-normalized keyword used as the merge key.

    NFKC-normalizes, lowercases, removes zero-width characters and collapses
    whitespace. Punctuation is kept ("c++", "what's") because it can change
    the query.
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    s = _ZERO_WIDTH_RE.sub("", s).lower()
    return " ".join(s.split())


def normalize_header(header: Any) -> str:
    """Normalize a column header: lowercase, drop "(...)", punctuation -> space."""
    h = str(header or "").lower()
    h = re.sub(r"\(.*?\)", " ", h)
    h = re.sub(r"[^a-z0-9]+", " ", h)
    return " ".join(h.split())


_THOUSANDS_RE = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_DECIMAL_COMMA_RE = re.compile(r"^\d+,\d+$")
_RANGE_RE = re.compile(r"^\s*([0-9][0-9.,]*\s*[kmb]?)\s*(?:-|\u2013|\u2014|to)\s*([0-9][0-9.,]*\s*[kmb]?)\s*$",
                       re.IGNORECASE)
_NULL_TOKENS = frozenset({"", "-", "--", "n/a", "na", "none", "null", "nan", "unknown"})


def _parse_scalar(text: str) -> Optional[float]:
    s = text.strip().lower().replace("\u00a0", "").replace(" ", "")
    s = s.lstrip("<>~≈").strip("%$€£")
    if not s:
        return None
    mult = 1.0
    if s[-1] in "kmb":
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}[s[-1]]
        s = s[:-1]
    if _THOUSANDS_RE.match(s):
        s = s.replace(",", "")
    elif _DECIMAL_COMMA_RE.match(s):
        s = s.replace(",", ".")
    try:
        val = float(s) * mult
    except ValueError:
        return None
    return val if math.isfinite(val) else None


def parse_number(value: Any) -> tuple[Optional[float], Optional[tuple[float, float]]]:
    """Parse an export cell into (value, range).

    Handles "1,200", "1.2K", "3M", "45%", "$1.20", blanks/dashes (None) and
    bucketed ranges such as Keyword Planner's "1K – 10K". A range returns its
    geometric midpoint (arithmetic midpoint when the lower bound is 0) plus
    the (low, high) tuple, because the demand component is log-scaled and the
    geometric midpoint is the centre of the range on that scale.
    """
    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, (int, float)):
        return (float(value) if math.isfinite(float(value)) else None), None
    s = str(value).strip()
    if s.lower() in _NULL_TOKENS:
        return None, None
    m = _RANGE_RE.match(s)
    if m:
        lo, hi = _parse_scalar(m.group(1)), _parse_scalar(m.group(2))
        if lo is not None and hi is not None and hi >= lo:
            mid = math.sqrt(lo * hi) if lo > 0 else hi / 2.0
            return round(mid, 1), (lo, hi)
    return _parse_scalar(s), None


def fold_token(token: str) -> str:
    """Naive plural folding used only for lexical comparison keys.

    "agencies" -> "agency", "tools" -> "tool"; "ss" endings ("business") and
    tokens of 3 characters or fewer are left alone.
    """
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def keyword_tokens(text: str) -> list[str]:
    """Stopword-free, plural-folded tokens in original order (duplicates removed)."""
    out: list[str] = []
    for tok in tokenize(text):
        f = fold_token(tok)
        if f not in out:
            out.append(f)
    return out


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def greedy_jaccard_groups(token_sets: list[Iterable[str]], threshold: float = GROUP_JACCARD
                          ) -> list[list[int]]:
    """Deterministic greedy grouping by token-set Jaccard similarity.

    Items are visited in the given order. Each item joins the existing group
    whose *head* (first member) has the highest Jaccard similarity with it,
    provided that similarity is >= ``threshold`` (ties go to the older group);
    otherwise it starts a new group. Items with an empty token set always form
    singleton groups. An inverted index on head tokens keeps this near-linear.
    Returns a list of groups, each a list of item indices.
    """
    groups: list[list[int]] = []
    heads: list[frozenset] = []
    index: dict[str, set[int]] = defaultdict(set)
    for i, toks in enumerate(token_sets):
        s = frozenset(toks)
        best_g, best_j = None, -1.0
        if s:
            candidates: set[int] = set()
            for t in s:
                candidates |= index.get(t, set())
            for g in sorted(candidates):
                j = jaccard(s, heads[g])
                if j >= threshold and j > best_j:
                    best_g, best_j = g, j
        if best_g is None:
            groups.append([i])
            heads.append(s)
            for t in s:
                index[t].add(len(groups) - 1)
        else:
            groups[best_g].append(i)
    return groups


def group_label(member_tokens: list[list[str]], fallback: str) -> str:
    """Label = tokens shared by every member (head order), else the 2 most frequent."""
    if not member_tokens or not member_tokens[0]:
        return fallback
    head = member_tokens[0]
    shared = set(head)
    for toks in member_tokens[1:]:
        shared &= set(toks)
    if shared:
        return " ".join(t for t in head if t in shared)
    counts = Counter(t for toks in member_tokens for t in set(toks))
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:2]
    return " ".join(t for t, _ in top) or fallback


def _csv_safe(value: Any) -> Any:
    """Neutralize spreadsheet formula injection in string cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def rows_to_csv(rows: list[dict], columns: Iterable[str]) -> str:
    cols = list(columns)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(cols)
    for row in rows:
        out = []
        for c in cols:
            v = row.get(c)
            if isinstance(v, (list, tuple, set)):
                v = "|".join(str(x) for x in v)
            elif isinstance(v, bool):
                v = "true" if v else "false"
            elif v is None:
                v = ""
            out.append(_csv_safe(v))
        writer.writerow(out)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Loading keyword records from any supported export
# ---------------------------------------------------------------------------

def _decode_text(raw: bytes) -> str:
    """Decode a file: UTF-16 (BOM or NUL-pattern, e.g. Keyword Planner CSV), else UTF-8."""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    head = raw[:200]
    if head and head.count(b"\x00") > len(head) // 4:
        enc = "utf-16-le" if head[1:2] == b"\x00" else "utf-16-be"
        return raw.decode(enc, errors="replace")
    return raw.decode("utf-8-sig", errors="replace")


def detect_columns(headers: Iterable[str], difficulty_column: Optional[str] = None
                   ) -> tuple[dict[str, str], list[str]]:
    """Map canonical fields to the original header names, case-insensitively.

    Returns (colmap, notes). Ads/PPC ``competition`` columns are never used
    as SEO difficulty unless ``difficulty_column`` names one explicitly.
    """
    headers = list(headers)
    norm: dict[str, str] = {}
    for h in headers:
        n = normalize_header(h)
        if n and n not in norm:
            norm[n] = h
    colmap: dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in norm:
                colmap[field] = norm[a]
                break
    notes: list[str] = []
    if difficulty_column:
        # Exact (case-insensitive) header match first: normalization drops
        # "(...)", so "Competition (indexed value)" would otherwise collide
        # with "Competition".
        wanted = difficulty_column.strip().lower()
        exact = next((h for h in headers if str(h).strip().lower() == wanted), None)
        key = normalize_header(difficulty_column)
        if exact is not None:
            colmap["difficulty"] = exact
        elif key in norm:
            colmap["difficulty"] = norm[key]
        else:
            colmap.pop("difficulty", None)
            notes.append(f"--difficulty-column {difficulty_column!r} not found; difficulty left empty")
    elif "difficulty" not in colmap and ADS_COMPETITION_HEADERS & set(norm):
        notes.append("Ads/PPC competition column ignored: it measures paid-ad competition, "
                     "not organic ranking difficulty")
    return colmap, notes


def _flatten_record(rec: dict) -> dict:
    """Flatten provider-specific nesting (DataForSEO items, GSC ``keys``)."""
    if isinstance(rec.get("keyword_data"), dict):           # DataForSEO ranked_keywords item
        kd = rec["keyword_data"]
        out = {"keyword": kd.get("keyword")}
        _merge_dataforseo_info(out, kd)
        serp = (rec.get("ranked_serp_element") or {}).get("serp_item") or {}
        out["position"] = serp.get("rank_group")
        out["url"] = serp.get("url")
        return out
    if isinstance(rec.get("keyword_info"), dict) or isinstance(rec.get("keyword_properties"), dict):
        out = {"keyword": rec.get("keyword")}                # DataForSEO keyword ideas/suggestions
        _merge_dataforseo_info(out, rec)
        return out
    if "query" not in rec and isinstance(rec.get("keys"), list) and rec["keys"]:
        out = dict(rec)                                      # raw GSC row: keys = [query, page]
        out["query"] = rec["keys"][0]
        if len(rec["keys"]) > 1:
            out["page"] = rec["keys"][1]
        return out
    return rec


def _merge_dataforseo_info(out: dict, node: dict) -> None:
    info = node.get("keyword_info") or {}
    props = node.get("keyword_properties") or {}
    intent = (node.get("search_intent_info") or {}).get("main_intent")
    out["search_volume"] = info.get("search_volume")
    out["cpc"] = info.get("cpc")
    out["keyword_difficulty"] = props.get("keyword_difficulty")
    if intent:
        out["intent"] = intent


def _normalize_record(rec: dict, colmap: dict[str, str], source: str) -> Optional[dict]:
    kw = normalize_keyword(rec.get(colmap["keyword"])) if "keyword" in colmap else ""
    if not kw:
        return None
    out: dict[str, Any] = {"keyword": kw, "source": source}
    volume, vrange = parse_number(rec.get(colmap["volume"])) if "volume" in colmap else (None, None)
    out["volume"] = volume if volume is None or volume >= 0 else None
    out["volume_range"] = list(vrange) if vrange else None
    diff = parse_number(rec.get(colmap["difficulty"]))[0] if "difficulty" in colmap else None
    out["difficulty"] = None if diff is None else max(0.0, min(100.0, diff))
    pos = parse_number(rec.get(colmap["position"]))[0] if "position" in colmap else None
    out["position"] = pos if pos is not None and pos > 0 else None
    url = rec.get(colmap["url"]) if "url" in colmap else None
    out["url"] = str(url).strip() if url not in (None, "") else None
    for field in ("cpc", "impressions", "clicks", "opp_clicks_monthly"):
        out[field] = parse_number(rec.get(colmap[field]))[0] if field in colmap else None
    intent = rec.get(colmap["intent"]) if "intent" in colmap else None
    out["provider_intent"] = str(intent).strip().lower() if intent not in (None, "") else None
    return out


def _records_from_dicts(items: Iterable[Any], source: str, difficulty_column: Optional[str],
                        notes: list[str]) -> tuple[list[dict], int]:
    records: list[dict] = []
    skipped = 0
    colmap_cache: dict[tuple, dict] = {}
    for item in items:
        if isinstance(item, str):
            item = {"keyword": item}
        if not isinstance(item, dict):
            skipped += 1
            continue
        flat = _flatten_record(item)
        key = tuple(sorted(flat.keys()))
        if key not in colmap_cache:
            colmap, col_notes = detect_columns(flat.keys(), difficulty_column)
            colmap_cache[key] = colmap
            notes.extend(n for n in col_notes if n not in notes)
        rec = _normalize_record(flat, colmap_cache[key], source)
        if rec is None:
            skipped += 1
        else:
            records.append(rec)
    return records, skipped


def _json_items(data: Any) -> tuple[list[Any], str]:
    """Locate the keyword records inside a supported JSON document."""
    if isinstance(data, list):
        return data, "list"
    if not isinstance(data, dict):
        raise InputError("unsupported JSON: expected an object or a list")
    if isinstance(data.get("tasks"), list):                          # DataForSEO envelope
        items: list[Any] = []
        for task in data["tasks"]:
            for result in (task or {}).get("result") or []:
                if isinstance(result, dict) and isinstance(result.get("items"), list):
                    items.extend(result["items"])
                elif isinstance(result, dict) and "keyword" in result:
                    items.append(result)                             # search_volume endpoint
        return items, "dataforseo"
    if isinstance(data.get("suggestions"), list):                    # keyword_research suggest
        items = [{"keyword": s} for s in data.get("seeds") or [] if isinstance(s, str)]
        items += [s for s in data["suggestions"]]
        return items, "google_suggest"
    if isinstance(data.get("striking"), list) or isinstance(data.get("ctr_underperformers"), list):
        return list(data.get("striking") or []) + list(data.get("ctr_underperformers") or []), "gsc"
    if isinstance(data.get("ideas"), list):                          # keyword_planner ideas
        return data["ideas"], "google_ads_keyword_planner"
    if isinstance(data.get("keywords"), list):
        kws = data["keywords"]
        if any(isinstance(k, dict) and "avg_monthly_searches" in k for k in kws):
            return kws, "google_ads_keyword_planner"                 # keyword_planner volume
        if "grouping" in data:
            return kws, "keyword_research_score"
        return kws, "list"
    if isinstance(data.get("rows"), list):                           # gsc_query.py output
        return data["rows"], "gsc"
    if isinstance(data.get("items"), list):                          # one DataForSEO result
        return data["items"], "dataforseo"
    raise InputError("unrecognized JSON shape: expected suggest/gsc/score output, "
                     "Keyword Planner JSON, a DataForSEO response, or a list of keywords")


def _records_from_table(text: str, path_label: str, difficulty_column: Optional[str],
                        notes: list[str]) -> tuple[list[dict], int, list[str]]:
    lines = text.splitlines()
    header_idx, delim = None, None
    keyword_aliases = set(COLUMN_ALIASES["keyword"])
    for i, line in enumerate(lines[:15]):
        best = None
        for d in ("\t", ",", ";"):
            try:
                cells = next(csv.reader([line], delimiter=d))
            except (csv.Error, StopIteration):
                continue
            if any(normalize_header(c) in keyword_aliases for c in cells):
                if best is None or len(cells) > best[1]:
                    best = (d, len(cells))
        if best:
            header_idx, delim = i, best[0]
            break
    if header_idx is None:
        items = [ln.strip() for ln in lines if ln.strip()]
        if any("\t" in ln or "," in ln for ln in items[:5]):
            raise InputError(f"{path_label}: no keyword column found (expected one of: "
                             + ", ".join(COLUMN_ALIASES["keyword"]) + ")")
        # Plain keyword list: one keyword per line, no header.
        records, skipped = _records_from_dicts(items, path_label, difficulty_column, notes)
        return records, skipped, ["(no header: one keyword per line)"]
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])), delimiter=delim)
    headers = list(reader.fieldnames or [])
    colmap, col_notes = detect_columns(headers, difficulty_column)
    notes.extend(col_notes)
    records, skipped = [], 0
    for row in reader:
        rec = _normalize_record(row, colmap, path_label)
        if rec is None:
            skipped += 1
        else:
            records.append(rec)
    return records, skipped, headers


_SELF_DERIVED_INTENT = frozenset({"gsc", "keyword_research_score"})


def load_records(path: str, difficulty_column: Optional[str] = None) -> tuple[list[dict], dict]:
    """Load keyword records from a JSON or CSV/TSV file.

    Returns (records, meta). Each record: keyword, volume, volume_range,
    difficulty, position, url, cpc, impressions, clicks, opp_clicks_monthly,
    provider_intent, source.
    """
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise InputError(f"{path}: cannot read ({exc.strerror or exc})") from exc
    text = _decode_text(raw)
    notes: list[str] = []
    stripped = text.lstrip()
    if p.suffix.lower() == ".json" or stripped[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InputError(f"{path}: invalid JSON ({exc})") from exc
        try:
            items, source = _json_items(data)
        except InputError as exc:
            raise InputError(f"{path}: {exc}") from exc
        if source == "list":
            source = p.stem
        records, skipped = _records_from_dicts(items, source, difficulty_column, notes)
        if source in _SELF_DERIVED_INTENT:
            # Our own gsc/score outputs carry *our* intent label, not a provider's.
            for r in records:
                r["provider_intent"] = None
        meta = {"path": str(p), "format": "json", "source": source}
    else:
        records, skipped, headers = _records_from_table(text, p.stem, difficulty_column, notes)
        meta = {"path": str(p), "format": "csv", "source": p.stem, "columns": headers}
    meta.update({"records": len(records), "skipped": skipped, "notes": notes})
    return records, meta


def merge_records(records: Iterable[dict]) -> dict[str, dict]:
    """Merge duplicate keywords (already normalized) across sources.

    Max volume (keeping that record's range), max difficulty (conservative
    when providers disagree), best (lowest) position with its URL, max of
    cpc / impressions / clicks / opp_clicks_monthly (the same row is often
    present in several inputs, so max de-duplicates where a sum would
    double-count), first provider intent, union of sources.
    """
    merged: dict[str, dict] = {}
    for r in records:
        kw = r["keyword"]
        m = merged.get(kw)
        if m is None:
            m = merged[kw] = {"keyword": kw, "volume": None, "volume_range": None,
                              "difficulty": None, "position": None, "url": None, "cpc": None,
                              "impressions": None, "clicks": None, "opp_clicks_monthly": None,
                              "provider_intent": None, "sources": set()}
        if r.get("volume") is not None and (m["volume"] is None or r["volume"] > m["volume"]):
            m["volume"], m["volume_range"] = r["volume"], r.get("volume_range")
        if r.get("difficulty") is not None and (m["difficulty"] is None or r["difficulty"] > m["difficulty"]):
            m["difficulty"] = r["difficulty"]
        if r.get("position") is not None and (m["position"] is None or r["position"] < m["position"]):
            m["position"] = r["position"]
            m["url"] = r.get("url") or m["url"]
        elif m["url"] is None and r.get("url"):
            m["url"] = r["url"]
        for field in ("cpc", "impressions", "clicks", "opp_clicks_monthly"):
            v = r.get(field)
            if v is not None and (m[field] is None or v > m[field]):
                m[field] = v
        if not m["provider_intent"] and r.get("provider_intent"):
            m["provider_intent"] = r["provider_intent"]
        m["sources"].add(r.get("source") or "unknown")
    return merged


def load_relevance(path: str) -> tuple[dict[str, float], list[str]]:
    """Read a keyword,relevance CSV (relevance 0-1; out-of-range values are clipped)."""
    p = Path(path)
    try:
        text = _decode_text(p.read_bytes())
    except OSError as exc:
        raise InputError(f"{path}: cannot read ({exc.strerror or exc})") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = {normalize_header(h): h for h in (reader.fieldnames or [])}
    kcol = next((headers[a] for a in COLUMN_ALIASES["keyword"] if a in headers), None)
    rcol = headers.get("relevance")
    if not kcol or not rcol:
        raise InputError(f"{path}: relevance file needs 'keyword' and 'relevance' columns")
    out: dict[str, float] = {}
    notes: list[str] = []
    for row in reader:
        kw = normalize_keyword(row.get(kcol))
        val = parse_number(row.get(rcol))[0]
        if not kw or val is None:
            continue
        if not 0.0 <= val <= 1.0:
            notes.append(f"relevance for {kw!r} was {val}; clipped to 0-1")
            val = max(0.0, min(1.0, val))
        out[kw] = val
    return out, notes


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------

def _route_for(intent: dict, flags: list[str]) -> Optional[str]:
    if "comparison" in flags or intent.get("competitor"):
        return "seo-competitor-pages"
    return None


def score_keywords(merged: dict[str, dict], brand_terms: Iterable[str] = (),
                   competitor_terms_: Iterable[str] = (), relevance: Optional[dict] = None,
                   min_volume: Optional[float] = None, target_position: float = 3.0) -> dict:
    """Score merged keywords. Pure: no I/O. Returns {keywords, groups, summary, ...}."""
    brands = list(brand_terms)
    comps = list(competitor_terms_)
    relevance = relevance or {}
    rows: list[dict] = []
    dropped = 0
    for kw, m in merged.items():
        if min_volume is not None and m["volume"] is not None and m["volume"] < min_volume:
            dropped += 1
            continue
        intent = classify_intent(kw, brands, comps)
        rel = relevance.get(kw, 1.0)
        opp = opportunity_score(m["volume"], m["difficulty"], m["position"], intent["lead_value"], rel)
        flags = geo_flags(kw)
        tp = traffic_potential(m["volume"], target_position)
        if m["opp_clicks_monthly"] is not None:
            basis, base = "gsc_opp_clicks", m["opp_clicks_monthly"]
        elif tp is not None:
            basis, base = "traffic_potential", tp
        else:
            basis, base = None, None
        rows.append({
            "keyword": kw,
            "opportunity_score": opp["score"],
            "completeness": opp["completeness"],
            "components": opp["components"],
            "intent": intent["intent"],
            "funnel": intent["funnel"],
            "lead_value": intent["lead_value"],
            "confidence": intent["confidence"],
            "local": intent["local"],
            "brand": intent["brand"],
            "competitor": intent["competitor"],
            "bucket": scenario_bucket(m["difficulty"], intent["lead_value"], m["position"]),
            "geo_flags": flags,
            "route": _route_for(intent, flags),
            "volume": m["volume"],
            "volume_range": m["volume_range"],
            "difficulty": m["difficulty"],
            "position": m["position"],
            "url": m["url"],
            "cpc": m["cpc"],
            "traffic_potential": tp,
            "opp_clicks_monthly": m["opp_clicks_monthly"],
            "lead_priority": round(base * intent["lead_value"] * rel, 1) if basis else None,
            "lead_priority_basis": basis,
            "relevance": rel,
            "provider_intent": m["provider_intent"],
            "sources": sorted(m["sources"]),
        })

    rows.sort(key=lambda r: (-r["opportunity_score"],
                             -(r["lead_priority"] if r["lead_priority"] is not None else -1.0),
                             r["keyword"]))

    token_lists = [keyword_tokens(r["keyword"]) for r in rows]
    raw_groups = greedy_jaccard_groups(token_lists, GROUP_JACCARD)
    groups = []
    for n, members in enumerate(raw_groups, start=1):
        gid = f"g{n:03d}"
        label = group_label([token_lists[i] for i in members], rows[members[0]]["keyword"])
        vols = [rows[i]["volume"] for i in members if rows[i]["volume"] is not None]
        lps = [rows[i]["lead_priority"] for i in members if rows[i]["lead_priority"] is not None]
        for i in members:
            rows[i]["group_id"] = gid
            rows[i]["group_label"] = label
        groups.append({
            "group_id": gid, "label": label, "size": len(members),
            "top_keyword": rows[members[0]]["keyword"],
            "max_opportunity_score": rows[members[0]]["opportunity_score"],
            "total_volume": round(sum(vols), 1) if vols else None,
            "total_lead_priority": round(sum(lps), 1) if lps else None,
            "keywords": [rows[i]["keyword"] for i in members],
        })

    def _count(field: str) -> dict:
        return dict(sorted(Counter(r[field] for r in rows).items()))

    summary = {
        "total": len(rows),
        "dropped_below_min_volume": dropped,
        "by_intent": _count("intent"),
        "by_funnel": _count("funnel"),
        "by_bucket": _count("bucket"),
        "with_volume": sum(1 for r in rows if r["volume"] is not None),
        "with_difficulty": sum(1 for r in rows if r["difficulty"] is not None),
        "with_position": sum(1 for r in rows if r["position"] is not None),
        "mean_completeness": (round(sum(r["completeness"] for r in rows) / len(rows), 2)
                              if rows else None),
        "groups": len(groups),
        "competitor_pages_candidates": sum(1 for r in rows if r["route"] == "seo-competitor-pages"),
    }
    return {"keywords": rows, "groups": groups, "summary": summary, "grouping": GROUPING_LABEL}


def score_limitations(summary: dict, target_position: float) -> list[str]:
    out = [
        "Intent, funnel and lead value come from deterministic modifier rules "
        "(seo_metrics.classify_intent), not from the live SERP; low-confidence rows "
        "should be checked against the actual results page.",
        f"traffic_potential = volume x expected CTR at position {target_position:g} on the "
        f"fallback curve: {CTR_CURVE_SOURCE}. Treat it as an upper bound on SERPs with AI "
        "Overviews or heavy SERP features.",
        "Groups are " + GROUPING_LABEL + ".",
        "Difficulty scales differ by provider (Ahrefs KD, Semrush KD%, DataForSEO KD); when "
        "several sources disagree the highest value is kept.",
    ]
    total = summary.get("total") or 0
    if total and summary.get("with_volume", 0) < total:
        out.append(f"{total - summary['with_volume']} of {total} keywords have no search volume "
                   "(e.g. autocomplete-only); unknown components count as neutral (0.5), "
                   "so compare scores at similar completeness.")
    if total and summary.get("with_difficulty", 0) == 0:
        out.append("No SEO difficulty data supplied: the ease component is excluded and buckets "
                   "treat difficulty as moderate (KD 45).")
    return out


# ---------------------------------------------------------------------------
# suggest
# ---------------------------------------------------------------------------

def build_queries(seed: str, depth: str = "basic") -> list[str]:
    """Expansion queries for one seed, in priority order."""
    s = normalize_keyword(seed)
    if not s:
        return []
    qs = [s]
    qs += [f"{p} {s}" for p in QUESTION_PREFIXES]
    qs += [f"{s} {m}" for m in MODIFIER_SUFFIXES]
    if depth == "full":
        qs += [f"{s} {c}" for c in ALNUM_SUFFIXES]
    seen: set[str] = set()
    return [q for q in qs if not (q in seen or seen.add(q))]


def plan_queries(seeds: Iterable[str], depth: str = "basic") -> list[tuple[str, str]]:
    """Round-robin the per-seed query lists so a request cap is shared fairly."""
    per_seed: list[tuple[str, list[str]]] = []
    seen_seeds: set[str] = set()
    for seed in seeds:
        s = normalize_keyword(seed)
        if s and s not in seen_seeds:
            seen_seeds.add(s)
            per_seed.append((s, build_queries(s, depth)))
    plan: list[tuple[str, str]] = []
    seen: set[str] = set()
    longest = max((len(q) for _, q in per_seed), default=0)
    for i in range(longest):
        for seed, queries in per_seed:
            if i < len(queries) and queries[i] not in seen:
                seen.add(queries[i])
                plan.append((seed, queries[i]))
    return plan


def build_suggest_url(query: str, hl: str = "en", gl: str = "us") -> str:
    params = {"client": "firefox", "hl": hl, "gl": gl, "ie": "utf-8", "oe": "utf-8", "q": query}
    return f"{SUGGEST_ENDPOINT}?{urlencode(params)}"


def parse_suggest_response(body: bytes, content_type: str = "") -> list[str]:
    """Parse ``[query, [suggestion, ...], ...]``; raises ValueError on any other shape."""
    m = re.search(r"charset=([\w-]+)", content_type or "", re.IGNORECASE)
    enc = m.group(1) if m else "utf-8"
    try:
        text = body.decode(enc, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    data = json.loads(text)
    if not (isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list)):
        raise ValueError("unexpected autocomplete response shape")
    return [s for s in data[1] if isinstance(s, str)]


def _http_suggest_fetch(url: str, timeout: float = 10.0) -> tuple[int, bytes, str]:
    """Default network fetch: SSRF/DNS-rebinding-safe GET via url_safety."""
    from url_safety import safe_requests_get  # lazy: keeps pure paths import-light

    resp = safe_requests_get(url, timeout=timeout,
                             headers={"Accept": "application/json, text/javascript, */*;q=0.1"})
    try:
        body = resp.content[:MAX_SUGGEST_BYTES]
    finally:
        resp.close()
    return resp.status_code, body, resp.headers.get("Content-Type", "")


def _secure_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _cache_path(cache_dir: Path, query: str, hl: str, gl: str) -> Path:
    key = hashlib.sha256(f"{hl}|{gl}|{query}".encode("utf-8")).hexdigest()
    return cache_dir / f"{key}.json"


def _cache_get(path: Path, max_age_s: float, now: float) -> Optional[list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fetched = payload.get("fetched_at")
    sugg = payload.get("suggestions")
    if not isinstance(fetched, (int, float)) or not isinstance(sugg, list):
        return None
    if now - fetched > max_age_s or now < fetched - 300:
        return None
    return [s for s in sugg if isinstance(s, str)]


def _cache_put(path: Path, payload: dict) -> None:
    _secure_mkdir(path.parent)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def run_suggest(seeds: Iterable[str], hl: str = "en", gl: str = "us", depth: str = "basic",
                max_requests: int = DEFAULT_MAX_REQUESTS, delay: float = DEFAULT_DELAY,
                cache_days: float = DEFAULT_CACHE_DAYS, use_cache: bool = True,
                data_dir: Optional[str] = None,
                fetch: Optional[Callable[[str], tuple[int, bytes, str]]] = None,
                sleep: Callable[[float], None] = time.sleep,
                clock: Callable[[], float] = time.time) -> dict:
    """Expand seeds via autocomplete. ``fetch``/``sleep``/``clock`` are injectable for tests."""
    seeds = [normalize_keyword(s) for s in seeds if normalize_keyword(s)]
    fetch = fetch or _http_suggest_fetch
    plan = plan_queries(seeds, depth)
    cache_dir = data_root(data_dir) / "cache" / "suggest"
    max_age = max(0.0, cache_days) * 86400.0

    suggestions: list[dict] = []
    seen: set[str] = set()
    errors: list[dict] = []
    requests_made = cache_hits = skipped = 0
    blocked_status: Optional[int] = None
    last_request_at: Optional[float] = None

    for seed, query in plan:
        cpath = _cache_path(cache_dir, query, hl, gl)
        results = _cache_get(cpath, max_age, clock()) if use_cache else None
        if results is not None:
            cache_hits += 1
        else:
            if blocked_status is not None or requests_made >= max_requests:
                skipped += 1
                continue
            if last_request_at is not None and delay > 0:
                wait = delay - (clock() - last_request_at)
                if wait > 0:
                    sleep(wait)
            last_request_at = clock()
            requests_made += 1
            try:
                status, body, ctype = fetch(build_suggest_url(query, hl, gl))
            except Exception as exc:  # fail soft: network/SSRF errors become entries
                errors.append({"query": query, "error": f"{type(exc).__name__}: {exc}"})
                continue
            if status != 200:
                errors.append({"query": query, "error": f"HTTP {status}"})
                if status in STOP_STATUSES:
                    blocked_status = status
                continue
            try:
                results = parse_suggest_response(body, ctype)
            except ValueError as exc:
                errors.append({"query": query, "error": f"parse error: {exc}"})
                continue
            if use_cache:
                try:
                    _cache_put(cpath, {"query": query, "hl": hl, "gl": gl,
                                       "fetched_at": clock(), "suggestions": results})
                except OSError as exc:
                    errors.append({"query": query, "error": f"cache write failed: {exc}"})
        for s in results:
            kw = normalize_keyword(s)
            if kw and kw not in seen:
                seen.add(kw)
                suggestions.append({"keyword": kw, "seed": seed, "source_query": query})

    limitations = [
        "Google autocomplete is an unofficial, undocumented endpoint: it returns no search "
        "volume or difficulty, reflects what people type (not how often), varies by locale, "
        "and may change or be blocked without notice.",
        "Use `score` with Keyword Planner, DataForSEO, Ahrefs or Semrush data for volume and "
        "difficulty; suggestions alone cannot rank keywords by demand.",
        "People Also Ask and related searches are not collected: scraping google.com/search "
        "is disallowed by Google's robots.txt and terms. Use seo-dataforseo for SERP features.",
    ]
    if skipped and blocked_status is None:
        limitations.append(f"{skipped} planned queries were not sent because --max-requests "
                           f"({max_requests}) was reached.")
    if blocked_status is not None:
        limitations.append(f"Google returned HTTP {blocked_status}; {skipped} remaining queries "
                           "were skipped. Retry later — cached results are reused.")
    if errors and not suggestions:
        limitations.append("Every request failed; no suggestions were collected.")
    return {
        "generated_at": utc_now(),
        "seeds": seeds,
        "provider": SUGGEST_PROVIDER,
        "hl": hl, "gl": gl, "depth": depth,
        "suggestions": suggestions,
        "queries_planned": len(plan),
        "requests_made": requests_made,
        "cache_hits": cache_hits,
        "queries_skipped": skipped,
        "errors": errors,
        "data_sources": [f"{SUGGEST_PROVIDER}: {SUGGEST_ENDPOINT} (client=firefox, hl={hl}, gl={gl})",
                         f"local cache {cache_dir} ({cache_hits} hits, max age {cache_days:g} days)"
                         if use_cache else "local cache disabled (--no-cache)"],
        "limitations": limitations,
    }


# ---------------------------------------------------------------------------
# gsc
# ---------------------------------------------------------------------------

def normalize_gsc_rows(raw_rows: Iterable[Any]) -> list[dict]:
    """Normalize GSC rows; CTR is recomputed as clicks/impressions (a 0-1 fraction).

    gsc_query.py reports ``ctr`` in percent; GSC exports vary. Recomputing
    from clicks and impressions sidesteps both.
    """
    out: list[dict] = []
    colmaps: dict[tuple, dict] = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        flat = _flatten_record(row)
        key = tuple(flat.keys())
        if key not in colmaps:
            colmaps[key] = detect_columns(flat.keys())[0]
        colmap = colmaps[key]
        query = normalize_keyword(flat.get(colmap["keyword"])) if "keyword" in colmap else ""
        if not query:
            continue
        impressions = parse_number(flat.get(colmap["impressions"]))[0] if "impressions" in colmap else None
        clicks = parse_number(flat.get(colmap["clicks"]))[0] if "clicks" in colmap else None
        position = parse_number(flat.get(colmap["position"]))[0] if "position" in colmap else None
        if not impressions or impressions <= 0:
            continue
        clicks = max(0.0, clicks or 0.0)
        page = flat.get(colmap["url"]) if "url" in colmap else None
        out.append({
            "query": query,
            "page": str(page).strip() if page else "",
            "clicks": clicks,
            "impressions": impressions,
            "position": position if position and position > 0 else None,
            "ctr": round(clicks / impressions, 4),
        })
    return out


def _period_days(date_range: Optional[dict], default_days: int) -> int:
    try:
        start = datetime.strptime(date_range["start"], "%Y-%m-%d").date()
        end = datetime.strptime(date_range["end"], "%Y-%m-%d").date()
        days = (end - start).days + 1
        return days if days > 0 else default_days
    except (TypeError, KeyError, ValueError):
        return default_days


def analyze_gsc_rows(rows: list[dict], brand_terms: Iterable[str] = (),
                     competitor_terms_: Iterable[str] = (),
                     min_impressions: float = DEFAULT_MIN_IMPRESSIONS,
                     include_brand: bool = False, lift: int = 5,
                     period_days: int = DEFAULT_GSC_DAYS,
                     limit: int = DEFAULT_LIST_LIMIT) -> dict:
    """Striking distance, CTR underperformers and cannibalization from normalized rows."""
    brands = list(brand_terms)
    comps = list(competitor_terms_)
    intents: dict[str, dict] = {}
    for r in rows:
        if r["query"] not in intents:
            intents[r["query"]] = classify_intent(r["query"], brands, comps)
    # Any brand mention is kept out of CTR calibration (brand CTR is not
    # representative). Only brand-*navigational* queries ("acme", "acme login")
    # are dropped from the opportunity lists: "acme vs hubspot" is a late-funnel
    # comparison query worth working on, and it is flagged brand=true instead.
    is_brand = {q: i["brand"] for q, i in intents.items()}
    is_brand_nav = {q: i["brand"] and i["intent"] == "navigational" for q, i in intents.items()}
    monthly = DAYS_PER_MONTH / max(1, period_days)

    nonbrand = [r for r in rows if not is_brand[r["query"]]]
    # A bucket built from one or two queries just reproduces their own CTR,
    # so calibrate_ctr_curve also requires MIN_BUCKET_ROWS rows per bucket.
    calib = calibrate_ctr_curve(nonbrand, min_rows=MIN_BUCKET_ROWS)
    usable = calib["curve"]
    if len(usable) >= MIN_CALIBRATION_BUCKETS:
        curve: Optional[dict] = usable
        curve_source = (f"site-calibrated from {len(nonbrand)} non-branded GSC rows "
                        f"({len(curve)} position buckets with >= {MIN_BUCKET_ROWS} rows and "
                        f">= 50 impressions; other positions fall back to {CTR_CURVE_SOURCE})")
    else:
        curve = None
        curve_source = CTR_CURVE_SOURCE

    cannibal = detect_cannibalization(rows, brands)
    cannibal_queries = {c["query"] for c in cannibal}

    striking, under = [], []
    for r in rows:
        if r["position"] is None or r["impressions"] < min_impressions:
            continue
        if is_brand_nav[r["query"]] and not include_brand:
            continue
        it = intents[r["query"]]
        base = {
            "query": r["query"], "page": r["page"], "position": r["position"],
            "impressions": r["impressions"], "clicks": r["clicks"], "ctr": r["ctr"],
            "intent": it["intent"], "funnel": it["funnel"], "lead_value": it["lead_value"],
            "brand": it["brand"], "geo_flags": geo_flags(r["query"]),
            "cannibalized": r["query"] in cannibal_queries,
        }
        if is_striking_distance(r["position"]):
            opp = striking_distance_opportunity(r["position"], r["ctr"], r["impressions"], curve, lift)
            opp_month = round(opp["opp_clicks"] * monthly, 1)
            striking.append({**base, **opp, "opp_clicks_monthly": opp_month,
                             "lead_priority": round(opp_month * it["lead_value"], 1),
                             "scenario": scenario_bucket(None, it["lead_value"], r["position"])})
        if r["position"] <= UNDERPERFORMER_MAX_POSITION:
            gap = ctr_gap(r["position"], r["ctr"], r["impressions"], curve)
            if gap["ctr_ratio"] is not None and gap["ctr_ratio"] < UNDERPERFORMER_RATIO:
                short_month = round(gap["click_shortfall"] * monthly, 1)
                under.append({**base, **gap, "click_shortfall_monthly": short_month,
                              "lead_priority": round(short_month * it["lead_value"], 1)})

    striking.sort(key=lambda x: (-x["lead_priority"], -x["opp_clicks"], -x["impressions"],
                                 x["query"], x["page"]))
    under.sort(key=lambda x: (-x["lead_priority"], -x["click_shortfall"], x["query"], x["page"]))

    branded = [r for r in rows if is_brand[r["query"]]]
    totals = {
        "rows": len(rows),
        "queries": len(intents),
        "pages": len({r["page"] for r in rows if r["page"]}),
        "clicks": round(sum(r["clicks"] for r in rows), 1),
        "impressions": round(sum(r["impressions"] for r in rows), 1),
        "branded_rows": len(branded),
        "branded_navigational_rows": sum(1 for r in rows if is_brand_nav[r["query"]]),
        "branded_clicks": round(sum(r["clicks"] for r in branded), 1),
        "nonbranded_clicks": round(sum(r["clicks"] for r in nonbrand), 1),
        "striking_total": len(striking),
        "ctr_underperformers_total": len(under),
        "cannibalized_queries": len(cannibal),
        "striking_opp_clicks_monthly": round(sum(s["opp_clicks_monthly"] for s in striking), 1),
    }
    cap = (lambda xs: xs[:limit]) if limit and limit > 0 else (lambda xs: xs)
    return {
        "period_days": period_days,
        "curve_source": curve_source,
        "ctr_curve": {"source": curve_source, "calibrated": curve is not None,
                      "curve": {str(k): v for k, v in (curve or {}).items()},
                      "buckets": {str(k): v for k, v in calib["buckets"].items()}},
        "parameters": {"min_impressions": min_impressions, "lift": lift,
                       "include_brand": include_brand, "brand_terms": brands,
                       "brand_rule": "brand-navigational queries excluded from lists unless "
                                     "--include-brand; every brand mention excluded from CTR "
                                     "calibration",
                       "striking_range": [4, 20],
                       "underperformer_rule": f"position <= {UNDERPERFORMER_MAX_POSITION:g} and "
                                              f"ctr_ratio < {UNDERPERFORMER_RATIO}",
                       "limit": limit},
        "striking": cap(striking),
        "ctr_underperformers": cap(under),
        "cannibalization": cap(cannibal),
        "totals": totals,
        "truncated": bool(limit and limit > 0 and (len(striking) > limit or len(under) > limit
                                                   or len(cannibal) > limit)),
    }


def gsc_limitations(brand_terms: list[str], calibrated: bool, include_brand: bool) -> list[str]:
    out = [
        "GSC position is an impression-weighted average across all impressions, not a single "
        "SERP rank; one query can sit at 3 on some searches and 15 on others.",
        "Query-level rows omit anonymized queries (an Ahrefs study put them at roughly 46% of "
        "clicks), so totals here undercount the property total.",
        "GSC data lags 2-3 days; the live window ends 3 days before today.",
        "opp_clicks assume the page keeps its current CTR-vs-curve behaviour after moving up "
        "5 positions; opp_clicks_monthly scales the period total to 30 days.",
        "A CTR underperformer has several possible causes the data cannot separate: the "
        "title/meta snippet, a SERP feature or AI Overview above it, or intent mismatch.",
    ]
    if not calibrated:
        out.append(f"Fewer than {MIN_CALIBRATION_BUCKETS} position buckets had enough non-branded "
                   f"impressions to calibrate; expected CTR uses the fallback curve "
                   f"({CTR_CURVE_SOURCE}), which overstates CTR where AI Overviews appear.")
    if not brand_terms:
        out.append("No brand terms supplied (--brand or --project): branded queries are not "
                   "recognised, stay in the lists and can inflate the calibrated curve.")
    elif include_brand:
        out.append("--include-brand: brand-navigational queries are included in the lists "
                   "(they are existing demand, lead value 0.3).")
    else:
        out.append("Brand-navigational queries (e.g. '<brand> login') are excluded from the "
                   "lists; queries that mention the brand with a commercial modifier "
                   "('<brand> vs X') are kept and flagged brand=true.")
    return out


def fetch_gsc_rows(site_url: str, days: int = DEFAULT_GSC_DAYS,
                   query_fn: Optional[Callable[..., dict]] = None,
                   today: Optional[date] = None) -> tuple[list[dict], dict, Optional[str]]:
    """Fetch query x page rows (dataState=final) via gsc_query.query_search_analytics.

    Returns (raw_rows, date_range, error).
    """
    end = (today or date.today()) - timedelta(days=GSC_LAG_DAYS)
    start = end - timedelta(days=max(1, days) - 1)
    date_range = {"start": start.isoformat(), "end": end.isoformat()}
    if query_fn is None:
        try:
            import gsc_query  # exits at import time when google-api-python-client is missing
        except (ImportError, SystemExit):
            return [], date_range, ("google-api-python-client is not installed; install the "
                                    "plugin requirements or pass --input with exported rows")
        query_fn = gsc_query.query_search_analytics
    res = query_fn(site_url, start_date=date_range["start"], end_date=date_range["end"],
                   dimensions=["query", "page"], search_type="web", row_limit=GSC_ROW_LIMIT,
                   data_state="final")
    if res.get("error"):
        return [], date_range, str(res["error"])
    rows = list(res.get("rows") or [])
    if max(res.get("row_count") or 0, len(rows)) >= GSC_ROW_LIMIT:
        date_range["row_cap_hit"] = GSC_ROW_LIMIT   # rows beyond the cap were not returned
    return rows, date_range, None


def load_gsc_input(path: str) -> tuple[list[Any], Optional[dict]]:
    """Rows from a gsc_query.py JSON, a list of rows, or a CSV export."""
    p = Path(path)
    try:
        text = _decode_text(p.read_bytes())
    except OSError as exc:
        raise InputError(f"{path}: cannot read ({exc.strerror or exc})") from exc
    if p.suffix.lower() == ".json" or text.lstrip()[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InputError(f"{path}: invalid JSON ({exc})") from exc
        if isinstance(data, list):
            return data, None
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return data["rows"], data.get("date_range")
        raise InputError(f"{path}: expected gsc_query.py JSON (with 'rows') or a list of rows")
    lines = text.splitlines()
    delim = "\t" if lines and lines[0].count("\t") > lines[0].count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delim)), None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _profile_or_error(project: Optional[str], data_dir: Optional[str]) -> Optional[dict]:
    if not project:
        return None
    profile = load_profile(project, data_dir)
    if profile is None:
        raise InputError(f"no project profile for {project!r}; create one with "
                         f"`python scripts/seo_project.py init {project}`")
    return profile


def _terms(explicit: list[str], profile: Optional[dict], fn: Callable[[dict], list[str]]) -> list[str]:
    if explicit:
        return [t.lower().strip() for t in explicit if t.strip()]
    return fn(profile) if profile else []


def _write(path: str, content: str) -> None:
    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    with open(Path(path).expanduser(), "w", encoding="utf-8", newline="") as fh:
        fh.write(content)


def _emit(result: dict, args: argparse.Namespace, csv_rows: list[dict], csv_cols: Iterable[str],
          summary_fn: Callable[[dict], str], fmt: Optional[str] = None) -> None:
    out_path = getattr(args, "output", None)
    fmt = fmt or ("csv" if out_path and out_path.lower().endswith(".csv") else "json")
    if out_path:
        _write(out_path, rows_to_csv(csv_rows, csv_cols) if fmt == "csv"
               else json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif fmt == "csv" and not out_path:
        sys.stdout.write(rows_to_csv(csv_rows, csv_cols))
    else:
        print(summary_fn(result))
        if out_path:
            print(f"\nWrote {out_path} ({fmt})")


def _summary_suggest(r: dict) -> str:
    lines = [f"Autocomplete expansion for {', '.join(r['seeds'])} ({r['provider']})",
             f"  queries planned {r['queries_planned']}, sent {r['requests_made']}, "
             f"cache hits {r['cache_hits']}, skipped {r['queries_skipped']}, errors {len(r['errors'])}",
             f"  {len(r['suggestions'])} unique suggestions"]
    lines += [f"    {s['keyword']}" for s in r["suggestions"][:30]]
    if len(r["suggestions"]) > 30:
        lines.append(f"    ... {len(r['suggestions']) - 30} more (use --json or --output)")
    return "\n".join(lines)


def _summary_gsc(r: dict) -> str:
    t = r["totals"]
    lines = [f"GSC opportunities ({r['period_days']} days, curve: {r['curve_source']})",
             f"  rows {t['rows']}, queries {t['queries']}, clicks {t['clicks']}, "
             f"impressions {t['impressions']} (branded clicks {t['branded_clicks']})",
             f"  striking distance: {t['striking_total']} "
             f"(~{t['striking_opp_clicks_monthly']} extra clicks/month if each rose 5 places)"]
    for s in r["striking"][:15]:
        lines.append(f"    {s['position']:>5.1f}  {s['impressions']:>8.0f} imp  "
                     f"+{s['opp_clicks_monthly']:>7.1f}/mo  {s['funnel']}  {s['query']}")
    lines.append(f"  CTR underperformers: {t['ctr_underperformers_total']}")
    for u in r["ctr_underperformers"][:10]:
        lines.append(f"    {u['position']:>5.1f}  ctr {u['ctr']:.1%} vs {u['expected_ctr']:.1%}  {u['query']}")
    lines.append(f"  cannibalized queries: {t['cannibalized_queries']}")
    for c in r["cannibalization"][:10]:
        lines.append(f"    {c['query']}: " + ", ".join(p["page"] for p in c["pages"]))
    return "\n".join(lines)


def _summary_score(r: dict) -> str:
    s = r["summary"]
    lines = [f"Scored {s['total']} keywords ({s['groups']} lexical groups, mean completeness "
             f"{s['mean_completeness']})",
             f"  intent {s['by_intent']}", f"  funnel {s['by_funnel']}", f"  bucket {s['by_bucket']}",
             "  score  compl  funnel  bucket      lead_pri  keyword"]
    for k in r["keywords"][:25]:
        lp = "-" if k["lead_priority"] is None else f"{k['lead_priority']:.1f}"
        lines.append(f"  {k['opportunity_score']:>5.1f}  {k['completeness']:>5.2f}  {k['funnel']:<6}  "
                     f"{k['bucket']:<10}  {lp:>8}  {k['keyword']}")
    return "\n".join(lines)


def cmd_suggest(args: argparse.Namespace) -> int:
    profile = _profile_or_error(args.project, args.data_dir)
    markets = (profile or {}).get("markets") or {}
    hl = args.hl or str(markets.get("language") or "en").lower()
    gl = args.gl or str(markets.get("country") or "us").lower()
    if args.max_requests < 0 or args.delay < 0:
        raise InputError("--max-requests and --delay must be >= 0")
    result = run_suggest(args.seeds, hl=hl, gl=gl, depth=args.depth, max_requests=args.max_requests,
                         delay=args.delay, cache_days=args.cache_days, use_cache=not args.no_cache,
                         data_dir=args.data_dir)
    _emit(result, args, result["suggestions"], CSV_COLUMNS_SUGGEST, _summary_suggest)
    return 1 if (result["errors"] and not result["suggestions"]) else 0


def cmd_gsc(args: argparse.Namespace) -> int:
    profile = _profile_or_error(args.project, args.data_dir)
    brands = _terms(args.brand, profile, all_brand_terms)
    comps = _terms(args.competitor, profile, competitor_terms)
    if args.input:
        raw, date_range = load_gsc_input(args.input)
        days = _period_days(date_range, args.days)
        sources = [f"GSC query x page rows from {args.input}"
                   + (f" ({date_range['start']}..{date_range['end']})" if date_range else
                      f" (period assumed {days} days; pass --days if different)")]
    else:
        prop = args.property or (profile or {}).get("gsc_property")
        if not prop:
            raise InputError("pass --property, --project with a gsc_property, or --input")
        raw, date_range, err = fetch_gsc_rows(prop, args.days)
        if err:
            result = {"error": err, "property": prop, "date_range": date_range,
                      "data_sources": [], "limitations": ["No GSC data retrieved."]}
            print(json.dumps(result, indent=2) if args.json else f"Error: {err}",
                  file=sys.stdout if args.json else sys.stderr)
            return 1
        days = _period_days(date_range, args.days)
        sources = [f"Google Search Console Search Analytics API, property {prop}, dimensions "
                   f"query x page, dataState=final, {date_range['start']}..{date_range['end']}"]
    rows = normalize_gsc_rows(raw)
    result = analyze_gsc_rows(rows, brands, comps, args.min_impressions, args.include_brand,
                              args.lift, days, args.limit)
    result = {"generated_at": utc_now(), "date_range": date_range, **result,
              "data_sources": sources,
              "limitations": gsc_limitations(brands, result["ctr_curve"]["calibrated"],
                                             args.include_brand)}
    if result["truncated"]:
        result["limitations"].append(f"Lists truncated to --limit {args.limit}; totals cover all rows.")
    if (date_range or {}).get("row_cap_hit"):
        result["limitations"].insert(0, f"Search Console returned the maximum {GSC_ROW_LIMIT:,} query x "
                                        "page rows; the low-traffic tail (where striking-distance "
                                        "queries often sit) was cut off. Shorten --days or filter "
                                        "by page/country and re-run.")
        result["row_cap_hit"] = True
    csv_rows = ([{"list": "striking", **s} for s in result["striking"]]
                + [{"list": "ctr_underperformer", **u} for u in result["ctr_underperformers"]])
    _emit(result, args, csv_rows, CSV_COLUMNS_GSC, _summary_gsc)
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    profile = _profile_or_error(args.project, args.data_dir)
    brands = _terms(args.brand, profile, all_brand_terms)
    comps = _terms(args.competitor, profile, competitor_terms)
    all_records: list[dict] = []
    inputs: list[dict] = []
    for path in args.input:
        records, meta = load_records(path, args.difficulty_column)
        all_records.extend(records)
        inputs.append(meta)
    relevance, rel_notes = (load_relevance(args.relevance) if args.relevance else ({}, []))
    merged = merge_records(all_records)
    scored = score_keywords(merged, brands, comps, relevance, args.min_volume, args.target_position)
    source_names = sorted({m["source"] for m in inputs})
    limitations = score_limitations(scored["summary"], args.target_position)
    limitations += [f"{m['path']}: {n}" for m in inputs for n in m["notes"]] + rel_notes
    if args.min_volume is not None:
        limitations.append(f"--min-volume {args.min_volume:g} drops only keywords with known volume; "
                           "keywords without volume data are kept.")
    if args.relevance:
        limitations.append("Relevance multipliers come from the operator's file; unlisted keywords "
                           "default to 1.0.")
    result = {
        "generated_at": utc_now(),
        "inputs": inputs,
        "parameters": {"brand_terms": brands, "competitor_terms": comps,
                       "min_volume": args.min_volume, "target_position": args.target_position,
                       "relevance_file": args.relevance,
                       "difficulty_column": args.difficulty_column},
        **scored,
        "data_sources": [f"{m['path']} ({m['source']}, {m['records']} records)" for m in inputs]
        + ([f"relevance multipliers from {args.relevance}"] if args.relevance else [])
        + [f"merged sources: {', '.join(source_names)}"],
        "limitations": limitations,
    }
    fmt = args.format or ("csv" if args.output and args.output.lower().endswith(".csv") else "json")
    _emit(result, args, result["keywords"], CSV_COLUMNS_SCORE, _summary_score, fmt)
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", help="Storage root override (profiles, cache); see seo_store.py")
    common.add_argument("--project", help="Project profile (domain or slug) for brand/competitor "
                                          "terms, market and GSC property")
    common.add_argument("--json", action="store_true", help="Print the full JSON result")
    common.add_argument("--output", help="Write the result to a .json or .csv file")

    parser = argparse.ArgumentParser(description="Keyword discovery, GSC opportunity mining "
                                                 "and deterministic keyword scoring")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("suggest", parents=[common], help="Expand seeds via Google autocomplete "
                                                         "(unofficial, no volume)")
    p.add_argument("seeds", nargs="+", help="Seed keyword(s)")
    p.add_argument("--hl", help="Interface language (default: profile language or en)")
    p.add_argument("--gl", help="Country (default: profile country or us)")
    p.add_argument("--depth", choices=["basic", "full"], default="basic",
                   help="basic: seed + questions + modifiers; full: + a-z and 0-9 suffixes")
    p.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS,
                   help=f"Hard cap on network requests (default {DEFAULT_MAX_REQUESTS})")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                   help=f"Seconds between network requests (default {DEFAULT_DELAY})")
    p.add_argument("--cache-days", type=float, default=DEFAULT_CACHE_DAYS,
                   help=f"Reuse cached responses younger than this (default {DEFAULT_CACHE_DAYS})")
    p.add_argument("--no-cache", action="store_true", help="Neither read nor write the cache")
    p.set_defaults(func=cmd_suggest)

    p = sub.add_parser("gsc", parents=[common], help="Striking distance, CTR gaps and "
                                                     "cannibalization from Search Console")
    p.add_argument("--property", help="GSC property (sc-domain:example.com or URL prefix)")
    p.add_argument("--input", help="Offline rows: gsc_query.py JSON, list of rows, or CSV")
    p.add_argument("--days", type=int, default=DEFAULT_GSC_DAYS,
                   help=f"Window length (default {DEFAULT_GSC_DAYS})")
    p.add_argument("--min-impressions", type=float, default=DEFAULT_MIN_IMPRESSIONS,
                   help=f"Impression floor per row (default {DEFAULT_MIN_IMPRESSIONS})")
    p.add_argument("--brand", action="append", default=[], help="Brand term (repeatable; "
                                                                "overrides the profile)")
    p.add_argument("--competitor", action="append", default=[], help="Competitor term (repeatable)")
    p.add_argument("--include-brand", action="store_true",
                   help="Keep branded queries in striking/underperformer lists")
    p.add_argument("--lift", type=int, default=5, help="Positions gained for opp_clicks (default 5)")
    p.add_argument("--limit", type=int, default=DEFAULT_LIST_LIMIT,
                   help=f"Max rows per list, 0 = all (default {DEFAULT_LIST_LIMIT})")
    p.set_defaults(func=cmd_gsc)

    p = sub.add_parser("score", parents=[common], help="Merge and score keyword lists")
    p.add_argument("--input", action="append", required=True,
                   help="Keyword file (JSON or CSV); repeatable")
    p.add_argument("--brand", action="append", default=[], help="Brand term (repeatable)")
    p.add_argument("--competitor", action="append", default=[], help="Competitor term (repeatable)")
    p.add_argument("--relevance", help="CSV with keyword,relevance (0-1) business-fit multipliers")
    p.add_argument("--min-volume", type=float, help="Drop keywords with known volume below N")
    p.add_argument("--difficulty-column", help="Use this column as difficulty (e.g. to opt in to a "
                                               "non-standard header)")
    p.add_argument("--target-position", type=float, default=3.0,
                   help="Position assumed for traffic_potential (default 3)")
    p.add_argument("--format", choices=["json", "csv"], help="Output format (default: json, or "
                                                             "csv when --output ends in .csv)")
    p.set_defaults(func=cmd_score)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
