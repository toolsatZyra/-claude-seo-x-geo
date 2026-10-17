#!/usr/bin/env python3
"""
Content optimizer: compare one page with the pages that rank for its keyword.

Measures how much of what competing pages consistently discuss this page also
covers: shared terms (1-3 word phrases), section topics, questions, length and
keyword placement. The result is a deterministic 0-100 content score with its
components and the arithmetic shown.

Interpretation is CORRELATIONAL. A high score means the page covers what
ranking pages discuss; it is not a ranking guarantee, and the script never
tells you to "add keyword X N times". The Princeton GEO study (Aggarwal et
al., KDD 2024) found keyword stuffing performed below the no-optimization
baseline in generative engines, so densities above 3% are flagged as a risk,
not a target.

Competitor URLs must come from the operator or from a SERP data provider the
operator pays for (e.g. DataForSEO). This script never scrapes Google.
Every URL is fetched through scripts/fetch_page.fetch_page (SSRF-safe,
DNS-pinned). Files can be passed instead of URLs for offline use; Markdown
drafts with front matter (content_export.py format) are supported.

Method and weights (fixed; documented in skills/seo-content/SKILL.md "Optimize mode"):
    term coverage   35  expected terms = 1-3-grams in >= 50% of competitor pages
                        (and >= 2 pages), top 60 by document frequency then
                        mean frequency per 1,000 words; coverage = share present
    headings        20  share of section topics most competitors head that this
                        page also has a heading for (lexical match)
    questions       15  share of competitor heading questions this page
                        addresses in a heading or paragraph (lexical match)
    length fit      15  1.0 inside [Q1, Q3 + 1.5*IQR] of competitor word counts,
                        own/Q1 below it, max(0.6, upper/own) above it
    placement       15  keyword tokens in title, H1, first 100 words, meta
                        description, slug, at least one H2 (zeroed when keyword
                        density > 3%, because repetition is what it would reward)
    Components with no data are excluded and the rest renormalized
    (scoring-rubric Rule 5).

Usage:
    python content_optimizer.py analyze --keyword "crm for startups" \
        --url https://example.com/blog/crm-for-startups \
        --competitor https://a.example/crm --competitor https://b.example/crm \
        --competitor https://c.example/crm --json
    python content_optimizer.py analyze --keyword "crm for startups" \
        --page-file draft.md --competitor-file c1.html --competitor-file c2.html \
        --competitor-file c3.html
"""

from __future__ import annotations

import argparse
import html as htmllib
import json
import logging
import math
import os
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_metrics import STOPWORDS, ngrams, tokenize  # noqa: E402
from seo_store import host_matches, utc_now  # noqa: E402

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - hard dependency
    print("Error: beautifulsoup4 is required (pip install -r requirements.txt)", file=sys.stderr)
    sys.exit(1)

try:
    import trafilatura  # type: ignore
    _HAVE_TRAFILATURA = True
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
except ImportError:  # pragma: no cover - optional dependency
    trafilatura = None
    _HAVE_TRAFILATURA = False

WEIGHTS = {"terms": 35, "headings": 20, "questions": 15, "length": 15, "placement": 15}
EXPECTED_DF_SHARE = 0.5
MAX_EXPECTED_TERMS = 60
MIN_COMPETITOR_WORDS = 100
STUFFING_DENSITY_PCT = 3.0
TOPIC_CLUSTER_JACCARD = 0.5
TOPIC_COVER_SHARE = 0.6
QUESTION_DEDUPE_JACCARD = 0.6
QUESTION_PARAGRAPH_SHARE = 0.75
INTERPRETATION = "correlational — coverage of what ranking pages discuss, not a ranking guarantee"
QUESTION_WORDS = ("what", "how", "why", "when", "who", "which", "where", "is", "are", "can",
                  "does", "do", "should", "will", "could", "would")
GENERIC_HEADINGS = frozenset({
    "conclusion", "conclusions", "summary", "introduction", "intro", "overview", "faq", "faqs",
    "frequently asked questions", "related posts", "related articles", "related", "comments",
    "leave a reply", "leave a comment", "share this", "share", "table of contents", "contents",
    "about the author", "subscribe", "newsletter", "references", "sources", "final thoughts",
    "key takeaways", "takeaways", "tl dr", "tldr", "next steps", "get started", "read more",
})
_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "form", "button",
              "nav", "aside", "footer", "select", "dialog")
_LEAF_BLOCKS = ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "blockquote", "pre",
                "dd", "dt", "figcaption")
# Function words that make poor term edges, on top of the shared STOPWORDS.
_TERM_EDGE_STOPWORDS = STOPWORDS | frozenset({
    "much", "many", "like", "really", "even", "still", "often", "usually", "every", "lot", "lots",
    "etc", "eg", "ie", "however", "though", "although", "already", "always", "never", "ever",
    "rather", "quite", "thing", "things", "way", "ways", "something", "anything", "everything",
})
_TRIGRAM_BAD_MIDDLE = frozenset({"and", "or", "but", "nor"})
_SEGMENT_SPLIT = re.compile(r"[.!?;:,\n\r|•·()\[\]{}\"“”]+")
_WORD_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")


class OptimizerError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1, detail: Optional[dict] = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def stem(token: str) -> str:
    """Light, deterministic suffix stripping used only for matching."""
    t = token
    if len(t) <= 3:
        return t
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("sses"):
        return t[:-2]
    if t.endswith("ss"):
        return t
    if t.endswith("ing") and len(t) > 5:
        return t[:-3]
    if t.endswith("ed") and len(t) > 4:
        return t[:-2]
    if t.endswith("es") and len(t) > 4:
        return t[:-2]
    if t.endswith("s") and not t.endswith(("us", "is")):
        return t[:-1]
    return t


def _clean_token(tok: str) -> str:
    tok = tok.replace("’", "'")
    if tok.endswith("'s"):
        tok = tok[:-2]
    return tok.strip("'-")


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def content_stems(text: str) -> set[str]:
    """Stemmed, stopword-free tokens of a short text (heading, keyword)."""
    return {stem(_clean_token(t)) for t in tokenize(text, drop_stopwords=True, min_len=2)
            if _clean_token(t) and not _clean_token(t).isdigit()}


def _is_num(tok: str) -> bool:
    return bool(re.fullmatch(r"[\d.,'+#-]+", tok))


def term_counts(text: str) -> tuple[Counter, dict]:
    """Count valid 1-3-gram terms. Returns (Counter keyed by stem tuple, surface forms)."""
    counts: Counter = Counter()
    surfaces: dict = {}
    for segment in _SEGMENT_SPLIT.split((text or "").lower()):
        toks = [_clean_token(t) for t in tokenize(segment, drop_stopwords=False, min_len=1)]
        toks = [t for t in toks if t]
        for n in (1, 2, 3):
            for i, gram in enumerate(ngrams(toks, n)):
                parts = toks[i:i + n]
                first, last = parts[0], parts[-1]
                if (first in _TERM_EDGE_STOPWORDS or last in _TERM_EDGE_STOPWORDS
                        or _is_num(first) or _is_num(last)):
                    continue
                if n == 3 and parts[1] in _TRIGRAM_BAD_MIDDLE:
                    continue
                if n == 1 and len(first) < 2:
                    continue
                key = tuple(stem(p) for p in parts)
                counts[key] += 1
                surfaces.setdefault(key, Counter())[gram] += 1
    return counts, surfaces


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _norm_ws(text: str) -> str:
    return " ".join((text or "").split())


def _leaf_block_texts(container) -> list[str]:
    out = []
    for el in container.find_all(_LEAF_BLOCKS):
        if el.find(_LEAF_BLOCKS):
            continue
        txt = _norm_ws(el.get_text(" ", strip=True))
        if txt:
            out.append(txt)
    return out


def slug_from_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def extract_document(html: str, url: Optional[str] = None, use_trafilatura: bool = True) -> dict:
    """Extract title, meta description, H1-H4, main text and paragraphs from HTML."""
    raw = BeautifulSoup(html or "", "lxml")
    title = _norm_ws(raw.title.get_text(" ", strip=True)) if raw.title else ""
    meta = ""
    for tag in raw.find_all("meta"):
        if (tag.get("name") or "").lower() == "description":
            meta = _norm_ws(tag.get("content") or "")
            break
    all_h1 = [_norm_ws(h.get_text(" ", strip=True)) for h in raw.find_all("h1")]

    soup = BeautifulSoup(html or "", "lxml")
    for el in soup.find_all(_DROP_TAGS):
        el.decompose()
    for el in soup.find_all(attrs={"role": ["navigation", "banner", "contentinfo", "complementary"]}):
        el.decompose()
    for el in soup.find_all("header"):
        if not el.find_parent(["article", "main"]):
            el.decompose()
    candidates = soup.find_all(["main", "article"])
    container = (max(candidates, key=lambda c: len(c.get_text(" ", strip=True))) if candidates
                 else (soup.body or soup))

    def heads(level: str) -> list[str]:
        return [t for t in (_norm_ws(h.get_text(" ", strip=True)) for h in container.find_all(level)) if t]

    h1 = heads("h1") or [h for h in all_h1 if h][:1]
    paragraphs = _leaf_block_texts(container)
    fallback_text = "\n".join(paragraphs)
    if word_count(fallback_text) < 100:
        alt = container.get_text("\n", strip=True)
        if word_count(alt) > word_count(fallback_text):
            fallback_text = alt
            paragraphs = [_norm_ws(p) for p in alt.split("\n") if p.strip()]
    text, extractor = fallback_text, "beautifulsoup"
    if use_trafilatura and _HAVE_TRAFILATURA:
        try:
            extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
        except Exception:  # extraction must never crash the analysis
            extracted = None
        if extracted and word_count(extracted) >= 50:
            text, extractor = extracted, "trafilatura"
            paragraphs = [_norm_ws(p) for p in extracted.split("\n") if p.strip()]
    return {
        "url": url, "title": title, "meta_description": meta, "h1": h1, "h2": heads("h2"),
        "h3": heads("h3"), "h4": heads("h4"), "text": text, "paragraphs": paragraphs,
        "word_count": word_count(text), "slug": slug_from_url(url), "extractor": extractor,
    }


def document_from_markdown(path: Path) -> dict:
    """Build an extracted document from a Markdown draft with front matter."""
    from content_export import load_document, markdown_to_html
    doc = load_document(path)
    fragment, _ = markdown_to_html(doc.body, engine="builtin")
    meta = doc.meta
    title = htmllib.escape(meta.get("title") or "", quote=False)
    description = htmllib.escape(meta.get("meta_description") or "", quote=True)
    head_h1 = "" if re.search(r"<h1\b", fragment) else f"<h1>{title}</h1>"
    html = (f"<html><head><title>{title}</title><meta name=\"description\" content=\"{description}\">"
            f"</head><body><article>{head_h1}{fragment}</article></body></html>")
    out = extract_document(html, url=meta.get("canonical") or None, use_trafilatura=False)
    out["slug"] = meta.get("slug") or out["slug"]
    out["extractor"] = "markdown-draft"
    return out


def _looks_like_markdown(path: Path, text: str) -> bool:
    if path.suffix.lower() in (".md", ".markdown", ".mdx", ".txt"):
        return True
    return text.lstrip().startswith("---")


def load_file_document(path_str: str, url: Optional[str] = None) -> dict:
    path = Path(path_str)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise OptimizerError(f"cannot read {path}: {exc}") from exc
    if _looks_like_markdown(path, text):
        doc = document_from_markdown(path)
        if url:
            doc["url"], doc["slug"] = url, slug_from_url(url) or doc["slug"]
    else:
        doc = extract_document(text, url=url)
    doc["source"] = str(path)
    return doc


def fetch_document(url: str, fetcher: Optional[Callable] = None) -> dict:
    """Fetch and extract a URL through fetch_page (SSRF-safe). Raises OptimizerError."""
    if fetcher is None:
        from fetch_page import fetch_page as fetcher  # noqa: N813
    res = fetcher(url)
    if res.get("error"):
        raise OptimizerError(f"{url}: {res['error']}")
    if res.get("status_code") != 200 or not res.get("content"):
        raise OptimizerError(f"{url}: HTTP {res.get('status_code')} or empty body")
    doc = extract_document(res["content"], url=res.get("url") or url)
    doc["source"] = url
    return doc


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _doc_terms(doc: dict) -> tuple[Counter, dict]:
    parts = [doc.get("title", ""), *doc.get("h1", []), *doc.get("h2", []), *doc.get("h3", []),
             doc.get("text", "")]
    return term_counts("\n".join(parts))


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _share_in(topic: set, other: set) -> float:
    return len(topic & other) / len(topic) if topic else 0.0


def _is_generic(heading: str) -> bool:
    return " ".join(re.findall(r"[a-z0-9]+", heading.lower())) in GENERIC_HEADINGS


def _is_question(heading: str) -> bool:
    h = heading.strip().lower()
    first = re.findall(r"[a-z]+", h)[:1]
    return h.endswith("?") or (bool(first) and first[0] in QUESTION_WORDS)


def length_fit(own: int, counts: list[int]) -> dict:
    counts = sorted(counts)
    median = statistics.median(counts)
    if len(counts) >= 2:
        q1, _, q3 = statistics.quantiles(counts, n=4, method="inclusive")
    else:
        q1 = q3 = float(counts[0])
    iqr = q3 - q1
    upper = q3 + 1.5 * iqr
    below = sum(1 for c in counts if c < own)
    equal = sum(1 for c in counts if c == own)
    percentile = round(100 * (below + 0.5 * equal) / len(counts), 1)
    if own < q1:
        fit, band = (own / q1 if q1 > 0 else 0.0), "below_q1"
    elif own <= upper:
        fit, band = 1.0, "within_range"
    else:
        fit, band = max(0.6, upper / own), "above_upper_fence"
    return {"own": own, "competitor_median": round(median, 1), "q1": round(q1, 1), "q3": round(q3, 1),
            "iqr": round(iqr, 1), "upper_fence": round(upper, 1), "percentile": percentile,
            "band": band, "fit": round(fit, 3)}


def keyword_placement(keyword: str, doc: dict) -> dict:
    kw_stems = content_stems(keyword) or {stem(t) for t in tokenize(keyword, drop_stopwords=False)}
    phrase = " ".join(tokenize(keyword, drop_stopwords=False, min_len=1))
    first_100 = " ".join(_WORD_RE.findall(doc.get("text", ""))[:100])
    slug = doc.get("slug")
    locations = {
        "title": doc.get("title") or "",
        "h1": " | ".join(doc.get("h1") or []),
        "first_100_words": first_100,
        "meta_description": doc.get("meta_description") or "",
        "slug": slug.replace("-", " ").replace("_", " ") if slug else None,
    }
    checks = {}
    for name, text in locations.items():
        if text is None:
            checks[name] = {"applicable": False, "pass": None, "exact_phrase": None,
                            "note": "no URL or slug available"}
            continue
        stems_here = {stem(_clean_token(t)) for t in tokenize(text, drop_stopwords=False, min_len=1)}
        norm = " ".join(tokenize(text, drop_stopwords=False, min_len=1))
        checks[name] = {"applicable": True, "pass": bool(kw_stems) and kw_stems <= stems_here,
                        "exact_phrase": bool(phrase) and f" {phrase} " in f" {norm} "}
    h2_hits = [h for h in doc.get("h2") or []
               if kw_stems <= {stem(_clean_token(t)) for t in tokenize(h, drop_stopwords=False, min_len=1)}]
    checks["h2"] = {"applicable": True, "pass": bool(h2_hits), "exact_phrase": None,
                    "matching_h2": h2_hits[:3]}
    applicable = [c for c in checks.values() if c["applicable"]]
    passed = sum(1 for c in applicable if c["pass"])
    return {"keyword_stems": sorted(kw_stems), "checks": checks, "passed": passed,
            "applicable": len(applicable),
            "share": round(passed / len(applicable), 3) if applicable else None}


def keyword_density(keyword: str, text: str) -> dict:
    kw = [_clean_token(t) for t in tokenize(keyword, drop_stopwords=False, min_len=1)]
    toks = [_clean_token(t) for t in tokenize(text, drop_stopwords=False, min_len=1)]
    k = len(kw)
    count = sum(1 for i in range(len(toks) - k + 1) if k and toks[i:i + k] == kw)
    words = word_count(text)
    density = round(100 * count / words, 2) if words else 0.0
    return {"occurrences": count, "words": words, "density_pct": density,
            "threshold_pct": STUFFING_DENSITY_PCT, "stuffing_risk": density > STUFFING_DENSITY_PCT}


def term_coverage(page: dict, competitors: list[dict]) -> dict:
    n = len(competitors)
    min_df = max(2, math.ceil(EXPECTED_DF_SHARE * n))
    df: Counter = Counter()
    rate_sum: Counter = Counter()
    surfaces: dict = {}
    for comp in competitors:
        counts, surf = _doc_terms(comp)
        words = max(1, comp.get("word_count") or 1)
        for key, c in counts.items():
            df[key] += 1
            rate_sum[key] += 1000.0 * c / words
        for key, forms in surf.items():
            surfaces.setdefault(key, Counter()).update(forms)
    candidates = {k for k, d in df.items() if d >= min_df}
    # A shorter phrase that only ever appears inside a longer expected phrase
    # (same document frequency) is redundant: keep the longer one.
    pruned = set(candidates)
    for longer in candidates:
        for size in range(1, len(longer)):
            for i in range(len(longer) - size + 1):
                sub = longer[i:i + size]
                if sub in pruned and df[sub] == df[longer]:
                    pruned.discard(sub)
    ranked = sorted(pruned, key=lambda k: (-df[k], -rate_sum[k] / n, -len(k), " ".join(k)))
    expected = ranked[:MAX_EXPECTED_TERMS]
    page_counts, _ = _doc_terms(page)

    def label(key):
        forms = surfaces.get(key) or Counter({" ".join(key): 1})
        return sorted(forms.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    present, missing = [], []
    for key in expected:
        row = {"term": label(key), "competitor_df": df[key], "df_share": round(df[key] / n, 2)}
        (present if page_counts.get(key) else missing).append(row)
    return {"competitors": n, "min_df": min_df, "expected_count": len(expected),
            "candidates_before_cap": len(pruned), "covered_count": len(present),
            "coverage": round(len(present) / len(expected), 3) if expected else None,
            "missing": missing, "present": present}


def heading_coverage(page: dict, competitors: list[dict]) -> dict:
    n = len(competitors)
    min_comp = max(2, math.ceil(EXPECTED_DF_SHARE * n))
    clusters: list[dict] = []
    for ci, comp in enumerate(competitors):
        for heading in (comp.get("h2") or []) + (comp.get("h3") or []):
            if _is_generic(heading):
                continue
            stems_h = content_stems(heading)
            if not stems_h:
                continue
            for cl in clusters:
                if _jaccard(cl["stems"], stems_h) >= TOPIC_CLUSTER_JACCARD:
                    cl["competitors"].add(ci)
                    cl["headings"].append(heading)
                    break
            else:
                clusters.append({"label": heading, "stems": stems_h, "competitors": {ci}, "headings": [heading]})
    own_heads = [content_stems(h) for h in (page.get("h1") or []) + (page.get("h2") or []) + (page.get("h3") or [])]
    topics = []
    for cl in clusters:
        if len(cl["competitors"]) < min_comp:
            continue
        best = max((_share_in(cl["stems"], oh) for oh in own_heads), default=0.0)
        topics.append({"topic": cl["label"], "competitors": len(cl["competitors"]),
                       "examples": cl["headings"][:3], "covered": best >= TOPIC_COVER_SHARE})
    topics.sort(key=lambda t: (t["covered"], -t["competitors"], t["topic"].lower()))
    covered = sum(1 for t in topics if t["covered"])
    return {"common_topics": len(topics), "covered": covered,
            "coverage": round(covered / len(topics), 3) if topics else None, "topics": topics}


def question_coverage(page: dict, competitors: list[dict]) -> dict:
    questions: list[dict] = []
    for ci, comp in enumerate(competitors):
        for heading in (comp.get("h2") or []) + (comp.get("h3") or []) + (comp.get("h4") or []):
            if not _is_question(heading):
                continue
            stems_q = content_stems(heading)
            if not stems_q:
                continue
            for q in questions:
                if _jaccard(q["stems"], stems_q) >= QUESTION_DEDUPE_JACCARD:
                    q["competitors"].add(ci)
                    break
            else:
                questions.append({"question": heading, "stems": stems_q, "competitors": {ci}})
    own_heads = [content_stems(h) for h in (page.get("h1") or []) + (page.get("h2") or [])
                 + (page.get("h3") or []) + (page.get("h4") or [])]
    own_paras = [content_stems(p) for p in page.get("paragraphs") or []]
    out = []
    for q in questions:
        matched = None
        if any(_share_in(q["stems"], oh) >= TOPIC_COVER_SHARE for oh in own_heads):
            matched = "heading"
        elif len(q["stems"]) >= 2 and any(_share_in(q["stems"], op) >= QUESTION_PARAGRAPH_SHARE
                                          for op in own_paras):
            matched = "paragraph"
        out.append({"question": q["question"], "competitors": len(q["competitors"]),
                    "addressed": matched is not None, "matched_by": matched})
    out.sort(key=lambda q: (q["addressed"], -q["competitors"], q["question"].lower()))
    addressed = sum(1 for q in out if q["addressed"])
    return {"total": len(out), "addressed": addressed,
            "coverage": round(addressed / len(out), 3) if out else None, "questions": out}


def _fmt_num(value: float) -> str:
    """Render a number so the expression string round-trips exactly (repr of the float)."""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def content_score(components: dict) -> dict:
    """Weighted 0-100 score; None components are excluded and weights renormalized.

    The score is computed by the same arithmetic, in the same order, as the
    ``expression`` string shows, from the exact component values, so
    ``eval(expression) == score`` always holds. Rounding is Python ``round()``
    (ties to even), as in aeo_score.py.
    """
    avail = {k: v for k, v in components.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in avail)
    parts = {k: {"value": (round(v, 3) if v is not None else None), "weight": WEIGHTS[k],
                 "points": (round(WEIGHTS[k] * v, 2) if v is not None else None)}
             for k, v in components.items()}
    if total_w == 0:
        return {"score": None, "components": parts, "completeness": 0.0, "expression": None,
                "interpretation": INTERPRETATION}
    terms = [(WEIGHTS[k], avail[k]) for k in WEIGHTS if k in avail]
    numerator = 0
    for w, v in terms:
        numerator = numerator + w * v
    expr = " + ".join(f"{w}*{_fmt_num(v)}" for w, v in terms)
    return {"score": round(100 * numerator / total_w), "components": parts,
            "completeness": round(total_w / sum(WEIGHTS.values()), 2),
            "expression": f"round(100 * ({expr}) / {total_w})",
            "excluded_as_na": [k for k in WEIGHTS if k not in avail],
            "interpretation": INTERPRETATION}


def _recommendations(terms: dict, heads: dict, questions: dict, length: dict,
                     placement: dict, density: dict) -> list[str]:
    recs = []
    if terms["coverage"] is not None and terms["coverage"] < 0.7 and terms["missing"]:
        sample = ", ".join(t["term"] for t in terms["missing"][:12])
        recs.append(f"Most competing pages discuss terms this page does not mention: {sample}. "
                    "Cover the ones that fit the page's purpose; do not insert terms for their own sake.")
    gaps = [t["topic"] for t in heads["topics"] if not t["covered"]]
    if gaps:
        recs.append("Section topics most competitors give a heading to, with no matching heading here: "
                    + "; ".join(gaps[:8]) + ".")
    open_q = [q["question"] for q in questions["questions"] if not q["addressed"]]
    if open_q:
        recs.append("Questions competitors answer that this page does not address (if added, open the "
                    "section with a direct, self-contained answer): " + "; ".join(open_q[:8]))
    if length["band"] == "below_q1":
        recs.append(f"Shorter than most competitors ({length['own']} words vs median "
                    f"{length['competitor_median']}). Length is not a ranking factor; check whether the "
                    "topic gaps above explain the difference.")
    elif length["band"] == "above_upper_fence":
        recs.append(f"Much longer than competitors ({length['own']} words vs upper fence "
                    f"{length['upper_fence']}). Check for padding or a page trying to serve two intents.")
    missing_places = [name for name, c in placement["checks"].items() if c["applicable"] and not c["pass"]]
    if missing_places:
        note = " Changing the slug of a live URL needs a 301 redirect." if "slug" in missing_places else ""
        recs.append("Primary keyword terms not found in: " + ", ".join(missing_places) + "." + note)
    if density["stuffing_risk"]:
        recs.append(f"Keyword density {density['density_pct']}% exceeds {STUFFING_DENSITY_PCT}%: reduce "
                    "repetition (keyword stuffing tested below baseline in the Princeton GEO study).")
    return recs


def analyze(keyword: str, page: dict, competitors: list[dict]) -> dict:
    """Pure analysis over already-extracted documents."""
    if not competitors:
        raise OptimizerError("no competitor documents", exit_code=2)
    terms = term_coverage(page, competitors)
    heads = heading_coverage(page, competitors)
    questions = question_coverage(page, competitors)
    length = length_fit(page.get("word_count") or 0, [c.get("word_count") or 0 for c in competitors])
    placement = keyword_placement(keyword, page)
    density = keyword_density(keyword, page.get("text", ""))
    placement_value = placement["share"]
    if density["stuffing_risk"] and placement_value is not None:
        placement_value = 0.0
    score = content_score({"terms": terms["coverage"], "headings": heads["coverage"],
                           "questions": questions["coverage"], "length": length["fit"],
                           "placement": placement_value})
    if density["stuffing_risk"]:
        score["notes"] = ["placement zeroed: keyword density above the stuffing threshold"]
    return {
        "keyword": keyword,
        "page": {k: page.get(k) for k in ("url", "source", "title", "meta_description", "h1", "slug",
                                          "word_count", "extractor")}
                | {"h2_count": len(page.get("h2") or []), "h3_count": len(page.get("h3") or [])},
        "competitors": [{"source": c.get("source"), "url": c.get("url"), "title": c.get("title"),
                         "word_count": c.get("word_count"), "extractor": c.get("extractor")}
                        for c in competitors],
        "score": score,
        "terms": terms,
        "headings": heads,
        "questions": questions,
        "length": length,
        "placement": placement,
        "density": density,
        "flags": ["keyword_stuffing_risk"] if density["stuffing_risk"] else [],
        "recommendations": _recommendations(terms, heads, questions, length, placement, density),
    }


LIMITATIONS = [
    "Correlational: shows what ranking pages have in common, not why they rank.",
    "Matching is lexical (light stemming, no synonyms or embeddings): a topic covered in different "
    "words is reported as missing.",
    "The competitor set is whatever the operator supplied; results change with it. Use pages that "
    "rank for the keyword (from the operator or DataForSEO SERP data), never scraped from Google.",
    "No JavaScript rendering: client-rendered pages may extract too little text and are dropped.",
    "Word count is not a ranking factor; the length component only flags outliers.",
]


def run(keyword: str, page_url: Optional[str], page_file: Optional[str], competitor_urls: list[str],
        competitor_files: list[str], min_competitors: int = 3, max_competitors: int = 10,
        fetcher: Optional[Callable] = None) -> dict:
    if not keyword.strip():
        raise OptimizerError("--keyword is required", exit_code=2)
    if bool(page_url) == bool(page_file):
        raise OptimizerError("pass exactly one of --url or --page-file", exit_code=2)
    page = (load_file_document(page_file) if page_file else fetch_document(page_url, fetcher))
    own_url = page_url or page.get("url")
    failed, competitors, seen = [], [], set()
    sources = [("url", u) for u in competitor_urls] + [("file", f) for f in competitor_files]
    notes = []
    if len(sources) > max_competitors:
        notes.append(f"{len(sources)} competitors supplied; analysing the first {max_competitors}")
        sources = sources[:max_competitors]
    for kind, src in sources:
        if kind == "url" and own_url and host_matches(src, own_url):
            failed.append({"source": src, "reason": "same site as the analysed page (not a competitor)"})
            continue
        try:
            doc = fetch_document(src, fetcher) if kind == "url" else load_file_document(src)
        except OptimizerError as exc:
            failed.append({"source": src, "reason": str(exc)})
            continue
        key = (doc.get("url") or src).rstrip("/")
        if key in seen:
            failed.append({"source": src, "reason": "duplicate of an earlier competitor"})
            continue
        seen.add(key)
        if (doc.get("word_count") or 0) < MIN_COMPETITOR_WORDS:
            failed.append({"source": src, "reason": f"only {doc.get('word_count')} words extracted "
                                                    "(JavaScript-rendered, blocked or thin)"})
            continue
        competitors.append(doc)
    if len(competitors) < min_competitors:
        raise OptimizerError(
            f"only {len(competitors)} competitor page(s) usable; need at least {min_competitors}. "
            "Supply more URLs of pages that rank for the keyword.",
            exit_code=2, detail={"failed_competitors": failed})
    result = analyze(keyword, page, competitors)
    result.update({
        "command": "analyze", "generated_at": utc_now(), "failed_competitors": failed, "notes": notes,
        "data_sources": [f"page: {page_url or page_file}",
                         f"competitors: {len(competitors)} of {len(sources)} supplied "
                         "(fetched via fetch_page, SSRF-safe; never scraped from Google)",
                         "extraction: trafilatura" if _HAVE_TRAFILATURA else "extraction: BeautifulSoup fallback"],
        "limitations": LIMITATIONS,
    })
    return result


def _text_report(r: dict) -> str:
    s = r["score"]
    lines = [f"Content score for '{r['keyword']}': {s['score']}/100 ({s['interpretation']})",
             f"  computed: {s['expression']}",
             f"  terms {r['terms']['covered_count']}/{r['terms']['expected_count']} | "
             f"topics {r['headings']['covered']}/{r['headings']['common_topics']} | "
             f"questions {r['questions']['addressed']}/{r['questions']['total']} | "
             f"length {r['length']['own']} words (median {r['length']['competitor_median']}) | "
             f"placement {r['placement']['passed']}/{r['placement']['applicable']} | "
             f"density {r['density']['density_pct']}%"]
    for rec in r["recommendations"]:
        lines.append(f"  - {rec}")
    for f in r["failed_competitors"]:
        lines.append(f"  skipped {f['source']}: {f['reason']}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a page with ranking competitor pages")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze", help="Score term/topic/question coverage against competitors")
    p.add_argument("--keyword", required=True)
    p.add_argument("--url", help="Live URL of the page to analyse")
    p.add_argument("--page-file", help="Local HTML or Markdown draft to analyse")
    p.add_argument("--competitor", action="append", default=[], help="Competitor URL (repeatable)")
    p.add_argument("--competitor-file", action="append", default=[], help="Competitor HTML file (repeatable)")
    p.add_argument("--min-competitors", type=int, default=3)
    p.add_argument("--max-competitors", type=int, default=10)
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.keyword, args.url, args.page_file, args.competitor, args.competitor_file,
                     args.min_competitors, args.max_competitors)
    except OptimizerError as exc:
        payload = {"error": str(exc), **exc.detail}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Error: {exc}", file=sys.stderr)
            for f in exc.detail.get("failed_competitors", []):
                print(f"  skipped {f['source']}: {f['reason']}", file=sys.stderr)
        return exc.exit_code
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else _text_report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
