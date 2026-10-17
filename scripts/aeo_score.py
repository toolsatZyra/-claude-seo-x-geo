#!/usr/bin/env python3
"""
The single AEO Readiness Score, and its deterministic AI-crawler-access input.

Before v3.1 the plugin carried four competing "AEO/GEO score" definitions
(seo-audit used the citability figure alone, agents/seo-geo.md a pre-merge
5-dimension "GEO Health", geo-platform-optimizer a "Combined GEO Score", and
geo-compare / geo-proposal / geo-prospect a "GEO Score" nothing produced).
This script is now the only place the AEO number is computed.

compute
    Weighted composite of six component scores (each 0-100, measured by its
    own skill). Weights come from zubair-trabzada/geo-seo-claude's composite
    GEO score (MIT; skills/geo-audit/SKILL.md, "Composite GEO Score
    Calculation"): citability 25, brand_authority 20, content_eeat 20,
    crawler_access 15, schema 10, platform 10. A component that was not
    measured is N/A: it is dropped from numerator AND denominator and the
    remaining weights renormalize (scoring-rubric Rule 5); ``completeness``
    reports the share of nominal weight that had data. ``expression`` is a
    literal Python expression that reproduces the score, so a reader can run
    ``python3 -c "print(<expression>)"`` (scoring-rubric Rule 4).

    Rounding: Python ``round()`` to an integer (ties go to the even integer),
    the same convention as the SEO Health Score expression in seo-audit.

    AI share of voice (ai_visibility.py) is an OUTCOME metric. It is never a
    component of this readiness score, and this score is never blended with
    the SEO Health Score.

crawlers
    Fetches /robots.txt raw (url_safety.safe_requests_get: SSRF + DNS-rebinding
    protection; never WebFetch, whose summarization can drop lines) and
    evaluates, per RFC 9309, whether each AI agent may fetch ``/`` (and any
    ``--path``). Score = 100 x share of ANSWER-SURFACE agents allowed.
    Training-only crawlers are reported but never scored: blocking model
    training is a legitimate policy choice and does not remove a site from
    any answer surface. Cloudflare's managed robots.txt block is detected
    (marker logic ported from zubair-trabzada/geo-seo-claude, MIT,
    scripts/fetch_page.py fetch_robots_txt) and flagged, because those
    Disallow lines are injected at the edge and are often not written, or
    even seen, by the site owner.

    robots.txt HTTP status (RFC 9309 section 2.3.1): 2xx parse; 4xx = no
    robots.txt, everything allowed; 5xx / 429 / network failure = not
    measured (score N/A, never 0). Bodies are read up to 500 KiB, the parse
    limit Google documents; anything beyond is ignored and flagged.

Vendor facts (who each user-agent token serves) were checked against
upstream claude-seo's skills/seo-agentic/references/vendor-matrix.md and
access-policy.md (checked 2026-09-23) and the vendors' own pages:
developers.openai.com/api/docs/bots, Anthropic's crawler support article
(support.anthropic.com/en/articles/8896518), docs.perplexity.ai/guides/bots,
developers.google.com/crawling and Apple's Applebot article
(support.apple.com/en-us/119829). Re-check before quoting a row that is more
than 60 days old (see CHECKED_ON).

Usage:
    python aeo_score.py compute --citability 62 --brand-authority 40 \
        --content-eeat 71 --crawler-access 78 --schema 55 --platform 48 --json
    python aeo_score.py compute --input components.json --project example.com \
        --emit-kpis kpis-aeo.json
    python aeo_score.py crawlers https://example.com --json
    python aeo_score.py crawlers https://example.com --path /blog/ --path /pricing
    python aeo_score.py crawlers example.com --robots-file draft-robots.txt --json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_kpi import EnvelopeError, write_envelope  # noqa: E402
from seo_store import normalize_domain, utc_now  # noqa: E402

SOURCE = "aeo_score.py"
CHECKED_ON = "2026-10-17"

# ---------------------------------------------------------------------------
# Composite AEO Readiness Score
# ---------------------------------------------------------------------------

# Nominal weights (sum 100). Source: zubair-trabzada/geo-seo-claude (MIT),
# skills/geo-audit/SKILL.md "Composite GEO Score Calculation". The upstream
# "Technical GEO" category is narrowed here to crawler access, measured
# deterministically by ``crawlers`` below; llms.txt carries no weight anywhere
# in this plugin (skills/seo-geo/references/llmstxt-evidence.md).
WEIGHTS: dict[str, int] = {
    "citability": 25,       # scripts/citability_scorer.py (geo-citability)
    "brand_authority": 20,  # geo-brand-mentions Brand Authority Score
    "content_eeat": 20,     # seo-content E-E-A-T / Content Quality Score
    "crawler_access": 15,   # aeo_score.py crawlers
    "schema": 10,           # seo-schema score
    "platform": 10,         # geo-platform-optimizer Platform Readiness Score
}
COMPONENT_SOURCES: dict[str, str] = {
    "citability": "scripts/citability_scorer.py average_citability_score (geo-citability)",
    "brand_authority": "geo-brand-mentions Brand Authority Score (part judgment)",
    "content_eeat": "seo-content Content Quality / E-E-A-T score",
    "crawler_access": "aeo_score.py crawlers (answer-surface agents allowed)",
    "schema": "seo-schema score",
    "platform": "geo-platform-optimizer Platform Readiness Score",
}

# Rating bands, also from geo-seo-claude's composite score interpretation.
RATING_BANDS = (
    (90, "Excellent"),
    (75, "Good"),
    (60, "Fair"),
    (40, "Poor"),
    (0, "Critical"),
)

# Below this share of nominal weight the score rests on too little evidence
# to compare with a fuller score; the output says so.
LOW_COMPLETENESS = 0.6


def rating_for(score: Optional[float]) -> str:
    """Rating label for a 0-100 score ('Not measured' when None)."""
    if score is None:
        return "Not measured"
    for floor, label in RATING_BANDS:
        if score >= floor:
            return label
    return "Critical"


def _fmt_num(value: float) -> str:
    """Render a number so the expression string round-trips exactly."""
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return str(int(value))
    return repr(float(value))


def validate_component(name: str, value: Any) -> Optional[float]:
    """Return a 0-100 float, None for 'not measured', or raise ValueError.

    Accepts a number, None, or an object carrying the number under
    ``score``, ``value`` or ``average_citability_score`` (so a scorer's JSON
    output can be passed through unchanged).
    """
    if name not in WEIGHTS:
        raise ValueError(f"unknown AEO component: {name!r} (expected one of {', '.join(WEIGHTS)})")
    if isinstance(value, dict):
        for key in ("score", "value", "average_citability_score"):
            if key in value:
                value = value[key]
                break
        else:
            raise ValueError(f"{name}: object has no 'score' field")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}: expected a number 0-100 or null, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value < 0 or value > 100:
        raise ValueError(f"{name}: {value} is outside 0-100")
    return value


def compute_aeo_score(components: dict[str, Any]) -> dict:
    """Compute the AEO Readiness Score from component scores.

    ``components`` maps component name -> 0-100 number or None. Unknown names
    raise ValueError; out-of-range values raise ValueError. Pure function.
    """
    clean: dict[str, Optional[float]] = {name: None for name in WEIGHTS}
    for name, value in components.items():
        clean[name] = validate_component(name, value)

    used = [(n, v) for n, v in clean.items() if v is not None]
    weight_total = sum(WEIGHTS[n] for n, _ in used)
    completeness = round(weight_total / sum(WEIGHTS.values()), 2)

    if not used:
        return {
            "score": None,
            "rating": rating_for(None),
            "components": {n: {"value": None, "weight": WEIGHTS[n], "status": "not measured",
                               "source": COMPONENT_SOURCES[n]} for n in WEIGHTS},
            "weights_used": {},
            "completeness": 0.0,
            "expression": None,
            "component_set": [],
            "warnings": ["no component was measured; the AEO score cannot be computed"],
        }

    terms = " + ".join(f"{_fmt_num(v)}*{WEIGHTS[n]}" for n, v in used)
    denom = " + ".join(str(WEIGHTS[n]) for n, _ in used)
    expression = f"round(({terms}) / ({denom}))"

    # Same operations, same order as the expression string, so eval(expression)
    # and this value can never disagree.
    numerator = 0
    for n, v in used:
        numerator = numerator + v * WEIGHTS[n]
    score = round(numerator / weight_total)

    warnings: list[str] = []
    if completeness < LOW_COMPLETENESS:
        warnings.append(
            f"completeness {completeness:.2f} < {LOW_COMPLETENESS:.2f}: the score rests on less than "
            f"{int(LOW_COMPLETENESS * 100)}% of the nominal weight; report it as provisional and do "
            "not compare it with a score built from a different component set")

    return {
        "score": score,
        "rating": rating_for(score),
        "components": {
            n: {"value": clean[n], "weight": WEIGHTS[n],
                "status": "measured" if clean[n] is not None else "not measured (N/A, excluded)",
                "source": COMPONENT_SOURCES[n]}
            for n in WEIGHTS
        },
        "weights_used": {n: round(WEIGHTS[n] / weight_total, 4) for n, _ in used},
        "completeness": completeness,
        "expression": expression,
        "component_set": sorted(n for n, _ in used),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# AI agents and their robots.txt tokens
# ---------------------------------------------------------------------------

# Answer surfaces: agents whose access decides whether a page can be fetched
# for, or cited in, an AI answer. These, and only these, are scored.
ANSWER_SURFACE_AGENTS: tuple[dict, ...] = (
    {"agent": "OAI-SearchBot", "operator": "OpenAI", "tokens": ("oai-searchbot",),
     "purpose": "ChatGPT search results (the crawler that decides ChatGPT Search citability; not training)",
     "robots_txt": "honoured"},
    {"agent": "ChatGPT-User", "operator": "OpenAI", "tokens": ("chatgpt-user",),
     "purpose": "fetches a page when a ChatGPT user's request needs it",
     "robots_txt": "may not apply (OpenAI: user-initiated)"},
    {"agent": "Claude-SearchBot", "operator": "Anthropic", "tokens": ("claude-searchbot",),
     "purpose": "Claude search-result citability (not training)",
     "robots_txt": "honoured"},
    {"agent": "Claude-User", "operator": "Anthropic", "tokens": ("claude-user",),
     "purpose": "fetches a page when a Claude user's request needs it",
     "robots_txt": "honoured"},
    {"agent": "PerplexityBot", "operator": "Perplexity", "tokens": ("perplexitybot",),
     "purpose": "Perplexity search index (not used for foundation-model training)",
     "robots_txt": "honoured"},
    {"agent": "Perplexity-User", "operator": "Perplexity", "tokens": ("perplexity-user",),
     "purpose": "fetches a page for a Perplexity user's question",
     "robots_txt": "generally ignored (Perplexity: user-initiated)"},
    {"agent": "Googlebot", "operator": "Google", "tokens": ("googlebot",),
     "purpose": "Google Search index; AI Overviews and AI Mode are served from it",
     "robots_txt": "honoured"},
    {"agent": "Bingbot", "operator": "Microsoft", "tokens": ("bingbot",),
     "purpose": "Bing index; Microsoft Copilot answers draw on it",
     "robots_txt": "honoured"},
    # Apple: "If robots instructions don't mention Applebot but do mention
    # Googlebot, the Apple robot will follow Googlebot instructions."
    {"agent": "Applebot", "operator": "Apple", "tokens": ("applebot", "googlebot"),
     "purpose": "Siri, Spotlight and Safari search suggestions",
     "robots_txt": "honoured (falls back to Googlebot rules when Applebot is not named)"},
)

# Training crawlers and AI-use control tokens: reported, never scored.
TRAINING_AGENTS: tuple[dict, ...] = (
    {"agent": "GPTBot", "operator": "OpenAI", "tokens": ("gptbot",),
     "purpose": "OpenAI model training only; does not affect ChatGPT Search"},
    {"agent": "ClaudeBot", "operator": "Anthropic", "tokens": ("claudebot",),
     "purpose": "Anthropic model training only; does not affect Claude search citability"},
    # Google-Extended is one switch for training AND grounding in Gemini Apps /
    # Vertex AI; there is no grounding-only opt-in, so blocking it is usually a
    # training-licensing decision. Reported (with the Gemini consequence), not scored.
    {"agent": "Google-Extended", "operator": "Google", "tokens": ("google-extended",),
     "purpose": "control token for Gemini/Vertex AI training and for grounding in Gemini Apps "
                "(one switch for both); not Google Search inclusion or ranking, not AI Overviews/AI Mode"},
    {"agent": "Applebot-Extended", "operator": "Apple", "tokens": ("applebot-extended",),
     "purpose": "opt-out token for Apple generative-model training; Siri/Spotlight/Safari "
                "discoverability is governed by Applebot"},
    {"agent": "CCBot", "operator": "Common Crawl", "tokens": ("ccbot",),
     "purpose": "Common Crawl dataset, widely used as training data"},
    {"agent": "Meta-ExternalAgent", "operator": "Meta", "tokens": ("meta-externalagent",),
     "purpose": "Meta AI model training"},
    {"agent": "Bytespider", "operator": "ByteDance", "tokens": ("bytespider",),
     "purpose": "ByteDance model training"},
)

# Tokens that appear in old robots.txt files but are not documented by the
# vendor today. Reported as information only.
UNDOCUMENTED_TOKENS = {
    "anthropic-ai": "not listed in Anthropic's current crawler documentation (ClaudeBot, "
                    "Claude-SearchBot, Claude-User are)",
    "claude-web": "not listed in Anthropic's current crawler documentation",
}

MAX_ROBOTS_BYTES = 500 * 1024  # Google parses the first 500 KiB and ignores the rest
CLOUDFLARE_BEGIN = "# begin cloudflare managed content"
CLOUDFLARE_END = "# end cloudflare managed content"
_TOKEN_RE = re.compile(r"[a-z_-]+")


# ---------------------------------------------------------------------------
# robots.txt parsing and evaluation (RFC 9309), pure functions
# ---------------------------------------------------------------------------

def _ua_token(value: str) -> str:
    """Product token of a user-agent line value: 'Googlebot/2.1 (+..)' -> 'googlebot'."""
    value = value.strip().lower()
    if value.startswith("*"):
        return "*"
    m = _TOKEN_RE.match(value)
    return m.group(0) if m else ""


def parse_robots(text: str) -> dict:
    """Parse robots.txt into groups (RFC 9309) plus non-group records.

    A group is one or more consecutive user-agent lines followed by rules.
    A user-agent line that follows a rule starts a new group; other records
    (sitemap, crawl-delay, content-signal) do not end a group's agent list.
    Rules before any user-agent line are ignored, as crawlers ignore them.
    """
    text = (text or "").lstrip("\ufeff")  # a BOM would hide the first User-agent line
    groups: list[dict] = []
    sitemaps: list[str] = []
    content_signals: list[dict] = []
    current: Optional[dict] = None
    accepting_agents = False
    cf_begin = cf_end = None

    for lineno, raw in enumerate(text.splitlines(), 1):
        lowered = raw.strip().lower()
        if lowered.startswith(CLOUDFLARE_BEGIN) and cf_begin is None:
            cf_begin = lineno
        elif lowered.startswith(CLOUDFLARE_END) and cf_begin is not None and cf_end is None:
            cf_end = lineno
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.lower().replace(" ", "-")
        if field in ("user-agent", "useragent"):
            if current is None or not accepting_agents:
                current = {"agents": [], "rules": [], "line": lineno}
                groups.append(current)
                accepting_agents = True
            token = _ua_token(value)
            if token:
                current["agents"].append({"token": token, "raw": value, "line": lineno})
        elif field in ("allow", "disallow"):
            accepting_agents = False
            if current is not None and value:  # an empty path matches nothing
                current["rules"].append({"kind": field, "pattern": value, "line": lineno})
        elif field == "sitemap":
            sitemaps.append(value)
        elif field == "content-signal":
            content_signals.append({
                "raw": value, "line": lineno,
                "group_agents": [a["raw"] for a in current["agents"]] if current else [],
                "parsed": _parse_content_signal(value),
            })

    managed = None
    if cf_begin is not None:
        managed = {"begin_line": cf_begin, "end_line": cf_end}
    return {"groups": groups, "sitemaps": sitemaps, "content_signals": content_signals,
            "cloudflare_managed": managed}


def _parse_content_signal(value: str) -> dict:
    out: dict[str, str] = {}
    for part in value.split(","):
        if "=" in part:
            key, val = (p.strip().lower() for p in part.split("=", 1))
            if key:
                out[key] = val
    return out


def _pattern_regex(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(regex + ("$" if anchored else ""), re.DOTALL)


def _select_groups(parsed: dict, tokens: Iterable[str]) -> tuple[list[dict], Optional[str]]:
    """Groups that apply to a crawler: its own token(s) first, then '*'.

    Matching groups for the same token are combined (RFC 9309 2.2.1).
    Returns (groups, matched_token) where matched_token is None when no
    group applies (everything allowed).
    """
    for token in tokens:
        hits = [g for g in parsed["groups"] if any(a["token"] == token for a in g["agents"])]
        if hits:
            return hits, token
    star = [g for g in parsed["groups"] if any(a["token"] == "*" for a in g["agents"])]
    if star:
        return star, "*"
    return [], None


def evaluate_path(groups: list[dict], path: str) -> dict:
    """Allow/deny for one path: longest matching pattern wins; Allow wins ties."""
    best: Optional[dict] = None
    for group in groups:
        for rule in group["rules"]:
            if _pattern_regex(rule["pattern"]).match(path):
                length = len(rule["pattern"])
                if (best is None or length > len(best["pattern"])
                        or (length == len(best["pattern"]) and rule["kind"] == "allow")):
                    best = rule
    if best is None:
        return {"allowed": True, "rule": None, "line": None}
    return {"allowed": best["kind"] == "allow",
            "rule": f"{best['kind'].capitalize()}: {best['pattern']}", "line": best["line"]}


def _in_managed_block(line: Optional[int], managed: Optional[dict]) -> bool:
    if line is None or not managed:
        return False
    end = managed.get("end_line") or float("inf")
    return managed["begin_line"] <= line <= end


def evaluate_agent(parsed: dict, spec: dict, paths: list[str]) -> dict:
    groups, matched = _select_groups(parsed, spec["tokens"])
    per_path = {p: evaluate_path(groups, p) for p in paths}
    allowed_all = all(r["allowed"] for r in per_path.values())
    root = per_path[paths[0]]
    if allowed_all:
        status = "allowed"
    elif root["allowed"]:
        status = "partial"
    else:
        status = "blocked"
    deciding = [r["line"] for r in per_path.values() if not r["allowed"]]
    evidence = (f"line {root['line']}: {root['rule']}" if root["rule"]
                else ("no rule for this user-agent (allowed by default)" if matched is None
                      else f"group '{matched}' has no rule matching {paths[0]}"))
    if status == "partial":
        blocked = [f"{p} (line {r['line']}: {r['rule']})" for p, r in per_path.items() if not r["allowed"]]
        evidence += "; blocked: " + ", ".join(blocked)
    return {
        "agent": spec["agent"],
        "operator": spec["operator"],
        "purpose": spec["purpose"],
        "robots_txt": spec.get("robots_txt", "honoured"),
        "status": status,
        "matched_group": matched,  # token whose group applied, '*', or None (no group)
        "evidence": evidence,
        "paths": per_path,
        "cloudflare_injected": any(_in_managed_block(line, parsed["cloudflare_managed"])
                                   for line in deciding),
    }


def analyze_robots(text: Optional[str], http_status: Optional[int], paths: Optional[list[str]] = None,
                   robots_url: str = "", fetch_note: str = "", truncated: bool = False,
                   content_type: str = "") -> dict:
    """Score answer-surface crawler access from a robots.txt body + status.

    ``text`` is the body (None when nothing usable was retrieved).
    ``http_status`` None means a network/safety failure.
    """
    paths = [p if p.startswith("/") else "/" + p for p in (paths or ["/"])] or ["/"]
    if "/" not in paths:
        paths = ["/"] + paths
    else:
        paths = ["/"] + [p for p in paths if p != "/"]

    notes: list[str] = []
    if http_status is not None and 200 <= http_status < 300 and text is not None:
        robots_status = "ok"
    elif http_status is not None and 400 <= http_status < 500 and http_status != 429:
        robots_status = "missing"
        text = ""
        notes.append(f"robots.txt returned HTTP {http_status}: per RFC 9309 crawlers may access "
                     "everything, so every agent is allowed")
    else:
        robots_status = "unavailable"

    base = {
        "robots_url": robots_url,
        "http_status": http_status,
        "robots_status": robots_status,
        "checked_at": utc_now(),
        "paths": paths,
        "truncated": truncated,
        "vendor_facts_checked_on": CHECKED_ON,
        "data_sources": [f"robots.txt fetched raw from {robots_url}" if robots_url else "robots.txt (local file)"],
        "limitations": [
            "robots.txt is a stated preference, not access control: WAF/CDN bot rules, "
            "authentication and user-triggered fetchers that ignore robots.txt are not visible here",
            "page-level noindex / X-Robots-Tag and JavaScript rendering are separate checks "
            "(geo-crawlers Steps 2, 3 and 5)",
            "vendor token facts change; re-check rows older than 60 days (vendor_facts_checked_on)",
        ],
    }

    if robots_status == "unavailable":
        reason = fetch_note or (f"HTTP {http_status}" if http_status else "no response")
        base.update({
            "score": None, "rating": rating_for(None), "expression": None,
            "allowed": None, "total": len(ANSWER_SURFACE_AGENTS),
            "answer_surface": [], "training": [], "undocumented_tokens": [],
            "cloudflare_managed": False, "cloudflare_injected_agents": [],
            "content_signals": [], "sitemaps": [],
            "notes": [f"robots.txt could not be retrieved ({reason}); crawler access is NOT MEASURED "
                      "(N/A, never 0). Compliant crawlers treat a 5xx/unreachable robots.txt as a "
                      "full disallow, so fixing it matters in its own right."],
        })
        return base

    parsed = parse_robots(text or "")
    answer = [evaluate_agent(parsed, spec, paths) for spec in ANSWER_SURFACE_AGENTS]
    training = [evaluate_agent(parsed, spec, paths) for spec in TRAINING_AGENTS]
    allowed = sum(1 for a in answer if a["status"] == "allowed")
    total = len(answer)
    expression = f"round(100 * {allowed} / {total})"
    score = round(100 * allowed / total)

    present_tokens = {a["token"] for g in parsed["groups"] for a in g["agents"]}
    undocumented = [{"token": t, "note": note} for t, note in UNDOCUMENTED_TOKENS.items()
                    if t in present_tokens]
    managed = parsed["cloudflare_managed"] is not None
    injected = [a["agent"] for a in answer + training if a["cloudflare_injected"]]
    if managed:
        notes.append(
            "Cloudflare managed robots.txt detected ('# BEGIN Cloudflare Managed content'). Its "
            "Disallow lines are prepended at the edge and may not have been written by the site "
            "owner; they never appear in the robots.txt file on the origin server. If blocking "
            "training is not intended, turn the setting off in the Cloudflare dashboard "
            "(bot traffic / managed robots.txt); if it is intended, record it as a deliberate choice.")
    if content_type and "html" in content_type.lower():
        notes.append(f"robots.txt was served as {content_type!r}; an HTML body usually means a "
                     "soft-404 or error page rather than a real robots.txt")
    if truncated:
        notes.append(f"robots.txt is larger than {MAX_ROBOTS_BYTES} bytes; only the first "
                     f"{MAX_ROBOTS_BYTES} bytes were evaluated, as Google ignores the remainder")
    if any(a["agent"] == "Google-Extended" and a["status"] != "allowed" for a in training):
        notes.append("Google-Extended is disallowed: Google may not use the content for Gemini/Vertex "
                     "training or for grounding answers in Gemini Apps. Google Search, AI Overviews and "
                     "AI Mode are unaffected (they follow Googlebot). Reported, not scored.")
    for agent in answer:
        if agent["status"] != "allowed" and agent["robots_txt"].startswith(("may not", "generally")):
            notes.append(f"{agent['agent']} is disallowed on at least one evaluated path, but the vendor "
                         "says it may not obey robots.txt for user-initiated fetches; the rule records "
                         "intent only")

    base.update({
        "score": score,
        "rating": rating_for(score),
        "expression": expression,
        "allowed": allowed,
        "total": total,
        "answer_surface": answer,
        "training": training,
        "training_note": "training crawlers and AI-use control tokens are reported for policy review "
                         "and never scored; blocking them is a licensing choice (Google-Extended also "
                         "covers Gemini Apps grounding, see notes)",
        "undocumented_tokens": undocumented,
        "cloudflare_managed": managed,
        "cloudflare_managed_block": parsed["cloudflare_managed"],
        "cloudflare_injected_agents": injected,
        "content_signals": parsed["content_signals"],
        "sitemaps": parsed["sitemaps"],
        "groups": len(parsed["groups"]),
        "notes": notes,
    })
    return base


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def robots_url_for(url: str) -> str:
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def fetch_robots(url: str, timeout: int = 15) -> dict:
    """Fetch robots.txt through url_safety; never raises for network errors.

    Returns {robots_url, http_status, text, truncated, content_type, note}.
    """
    import requests  # local: keep `compute` usable without requests installed
    from url_safety import URLSafetyError, decode_body, safe_requests_get

    robots_url = robots_url_for(url)
    out = {"robots_url": robots_url, "http_status": None, "text": None,
           "truncated": False, "content_type": "", "note": ""}
    try:
        resp = safe_requests_get(robots_url, timeout=timeout, stream=True,
                                 headers={"Accept": "text/plain,*/*;q=0.5"})
    except URLSafetyError as exc:
        out["note"] = f"refused by url_safety: {exc}"
        return out
    except requests.RequestException as exc:
        out["note"] = f"request failed: {exc.__class__.__name__}"
        return out
    try:
        out["http_status"] = resp.status_code
        out["content_type"] = resp.headers.get("Content-Type", "") if resp.headers else ""
        if 200 <= resp.status_code < 300:
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) > MAX_ROBOTS_BYTES:
                    out["truncated"] = True
                    break
            out["text"] = decode_body(bytes(buf[:MAX_ROBOTS_BYTES]), out["content_type"])
    except requests.RequestException as exc:
        out["http_status"] = None
        out["note"] = f"body read failed: {exc.__class__.__name__}"
    finally:
        resp.close()
    return out


def check_crawlers(url: str, paths: Optional[list[str]] = None, robots_file: Optional[str] = None,
                   timeout: int = 15) -> dict:
    """Fetch (or read) robots.txt and return the analysis."""
    if robots_file:
        text = Path(robots_file).read_text(encoding="utf-8-sig", errors="replace")
        truncated = len(text.encode("utf-8")) > MAX_ROBOTS_BYTES
        if truncated:
            text = text.encode("utf-8")[:MAX_ROBOTS_BYTES].decode("utf-8", errors="ignore")
        result = analyze_robots(text, 200, paths, robots_url="", truncated=truncated)
        result["data_sources"] = [f"local robots.txt file {robots_file} (not the live file)"]
        result["site"] = normalize_domain(url)
        return result
    fetched = fetch_robots(url, timeout=timeout)
    result = analyze_robots(fetched["text"], fetched["http_status"], paths,
                            robots_url=fetched["robots_url"], fetch_note=fetched["note"],
                            truncated=fetched["truncated"], content_type=fetched["content_type"])
    result["site"] = normalize_domain(url)
    return result


def write_kpi_envelope(path: str, project: str, metrics: dict, meta: dict,
                       day: Optional[str] = None) -> dict:
    """Validate and write a KPI envelope (contract: scripts/seo_kpi.py).

    Raises seo_kpi.EnvelopeError when a value breaks the contract (e.g. a
    score outside 0-100), so a bad number never reaches the KPI history.
    """
    return write_envelope(path, project, SOURCE, metrics, day=day, meta=meta)


def _valid_day(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def _load_components_file(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("components"), dict):
        data = data["components"]
    if not isinstance(data, dict):
        raise ValueError("--input must be a JSON object of component -> score")
    return data


def _print_compute(result: dict) -> None:
    if result["score"] is None:
        print("AEO Readiness Score: not measured (no component data)")
        return
    print(f"AEO Readiness Score: {result['score']}/100 ({result['rating']})  "
          f"completeness {result['completeness']:.2f}")
    for name, comp in result["components"].items():
        value = "N/A" if comp["value"] is None else f"{comp['value']:g}"
        used = result["weights_used"].get(name)
        share = f"-> {used:.4f}" if used is not None else "(excluded)"
        print(f"  {name:<16} {value:>6}  weight {comp['weight']:>2} {share}")
    print(f"Expression: {result['expression']}")
    for w in result["warnings"]:
        print(f"Warning: {w}")


def _print_crawlers(result: dict) -> None:
    print(f"robots.txt: {result['robots_url'] or '(local file)'}  status={result['robots_status']}"
          f"  http={result['http_status']}")
    if result["score"] is None:
        print("Crawler access: not measured")
    else:
        print(f"Crawler access (answer surfaces): {result['score']}/100  "
              f"{result['allowed']}/{result['total']} allowed  [{result['expression']}]")
        for a in result["answer_surface"]:
            print(f"  {a['agent']:<18} {a['status']:<8} {a['evidence']}")
        print("Training crawlers (reported, not scored):")
        for a in result["training"]:
            print(f"  {a['agent']:<18} {a['status']:<8} {a['evidence']}")
    for note in result["notes"]:
        print(f"Note: {note}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AEO Readiness Score and AI crawler access sub-score")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("compute", help="Compute the AEO Readiness Score from component scores")
    for name in WEIGHTS:
        pc.add_argument(f"--{name.replace('_', '-')}", dest=name, type=float, default=None,
                        help=f"0-100 ({COMPONENT_SOURCES[name]}); omit if not measured")
    pc.add_argument("--input", help="JSON object of component -> score (CLI flags override)")
    pc.add_argument("--project", help="Client domain (required with --emit-kpis)")
    pc.add_argument("--date", type=_valid_day, help="Measurement date for the KPI envelope (default today)")
    pc.add_argument("--emit-kpis", help="Write a KPI envelope (aeo.*) to this path")
    pc.add_argument("--json", action="store_true")

    pr = sub.add_parser("crawlers", help="Deterministic AI-crawler access sub-score from robots.txt")
    pr.add_argument("url")
    pr.add_argument("--path", action="append", default=[], help="Extra path to evaluate (repeatable)")
    pr.add_argument("--robots-file", help="Evaluate a local robots.txt instead of fetching")
    pr.add_argument("--timeout", type=int, default=15)
    pr.add_argument("--project", help="Client domain for --emit-kpis (default: the URL's host)")
    pr.add_argument("--date", type=_valid_day)
    pr.add_argument("--emit-kpis", help="Write a KPI envelope (aeo.crawler_access) to this path")
    pr.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "compute":
        try:
            components = _load_components_file(args.input) if args.input else {}
            for name in WEIGHTS:
                if getattr(args, name) is not None:
                    components[name] = getattr(args, name)
            result = compute_aeo_score(components)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        result["data_sources"] = [COMPONENT_SOURCES[n] for n in result["component_set"]]
        result["limitations"] = [
            "readiness, not outcome: AI share of voice (ai_visibility.py) is tracked separately "
            "and is never part of this score",
            "never blended with the SEO Health Score",
            "brand_authority is part researcher judgment (geo-brand-mentions)",
            "compare two AEO scores only when component_set is identical",
        ]
        if args.emit_kpis:
            if not args.project:
                print("Error: --emit-kpis requires --project", file=sys.stderr)
                return 2
            metrics = {"aeo.score": result["score"]}
            metrics.update({f"aeo.{n}": c["value"] for n, c in result["components"].items()})
            try:
                write_kpi_envelope(args.emit_kpis, args.project, metrics, day=args.date, meta={
                    "completeness": result["completeness"], "rating": result["rating"],
                    "expression": result["expression"], "component_set": result["component_set"]})
            except EnvelopeError as exc:
                print(f"Error: KPI envelope rejected, nothing written: {exc}", file=sys.stderr)
                return 2
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            _print_compute(result)
        return 0 if result["score"] is not None else 1

    try:
        result = check_crawlers(args.url, args.path, args.robots_file, args.timeout)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.emit_kpis:
        try:
            write_kpi_envelope(args.emit_kpis, args.project or result["site"],
                               {"aeo.crawler_access": result["score"]}, day=args.date, meta={
                                   "robots_status": result["robots_status"],
                                   "allowed": result["allowed"], "total": result["total"],
                                   "expression": result["expression"],
                                   "cloudflare_managed": result["cloudflare_managed"]})
        except EnvelopeError as exc:
            print(f"Error: KPI envelope rejected, nothing written: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_crawlers(result)
    return 0 if result["score"] is not None else 1


if __name__ == "__main__":
    sys.exit(main())
