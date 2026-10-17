#!/usr/bin/env python3
"""
Competitor gap analysis for the seo-competitors skill.

Two subcommands, each emitting JSON with ``data_sources`` and ``limitations``:

  keywords  Segment keywords from ranking exports (ours + each competitor's)
            into four groups, using "ranks" = position <= --threshold:
              moat         only we rank
              battleground we and >= 1 competitor rank (leader + position delta)
              gap          >= 1 competitor ranks, we do not
              pioneer      in a supplied --universe, nobody ranks
            Gaps are ordered by gap priority = opportunity score (lead value
            from intent), tie-broken by how many competitors rank and the
            best competitor position. Comparison / alternatives / competitor-
            brand gaps are routed to seo-competitor-pages. A true keyword gap
            needs third-party ranking data (DataForSEO ranked keywords,
            Ahrefs or Semrush organic-keyword exports); Search Console only
            covers your own site.
  content   Free approximation from public XML sitemaps: discover sitemaps
            (robots.txt ``Sitemap:`` lines, then /sitemap.xml,
            /sitemap_index.xml), walk sitemap indexes within caps (.xml.gz
            decompressed with a size cap), classify every URL into a page type
            by path pattern, then report format gaps (page types competitors
            publish that we lack or have far fewer of) and topic gaps
            (competitor URL-slug token sets with no own slug at Jaccard >= 0.5),
            ranked by how many competitors cover them. All fetches go through
            url_safety (SSRF + DNS-rebinding protection); XML is parsed with
            entity resolution, DTD loading and network access disabled.

Method and thresholds: skills/seo-competitors/references/gap-segmentation.md.
Segmentation idea credited to aaron-he-zhu/seo-geo-claude-skills (Apache-2.0),
re-implemented here.

Usage:
    python competitor_gap.py keywords --own own.csv --competitor rival=rival.csv \\
        --competitor other=other.json --json
    python competitor_gap.py keywords --project example.com --own own.csv \\
        --competitor rival=rival.csv --universe suggestions.json --threshold 10
    python competitor_gap.py content --own example.com --competitor rival.com \\
        --competitor other.io --json
    python competitor_gap.py content --project example.com --max-urls 2000 --max-sitemaps 20
    python competitor_gap.py content --own example.com --input inventory.json --json  # offline

Exit codes: 0 ok; 1 bad input / no URLs discovered for the own domain.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import statistics
import sys
import time
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urljoin, urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from keyword_research import (  # noqa: E402
    InputError,
    _write,
    fold_token,
    greedy_jaccard_groups,
    jaccard,
    load_records,
    merge_records,
    rows_to_csv,
)
from seo_metrics import FUNNEL_LEAD_VALUE, classify_intent, geo_flags, opportunity_score, tokenize  # noqa: E402
from seo_project import all_brand_terms, competitor_terms, load_profile, registrable_label  # noqa: E402
from seo_store import host_matches, normalize_domain, utc_now  # noqa: E402

DEFAULT_THRESHOLD = 20.0
DEFAULT_MAX_URLS = 2000
DEFAULT_MAX_SITEMAPS = 20
# Statuses that mean "stop crawling this site now": access denied, rate
# limited, or unavailable. Retrying more sitemaps would only add load.
CRAWL_STOP_STATUSES = frozenset({403, 429, 503})
DEFAULT_MAX_BYTES = 20_000_000
DEFAULT_TIMEOUT = 20.0
DEFAULT_DELAY = 0.5
DEFAULT_MAX_TOPICS = 100
ROBOTS_MAX_BYTES = 512_000
TOPIC_JACCARD = 0.5
THIN_RATIO = 0.25
THIN_MIN_COMPETITOR_PAGES = 5

# ---------------------------------------------------------------------------
# keywords: 4-way segmentation
# ---------------------------------------------------------------------------


def parse_competitor_arg(value: str) -> tuple[str, str]:
    """``NAME=FILE`` -> (name, file). A bare FILE uses the file stem as name."""
    if "=" in value:
        name, path = value.split("=", 1)
        name, path = name.strip(), path.strip()
    else:
        path = value.strip()
        name = Path(path).stem
    if not name or not path:
        raise InputError(f"--competitor expects NAME=FILE, got {value!r}")
    return name, path


def _name_terms(name: str) -> list[str]:
    n = name.lower().strip()
    out = [n]
    if "." in n:
        label = registrable_label(n)
        if label and label not in out:
            out.append(label)
    return out


def _is_competitor_navigational(keyword: str, intent: dict) -> bool:
    """Competitor brand + navigational modifier, or the bare competitor name."""
    comps = intent.get("competitor") or []
    if not comps:
        return False
    if intent.get("signals", {}).get("navigational"):
        return True
    rest = f" {keyword} "
    for c in comps:
        rest = re.sub(r"(?<![a-z0-9])" + re.escape(c) + r"(?![a-z0-9])", " ", rest)
    return not rest.strip()


def segment_keywords(own: dict[str, dict], competitors: dict[str, dict[str, dict]],
                     universe: Optional[dict[str, dict]] = None,
                     threshold: float = DEFAULT_THRESHOLD, min_volume: float = 0.0,
                     brand_terms: Iterable[str] = (), competitor_terms_: Iterable[str] = (),
                     include_brand: bool = False) -> dict:
    """Pure segmentation. Inputs are merge_records() outputs keyed by keyword."""
    brands = list(brand_terms)
    comp_terms = list(competitor_terms_)
    for name in competitors:
        for t in _name_terms(name):
            if t not in comp_terms:
                comp_terms.append(t)
    universe = universe or {}

    all_kw: list[str] = []
    seen: set[str] = set()
    for source in [own, *competitors.values(), universe]:
        for kw in source:
            if kw not in seen:
                seen.add(kw)
                all_kw.append(kw)

    def ranks(rec: Optional[dict]) -> Optional[float]:
        if rec and rec.get("position") is not None and rec["position"] <= threshold:
            return rec["position"]
        return None

    segments: dict[str, list[dict]] = {"moat": [], "battleground": [], "gap": [], "pioneer": []}
    excluded = Counter()
    comp_stats = {name: {"name": name, "keywords_loaded": len(recs), "ranking": 0,
                         "in_gaps": 0, "leads_battlegrounds": 0, "shared_with_own": 0}
                  for name, recs in competitors.items()}
    own_ranking = 0

    for kw in all_kw:
        recs = [own.get(kw), *[c.get(kw) for c in competitors.values()], universe.get(kw)]
        volume = max((r["volume"] for r in recs if r and r.get("volume") is not None), default=None)
        difficulty = max((r["difficulty"] for r in recs if r and r.get("difficulty") is not None),
                         default=None)
        if volume is not None and volume < min_volume:
            excluded["below_min_volume"] += 1
            continue
        intent = classify_intent(kw, brands, comp_terms)
        # Only brand-*navigational* queries are excluded: "rival vs acme" mentions
        # our brand but is a late-funnel comparison gap worth winning.
        if not include_brand and intent["brand"] and intent["intent"] == "navigational":
            excluded["own_brand"] += 1
            continue
        if not include_brand and _is_competitor_navigational(kw, intent):
            excluded["competitor_navigational"] += 1
            continue

        own_rec = own.get(kw)
        own_pos = ranks(own_rec)
        comp_pos = {name: ranks(recs_.get(kw)) for name, recs_ in competitors.items()}
        comp_pos = {n: p for n, p in comp_pos.items() if p is not None}
        for n in comp_pos:
            comp_stats[n]["ranking"] += 1
            if own_pos is not None:
                comp_stats[n]["shared_with_own"] += 1
        if own_pos is not None:
            own_ranking += 1

        flags = geo_flags(kw)
        base = {"keyword": kw, "volume": volume, "difficulty": difficulty,
                "intent": intent["intent"], "funnel": intent["funnel"],
                "lead_value": intent["lead_value"], "geo_flags": flags}
        best_name, best_pos = (None, None)
        if comp_pos:
            best_name, best_pos = min(comp_pos.items(), key=lambda kv: (kv[1], kv[0]))

        if own_pos is not None and not comp_pos:
            opp = opportunity_score(volume, difficulty, own_pos, intent["lead_value"])
            segments["moat"].append({**base, "own_position": own_pos,
                                     "own_url": own_rec.get("url") if own_rec else None,
                                     "opportunity_score": opp["score"]})
        elif own_pos is not None:
            delta = round(own_pos - best_pos, 1)
            leader = "own" if delta < 0 else ("tie" if delta == 0 else best_name)
            if leader not in ("own", "tie"):
                comp_stats[best_name]["leads_battlegrounds"] += 1
            opp = opportunity_score(volume, difficulty, own_pos, intent["lead_value"])
            segments["battleground"].append({
                **base, "own_position": own_pos,
                "own_url": own_rec.get("url") if own_rec else None,
                "leader": leader, "best_competitor": best_name,
                "best_competitor_position": best_pos, "position_delta": delta,
                "competitors": dict(sorted(comp_pos.items())),
                "opportunity_score": opp["score"], "completeness": opp["completeness"]})
        elif comp_pos:
            own_any = own_rec.get("position") if own_rec else None
            opp = opportunity_score(volume, difficulty, own_any, intent["lead_value"])
            for n in comp_pos:
                comp_stats[n]["in_gaps"] += 1
            comparison = "comparison" in flags or bool(intent["competitor"])
            best_url = (competitors[best_name].get(kw) or {}).get("url")
            segments["gap"].append({
                **base, "gap_priority": opp["score"], "completeness": opp["completeness"],
                "competitors": dict(sorted(comp_pos.items())), "n_competitors": len(comp_pos),
                "best_competitor": best_name, "best_competitor_position": best_pos,
                "best_competitor_url": best_url, "own_position": own_any,
                "bofu": intent["funnel"] == "BOFU",
                "route": "seo-competitor-pages" if comparison else "seo-content-brief"})
        elif kw in universe:
            opp = opportunity_score(volume, difficulty, None, intent["lead_value"])
            segments["pioneer"].append({**base, "opportunity_score": opp["score"],
                                        "completeness": opp["completeness"]})
        else:
            excluded["nobody_ranks_not_in_universe"] += 1

    segments["gap"].sort(key=lambda g: (-g["gap_priority"], -g["n_competitors"],
                                        g["best_competitor_position"], g["keyword"]))
    segments["battleground"].sort(key=lambda b: (b["leader"] in ("own", "tie"),
                                                 -b["opportunity_score"], b["keyword"]))
    segments["moat"].sort(key=lambda m: (-(m["volume"] if m["volume"] is not None else -1.0),
                                         m["own_position"], m["keyword"]))
    segments["pioneer"].sort(key=lambda p: (-p["opportunity_score"], p["keyword"]))

    for name, st in comp_stats.items():
        st["overlap_with_own"] = round(st["shared_with_own"] / own_ranking, 3) if own_ranking else None

    gaps = segments["gap"]
    summary = {
        "counts": {k: len(v) for k, v in segments.items()},
        "own_ranking_keywords": own_ranking,
        "battlegrounds_trailing": sum(1 for b in segments["battleground"]
                                      if b["leader"] not in ("own", "tie")),
        "bofu_gaps": sum(1 for g in gaps if g["bofu"]),
        "competitor_pages_candidates": sum(1 for g in gaps if g["route"] == "seo-competitor-pages"),
        "excluded": dict(sorted(excluded.items())),
    }
    return {"segments": segments, "summary": summary,
            "competitors": [comp_stats[n] for n in competitors],
            "parameters": {"threshold": threshold, "min_volume": min_volume,
                           "brand_terms": brands, "competitor_terms": comp_terms,
                           "include_brand": include_brand}}


def keyword_limitations(threshold: float, has_universe: bool, own_meta: dict) -> list[str]:
    out = [
        f"'Ranks' means position <= {threshold:g} in the supplied exports; exports are "
        "snapshots from one date, location and device, and providers sample SERPs differently.",
        "Keyword sets come from third-party ranking databases, which miss long-tail and new "
        "queries; a keyword absent from an export is treated as not ranking.",
        "gap_priority uses seo_metrics.opportunity_score with lead value from rule-based intent; "
        "it ranks keywords, it does not forecast traffic.",
        "Volume and difficulty are the maximum across all supplied files; difficulty scales "
        "differ between providers.",
    ]
    if not has_universe:
        out.append("No --universe supplied: the pioneer segment (keywords nobody ranks for) "
                   "is empty by construction.")
    if own_meta.get("source") == "gsc":
        out.append("Own positions come from Search Console (impression-weighted average "
                   "position); competitor positions come from a rank database. Compare with care.")
    return out


# ---------------------------------------------------------------------------
# content: page-type taxonomy
# ---------------------------------------------------------------------------

# Segment vocabulary per page type. Sets are disjoint; the first path segment
# (left to right) that matches any set decides the type.
PAGE_TYPE_SEGMENTS: dict[str, frozenset] = {
    "blog": frozenset({"blog", "blogs", "articles", "article", "news", "insights", "posts", "post",
                       "guides", "guide", "learn", "resources", "library", "magazine", "journal",
                       "academy"}),
    "integrations": frozenset({"integrations", "integration", "connectors", "connector",
                               "marketplace", "apps", "app-directory", "extensions", "plugins"}),
    "pricing": frozenset({"pricing", "prices", "price", "plans", "plans-pricing",
                          "plans-and-pricing"}),
    "features": frozenset({"features", "feature", "capabilities", "platform", "product-tour",
                           "tour", "how-it-works"}),
    "solutions": frozenset({"solutions", "solution", "use-cases", "use-case", "usecases", "for",
                            "teams", "roles", "departments"}),
    "industries": frozenset({"industries", "industry", "sectors", "sector", "verticals"}),
    "customers": frozenset({"customers", "customer-stories", "case-studies", "case-study",
                            "casestudies", "success-stories", "testimonials", "work", "our-work",
                            "portfolio", "showcase"}),
    "services": frozenset({"services", "service", "what-we-do", "offerings"}),
    "docs": frozenset({"docs", "doc", "documentation", "help", "support", "kb", "knowledge-base",
                       "knowledgebase", "faq", "faqs", "api", "developers", "developer",
                       "help-center", "helpcenter", "manual"}),
    "templates": frozenset({"templates", "template"}),
    "glossary": frozenset({"glossary", "dictionary", "definitions", "wiki", "encyclopedia",
                           "terminology", "what-is"}),
    "tools": frozenset({"tools", "tool", "free-tools", "calculator", "calculators", "generator",
                        "generators", "checker", "checkers", "grader"}),
    "locations": frozenset({"locations", "location", "cities", "city", "areas", "service-areas",
                            "service-area", "near-me", "stores", "store-locator", "offices",
                            "branches"}),
    "careers": frozenset({"careers", "career", "jobs", "job", "hiring", "join-us", "work-with-us",
                          "vacancies"}),
    "legal": frozenset({"legal", "privacy", "privacy-policy", "terms", "terms-of-service",
                        "terms-and-conditions", "tos", "cookie-policy", "cookies", "gdpr", "dpa",
                        "imprint", "impressum", "disclaimer", "acceptable-use"}),
    "company": frozenset({"about", "about-us", "contact", "contact-us", "team", "partners",
                          "press", "company", "leadership"}),
}
_SEGMENT_TO_TYPE = {seg: t for t, segs in PAGE_TYPE_SEGMENTS.items() for seg in segs}

# (funnel stage, skill that acts on a gap of this format). None = not a lead-gen format.
PAGE_TYPE_INFO: dict[str, tuple[Optional[str], Optional[str]]] = {
    "comparison": ("BOFU", "seo-competitor-pages"),
    "alternatives": ("BOFU", "seo-competitor-pages"),
    "pricing": ("BOFU", "seo-content-brief"),
    "customers": ("BOFU", "seo-content-brief"),
    "services": ("BOFU", "seo-content-brief"),
    "locations": ("BOFU", "seo-programmatic"),
    "integrations": ("MOFU", "seo-programmatic"),
    "features": ("MOFU", "seo-content-brief"),
    "solutions": ("MOFU", "seo-content-brief"),
    "industries": ("MOFU", "seo-programmatic"),
    "templates": ("MOFU", "seo-programmatic"),
    "tools": ("MOFU", "seo-content-brief"),
    "glossary": ("TOFU", "seo-programmatic"),
    "blog": ("TOFU", "seo-cluster"),
    "docs": (None, None),
    "careers": (None, None),
    "legal": (None, None),
    "company": (None, None),
    "home": (None, None),
    "other": (None, None),
}
PAGE_TYPES = tuple(PAGE_TYPE_INFO)
TOPIC_EXCLUDED_TYPES = frozenset({"docs", "careers", "legal", "company", "home", "customers",
                                  "pricing"})
SLUG_NOISE = frozenset({"html", "htm", "php", "aspx", "asp", "amp", "index", "page", "www",
                        "en", "us", "uk", "default"})

_VS_RE = re.compile(r"(?:^|-)(?:vs|versus)(?:-|$)")
_COMPARE_RE = re.compile(r"^(?:compare|comparison|comparisons)(?:-|$)")
_ID_RE = re.compile(r"^(?:\d+|[0-9a-f]{8,})$")


def _segments(url: str) -> list[str]:
    path = urlparse(url).path.lower()
    segs = [s for s in path.split("/") if s]
    if segs:
        segs[-1] = re.sub(r"\.(?:html?|php|aspx?)$", "", segs[-1])
    return [s for s in segs if s]


def classify_page_type(url: str) -> str:
    """Classify a URL into a page type by its path (see PAGE_TYPE_SEGMENTS)."""
    segs = _segments(url)
    if not segs:
        return "home"
    if any("alternative" in s for s in segs):
        return "alternatives"
    if segs[0] not in PAGE_TYPE_SEGMENTS["pricing"] and any(
            _VS_RE.search(s) or _COMPARE_RE.match(s) for s in segs):
        return "comparison"
    for s in segs:
        if s in _SEGMENT_TO_TYPE:
            return _SEGMENT_TO_TYPE[s]
    last = segs[-1]
    if re.search(r"-(?:calculator|generator|checker|grader)s?$", last):
        return "tools"
    if re.search(r"-templates?$", last):
        return "templates"
    if last.startswith("what-is-"):
        return "glossary"
    return "other"


def slug_tokens(url: str) -> list[str]:
    """Topic tokens from the URL slug (last non-ID segment), plural-folded, in order."""
    segs = _segments(url)
    while segs and _ID_RE.match(segs[-1]):
        segs.pop()
    if not segs:
        return []
    out: list[str] = []
    for tok in tokenize(re.sub(r"[-_.+]+", " ", segs[-1])):
        if tok.isdigit() or tok in SLUG_NOISE:
            continue
        f = fold_token(tok)
        if f not in out:
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# content: sitemap discovery and safe parsing
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    url: str
    status: Optional[int] = None
    body: bytes = b""
    final_url: Optional[str] = None
    truncated: bool = False
    error: Optional[str] = None


def _supports_local_target_switch(fn: Callable) -> bool:
    try:
        return "allow_local_targets" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def bounded_fetch(url: str, max_bytes: int = DEFAULT_MAX_BYTES,
                  timeout: float = DEFAULT_TIMEOUT, from_content: bool = False) -> FetchResult:
    """SSRF/DNS-rebinding-safe streamed GET that stops reading at ``max_bytes``.

    Transfer encodings (Content-Encoding: gzip) are decoded incrementally by
    requests, and the cap applies to the decoded bytes, so a compression bomb
    cannot exhaust memory. ``from_content=True`` marks a URL that was read
    from fetched content (robots.txt ``Sitemap:`` lines, sitemap indexes):
    the operator's CLAUDE_SEO_LOCAL_TARGETS allowlist is then not honoured.
    """
    import requests
    from url_safety import URLSafetyError, safe_requests_get

    res = FetchResult(url=url)
    extra: dict[str, Any] = {}
    if from_content and _supports_local_target_switch(safe_requests_get):
        extra["allow_local_targets"] = False
    try:
        resp = safe_requests_get(url, timeout=timeout, stream=True, headers={
            "Accept": "application/xml,text/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5"}, **extra)
    except URLSafetyError as exc:
        res.error = f"url_safety: {exc}"
        return res
    except requests.RequestException as exc:
        res.error = f"{type(exc).__name__}: {exc}"
        return res
    try:
        res.status = resp.status_code
        res.final_url = resp.url
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(65536):
            if total + len(chunk) > max_bytes:
                chunks.append(chunk[:max_bytes - total])
                res.truncated = True
                break
            chunks.append(chunk)
            total += len(chunk)
        res.body = b"".join(chunks)
    except requests.RequestException as exc:
        res.error = f"{type(exc).__name__}: {exc}"
    finally:
        resp.close()
    return res


def maybe_gunzip(data: bytes, max_bytes: int = DEFAULT_MAX_BYTES) -> tuple[bytes, bool]:
    """Decompress gzip data (magic 1f 8b) to at most ``max_bytes``; returns (data, truncated)."""
    if not data.startswith(b"\x1f\x8b"):
        return data, False
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = d.decompress(data, max_bytes)
    except zlib.error:
        return b"", True
    return out, bool(d.unconsumed_tail) or len(out) >= max_bytes


def parse_robots_sitemaps(text: str, base_url: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.lower().startswith("sitemap:"):
            url = urljoin(base_url, line.split(":", 1)[1].strip())
            if url.startswith(("http://", "https://")) and url not in out:
                out.append(url)
    return out


def parse_sitemap(data: bytes, max_urls: int = DEFAULT_MAX_URLS) -> dict:
    """Parse a sitemap safely. Returns {kind, locs, truncated, error}.

    kind is "urlset", "sitemapindex", "text" or None. Entity declarations are
    refused outright; lxml runs with resolve_entities/load_dtd/no_network
    hardening and incrementally, so a truncated body still yields the URLs
    read before the cut.
    """
    from lxml import etree

    result: dict[str, Any] = {"kind": None, "locs": [], "truncated": False, "error": None}
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    head = data[:65536].lower()
    if b"<!entity" in head:
        result["error"] = "refused: sitemap declares XML entities"
        return result
    stripped = data.lstrip()
    if stripped and not stripped.startswith(b"<"):
        result["kind"] = "text"   # plain-text sitemap: one URL per line
        for line in stripped.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith(("http://", "https://")):
                if len(result["locs"]) >= max_urls:
                    result["truncated"] = True
                    break
                result["locs"].append(line)
        if not result["locs"]:
            result["error"] = "not a sitemap (no XML root and no URLs)"
        return result

    parser = etree.XMLPullParser(events=("start", "end"), resolve_entities=False,
                                 no_network=True, load_dtd=False, huge_tree=False,
                                 remove_comments=True, remove_pis=True)
    container = None
    depth = 0
    try:
        for i in range(0, len(data), 65536):
            parser.feed(data[i:i + 65536])
            for event, el in parser.read_events():
                tag = etree.QName(el).localname if isinstance(el.tag, str) else ""
                if event == "start":
                    depth += 1
                    if depth == 1:
                        result["kind"] = tag or None
                        container = "url" if tag == "urlset" else "sitemap"
                    continue
                depth -= 1
                if tag == "loc" and el.getparent() is not None and \
                        etree.QName(el.getparent()).localname == container:
                    loc = (el.text or "").strip()
                    if loc:
                        if len(result["locs"]) >= max_urls:
                            result["truncated"] = True
                            return result
                        result["locs"].append(loc)
                elif tag == container:
                    el.clear()
                    parent = el.getparent()
                    while parent is not None and el.getprevious() is not None:
                        del parent[0]
        parser.close()
    except etree.XMLSyntaxError as exc:
        result["error"] = f"XML parse error: {exc}"
        result["truncated"] = bool(result["locs"])
    if result["kind"] not in ("urlset", "sitemapindex", None):
        result["error"] = result["error"] or f"unsupported sitemap root <{result['kind']}>"
        result["locs"] = []
    return result


def _family(url: str) -> str:
    """Sitemap family key: file name with digits removed (post-sitemap2 -> post-sitemap)."""
    name = urlparse(url).path.rsplit("/", 1)[-1].lower()
    return re.sub(r"\d+", "", name)


def diversify(urls: list[str]) -> list[str]:
    """Interleave sitemaps by family so caps sample every content type, not just posts."""
    fams: dict[str, list[str]] = {}
    for u in urls:
        fams.setdefault(_family(u), []).append(u)
    out: list[str] = []
    longest = max((len(v) for v in fams.values()), default=0)
    for i in range(longest):
        for v in fams.values():
            if i < len(v):
                out.append(v[i])
    return out


def crawl_domain(domain: str, fetch: Optional[Callable[[str, int, bool], FetchResult]] = None,
                 max_urls: int = DEFAULT_MAX_URLS, max_sitemaps: int = DEFAULT_MAX_SITEMAPS,
                 max_bytes: int = DEFAULT_MAX_BYTES, delay: float = DEFAULT_DELAY,
                 sleep: Callable[[float], None] = time.sleep) -> dict:
    """Discover and read a domain's sitemaps within caps.

    ``fetch(url, max_bytes, from_content) -> FetchResult`` is injectable for
    tests; the default is bounded_fetch (url_safety-protected, streamed,
    size-capped). ``from_content`` is True for URLs read out of robots.txt or
    a sitemap index rather than built from the operator's domain.
    """
    domain = normalize_domain(domain)
    fetch = fetch or (lambda u, cap, fc: bounded_fetch(u, max_bytes=cap, from_content=fc))
    info: dict[str, Any] = {"domain": domain, "redirected_to": None, "robots_url": None,
                            "sitemaps_declared": [],
                            "sitemaps_fetched": [], "sitemap_attempts": 0, "sitemaps_skipped": 0,
                            "offsite_sitemaps_ignored": 0, "stopped": None, "urls_seen": 0,
                            "urls": [], "offsite_ignored": 0, "truncated": False, "errors": []}
    calls = {"n": 0}

    def get(url: str, cap: int, from_content: bool) -> FetchResult:
        if calls["n"] and delay > 0:
            sleep(delay)
        calls["n"] += 1
        r = fetch(url, cap, from_content)
        if r.body and len(r.body) > cap:   # defence in depth if a fetcher ignores the cap
            r.body, r.truncated = r.body[:cap], True
        return r

    origin = None
    declared: list[str] = []
    bases = [f"https://{domain}"] + ([f"https://www.{domain}"] if not domain.startswith("www.") else [])
    for base in bases:
        r = get(f"{base}/robots.txt", ROBOTS_MAX_BYTES, False)
        if r.error:
            info["errors"].append({"url": f"{base}/robots.txt", "error": r.error})
            continue
        final = r.final_url or f"{base}/robots.txt"
        origin = f"{urlparse(final).scheme}://{urlparse(final).netloc}"
        info["robots_url"] = final
        if not host_matches(final, domain):
            # The site moved (e.g. old.in -> www.new.studio): its pages now live
            # on the redirect target, so URLs there count as this domain's own.
            info["redirected_to"] = normalize_domain(final)
        if r.status == 200:
            declared = parse_robots_sitemaps(r.body.decode("utf-8", errors="replace"), final)
        break
    if origin is None:
        info["errors"].append({"url": domain, "error": "site unreachable over https"})
        return info
    info["sitemaps_declared"] = declared
    queue = list(declared) if declared else [f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml"]
    fallback = not declared
    # Fallback paths on the operator's own host are operator-derived; anything
    # declared in robots.txt, listed in an index, or reached via a cross-host
    # redirect came from fetched content.
    operator_derived = set(queue) if fallback and host_matches(origin, domain) else set()
    visited: set[str] = set()
    per_sitemap: list[list[str]] = []
    seen_urls: set[str] = set()

    def own_site(u: str) -> bool:
        return host_matches(u, domain) or bool(info["redirected_to"] and host_matches(u, info["redirected_to"]))

    # Every attempt counts toward max_sitemaps, including failures: a sitemap
    # index listing thousands of dead children must not turn into thousands
    # of requests.
    while queue and info["sitemap_attempts"] < max_sitemaps:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        info["sitemap_attempts"] += 1
        r = get(url, max_bytes, url not in operator_derived)
        if r.status in CRAWL_STOP_STATUSES:
            info["errors"].append({"url": url, "error": f"HTTP {r.status}"})
            info["stopped"] = f"HTTP {r.status} from {urlparse(url).netloc}: stopped crawling this site"
            info["truncated"] = True
            break
        if r.error or r.status != 200:
            info["errors"].append({"url": url, "error": r.error or f"HTTP {r.status}"})
            continue
        body, gz_trunc = maybe_gunzip(r.body, max_bytes)
        parsed = parse_sitemap(body, max_urls)
        if parsed["error"] and not parsed["locs"]:
            info["errors"].append({"url": url, "error": parsed["error"]})
            continue
        info["sitemaps_fetched"].append(url)
        if r.truncated or gz_trunc or parsed["truncated"]:
            info["truncated"] = True
        if parsed["error"]:
            info["errors"].append({"url": url, "error": parsed["error"] + " (partial read kept)"})
        if parsed["kind"] == "sitemapindex":
            children = [c for c in parsed["locs"] if c.startswith(("http://", "https://"))
                        and c not in visited]
            # Child sitemaps must live on the site itself (or its redirect
            # target / subdomains); an index cannot send the crawler elsewhere.
            onsite = [c for c in children if own_site(c)]
            info["offsite_sitemaps_ignored"] += len(children) - len(onsite)
            # Interleave first (so a cap still samples every sitemap type),
            # then keep only what the remaining attempt budget can fetch.
            room = max(0, max_sitemaps - info["sitemap_attempts"])
            combined = diversify(queue + onsite)
            if len(combined) > room:
                info["truncated"] = True
                info["sitemaps_skipped"] += len(combined) - room
            queue = combined[:room]
        else:
            kept = []
            for loc in parsed["locs"]:
                info["urls_seen"] += 1
                if not (host_matches(loc, domain) or
                        (info["redirected_to"] and host_matches(loc, info["redirected_to"]))):
                    info["offsite_ignored"] += 1
                    continue
                clean = loc.split("#", 1)[0]
                if clean not in seen_urls:
                    seen_urls.add(clean)
                    kept.append(clean)
            per_sitemap.append(kept)
        if fallback and parsed["kind"] in ("urlset", "sitemapindex", "text"):
            # /sitemap.xml worked: do not also read the /sitemap_index.xml fallback.
            queue = [q for q in queue if q != f"{origin}/sitemap_index.xml"]
            fallback = False
    info["sitemaps_skipped"] += len([q for q in queue if q not in visited])
    if info["sitemaps_skipped"]:
        info["truncated"] = True

    # Round-robin across sitemaps so the URL cap samples every sitemap evenly.
    merged: list[str] = []
    longest = max((len(v) for v in per_sitemap), default=0)
    for i in range(longest):
        for v in per_sitemap:
            if i < len(v):
                merged.append(v[i])
    if len(merged) > max_urls:
        info["truncated"] = True
    info["urls"] = merged[:max_urls]
    return info


# ---------------------------------------------------------------------------
# content: gap analysis (pure)
# ---------------------------------------------------------------------------

def _funnel_weight(page_type: str) -> float:
    funnel = PAGE_TYPE_INFO.get(page_type, (None, None))[0]
    return FUNNEL_LEAD_VALUE.get(funnel, 0.0) if funnel else 0.0


def analyze_content(inventories: dict[str, list[str]], own: str, competitors: list[str],
                    max_topics: int = DEFAULT_MAX_TOPICS, examples: int = 3) -> dict:
    """Format and topic gaps from URL inventories ({domain: [urls]})."""
    typed: dict[str, list[tuple[str, str]]] = {
        d: [(u, classify_page_type(u)) for u in inventories.get(d, [])] for d in [own, *competitors]}
    counts = {d: Counter(t for _, t in typed[d]) for d in typed}
    active = [c for c in competitors if typed[c]]

    matrix, format_gaps = [], []
    for pt in PAGE_TYPES:
        funnel, route = PAGE_TYPE_INFO[pt]
        comp_counts = {c: counts[c].get(pt, 0) for c in active}
        having = [n for n in comp_counts.values() if n > 0]
        median = round(float(statistics.median(having)), 1) if having else 0.0
        own_n = counts[own].get(pt, 0)
        matrix.append({"page_type": pt, "funnel": funnel, "own": own_n,
                       "competitors": comp_counts, "competitors_with": len(having),
                       "competitor_median": median})
        if funnel is None or not having:
            continue
        if own_n == 0:
            severity = "missing"
        elif median >= THIN_MIN_COMPETITOR_PAGES and own_n < THIN_RATIO * median:
            severity = "thin"
        else:
            continue
        ex = []
        for c in active:
            ex += [{"competitor": c, "url": u} for u, t in typed[c] if t == pt][:examples]
        format_gaps.append({"page_type": pt, "severity": severity, "own_count": own_n,
                            "competitor_counts": comp_counts, "competitors_with": len(having),
                            "competitor_median": median, "funnel": funnel,
                            "lead_gen_format": funnel in ("BOFU", "MOFU"), "route": route,
                            "examples": ex})
    format_gaps.sort(key=lambda g: (g["severity"] != "missing", -_funnel_weight(g["page_type"]),
                                    -g["competitors_with"], -g["competitor_median"], g["page_type"]))

    # Topic gaps: competitor slug token sets with no own slug at Jaccard >= 0.5.
    own_sets = [frozenset(slug_tokens(u)) for u, _ in typed[own]]
    index: dict[str, set[int]] = defaultdict(set)
    for i, s in enumerate(own_sets):
        for t in s:
            index[t].add(i)
    uncovered = []
    for c in active:
        for u, pt in typed[c]:
            if pt in TOPIC_EXCLUDED_TYPES:
                continue
            toks = slug_tokens(u)
            s = frozenset(toks)
            if not s:
                continue
            cands: set[int] = set()
            for t in s:
                cands |= index.get(t, set())
            if any(jaccard(s, own_sets[i]) >= TOPIC_JACCARD for i in cands):
                continue
            uncovered.append({"competitor": c, "url": u, "page_type": pt, "tokens": toks})
    # Group within a page type: a topic then has one format, funnel and route,
    # and short slugs cannot pull unrelated formats together (e.g. an
    # /integrations/hubspot page into a "hubspot alternatives" topic).
    by_type: dict[str, list[dict]] = defaultdict(list)
    for x in uncovered:
        by_type[x["page_type"]].append(x)
    topics = []
    for pt in sorted(by_type):
        items_pt = sorted(by_type[pt], key=lambda x: (" ".join(sorted(x["tokens"])),
                                                     x["competitor"], x["url"]))
        funnel, route = PAGE_TYPE_INFO[pt]
        for members in greedy_jaccard_groups([x["tokens"] for x in items_pt], TOPIC_JACCARD):
            items = [items_pt[i] for i in members]
            comps = sorted({x["competitor"] for x in items})
            topics.append({"topic": " ".join(items[0]["tokens"]), "tokens": items[0]["tokens"],
                           "page_type": pt, "competitors": comps, "n_competitors": len(comps),
                           "pages": len(items), "funnel": funnel,
                           "route": route or "seo-content-brief",
                           "examples": [{"competitor": x["competitor"], "url": x["url"]}
                                        for x in items[:5]]})
    topics.sort(key=lambda t: (-t["n_competitors"], -FUNNEL_LEAD_VALUE.get(t["funnel"] or "", 0.0),
                               -t["pages"], t["topic"], t["page_type"]))
    return {
        "page_type_counts": {d: dict(sorted(counts[d].items())) for d in counts},
        "page_type_matrix": matrix,
        "format_gaps": format_gaps,
        "topic_gaps": topics[:max_topics] if max_topics else topics,
        "topic_gaps_total": len(topics),
        "competitors_without_urls": [c for c in competitors if not typed[c]],
    }


def content_limitations(domains: dict[str, dict], competitors_without_urls: list[str]) -> list[str]:
    out = [
        "Inventories come from XML sitemaps only: pages missing from a sitemap are invisible, "
        "and a sitemap URL is not proof the page is indexed or ranks.",
        "Page types are inferred from URL path patterns, not page content; a /blog/x-vs-y URL "
        "counts as a comparison page.",
        "Topic gaps compare URL slugs, not page content: a topic we cover under a different "
        "slug can still be listed (INFERRED, verify before briefing).",
        "This is a content/format gap approximation; a true keyword gap needs ranking data "
        "(competitor_gap.py keywords with DataForSEO / Ahrefs / Semrush exports).",
    ]
    truncated = [d for d, i in domains.items() if i.get("truncated")]
    if truncated:
        out.append("Caps truncated the inventory for " + ", ".join(sorted(truncated)) +
                   "; counts there are samples (round-robin across sitemaps), so 'thin' "
                   "comparisons are approximate.")
    moved = [f"{d} -> {i['redirected_to']}" for d, i in sorted(domains.items())
             if i.get("redirected_to")]
    if moved:
        out.append("Redirected domains (" + ", ".join(moved) + "): sitemap URLs on the "
                   "redirect target were treated as that domain's own pages.")
    if competitors_without_urls:
        out.append("No URLs discovered for " + ", ".join(competitors_without_urls) +
                   "; they are excluded from the gap comparison.")
    return out


def load_inventory(path: str) -> dict[str, list[str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"{path}: cannot read inventory JSON ({exc})") from exc
    if isinstance(data, dict) and isinstance(data.get("domains"), dict):
        data = data["domains"]
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise InputError(f"{path}: expected {{\"domains\": {{domain: [urls]}}}} or {{domain: [urls]}}")
    return {normalize_domain(d): [str(u) for u in urls if isinstance(u, str)] for d, urls in data.items()}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _profile(project: Optional[str], data_dir: Optional[str]) -> Optional[dict]:
    if not project:
        return None
    profile = load_profile(project, data_dir)
    if profile is None:
        raise InputError(f"no project profile for {project!r}; create one with "
                         f"`python scripts/seo_project.py init {project}`")
    return profile


def _load_merged(path: str, difficulty_column: Optional[str]) -> tuple[dict, dict]:
    records, meta = load_records(path, difficulty_column)
    return merge_records(records), meta


GAP_CSV_COLUMNS = ("segment", "keyword", "volume", "difficulty", "intent", "funnel", "lead_value",
                   "gap_priority", "opportunity_score", "own_position", "best_competitor",
                   "best_competitor_position", "position_delta", "leader", "n_competitors",
                   "bofu", "route", "geo_flags")


def cmd_keywords(args: argparse.Namespace) -> int:
    profile = _profile(args.project, args.data_dir)
    brands = [b.lower() for b in args.brand] or (all_brand_terms(profile) if profile else [])
    comp_terms = [c.lower() for c in args.competitor_term] or (competitor_terms(profile) if profile else [])
    if not args.competitor:
        raise InputError("pass at least one --competitor NAME=FILE")
    own, own_meta = _load_merged(args.own, args.difficulty_column)
    comps: dict[str, dict] = {}
    metas = [own_meta]
    for spec in args.competitor:
        name, path = parse_competitor_arg(spec)
        if name in comps:
            raise InputError(f"duplicate competitor name {name!r}")
        comps[name], meta = _load_merged(path, args.difficulty_column)
        metas.append(meta)
    universe = None
    if args.universe:
        universe, meta = _load_merged(args.universe, args.difficulty_column)
        metas.append(meta)
    seg = segment_keywords(own, comps, universe, args.threshold, args.min_volume, brands,
                           comp_terms, args.include_brand)
    for st, spec in zip(seg["competitors"], args.competitor):
        st["file"] = parse_competitor_arg(spec)[1]
    limitations = keyword_limitations(args.threshold, bool(args.universe), own_meta)
    limitations += [f"{m['path']}: {n}" for m in metas for n in m["notes"]]
    result = {"generated_at": utc_now(), "inputs": metas, **seg,
              "data_sources": [f"{m['path']} ({m['source']}, {m['records']} records)" for m in metas],
              "limitations": limitations}
    if args.limit and args.limit > 0:
        for k, v in result["segments"].items():
            if len(v) > args.limit:
                result["segments"][k] = v[:args.limit]
                result["limitations"].append(f"{k} list truncated to --limit {args.limit} "
                                             f"(count {seg['summary']['counts'][k]})")
    csv_rows = [{"segment": k, **r} for k, rows in result["segments"].items() for r in rows]
    _emit_result(result, args, csv_rows, GAP_CSV_COLUMNS, _summary_keywords)
    return 0


def cmd_content(args: argparse.Namespace) -> int:
    profile = _profile(args.project, args.data_dir)
    own = normalize_domain(args.own or (profile or {}).get("domain") or "")
    if not own:
        raise InputError("pass --own DOMAIN or --project")
    if args.competitor:
        comps = [normalize_domain(c) for c in args.competitor]
    elif profile:
        comps = [normalize_domain(c["domain"]) for c in profile.get("competitors", [])]
    else:
        comps = []
    domains_info: dict[str, dict] = {}
    inv = load_inventory(args.input) if args.input else None
    if inv is not None and not comps:
        comps = list(inv)
    comps = [c for c in dict.fromkeys(comps) if c and c != own]   # dedupe, keep order
    if not comps:
        raise InputError("pass at least one --competitor DOMAIN (or add competitors to the profile)")
    if inv is not None:
        for d in [own, *comps]:
            urls = inv.get(d, [])
            domains_info[d] = {"domain": d, "source": args.input, "urls": urls[:args.max_urls],
                               "urls_seen": len(urls), "truncated": len(urls) > args.max_urls,
                               "errors": []}
        sources = [f"URL inventory from {args.input}"]
    else:
        for d in [own, *comps]:
            domains_info[d] = crawl_domain(d, max_urls=args.max_urls, max_sitemaps=args.max_sitemaps,
                                           max_bytes=args.max_bytes, delay=args.delay)
        sources = [f"XML sitemaps of {d} ({len(i['sitemaps_fetched'])} fetched via url_safety)"
                   for d, i in domains_info.items()]
    if not domains_info[own]["urls"]:
        result = {"error": f"no URLs discovered for own domain {own}; gaps not computed "
                           "(every competitor format would look 'missing')",
                  "domains": {d: {k: v for k, v in i.items() if k != "urls"}
                              for d, i in domains_info.items()},
                  "data_sources": sources, "limitations": []}
        if args.output:
            _write(args.output, json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(result, indent=2) if args.json else f"Error: {result['error']}",
              file=sys.stdout if args.json else sys.stderr)
        return 1
    analysis = analyze_content({d: i["urls"] for d, i in domains_info.items()}, own, comps,
                               args.max_topics)
    domains_out = {}
    for d, i in domains_info.items():
        summary = {k: v for k, v in i.items() if k != "urls"}
        summary["urls_kept"] = len(i["urls"])
        summary["page_types"] = analysis["page_type_counts"].get(d, {})
        domains_out[d] = summary
    result = {"generated_at": utc_now(), "own": own, "competitors": comps, "domains": domains_out,
              **{k: v for k, v in analysis.items() if k != "page_type_counts"},
              "caps": {"max_urls": args.max_urls, "max_sitemaps": args.max_sitemaps,
                       "max_bytes": args.max_bytes, "max_topics": args.max_topics},
              "data_sources": sources,
              "limitations": content_limitations(domains_out, analysis["competitors_without_urls"])}
    csv_rows = [{"kind": "format_gap", "item": g["page_type"], "severity": g["severity"],
                 "own_count": g["own_count"], "competitors_with": g["competitors_with"],
                 "funnel": g["funnel"], "route": g["route"],
                 "examples": [e["url"] for e in g["examples"]]} for g in result["format_gaps"]]
    csv_rows += [{"kind": "topic_gap", "item": f"{t['topic']} [{t['page_type']}]",
                  "competitors_with": t["n_competitors"],
                  "funnel": t["funnel"], "route": t["route"],
                  "examples": [e["url"] for e in t["examples"]]} for t in result["topic_gaps"]]
    _emit_result(result, args, csv_rows, ("kind", "item", "severity", "own_count",
                                          "competitors_with", "funnel", "route", "examples"),
                 _summary_content)
    return 0


def _emit_result(result: dict, args: argparse.Namespace, csv_rows: list[dict],
                 csv_cols: Iterable[str], summary_fn: Callable[[dict], str]) -> None:
    if args.output:
        _write(args.output, rows_to_csv(csv_rows, csv_cols) if args.output.lower().endswith(".csv")
               else json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(summary_fn(result))
        if args.output:
            print(f"\nWrote {args.output}")


def _summary_keywords(r: dict) -> str:
    s = r["summary"]
    lines = [f"Keyword gap (ranks = position <= {r['parameters']['threshold']:g}): {s['counts']}",
             f"  excluded {s['excluded']}; BOFU gaps {s['bofu_gaps']}; "
             f"competitor-page candidates {s['competitor_pages_candidates']}",
             "  Top gaps (priority, competitors, best position, keyword):"]
    for g in r["segments"]["gap"][:20]:
        lines.append(f"    {g['gap_priority']:>5.1f}  {g['n_competitors']}  "
                     f"{g['best_competitor']}@{g['best_competitor_position']:g}  {g['keyword']}"
                     + ("  -> seo-competitor-pages" if g["route"] == "seo-competitor-pages" else ""))
    lines.append(f"  Battlegrounds where a competitor leads: {s['battlegrounds_trailing']}")
    for c in r["competitors"]:
        lines.append(f"  {c['name']}: ranks {c['ranking']}, in gaps {c['in_gaps']}, leads "
                     f"{c['leads_battlegrounds']} battlegrounds, overlap {c['overlap_with_own']}")
    return "\n".join(lines)


def _summary_content(r: dict) -> str:
    lines = [f"Content gap: {r['own']} vs {', '.join(r['competitors'])}"]
    for d, i in r["domains"].items():
        lines.append(f"  {d}: {i['urls_kept']} URLs{' (truncated)' if i.get('truncated') else ''} "
                     f"{i['page_types']}")
    lines.append("  Format gaps:")
    for g in r["format_gaps"]:
        lines.append(f"    {g['severity']:<8} {g['page_type']:<13} own {g['own_count']}, "
                     f"{g['competitors_with']} competitor(s), median {g['competitor_median']}"
                     f" -> {g['route']}")
    lines.append(f"  Topic gaps: {r['topic_gaps_total']} (top 15)")
    for t in r["topic_gaps"][:15]:
        lines.append(f"    {t['n_competitors']}  {t['topic']}  [{t['page_type']}]  "
                     f"({', '.join(t['competitors'])})")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", help="Project profile (domain or slug)")
    common.add_argument("--data-dir", help="Storage root override (see seo_store.py)")
    common.add_argument("--json", action="store_true", help="Print the full JSON result")
    common.add_argument("--output", help="Write the result to .json or .csv")

    parser = argparse.ArgumentParser(description="Competitor keyword and content gap analysis")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("keywords", parents=[common], help="4-way keyword segmentation from "
                                                          "ranking exports")
    p.add_argument("--own", required=True, help="Our ranking export (JSON or CSV)")
    p.add_argument("--competitor", action="append", default=[], metavar="NAME=FILE",
                   help="Competitor ranking export (repeatable)")
    p.add_argument("--universe", help="Keyword universe file for the pioneer segment")
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                   help=f"Ranks = position <= this (default {DEFAULT_THRESHOLD:g})")
    p.add_argument("--min-volume", type=float, default=0.0,
                   help="Drop keywords with known volume below N (default 0)")
    p.add_argument("--brand", action="append", default=[], help="Own brand term (repeatable)")
    p.add_argument("--competitor-term", action="append", default=[],
                   help="Extra competitor brand term (repeatable); competitor NAMEs are added")
    p.add_argument("--include-brand", action="store_true",
                   help="Keep own-brand and competitor-navigational keywords")
    p.add_argument("--difficulty-column", help="Explicit difficulty column name")
    p.add_argument("--limit", type=int, default=500, help="Max rows per segment list (0 = all)")
    p.set_defaults(func=cmd_keywords)

    p = sub.add_parser("content", parents=[common], help="Format and topic gaps from sitemaps")
    p.add_argument("--own", help="Our domain (default: profile domain)")
    p.add_argument("--competitor", action="append", default=[], metavar="DOMAIN",
                   help="Competitor domain (repeatable; default: profile competitors)")
    p.add_argument("--input", help="Offline URL inventory JSON {domain: [urls]} instead of fetching")
    p.add_argument("--max-urls", type=int, default=DEFAULT_MAX_URLS,
                   help=f"Max page URLs kept per domain (default {DEFAULT_MAX_URLS})")
    p.add_argument("--max-sitemaps", type=int, default=DEFAULT_MAX_SITEMAPS,
                   help=f"Max sitemap files fetched per domain (default {DEFAULT_MAX_SITEMAPS})")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                   help=f"Max decompressed bytes per sitemap (default {DEFAULT_MAX_BYTES})")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                   help=f"Seconds between requests to a domain (default {DEFAULT_DELAY})")
    p.add_argument("--max-topics", type=int, default=DEFAULT_MAX_TOPICS,
                   help=f"Max topic gaps listed, 0 = all (default {DEFAULT_MAX_TOPICS})")
    p.set_defaults(func=cmd_content)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    for name in ("max_urls", "max_sitemaps", "max_bytes"):
        if getattr(args, name, 1) is not None and getattr(args, name, 1) <= 0:
            print(f"Error: --{name.replace('_', '-')} must be > 0", file=sys.stderr)
            return 1
    try:
        return args.func(args)
    except InputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
