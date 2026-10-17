#!/usr/bin/env python3
"""
Shared, deterministic SEO/AEO metrics used by every research and tracking script.

Before this module, intent rules, "quick win" position bands and CTR
assumptions were restated in prose across several skills and never computed
the same way twice. Everything here is pure (no network, no randomness) so the
same input always yields the same score, which is what the plugin's scoring
rubric (skills/seo/references/scoring-rubric.md, Rules 1-4) demands.

Contents:
    classify_intent()        rule-based search intent + funnel stage + lead value
    expected_ctr()           position -> expected organic CTR (default curve or
                             a site-calibrated one from calibrate_ctr_curve())
    opportunity_score()      0-100 keyword opportunity with renormalized weights
    wilson_interval()        95% CI for a proportion (AI mention rates)
    tokenize()/ngrams()      shared tokenizer for content and gap analysis
    position_band()          the one definition of striking distance, etc.

Methodology and sources: skills/seo-keywords/references/keyword-scoring.md

Usage:
    python seo_metrics.py intent "best crm for small business"
    python seo_metrics.py intent "acme login" --brand acme --json
    python seo_metrics.py ctr 3
    python seo_metrics.py score --volume 2400 --difficulty 35 --position 8 \
        --keyword "crm pricing"
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from typing import Iterable, Optional

# ---------------------------------------------------------------------------
# Position bands — the single definition used by gsc/rank/keyword scripts.
# ---------------------------------------------------------------------------

POSITION_BANDS = (
    (1.0, 3.0, "top3"),
    (3.0, 10.0, "page1"),        # positions >3 and <=10
    (10.0, 20.0, "striking"),    # page 2: the classic "striking distance"
    (20.0, 50.0, "deep"),
    (50.0, float("inf"), "far"),
)

# "Striking distance" = average position 4-20: on page 1 below the fold, or
# on page 2. These are the rankings where on-page work most often moves
# clicks, because the page is already judged relevant.
STRIKING_MIN = 4.0
STRIKING_MAX = 20.0


def position_band(position: Optional[float]) -> str:
    """Return the band label for an average position (None -> 'unranked')."""
    if position is None or position <= 0:
        return "unranked"
    for low, high, label in POSITION_BANDS:
        if (low == 1.0 and position <= high) or (low < position <= high):
            return label
    return "far"


def is_striking_distance(position: Optional[float]) -> bool:
    return position is not None and STRIKING_MIN <= position <= STRIKING_MAX


# ---------------------------------------------------------------------------
# Expected CTR by position
# ---------------------------------------------------------------------------

# Fallback organic CTR curve, positions 1-10, from Backlinko's analysis of
# 4 million Google results (https://backlinko.com/google-ctr-stats). It
# predates AI Overviews and OVERSTATES CTR on SERPs that show one: Ahrefs
# measured position-1 CTR on AI-Overview keywords falling from 7.3% to 1.6%
# (Dec 2023 -> Dec 2025, ahrefs.com/blog/ai-overviews-reduce-clicks-update/).
# Treat it as a "classic SERP" upper bound. Every script that compares actual
# CTR against expected CTR must prefer calibrate_ctr_curve() on the site's own
# non-branded GSC rows and report which curve it used.
DEFAULT_CTR_CURVE: dict[int, float] = {
    1: 0.276,
    2: 0.158,
    3: 0.110,
    4: 0.084,
    5: 0.063,
    6: 0.049,
    7: 0.039,
    8: 0.033,
    9: 0.027,
    10: 0.024,
}
# Page 2 (positions 11-20): Backlinko reports 0.63% of searchers click a
# second-page result. Beyond 20 the value is a floor assumption, labelled as
# such in every output that uses it.
PAGE2_CTR = 0.0063
DEEP_CTR_ASSUMPTION = 0.001
CTR_CURVE_SOURCE = "Backlinko 4M-result study (fallback; pre-AI-Overview, overstates CTR)"


def striking_distance_opportunity(position: float, ctr: float, impressions: float,
                                  curve: Optional[dict] = None, lift: int = 5) -> dict:
    """Extra monthly clicks if a query climbed ``lift`` positions.

    opp_clicks = impressions * max(0, CTR(target) - actual_ctr), with
    target = max(1, round(position) - lift). Conservative by design: it
    assumes the snippet keeps its current CTR-vs-curve behaviour.
    """
    target = max(1, int(round(position)) - lift)
    exp_target = expected_ctr(target, curve)
    return {
        "target_position": target,
        "expected_ctr_at_target": round(exp_target, 4),
        "opp_clicks": round(max(0.0, impressions * (exp_target - ctr)), 1),
    }


def expected_ctr(position: Optional[float], curve: Optional[dict] = None) -> float:
    """Expected organic CTR (0-1) for an average position.

    Fractional positions interpolate linearly between the integer points.
    ``curve`` may be a calibrated {int_position: ctr} mapping; missing points
    fall back to the default curve.
    """
    if position is None or position <= 0:
        return 0.0
    merged = dict(DEFAULT_CTR_CURVE)
    if curve:
        merged.update({int(k): float(v) for k, v in curve.items() if 1 <= int(k) <= 10})
    if position > 20:
        return DEEP_CTR_ASSUMPTION
    if position > 10:
        return PAGE2_CTR
    lo = max(1, int(math.floor(position)))
    hi = min(10, lo + 1)
    frac = position - lo
    if lo == hi or frac <= 0:
        return merged[lo]
    return merged[lo] + (merged[hi] - merged[lo]) * frac


def calibrate_ctr_curve(rows: Iterable[dict], min_impressions: int = 50) -> dict:
    """Build a site-specific CTR curve from GSC query rows.

    Each row needs ``position``, ``clicks`` and ``impressions``. Rows are
    bucketed by rounded position (1-10); a bucket's CTR is total clicks /
    total impressions (impression-weighted, so one tiny query cannot skew it).
    Buckets with fewer than ``min_impressions`` impressions are omitted and
    fall back to the default curve when used.

    Returns {"curve": {pos: ctr}, "buckets": {pos: {...}}, "source": str}.
    """
    buckets: dict[int, dict] = {}
    for row in rows:
        try:
            pos = float(row.get("position", 0))
            clicks = float(row.get("clicks", 0))
            imps = float(row.get("impressions", 0))
        except (TypeError, ValueError):
            continue
        if pos <= 0 or imps <= 0:
            continue
        p = int(round(pos))
        if not 1 <= p <= 10:
            continue
        b = buckets.setdefault(p, {"clicks": 0.0, "impressions": 0.0, "rows": 0})
        b["clicks"] += clicks
        b["impressions"] += imps
        b["rows"] += 1
    curve = {
        p: round(b["clicks"] / b["impressions"], 4)
        for p, b in sorted(buckets.items())
        if b["impressions"] >= min_impressions
    }
    return {
        "curve": curve,
        "buckets": {p: buckets[p] for p in sorted(buckets)},
        "source": "site-calibrated from GSC rows" if curve else CTR_CURVE_SOURCE,
    }


def ctr_gap(position: float, actual_ctr: float, impressions: float,
            curve: Optional[dict] = None) -> dict:
    """Compare a query's actual CTR with the expected CTR for its position.

    Returns expected CTR, the ratio actual/expected, and the click shortfall
    (impressions * (expected - actual), floored at 0). A large shortfall at a
    good position usually points at the snippet (title/meta), a SERP feature
    stealing clicks, or intent mismatch — the script cannot tell which.
    """
    exp = expected_ctr(position, curve)
    ratio = (actual_ctr / exp) if exp > 0 else None
    shortfall = max(0.0, impressions * (exp - actual_ctr))
    return {
        "expected_ctr": round(exp, 4),
        "ctr_ratio": round(ratio, 2) if ratio is not None else None,
        "click_shortfall": round(shortfall, 1),
    }


# ---------------------------------------------------------------------------
# Search intent, funnel stage and lead value
# ---------------------------------------------------------------------------

_TRANSACTIONAL = (
    "buy", "price", "prices", "pricing", "cost", "costs", "quote", "quotes",
    "order", "discount", "coupon", "deal", "deals", "cheap", "cheapest",
    "affordable", "purchase", "hire", "book", "booking", "demo", "trial",
    "free trial", "sign up", "signup", "subscribe", "for sale", "rates",
    "fee", "fees", "estimate", "consultation", "near me", "contact",
    "get started", "download", "install", "plans",
)
_COMMERCIAL = (
    "best", "top", "vs", "versus", "alternative", "alternatives", "compare",
    "comparison", "review", "reviews", "rated", "ranking", "rankings",
    "software", "tool", "tools", "app", "apps", "platform", "platforms",
    "service", "services", "agency", "agencies", "company", "companies",
    "provider", "providers", "vendor", "vendors", "solution", "solutions",
    "consultant", "consultants", "firm", "firms", "pros and cons", "features",
    "choose", "choosing", "worth it", "options",
)
_INFORMATIONAL = (
    "what", "how", "why", "when", "who", "which", "where", "guide",
    "tutorial", "examples", "example", "ideas", "tips", "meaning",
    "definition", "define", "template", "templates", "checklist", "learn",
    "is", "are", "can", "does", "do", "should", "ways", "steps", "explained",
    "history", "benefits", "types", "statistics", "stats", "faq",
)
_NAVIGATIONAL = ("login", "log in", "sign in", "signin", "website", "official", "portal", "account", "dashboard")
_LOCAL = ("near me", "nearby", "open now", "closest", "local", "in my area")
_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")

FUNNEL_LEAD_VALUE = {"BOFU": 1.0, "MOFU": 0.6, "TOFU": 0.25}
OWN_BRAND_LEAD_VALUE = 0.3  # existing demand: defend, don't count as new acquisition


def _has_term(text: str, term: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None


def classify_intent(keyword: str, brand_terms: Iterable[str] = (),
                    competitor_terms: Iterable[str] = ()) -> dict:
    """Classify a keyword's intent, funnel stage and lead value.

    Deterministic modifier matching — no model call. Priority when several
    families match: navigational(own brand) > transactional > commercial >
    informational. ``local`` is a flag layered on top (a "plumber near me"
    query is transactional + local).

    Returns {intent, funnel, lead_value, local, brand, competitor, signals,
    confidence} where confidence is "high" (2+ signals in the winning family),
    "medium" (1 signal) or "low" (no signal; defaulted).
    """
    text = " " + re.sub(r"\s+", " ", (keyword or "").lower().strip()) + " "
    brands = [b.lower().strip() for b in brand_terms if b and b.strip()]
    competitors = [c.lower().strip() for c in competitor_terms if c and c.strip()]

    hits = {
        "transactional": [t for t in _TRANSACTIONAL if _has_term(text, t)],
        "commercial": [t for t in _COMMERCIAL if _has_term(text, t)],
        "informational": [t for t in _INFORMATIONAL if _has_term(text, t)],
        "navigational": [t for t in _NAVIGATIONAL if _has_term(text, t)],
    }
    own_brand = [b for b in brands if _has_term(text, b)]
    competitor = [c for c in competitors if _has_term(text, c)]
    local = bool([t for t in _LOCAL if _has_term(text, t)]) or bool(_ZIP_RE.search(text))

    if own_brand and (hits["navigational"] or len(text.split()) <= len(own_brand[0].split()) + 1):
        intent = "navigational"
    elif hits["transactional"]:
        intent = "transactional"
    elif hits["commercial"] or competitor:
        intent = "commercial"
    elif hits["informational"]:
        intent = "informational"
    elif hits["navigational"]:
        intent = "navigational"
    else:
        intent = "informational"

    if intent == "transactional":
        funnel = "BOFU"
    elif intent == "commercial":
        # Head-to-head and alternative queries sit at the bottom of the funnel:
        # the searcher has a shortlist.
        late = ("vs", "versus", "alternative", "alternatives", "compare", "comparison", "reviews", "review")
        funnel = "BOFU" if any(t in hits["commercial"] for t in late) or competitor else "MOFU"
    elif intent == "navigational":
        funnel = "BOFU"
    else:
        funnel = "TOFU"

    lead_value = OWN_BRAND_LEAD_VALUE if (intent == "navigational" and own_brand) else FUNNEL_LEAD_VALUE[funnel]

    family_key = intent if intent in hits else "informational"
    n_signals = len(hits.get(family_key, [])) + (len(own_brand) if intent == "navigational" else 0)
    confidence = "high" if n_signals >= 2 else "medium" if n_signals == 1 else "low"

    return {
        "keyword": keyword,
        "intent": intent,
        "funnel": funnel,
        "lead_value": lead_value,
        "local": local,
        "brand": bool(own_brand),
        "competitor": competitor,
        "signals": {k: v for k, v in hits.items() if v},
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Opportunity score
# ---------------------------------------------------------------------------

OPPORTUNITY_WEIGHTS = {"demand": 0.30, "ease": 0.25, "lead_value": 0.30, "position": 0.15}
VOLUME_CAP = 100_000  # log-scaled demand saturates at 100k searches/month


def _position_factor(position: Optional[float]) -> Optional[float]:
    """Upside from the current ranking. None when no ranking data exists."""
    if position is None:
        return None
    if position <= 0:
        return 0.5        # tracked but not ranking: new-page opportunity
    if position <= 3:
        return 0.3        # already won: defend, limited headroom
    if position <= STRIKING_MAX:
        return 1.0        # striking distance: most clicks per unit of effort
    if position <= 50:
        return 0.6
    return 0.4


def opportunity_score(volume: Optional[float] = None, difficulty: Optional[float] = None,
                      position: Optional[float] = None, lead_value: Optional[float] = None,
                      relevance: float = 1.0, weights: Optional[dict] = None) -> dict:
    """0-100 keyword opportunity score with N/A components renormalized.

    Components (each 0-1):
        demand      log10(volume+1) / log10(VOLUME_CAP+1), capped at 1
        ease        1 - difficulty/100
        lead_value  from classify_intent() (BOFU 1.0, MOFU 0.6, TOFU 0.25)
        position    upside from the current ranking (see _position_factor)

    A component with no data is dropped and the remaining weights are
    renormalized (scoring-rubric Rule 5), and ``completeness`` reports the
    share of weight that had data so a reader can discount thin scores.
    ``relevance`` (0-1) is the business-fit multiplier — the operator's or
    client's judgement of whether ranking would matter to the business.
    """
    w = dict(OPPORTUNITY_WEIGHTS)
    if weights:
        w.update(weights)
    comps: dict[str, Optional[float]] = {
        "demand": (min(1.0, math.log10(max(0.0, float(volume)) + 1) / math.log10(VOLUME_CAP + 1))
                   if volume is not None else None),
        "ease": (max(0.0, min(1.0, 1 - float(difficulty) / 100)) if difficulty is not None else None),
        "lead_value": (max(0.0, min(1.0, float(lead_value))) if lead_value is not None else None),
        "position": _position_factor(position),
    }
    avail = {k: v for k, v in comps.items() if v is not None}
    total_w = sum(w[k] for k in avail)
    if total_w <= 0:
        raw = 0.0
    else:
        raw = sum(w[k] * v for k, v in avail.items()) / total_w
    rel = max(0.0, min(1.0, float(relevance)))
    score = round(100 * raw * rel, 1)
    return {
        "score": score,
        "components": {k: (round(v, 3) if v is not None else None) for k, v in comps.items()},
        "completeness": round(total_w / sum(w.values()), 2),
        "relevance": rel,
    }


def traffic_potential(volume: Optional[float], target_position: float = 3.0,
                      curve: Optional[dict] = None) -> Optional[float]:
    """Estimated monthly clicks if the keyword reached ``target_position``."""
    if volume is None:
        return None
    return round(float(volume) * expected_ctr(target_position, curve), 1)


def scenario_bucket(difficulty: Optional[float], lead_value: float,
                    position: Optional[float] = None) -> str:
    """Place a keyword in an action bucket.

    quick_win   already in striking distance, or easy (KD < 30) with lead value >= 0.6
    growth      moderate difficulty (KD < 60) with lead value >= 0.6
    long_term   hard (KD >= 60) but valuable (lead value >= 0.6)
    awareness   low lead value (TOFU) — publish for topical authority / AEO, not leads
    Unknown difficulty is treated as moderate.
    """
    if is_striking_distance(position) and lead_value >= 0.25:
        return "quick_win"
    kd = 45.0 if difficulty is None else float(difficulty)
    if lead_value < 0.6:
        return "awareness"
    if kd < 30:
        return "quick_win"
    if kd < 60:
        return "growth"
    return "long_term"


_GEO_PATTERNS = {
    "question": re.compile(r"^(what|how|why|when|who|which|where|is|are|can|does|do|should)\b|\?$"),
    "definition": re.compile(r"\b(what is|what are|meaning|definition|define)\b"),
    "comparison": re.compile(r"\b(vs|versus|compare|comparison|difference between|alternatives?)\b"),
    "list": re.compile(r"\b(best|top|examples|ideas|types|ways|tools|list)\b"),
    "how_to": re.compile(r"\b(how to|steps|guide|tutorial)\b"),
}


def geo_flags(keyword: str) -> list[str]:
    """Answer-engine formats a keyword is likely to trigger.

    These are the query shapes AI Overviews / ChatGPT / Perplexity most often
    answer directly, so content targeting them should open with a
    self-contained answer (see skills/seo-geo references). A flag is a format
    hint, not a prediction that an AI answer will appear.
    """
    text = (keyword or "").lower().strip()
    return [name for name, pat in _GEO_PATTERNS.items() if pat.search(text)]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (default 95%).

    Used for AI mention/citation rates, where n is small (a handful of runs
    per prompt) and the normal approximation misbehaves near 0 and 1.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def pct_change(old: Optional[float], new: Optional[float]) -> Optional[float]:
    """Percent change old -> new, None when undefined (old missing or zero)."""
    if old is None or new is None or old == 0:
        return None
    return round((new - old) / abs(old) * 100, 1)


def sign_test_p(n_up: int, n_down: int) -> float:
    """Exact two-sided sign test p-value (ties already removed).

    Used for paired period-over-period comparisons over the SAME prompts or
    keywords: each pair contributes one up or down; H0 is p(up) = 0.5.
    """
    n = n_up + n_down
    if n == 0:
        return 1.0
    k = min(n_up, n_down)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 6)


def holm_adjust(pvalues: list[float]) -> list[float]:
    """Holm-Bonferroni step-down adjustment; returns adjusted p in input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        val = min(1.0, (m - rank) * pvalues[idx])
        running = max(running, val)
        adjusted[idx] = round(running, 6)
    return adjusted


# ---------------------------------------------------------------------------
# Keyword cannibalization (query x page rows)
# ---------------------------------------------------------------------------

CANNIBAL_MIN_SHARE = 0.10


def detect_cannibalization(rows: Iterable[dict], brand_terms: Iterable[str] = (),
                           min_share: float = CANNIBAL_MIN_SHARE) -> list[dict]:
    """Find queries where two or more of the site's pages split the clicks.

    Rule (after J.C. Chouinard's published method): a query is cannibalized
    when at least two pages each take >= ``min_share`` of the query's clicks
    AND the query is >= ``min_share`` of each of those pages' clicks — i.e.
    the split matters to both the query and the pages. Branded queries are
    skipped (several pages legitimately rank for the brand). Queries with no
    clicks are evaluated on impressions and labelled basis="impressions"
    (weaker evidence).

    Each row needs query, page, clicks, impressions.
    """
    brands = [b.lower() for b in brand_terms if b]
    by_query: dict[str, list[dict]] = {}
    page_clicks: dict[str, float] = {}
    page_imps: dict[str, float] = {}
    for r in rows:
        q = (r.get("query") or "").strip().lower()
        page = r.get("page") or ""
        if not q or not page:
            continue
        if brands and any(_has_term(f" {q} ", b) for b in brands):
            continue
        clicks = float(r.get("clicks") or 0)
        imps = float(r.get("impressions") or 0)
        by_query.setdefault(q, []).append({"page": page, "clicks": clicks, "impressions": imps,
                                           "position": r.get("position")})
        page_clicks[page] = page_clicks.get(page, 0.0) + clicks
        page_imps[page] = page_imps.get(page, 0.0) + imps

    out = []
    for q, pages in by_query.items():
        if len(pages) < 2:
            continue
        total_clicks = sum(p["clicks"] for p in pages)
        basis = "clicks" if total_clicks >= 1 else "impressions"
        total = total_clicks if basis == "clicks" else sum(p["impressions"] for p in pages)
        if total <= 0:
            continue
        page_tot = page_clicks if basis == "clicks" else page_imps
        competing = []
        for p in pages:
            q_share = p[basis] / total
            p_share = (p[basis] / page_tot[p["page"]]) if page_tot.get(p["page"]) else 0.0
            if q_share >= min_share and p_share >= min_share:
                competing.append({"page": p["page"], "query_share": round(q_share, 3),
                                  "page_share": round(p_share, 3), "clicks": p["clicks"],
                                  "impressions": p["impressions"], "position": p["position"]})
        if len(competing) >= 2:
            competing.sort(key=lambda c: c["query_share"], reverse=True)
            out.append({"query": q, "basis": basis, "total": total, "pages": competing})
    out.sort(key=lambda c: c["total"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Text utilities shared by content optimization and gap analysis
# ---------------------------------------------------------------------------

STOPWORDS = frozenset("""
a about above after again against all am an and any are as at be because been
before being below between both but by can could did do does doing down during
each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself just me more most my myself no nor
not now of off on once only or other our ours ourselves out over own same she
should so some such than that the their theirs them themselves then there these
they this those through to too under until up very was we were what when where
which while who whom why will with would you your yours yourself yourselves
also get got may might must one two us via vs within without yet across per
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#'\-]*[a-z0-9+#]|[a-z0-9]")


def tokenize(text: str, drop_stopwords: bool = True, min_len: int = 2) -> list[str]:
    """Lowercase word tokens; stopwords and very short tokens removed by default."""
    toks = _TOKEN_RE.findall((text or "").lower())
    return [t for t in toks if len(t) >= min_len and not (drop_stopwords and t in STOPWORDS)]


def ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic SEO metric helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_int = sub.add_parser("intent", help="Classify search intent / funnel / lead value")
    p_int.add_argument("keywords", nargs="+")
    p_int.add_argument("--brand", action="append", default=[], help="Own brand term (repeatable)")
    p_int.add_argument("--competitor", action="append", default=[], help="Competitor brand (repeatable)")
    p_int.add_argument("--json", action="store_true")

    p_ctr = sub.add_parser("ctr", help="Expected CTR for a position")
    p_ctr.add_argument("position", type=float)
    p_ctr.add_argument("--json", action="store_true")

    p_sc = sub.add_parser("score", help="Opportunity score for one keyword")
    p_sc.add_argument("--keyword", required=True)
    p_sc.add_argument("--volume", type=float)
    p_sc.add_argument("--difficulty", type=float)
    p_sc.add_argument("--position", type=float)
    p_sc.add_argument("--relevance", type=float, default=1.0)
    p_sc.add_argument("--brand", action="append", default=[])
    p_sc.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.cmd == "intent":
        out = [classify_intent(k, args.brand, args.competitor) for k in args.keywords]
        if args.json:
            print(json.dumps(out, indent=2))
        else:
            for r in out:
                print(f"{r['keyword']:<45} {r['intent']:<14} {r['funnel']}  lead={r['lead_value']}"
                      f"  conf={r['confidence']}{'  local' if r['local'] else ''}")
    elif args.cmd == "ctr":
        out = {"position": args.position, "expected_ctr": round(expected_ctr(args.position), 4),
               "band": position_band(args.position), "source": CTR_CURVE_SOURCE}
        print(json.dumps(out, indent=2) if args.json else
              f"pos {args.position}: expected CTR {out['expected_ctr']:.1%} ({out['band']})")
    elif args.cmd == "score":
        intent = classify_intent(args.keyword, args.brand)
        res = opportunity_score(args.volume, args.difficulty, args.position,
                                intent["lead_value"], args.relevance)
        res.update({"keyword": args.keyword, "intent": intent["intent"], "funnel": intent["funnel"],
                    "traffic_potential_pos3": traffic_potential(args.volume)})
        print(json.dumps(res, indent=2) if args.json else
              f"{args.keyword}: {res['score']}/100 ({intent['intent']}/{intent['funnel']}, "
              f"completeness {res['completeness']:.0%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
