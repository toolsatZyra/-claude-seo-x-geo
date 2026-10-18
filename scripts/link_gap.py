#!/usr/bin/env python3
"""
Competitor link gap and prospect scoring for the seo-links skill.

Reads the latest referring-domain snapshot per target from ONE source (see
link_sources.py), segments every referring domain, removes non-prospects, then
classifies and scores the rest. Deterministic: no network, except the optional
read of the client's sitemap used to derive topic terms when the profile has none.

Segments (competitors = profile competitors that have a snapshot from the source):
    gap     links to >= 2 competitors and not to the client
    single  links to exactly 1 competitor and not to the client
    shared  links to the client and at least 1 competitor
    moat    links to the client only

Prospect score (0-100), see skills/seo-links/references/prospect-scoring.md:
    round_half_up(30*overlap + 20*authority + 20*topic + 10*market + 10*quality + 10*type)

Usage:
    python link_gap.py gap --project acme.io --source dataforseo --json
    python link_gap.py prospects --project acme.io --source dataforseo --top 50 --json
    python link_gap.py prospects --project acme.io --source csv-ahrefs --no-sitemap --csv prospects.csv
    python link_gap.py kpis --project acme.io --source dataforseo --emit-kpis kpis-links-gap.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from competitor_gap import crawl_domain, slug_tokens  # noqa: E402
from keyword_research import fold_token  # noqa: E402
from link_store import latest_snapshots, open_store, snapshot_records  # noqa: E402
from seo_kpi import EnvelopeError, write_envelope  # noqa: E402
from seo_metrics import STOPWORDS  # noqa: E402
from seo_project import all_brand_terms, load_profile  # noqa: E402
from seo_store import host_matches, normalize_domain  # noqa: E402

SPAM_THRESHOLD = 60.0
GENERIC_TLDS = frozenset({"com", "org", "net", "io", "co", "ai"})
COUNTRY_TLD_OVERRIDES = {"GB": "uk"}
SOCIAL_UGC_HOSTS = ("linkedin.com", "facebook.com", "x.com", "twitter.com", "instagram.com",
                    "youtube.com", "pinterest.com", "tiktok.com", "medium.com", "threads.net", "t.co")
COMMUNITY_HOSTS = ("reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com")
DIRECTORY_HOSTS = ("clutch.co", "goodfirms.co", "designrush.com", "g2.com", "capterra.com",
                   "sortlist.com", "themanifest.com", "upcity.com", "trustpilot.com", "crunchbase.com",
                   "indiamart.com", "justdial.com", "sulekha.com", "tradeindia.com")
PAID_TOKENS = ("sponsored", "advertorial", "guest-post-pricing", "buy-backlinks", "link-insertion",
               "paid-post")
DIRECTORY_TOKENS = frozenset({"directory", "listing", "listings", "companies", "vendors", "agencies"})
ASSOCIATION_TOKENS = frozenset({"association", "society", "council", "chamber", "institute"})
COMMUNITY_TOKENS = frozenset({"forum", "forums", "community"})
EVENT_TOKENS = frozenset({"podcast", "podcasts", "episode", "episodes", "conference", "summit",
                          "webinar", "webinars", "expo", "awards", "event", "events"})
RESOURCE_TOKENS = frozenset({"resources", "resource", "links", "tools", "useful", "recommended"})
PARTNER_TOKENS = frozenset({"partners", "partner", "integrations", "integration", "marketplace",
                            "customers", "clients"})
PUBLICATION_LABEL_PARTS = ("news", "magazine", "journal", "times", "media")
EVIDENCE_FIELDS = ("authority", "spam_score", "dofollow", "attributes", "sample_url",
                   "sample_anchor", "sample_title", "tld")

WEIGHTS = {"overlap": 30, "authority": 20, "topic": 20, "market": 10, "quality": 10, "type": 10}
TYPE_VALUE = {"publication": 1.0, "association": 1.0, "resource": 0.8, "partner": 0.8, "event": 0.7,
              "directory": 0.6, "blog": 0.6, "unclassified": 0.5, "community": 0.3}
EFFORT = {"directory": "low", "partner": "low", "resource": "medium", "event": "medium",
          "association": "medium", "community": "medium", "unclassified": "medium",
          "publication": "high", "blog": "high"}
TACTIC = {
    "directory": "Create or complete a genuine profile; ask real clients for reviews",
    "partner": "Ask a vendor or partner you genuinely work with for a listing",
    "resource": "Offer your most relevant, genuinely useful page for their resource list",
    "event": "Pitch a speaker, panel or podcast guest slot",
    "association": "Join, or get listed as a member",
    "community": "Participate and answer questions; never drop links",
    "publication": "Pitch expert commentary or an original data point",
    "blog": "Offer an expert contribution or a correction; never paid",
    "unclassified": "Review the site manually before any outreach",
}
SEGMENTS = ("gap", "single", "shared", "moat")
BUCKETS = ("high_value", "quick_win", "backlog")


class GapError(ValueError):
    """The analysis cannot run (no profile, no competitors, or no client snapshot)."""


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def fold_words(text: str) -> list:
    """Lowercase alphanumeric words with naive plural folding (keyword_research.fold_token)."""
    return [fold_token(w) for w in _words(text)]


def _host_in(domain: str, hosts) -> bool:
    return any(domain == h or domain.endswith("." + h) for h in hosts)


def classify(sig: dict) -> tuple:
    """(type, matched_rule) for one prospect; first matching rule wins. Always INFERRED."""
    dom = sig["domain"]
    url = (sig.get("sample_url") or "").lower()
    path = urlparse(url).path if url else ""
    path_words = set(_words(path))
    text_words = path_words | set(_words(sig.get("sample_title") or ""))
    dom_words = set(_words(dom))
    if (_host_in(dom, DIRECTORY_HOSTS) or DIRECTORY_TOKENS & (text_words | dom_words)
            or re.search(r"top-[a-z0-9-]*-(?:companies|agencies)", path)):
        return "directory", "rule1:directory-or-review"
    if (re.search(r"\.(?:edu|gov|mil)$|\.(?:ac|gov|edu)\.[a-z]{2}$", dom)
            or ASSOCIATION_TOKENS & (text_words | dom_words)):
        return "association", "rule2:association-edu-gov"
    if _host_in(dom, COMMUNITY_HOSTS) or COMMUNITY_TOKENS & (text_words | dom_words):
        return "community", "rule3:community"
    if EVENT_TOKENS & (text_words | dom_words):
        return "event", "rule4:event-or-podcast"
    if RESOURCE_TOKENS & path_words:
        return "resource", "rule5:resource-page"
    if PARTNER_TOKENS & path_words:
        return "partner", "rule6:partner-or-integration"
    article = re.search(r"/(?:news|article|articles)/|/(?:19|20)\d{2}/\d{1,2}/", path)
    label = dom.rsplit(".", 1)[0]
    if ((sig.get("authority") or 0) >= 60 and article) or any(p in label for p in PUBLICATION_LABEL_PARTS):
        return "publication", "rule7:publication"
    if dom.startswith("blog.") or "/blog/" in path:
        return "blog", "rule8:blog"
    return "unclassified", "rule9:no-rule-matched"


def exclusion_reason(sig: dict, client: str, competitors: list) -> Optional[str]:
    """Why a referring domain is not a prospect, or None."""
    dom = sig["domain"]
    if host_matches(dom, client):
        return "own_property"
    if any(host_matches(dom, c) for c in competitors):
        return "competitor_property"
    if _host_in(dom, SOCIAL_UGC_HOSTS):
        return "social_ugc"
    spam = sig.get("spam_score")
    if isinstance(spam, (int, float)) and spam >= SPAM_THRESHOLD:
        return "spam"
    blob = " ".join(sig.get("texts") or []).lower()
    if "sponsored" in (sig.get("attributes") or []) or any(t in blob for t in PAID_TOKENS):
        return "paid_or_scheme"
    return None


def segment_domains(client_records: list, competitor_records: dict) -> dict:
    """Merge per-target records into {domain: {domain, competitors, evidence, k, segment}}."""
    client = {r["domain"] for r in client_records}
    merged: dict = {}
    for comp in sorted(competitor_records):
        for rec in competitor_records[comp]:
            entry = merged.setdefault(rec["domain"], {"domain": rec["domain"], "competitors": [],
                                                      "evidence": []})
            entry["competitors"].append(comp)
            entry["evidence"].append({"competitor": comp, **{f: rec.get(f) for f in EVIDENCE_FIELDS}})
    for rec in client_records:
        merged.setdefault(rec["domain"], {"domain": rec["domain"], "competitors": [], "evidence": []})
    for dom, entry in merged.items():
        k = len(entry["competitors"])
        in_client = dom in client
        entry["k"] = k
        entry["segment"] = ("shared" if in_client and k else "moat" if in_client
                            else "gap" if k >= 2 else "single")
    return merged


def merged_signals(entry: dict) -> dict:
    """One signal dict per referring domain from all its competitor evidence."""
    ev = entry["evidence"]
    auths = [e["authority"] for e in ev if isinstance(e.get("authority"), (int, float))]
    spams = [e["spam_score"] for e in ev if isinstance(e.get("spam_score"), (int, float))]
    dofollow = [e["dofollow"] for e in ev if isinstance(e.get("dofollow"), bool)]
    first = next((e for e in ev if e.get("sample_url")), ev[0] if ev else {})
    tld = next((e["tld"] for e in ev if e.get("tld")), entry["domain"].rsplit(".", 1)[-1])
    return {"domain": entry["domain"], "authority": max(auths) if auths else None,
            "spam_score": max(spams) if spams else None,
            "quality": (1.0 if any(dofollow) else 0.0) if dofollow else 0.5,
            "attributes": sorted({a for e in ev for a in (e.get("attributes") or [])}),
            "sample_url": first.get("sample_url"), "sample_title": first.get("sample_title"),
            "sample_anchor": first.get("sample_anchor"), "tld": tld,
            "texts": [t for e in ev for t in (e.get("sample_title"), e.get("sample_url"),
                                              e.get("sample_anchor")) if t]}


def topic_matches(terms: list, texts: list) -> int:
    """How many distinct topic terms appear as whole phrases in the texts (plural-folded)."""
    words: list = []
    for text in texts:
        words += fold_words(text) + [""]  # "" separates texts, so a phrase never spans two
    count = 0
    for term in terms:
        tw = fold_words(term)
        if tw and any(words[i:i + len(tw)] == tw for i in range(len(words) - len(tw) + 1)):
            count += 1
    return count


def market_fit(tld: str, country: str) -> float:
    """1.0 same-country ccTLD, 0.5 generic TLD, 0.2 any other ccTLD."""
    code = (country or "").upper()
    cc = COUNTRY_TLD_OVERRIDES.get(code, code.lower())
    tld = (tld or "").lower()
    if cc and tld == cc:
        return 1.0
    if tld in GENERIC_TLDS:
        return 0.5
    return 0.2


def _round_half_up(value: float) -> int:
    return int(Decimal(repr(round(value, 9))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def score_prospect(k: int, authority, topic_fit: float, market: float, quality: float,
                   type_: str) -> tuple:
    """(score 0-100, components 0-1) per references/prospect-scoring.md."""
    comps = {"overlap": min(k, 3) / 3,
             "authority": 0.5 if authority is None else max(0.0, min(float(authority), 100.0)) / 100,
             "topic": topic_fit, "market": market, "quality": quality, "type": TYPE_VALUE[type_]}
    total = sum(WEIGHTS[name] * value for name, value in comps.items())
    return _round_half_up(total), {name: round(value, 4) for name, value in comps.items()}


def plan_bucket(score: int, effort: str) -> str:
    """high_value (score >= 70), then quick_win (low effort, score >= 50), else backlog."""
    if score >= 70:
        return "high_value"
    if effort == "low" and score >= 50:
        return "quick_win"
    return "backlog"


def resolve_topics(profile: dict, sitemap_urls: Optional[list]) -> tuple:
    """(terms, origin): profile topics; else the 10 commonest sitemap slug tokens; else none."""
    terms = [t.strip().lower() for t in (profile.get("topics") or [])
             if isinstance(t, str) and t.strip()]
    if terms:
        return terms, "profile"
    if not sitemap_urls:
        return [], "none"
    brand = {fold_token(w) for t in all_brand_terms(profile) for w in _words(t)}
    counts: Counter = Counter()
    for url in sitemap_urls:
        for tok in set(slug_tokens(url)):
            if tok in brand or tok in STOPWORDS or tok.isdigit() or len(tok) < 3:
                continue
            counts[tok] += 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    return [tok for tok, _ in top], "sitemap"


def load_targets(conn, project: str, source: str, client: str, competitors: list) -> dict:
    latest = latest_snapshots(conn, project, source)
    data = {"client": None, "competitors": {}, "missing": [], "collected": {}, "row_cap_hit": []}
    if client in latest:
        data["client"] = snapshot_records(conn, latest[client]["id"])
        data["collected"][client] = latest[client]["collected_at"]
    for comp in competitors:
        if comp in latest:
            data["competitors"][comp] = snapshot_records(conn, latest[comp]["id"])
            data["collected"][comp] = latest[comp]["collected_at"]
        else:
            data["missing"].append(comp)
    wanted = {client, *competitors}
    data["row_cap_hit"] = sorted(t for t, row in latest.items() if row["row_cap_hit"] and t in wanted)
    return data


def analyze(client: str, profile: dict, competitors: list, data: dict, topics: list,
            topics_source: str, source: str) -> dict:
    warnings = []
    if data["missing"]:
        warnings.append(f"no {source} snapshot for: {', '.join(data['missing'])} "
                        "(coverage gap; never filled from another source)")
    if len(data["competitors"]) < 2:
        warnings.append("fewer than 2 competitors with data: the gap segment needs at least 2, "
                        "so only 'single' prospects are possible")
    if data["row_cap_hit"]:
        warnings.append(f"row cap hit for: {', '.join(data['row_cap_hit'])}; "
                        "lower-authority referring domains are missing")
    if not topics:
        warnings.append("no topic terms: topic fit is neutral (0.5) for every prospect; "
                        "set them with seo_project.py set <domain> topics '[...]'")
    country = (profile.get("markets") or {}).get("country", "")
    merged = segment_domains(data["client"] or [], data["competitors"])
    counts = Counter(e["segment"] for e in merged.values())
    prospects, excluded = [], []
    for dom in sorted(merged):
        entry = merged[dom]
        if entry["segment"] not in ("gap", "single"):
            continue
        sig = merged_signals(entry)
        reason = exclusion_reason(sig, client, competitors)
        if reason:
            excluded.append({"domain": dom, "reason": reason, "segment": entry["segment"],
                             "competitors": entry["competitors"]})
            continue
        type_, rule = classify(sig)
        if not sig["texts"] or not topics:
            topic_fit = 0.5
        else:
            topic_fit = min(topic_matches(topics, sig["texts"]), 3) / 3
        score, comps = score_prospect(entry["k"], sig["authority"], topic_fit,
                                      market_fit(sig["tld"], country), sig["quality"], type_)
        effort = EFFORT[type_]
        prospects.append({"domain": dom, "segment": entry["segment"],
                          "competitors": entry["competitors"], "k": entry["k"], "type": type_,
                          "matched_rule": rule, "score": score, "components": comps,
                          "effort": effort, "bucket": plan_bucket(score, effort),
                          "tactic": TACTIC[type_], "authority": sig["authority"],
                          "evidence": entry["evidence"]})
    prospects.sort(key=lambda p: (-p["score"], -p["k"], p["domain"]))
    buckets = Counter(p["bucket"] for p in prospects)
    return {"project": client, "source": source, "collected": data["collected"],
            "coverage": {"client": data["client"] is not None,
                         "competitors_with_data": sorted(data["competitors"]),
                         "missing": data["missing"], "row_cap_hit": data["row_cap_hit"]},
            "topics": topics, "topics_source": topics_source,
            "segments": {s: counts.get(s, 0) for s in SEGMENTS},
            "buckets": {b: buckets.get(b, 0) for b in BUCKETS},
            "warnings": warnings,
            "domains": [{"domain": d, "segment": merged[d]["segment"],
                         "competitors": merged[d]["competitors"]} for d in sorted(merged)],
            "prospects": prospects, "excluded": excluded,
            "kpis": {"links.referring_domains": len(data["client"] or []),
                     "links.gap_domains": counts.get("gap", 0)}}


def analyze_project(project: str, source: str, data_dir: Optional[str] = None,
                    use_sitemap: bool = True, crawl: Optional[Callable] = None) -> dict:
    """Load profile and snapshots for one source, then analyze. Raises GapError."""
    client = normalize_domain(project)
    profile = load_profile(client, data_dir)
    if not profile:
        raise GapError(f"no profile for {client}: run seo_project.py init {client} --competitor <domain>")
    competitors = [normalize_domain(c["domain"]) for c in profile.get("competitors") or []
                   if c.get("domain")]
    if not competitors:
        raise GapError("the profile lists no competitors: add 3-7 with seo_project.py add-competitor")
    conn = open_store(data_dir)
    data = load_targets(conn, client, source, client, competitors)
    if data["client"] is None:
        raise GapError(f"no {source} snapshot for the client {client}: run link_sources.py "
                       "fetch (or import) for the client first")
    sitemap_urls = None
    if use_sitemap and not profile.get("topics"):
        sitemap_urls = (crawl or crawl_domain)(client).get("urls") or []
    topics, topics_source = resolve_topics(profile, sitemap_urls)
    return analyze(client, profile, competitors, data, topics, topics_source, source)


CSV_COLUMNS = ("domain", "score", "bucket", "effort", "type", "matched_rule", "segment", "k",
               "competitors", "tactic", "sample_url", "sample_anchor", "sample_title")


def _write_csv(path: str, prospects: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for p in prospects:
            first = next((e for e in p["evidence"] if e.get("sample_url")), p["evidence"][0])
            writer.writerow({"domain": p["domain"], "score": p["score"], "bucket": p["bucket"],
                             "effort": p["effort"], "type": p["type"],
                             "matched_rule": p["matched_rule"], "segment": p["segment"], "k": p["k"],
                             "competitors": ";".join(p["competitors"]), "tactic": p["tactic"],
                             "sample_url": first.get("sample_url") or "",
                             "sample_anchor": first.get("sample_anchor") or "",
                             "sample_title": first.get("sample_title") or ""})


def _print(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    for key in ("project", "source", "topics_source", "segments", "buckets", "coverage"):
        if key in result:
            print(f"{key}: {result[key]}")
    for warning in result.get("warnings", []):
        print(f"WARNING: {warning}")
    for p in result.get("prospects", []):
        print(f"  {p['score']:3d}  {p['bucket']:10s} {p['effort']:6s} {p['type']:12s} "
              f"{p['domain']}  <- {', '.join(p['competitors'])}")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True, help="Client domain (profile slug)")
    common.add_argument("--source", required=True,
                        help="Snapshot source: dataforseo | moz | csv-ahrefs | csv-semrush | csv-gsc | csv-generic")
    common.add_argument("--no-sitemap", action="store_true",
                        help="Do not read the client sitemap to derive topic terms")
    common.add_argument("--data-dir", help="Storage root (default $CLAUDE_SEO_DATA_DIR or ~/.cache/claude-seo)")
    common.add_argument("--json", action="store_true", help="Output JSON")
    parser = argparse.ArgumentParser(description="Competitor link gap and prospect scoring (seo-links)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gap", parents=[common], help="Segment referring domains: gap/single/shared/moat")
    p = sub.add_parser("prospects", parents=[common], help="Classify, score and rank prospects")
    p.add_argument("--top", type=int, default=50, help="How many prospects to print (default 50)")
    p.add_argument("--csv", help="Also write the ranked prospects to this CSV file")
    k = sub.add_parser("kpis", parents=[common], help="Write links.referring_domains and links.gap_domains")
    k.add_argument("--emit-kpis", required=True, help="Path for the KPI envelope (performance_tracker.py ingest)")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = analyze_project(args.project, args.source, args.data_dir,
                                 use_sitemap=not args.no_sitemap)
    except ValueError as exc:  # GapError, a profile file that belongs to another domain, a bad --project
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "gap":
        _print({k: result[k] for k in ("project", "source", "collected", "coverage", "segments",
                                       "warnings", "domains")}, args.json)
        return 0
    if args.cmd == "prospects":
        if args.csv:
            _write_csv(args.csv, result["prospects"])
        shown = {k: result[k] for k in ("project", "source", "collected", "coverage", "topics",
                                        "topics_source", "segments", "buckets", "warnings",
                                        "excluded")}
        shown["total_prospects"] = len(result["prospects"])
        shown["prospects"] = result["prospects"][:args.top]
        _print(shown, args.json)
        return 0
    try:
        env = write_envelope(args.emit_kpis, result["project"], f"link_gap.py ({args.source})",
                             result["kpis"], meta={"data_source": args.source,
                                                   "collected": result["collected"]})
    except EnvelopeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    _print(env, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
