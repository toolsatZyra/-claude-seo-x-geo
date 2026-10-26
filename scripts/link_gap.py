#!/usr/bin/env python3
"""
Competitor link gap and prospect scoring for the seo-links skill.

Reads the latest referring-domain snapshot per target from ONE source (see
link_sources.py), segments every referring domain, removes non-prospects, then
classifies and scores the rest. Deterministic: no network, except that
prospects (and link_outreach.py add) may read the client's sitemap ONCE to derive topic terms
when the profile has none. Derived terms are stored in the links store and reused, so every
later run ranks identically; they are never written to the profile. gap and kpis never read
the sitemap.

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
    python link_gap.py prospects --project acme.io --source dataforseo --refresh-topics --json
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
from link_hosts import excluded_category, known_type  # noqa: E402
from link_store import (latest_snapshots, load_topics, open_store, save_topics,  # noqa: E402
                        snapshot_records)
from seo_kpi import EnvelopeError, write_envelope  # noqa: E402
from seo_metrics import STOPWORDS  # noqa: E402
from seo_project import all_brand_terms, load_profile  # noqa: E402
from seo_store import host_matches, normalize_domain, registrable_domain, utc_now  # noqa: E402

SPAM_THRESHOLD = 60.0
GENERIC_TLDS = frozenset({"com", "org", "net", "io", "co", "ai"})
COUNTRY_TLD_OVERRIDES = {"GB": "uk"}
SOCIAL_UGC_HOSTS = ("linkedin.com", "facebook.com", "x.com", "twitter.com", "instagram.com",
                    "youtube.com", "pinterest.com", "tiktok.com", "medium.com", "threads.net", "t.co",
                    "behance.net", "dribbble.com")  # last two: portfolios and job posts
# Hosting platforms whose subdomains are staging or preview sites, never editorial prospects.
STAGING_PLATFORM_HOSTS = ("wpengine.com", "kinsta.cloud", "netlify.app", "vercel.app", "herokuapp.com",
                          "pages.dev", "hostingersite.com")
# A subdomain label that starts with one of these (followed by a non-letter): staging.x.com, dev2.x.com.
STAGING_LABEL = re.compile(r"^(?:staging|stage|dev|test|uat|preview)(?![a-z])")
# stage/staging as a hyphenated part of a label: acme-staging.com, new-stage-site.com.
STAGING_PART = re.compile(r"(?:^|-)(?:stage|staging)(?:-|$)")
COMMUNITY_HOSTS = ("reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com")
DIRECTORY_HOSTS = ("clutch.co", "goodfirms.co", "designrush.com", "g2.com", "capterra.com",
                   "sortlist.com", "themanifest.com", "upcity.com", "trustpilot.com", "crunchbase.com",
                   "indiamart.com", "justdial.com", "sulekha.com", "tradeindia.com",
                   "cbinsights.com", "golden.com", "dealroom.co", "wellfound.com", "tracxn.com",
                   "owler.com", "zaubacorp.com")
# Link-selling and link-scheme signals, matched as whole words on the normalized URL, title and anchor
# (lowercase, every run of non-alphanumerics read as one space, so "buy-backlinks" == "buy backlinks").
SCHEME_PATTERNS = (r"sponsored", r"advertorials?", r"guest post(?:ing)? pricing", r"buy backlinks?",
                   r"link insertions?", r"paid posts?", r"backlinks?", r"seo links", r"buy links",
                   r"do ?follow", r"link building services?", r"guest post services?")
SCHEME_RE = re.compile(r"\b(?:" + "|".join(SCHEME_PATTERNS) + r")\b")
# Rules 1-6 look at the FIRST path segment (after a language prefix) and at the domain's own words,
# never at titles or deeper path segments, so blog posts that mention a word are not mistaken for pages of it.
DIRECTORY_TOKENS = frozenset({"directory", "directories", "listing", "listings", "companies", "vendors",
                              "agencies"})
DIRECTORY_SEGMENTS = DIRECTORY_TOKENS | frozenset({"company", "organization", "organizations", "profile",
                                                   "profiles", "wiki", "apps", "startups"})
ASSOCIATION_TOKENS = frozenset({"association", "society", "council", "chamber", "institute"})
COMMUNITY_TOKENS = frozenset({"forum", "forums", "community"})
EVENT_TOKENS = frozenset({"podcast", "podcasts", "episode", "episodes", "conference", "summit",
                          "webinar", "webinars", "expo", "awards", "event", "events"})
RESOURCE_TOKENS = frozenset({"resources", "resource", "links", "tools", "recommended"})
PARTNER_TOKENS = frozenset({"partners", "partner", "integrations", "integration", "marketplace",
                            "customers", "clients"})
EDITORIAL_LABELS = frozenset({"blog", "blogs", "learn"})
PUBLICATION_STRONG_PARTS = ("news", "magazine", "journal", "times")
PUBLICATION_WORD_PARTS = ("media",)  # only as a whole label or hyphen part: "my-media", never "digitalmedia"
LOCALE_SEGMENT = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2,4})?$")  # en, id, en-us, pt-br
# "top 10 video production companies": a ranking list where agencies get listed. "tools for agencies"
# and "software for companies" are not.
LISTICLE_RE = re.compile(r"\btop\b (?:\d+ )?(?:(?!for\b|tools?\b|software\b)[a-z0-9]+ ){0,6}?"
                         r"(?:companies|agencies)\b")
# Link-network footprint: the same path or title on this many distinct organizations in one snapshot.
NETWORK_MIN_DOMAINS = 5
# Paths many unrelated sites share for ordinary reasons: pagination and date archives.
NOT_FOOTPRINT_PATH = re.compile(r"(?:^|/)(?:page|p)/\d+$|^\d{4}(?:/\d{1,2}){0,2}$")
GENERIC_TITLES = frozenset({"just another wordpress site", "apache2 ubuntu default page: it works",
                            "welcome to nginx!", "index of /", "default web site page"})
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


def _norm_words(text: str) -> str:
    """Lowercase text with every run of non-alphanumerics read as one space."""
    return " ".join(_words(text))


def _segments(path: str) -> list:
    """Non-empty path segments, minus a leading language prefix (/en/, /id/, /pt-br/)."""
    segs = [x for x in (path or "").split("/") if x]
    if len(segs) > 1 and LOCALE_SEGMENT.match(segs[0]):
        segs = segs[1:]
    return segs


def _lead_words(segs: list) -> set:
    """Words of the first path segment when it is a short slug (at most 2 words), else none.

    A long first segment is an article slug ("how-to-pick-an-integration-partner"), not a section.
    """
    words = _words(segs[0]) if segs else []
    return set(words) if 0 < len(words) <= 2 else set()


def is_staging_host(domain: str) -> bool:
    """Staging, preview or dev hosting: a platform subdomain, or a staging-style host label."""
    if _host_in(domain, STAGING_PLATFORM_HOSTS):
        return True
    reg = registrable_domain(domain)
    sub = [x for x in domain[: -len(reg)].strip(".").split(".") if x] if reg and domain != reg else []
    if any(STAGING_LABEL.match(lab) or STAGING_PART.search(lab) for lab in sub):
        return True
    label = reg.split(".")[0]
    return "-" in label and bool(STAGING_PART.search(label))  # acme-staging.com, not stage.com


def classify(sig: dict) -> tuple:
    """(type, matched_rule) for one prospect; first matching rule wins. Always INFERRED."""
    dom = sig["domain"]
    url = (sig.get("sample_url") or "").lower()
    path = urlparse(url).path if url else ""
    segs = _segments(path)
    lead = _lead_words(segs)
    dom_words = set(_words(dom))
    host_labels = dom.split(".")
    editorial = bool((segs and segs[0] in EDITORIAL_LABELS) or EDITORIAL_LABELS & set(host_labels[:-2]))
    path_text = _norm_words(path)
    title_text = _norm_words(sig.get("sample_title") or "")
    hint = known_type(dom)
    if (((_host_in(dom, DIRECTORY_HOSTS) or hint == "directory") and not editorial)
            or DIRECTORY_SEGMENTS & lead
            or DIRECTORY_TOKENS & dom_words or LISTICLE_RE.search(path_text)
            or LISTICLE_RE.search(title_text)):
        return "directory", "rule1:directory-or-review"
    if (re.search(r"\.(?:edu|gov|mil)$|\.(?:ac|gov|edu)\.[a-z]{2}$", dom)
            or ASSOCIATION_TOKENS & (lead | dom_words)):
        return "association", "rule2:association-edu-gov"
    if _host_in(dom, COMMUNITY_HOSTS) or COMMUNITY_TOKENS & (lead | dom_words):
        return "community", "rule3:community"
    if hint == "event" or EVENT_TOKENS & (lead | dom_words):
        return "event", "rule4:event-or-podcast"
    if RESOURCE_TOKENS & lead:
        return "resource", "rule5:resource-page"
    if PARTNER_TOKENS & lead:
        return "partner", "rule6:partner-or-integration"
    article = re.search(r"/(?:news|article|articles)/|/(?:19|20)\d{2}/\d{1,2}/", path)
    labels = host_labels[:-1]
    strong = any(part in lab for lab in labels for part in PUBLICATION_STRONG_PARTS)
    word = any(part in lab.split("-") for lab in labels for part in PUBLICATION_WORD_PARTS)
    if hint == "publication":
        return "publication", "rule7:publication-known-host"
    if ((sig.get("authority") or 0) >= 60 and article) or strong or word:
        return "publication", "rule7:publication"
    if EDITORIAL_LABELS & set(host_labels[:-2]) or "/blog/" in path:
        return "blog", "rule8:blog"
    return "unclassified", "rule9:no-rule-matched"


def exclusion_reason(sig: dict, client: str, competitors: list,
                     network: Optional[dict] = None) -> Optional[str]:
    """Why a referring domain is not a prospect, or None. The order is fixed:
    own_property, competitor_property, social_ugc, staging_or_dev_host, then the link_hosts
    categories (invalid_host, url_shortener, press_release_wire, data_broker, content_farm,
    site_stats, job_board, social_ugc), spam, paid_or_scheme, link_network. ``network`` is
    link_network_domains() output for the same snapshots."""
    dom = sig["domain"]
    if host_matches(dom, client):
        return "own_property"
    if any(host_matches(dom, c) for c in competitors):
        return "competitor_property"
    if _host_in(dom, SOCIAL_UGC_HOSTS):
        return "social_ugc"
    if is_staging_host(dom):
        return "staging_or_dev_host"
    category = excluded_category(dom, sig.get("sample_url"))
    if category:
        return category
    spam = sig.get("spam_score")
    if isinstance(spam, (int, float)) and spam >= SPAM_THRESHOLD:
        return "spam"
    blob = _norm_words(" ".join(sig.get("texts") or []))
    if "sponsored" in (sig.get("attributes") or []) or SCHEME_RE.search(blob):
        return "paid_or_scheme"
    if network and dom in network:
        return "link_network"
    return None


def _footprint_path(url) -> str:
    """A path distinctive enough to fingerprint a network (language prefix dropped), or "".

    Two kinds qualify: a path carrying a numeric id, the usual link-farm page
    (/directory-website-list-1410/, /all/166/7.html, /report/21009), and a 2+ segment path
    with a long last segment. Pagination and date archives are not footprints.
    """
    try:
        path = urlparse((url or "").lower()).path
    except ValueError:
        return ""
    segs = _segments(path)
    if not segs:
        return ""
    joined = "/".join(segs)
    if NOT_FOOTPRINT_PATH.search(joined):
        return ""
    if re.search(r"\d", joined) or (len(segs) >= 2 and len(segs[-1]) >= 10):
        return "/" + joined
    return ""


def _footprint_title(title) -> str:
    text = " ".join((title or "").lower().split())
    if len(text) < 20 or len(text.split()) < 3 or text in GENERIC_TITLES:
        return ""
    return text


def link_network_domains(competitor_records: dict) -> dict:
    """{domain: detail} for domains that share a distinctive sample path or title with at least
    NETWORK_MIN_DOMAINS distinct referring domains in ONE competitor snapshot: a link farm's footprint."""
    flagged: dict = {}
    for comp in sorted(competitor_records):
        groups: dict = {}
        for rec in competitor_records[comp]:
            for kind, key in (("path", _footprint_path(rec.get("sample_url"))),
                              ("title", _footprint_title(rec.get("sample_title")))):
                if key:
                    groups.setdefault((kind, key), set()).add(rec["domain"])
        for (kind, key), domains in sorted(groups.items()):
            # Count organizations, not domains: one company on nine country TLDs is not a network.
            orgs = {registrable_domain(d).split(".")[0] for d in domains}
            if len(orgs) >= NETWORK_MIN_DOMAINS:
                for dom in domains:
                    flagged.setdefault(dom, f"same {kind} {key!r} on {len(domains)} domains in {comp}")
    return flagged


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
            topics_source: str, source: str, topics_derived_at: Optional[str] = None) -> dict:
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
    country = (profile.get("markets") or {}).get("country", "")
    network = link_network_domains(data["competitors"])
    merged = segment_domains(data["client"] or [], data["competitors"])
    counts = Counter(e["segment"] for e in merged.values())
    prospects, excluded = [], []
    for dom in sorted(merged):
        entry = merged[dom]
        if entry["segment"] not in ("gap", "single"):
            continue
        sig = merged_signals(entry)
        reason = exclusion_reason(sig, client, competitors, network)
        if reason:
            item = {"domain": dom, "reason": reason, "segment": entry["segment"],
                    "competitors": entry["competitors"]}
            if reason == "link_network":
                item["detail"] = network[dom]
            excluded.append(item)
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
            "topics": topics, "topics_source": topics_source, "topics_derived_at": topics_derived_at,
            "segments": {s: counts.get(s, 0) for s in SEGMENTS},
            "buckets": {b: buckets.get(b, 0) for b in BUCKETS},
            "warnings": warnings,
            "domains": [{"domain": d, "segment": merged[d]["segment"],
                         "competitors": merged[d]["competitors"]} for d in sorted(merged)],
            "prospects": prospects,
            "gap_prospects": [p for p in prospects if p["segment"] == "gap"],
            "excluded": excluded,
            "excluded_counts": dict(sorted(Counter(e["reason"] for e in excluded).items())),
            "kpis": {"links.referring_domains": len(data["client"] or []),
                     "links.gap_domains": counts.get("gap", 0)}}


def _profile_topics(profile: dict) -> list:
    return [t.strip().lower() for t in (profile.get("topics") or []) if isinstance(t, str) and t.strip()]


def resolve_project_topics(conn, client: str, profile: dict, may_crawl: bool,
                           crawl: Optional[Callable] = None, refresh: bool = False) -> dict:
    """The topic terms to score with: {"terms", "origin", "derived_at", "notes"}.

    Order: the profile's ``topics`` (origin "profile"); else the terms stored in the links store
    for this project (origin "sitemap"); else, only when ``may_crawl``, the 10 commonest sitemap
    slug tokens, which are stored for every later run. ``refresh`` re-reads the sitemap even when
    terms are stored; if that read yields nothing the stored terms are kept. The profile file is
    never written.
    """
    notes: list = []
    terms = _profile_topics(profile)
    if terms:
        return {"terms": terms, "origin": "profile", "derived_at": None, "notes": notes}
    stored = load_topics(conn, client)
    if stored and not (refresh and may_crawl):
        return {**stored, "notes": notes}
    if may_crawl:
        try:
            urls = (crawl or crawl_domain)(client).get("urls") or []
        except Exception as exc:  # noqa: BLE001 - an unreadable sitemap must not stop the analysis
            urls = []
            notes.append(f"the sitemap could not be read ({type(exc).__name__}: {exc})")
        derived, origin = resolve_topics(profile, urls)
        if origin == "sitemap":
            at = utc_now()
            save_topics(conn, client, derived, "sitemap", at)
            return {"terms": derived, "origin": "sitemap", "derived_at": at, "notes": notes}
        if stored:
            notes.append(f"topic refresh found no sitemap URLs; keeping the terms stored on "
                         f"{stored['derived_at']}")
            return {**stored, "notes": notes}
        notes.append("the sitemap gave no usable topic terms")
    return {"terms": [], "origin": "none", "derived_at": None, "notes": notes}


def topic_warnings(domain: str, resolved: dict) -> list:
    """What the user should know about where the topic terms came from."""
    out = list(resolved["notes"])
    if resolved["origin"] == "sitemap":
        out.append(f"topic terms come from the sitemap ({', '.join(resolved['terms'])}; derived "
                   f"{resolved['derived_at']}). Sitemap tokens are noisy: confirm or set the real service "
                   f"terms with seo_project.py set {domain} topics '[\"term one\", \"term two\"]' "
                   "(the profile always wins). --refresh-topics re-reads the sitemap.")
    elif resolved["origin"] == "none":
        out.append("no topic terms: topic fit is neutral (0.5) for every prospect; set them with "
                   f"seo_project.py set {domain} topics '[...]'")
    return out


def analyze_project(project: str, source: str, data_dir: Optional[str] = None,
                    use_sitemap: bool = True, crawl: Optional[Callable] = None,
                    refresh_topics: bool = False, derive_topics: bool = True) -> dict:
    """Load profile and snapshots for one source, then analyze. Raises GapError.

    ``derive_topics=False`` (gap, kpis) never reads the sitemap or the stored topics: those
    commands do not depend on topic fit. ``use_sitemap=False`` (--no-sitemap) still uses stored
    topics but does not read the sitemap now.
    """
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
    if derive_topics:
        resolved = resolve_project_topics(conn, client, profile, use_sitemap, crawl, refresh_topics)
    else:
        terms = _profile_topics(profile)
        resolved = {"terms": terms, "origin": "profile" if terms else "none", "derived_at": None, "notes": []}
    result = analyze(client, profile, competitors, data, resolved["terms"], resolved["origin"], source,
                     resolved["derived_at"])
    if derive_topics:
        result["warnings"] += topic_warnings(client, resolved)
    return result


def csv_safe(value):
    """Neutralize spreadsheet formulas: a text cell that starts with = + - @ (or a tab or carriage
    return) gets a leading apostrophe. Anchors and titles come from third-party pages."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


CSV_COLUMNS = ("domain", "score", "bucket", "effort", "type", "matched_rule", "segment", "k",
               "competitors", "tactic", "sample_url", "sample_anchor", "sample_title")


def _write_csv(path: str, prospects: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for p in prospects:
            first = next((e for e in p["evidence"] if e.get("sample_url")), p["evidence"][0])
            row = {"domain": p["domain"], "score": p["score"], "bucket": p["bucket"],
                   "effort": p["effort"], "type": p["type"],
                   "matched_rule": p["matched_rule"], "segment": p["segment"], "k": p["k"],
                   "competitors": ";".join(p["competitors"]), "tactic": p["tactic"],
                   "sample_url": first.get("sample_url") or "",
                   "sample_anchor": first.get("sample_anchor") or "",
                   "sample_title": first.get("sample_title") or ""}
            writer.writerow({key: csv_safe(value) for key, value in row.items()})


def _print(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    for key in ("project", "source", "topics_source", "segments", "buckets", "excluded_counts", "coverage"):
        if key in result:
            print(f"{key}: {result[key]}")
    for warning in result.get("warnings", []):
        print(f"WARNING: {warning}")
    def line(p):
        print(f"  {p['score']:3d}  {p['bucket']:10s} {p['effort']:6s} {p['type']:12s} "
              f"{p['domain']}  <- {', '.join(p['competitors'])}")

    if result.get("gap_prospects"):
        print("GAP PROSPECTS (link to 2+ competitors, not to you):")
        for p in result["gap_prospects"]:
            line(p)
    if result.get("prospects"):
        print("ALL SEGMENTS (ranked by score):")
        for p in result["prospects"]:
            line(p)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True, help="Client domain (profile slug)")
    common.add_argument("--source", required=True,
                        help="Snapshot source: dataforseo | moz | csv-ahrefs | csv-semrush | csv-gsc | csv-generic")
    common.add_argument("--no-sitemap", action="store_true",
                        help="Do not read the client sitemap now (stored topic terms are still used; "
                             "gap and kpis never read it)")
    common.add_argument("--data-dir", help="Storage root (default $CLAUDE_SEO_DATA_DIR or ~/.cache/claude-seo)")
    common.add_argument("--json", action="store_true", help="Output JSON")
    parser = argparse.ArgumentParser(description="Competitor link gap and prospect scoring (seo-links)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gap", parents=[common], help="Segment referring domains: gap/single/shared/moat")
    p = sub.add_parser("prospects", parents=[common], help="Classify, score and rank prospects")
    p.add_argument("--top", type=int, default=50, help="How many prospects to print (default 50)")
    p.add_argument("--refresh-topics", action="store_true",
                   help="Re-read the sitemap and replace the stored topic terms (profile topics still win)")
    p.add_argument("--csv", help="Also write the ranked prospects to this CSV file")
    k = sub.add_parser("kpis", parents=[common], help="Write links.referring_domains and links.gap_domains")
    k.add_argument("--emit-kpis", required=True, help="Path for the KPI envelope (performance_tracker.py ingest)")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = analyze_project(args.project, args.source, args.data_dir,
                                 use_sitemap=not args.no_sitemap,
                                 refresh_topics=getattr(args, "refresh_topics", False),
                                 derive_topics=args.cmd == "prospects")
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
                                        "topics_source", "topics_derived_at", "segments", "buckets",
                                        "warnings", "excluded_counts", "excluded")}
        shown["total_prospects"] = len(result["prospects"])
        shown["total_gap_prospects"] = len(result["gap_prospects"])
        shown["gap_prospects"] = result["gap_prospects"][:args.top]  # present these first
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
