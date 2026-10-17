"""
Tests for scripts/content_optimizer.py — competitor term/topic/question
coverage, placement, density and the deterministic content score.

Offline: pages are HTML strings or files under tmp_path; URL fetching goes
through an injected fake fetcher (or the real fetch_page with blocked IP
literals, which fail before any socket is opened).
"""
from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import content_optimizer as co  # noqa: E402

PY = sys.executable
SCRIPT = str(SCRIPTS / "content_optimizer.py")

FILLER = ("Customer relationship management software helps small teams track every lead, deal and "
          "customer conversation in one shared place. ") * 6


def html_page(title, h1, sections, meta=None):
    body = "".join(f"<h2>{h}</h2><p>{p}</p>" for h, p in sections)
    return (f"<html><head><title>{title}</title><meta name='description' content='{meta or title}'>"
            "</head><body><header><nav><a href='/'>Home</a> Login Signup cookie banner</nav></header>"
            f"<main><article><h1>{h1}</h1>{body}</article></main>"
            "<footer>All rights reserved privacy policy newsletter</footer></body></html>")


COMPETITORS = [
    html_page("CRM pricing explained", "CRM pricing explained", [
        ("How much does a CRM cost?", "Most CRM pricing plans charge per user per month. " + FILLER),
        ("Free CRM plans", "A free CRM plan limits contacts and pipeline automation. " + FILLER),
        ("Hidden costs", "Implementation fees, data migration and paid integrations add hidden costs. " + FILLER),
    ]),
    html_page("CRM pricing guide", "CRM pricing guide", [
        ("How much does a CRM cost per user?", "CRM pricing plans usually charge per user per month. " + FILLER),
        ("Hidden costs to watch", "Data migration and paid integrations are common hidden costs. " + FILLER),
        ("Is a free CRM enough?", "A free CRM plan works for a solo founder. " + FILLER),
    ]),
    html_page("Compare CRM pricing", "CRM pricing comparison", [
        ("Free CRM plans compared", "Every free CRM plan caps contacts. " + FILLER),
        ("Hidden costs of CRM software", "Hidden costs include data migration and onboarding. " + FILLER),
        ("What affects CRM pricing plans?", "Seats and automation drive CRM pricing plans per user per month. "
         + FILLER),
    ]),
]

THIN_OWN = html_page("Our CRM", "Why our CRM is great", [("Features", "Our CRM has features. " + FILLER[:300])])

GOOD_OWN = html_page(
    "CRM pricing: plans, free tiers and hidden costs", "CRM pricing explained for small teams", [
        ("CRM pricing plans per user", "CRM pricing plans charge per user per month; annual billing is cheaper. "
         + FILLER),
        ("Free CRM plans and their limits", "A free CRM plan caps contacts and automation. " + FILLER),
        ("Hidden costs", "Data migration and paid integrations are the usual hidden cost. " + FILLER),
        ("What drives the price", "How much a CRM costs depends on seats, automation and support. " + FILLER),
    ], meta="Compare CRM pricing plans, free CRM tiers and the hidden costs of data migration and paid integrations.")


def docs(*htmls, use_trafilatura=False):
    return [co.extract_document(h, use_trafilatura=use_trafilatura) for h in htmls]


@pytest.fixture
def competitors():
    return docs(*COMPETITORS)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def test_fallback_extraction_drops_nav_header_footer():
    d = co.extract_document(COMPETITORS[0], url="https://a.example/crm-pricing", use_trafilatura=False)
    assert d["extractor"] == "beautifulsoup"
    assert "cookie banner" not in d["text"] and "privacy policy" not in d["text"]
    assert d["h1"] == ["CRM pricing explained"]
    assert d["h2"][0] == "How much does a CRM cost?"
    assert d["slug"] == "crm-pricing"
    assert d["meta_description"] == "CRM pricing explained"


@pytest.mark.skipif(not co._HAVE_TRAFILATURA, reason="trafilatura not installed")
def test_trafilatura_extraction_when_available():
    d = co.extract_document(COMPETITORS[0], use_trafilatura=True)
    assert d["extractor"] == "trafilatura"
    assert "privacy policy" not in d["text"]


def test_markdown_draft_page_file(tmp_path):
    md = tmp_path / "draft.md"
    md.write_text("---\ntitle: CRM pricing guide\nslug: crm-pricing\n"
                  "meta_description: Everything about CRM pricing plans and hidden costs for small teams.\n"
                  "---\n\n## Hidden costs\n\nData migration adds hidden costs. " + FILLER, encoding="utf-8")
    d = co.load_file_document(str(md))
    assert d["extractor"] == "markdown-draft"
    assert d["title"] == "CRM pricing guide"
    assert d["h1"] == ["CRM pricing guide"]        # title becomes the H1 when the body has none
    assert d["slug"] == "crm-pricing"
    assert d["h2"] == ["Hidden costs"]


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

def test_expected_terms_need_half_of_competitors_and_two_pages(competitors):
    page = docs(THIN_OWN)[0]
    terms = co.term_coverage(page, competitors)
    assert terms["min_df"] == 2
    missing = {t["term"] for t in terms["missing"]}
    assert {"hidden costs", "data migration"} <= missing
    assert all(t["competitor_df"] >= 2 for t in terms["missing"] + terms["present"])
    assert terms["expected_count"] <= co.MAX_EXPECTED_TERMS


def test_stemming_counts_singular_as_covered(competitors):
    page = docs(GOOD_OWN)[0]          # says "hidden cost" (singular) in one place
    terms = co.term_coverage(page, competitors)
    present = {t["term"] for t in terms["present"]}
    assert "hidden costs" in present
    assert terms["coverage"] > co.term_coverage(docs(THIN_OWN)[0], competitors)["coverage"]


def test_redundant_subphrases_are_pruned(competitors):
    terms = co.term_coverage(docs(THIN_OWN)[0], competitors)
    labels = [t["term"] for t in terms["missing"] + terms["present"]]
    assert "free crm plans" in labels
    assert "free crm" not in labels   # only ever appears inside "free crm plans" at the same DF


def test_heading_topics_and_coverage(competitors):
    heads = co.heading_coverage(docs(GOOD_OWN)[0], competitors)
    topics = {t["topic"]: t for t in heads["topics"]}
    assert topics["Hidden costs"]["competitors"] == 3 and topics["Hidden costs"]["covered"]
    assert topics["Free CRM plans"]["covered"]
    thin = co.heading_coverage(docs(THIN_OWN)[0], competitors)
    assert thin["covered"] == 0 and thin["coverage"] == 0.0


def test_generic_headings_are_not_topics():
    comps = docs(*[html_page("x", "x", [("Conclusion", FILLER), ("FAQ", FILLER)]) for _ in range(3)])
    assert co.heading_coverage(docs(THIN_OWN)[0], comps)["common_topics"] == 0


def test_questions_addressed_by_heading_or_paragraph(competitors):
    q = co.question_coverage(docs(GOOD_OWN)[0], competitors)
    by_text = {x["question"]: x for x in q["questions"]}
    cost = by_text["How much does a CRM cost?"]
    assert cost["competitors"] == 2               # deduped with "... cost per user?"
    assert cost["addressed"] and cost["matched_by"] == "paragraph"
    assert by_text["Is a free CRM enough?"]["addressed"]
    assert q["questions"][0]["addressed"] is False or q["addressed"] == q["total"]


def test_placement_checks():
    page = co.extract_document(GOOD_OWN, url="https://ex.com/blog/crm-pricing", use_trafilatura=False)
    pl = co.keyword_placement("crm pricing", page)
    checks = pl["checks"]
    assert checks["title"]["pass"] and checks["h1"]["pass"] and checks["slug"]["pass"]
    assert checks["meta_description"]["pass"] and checks["first_100_words"]["pass"]
    assert checks["h2"]["pass"] and checks["h2"]["matching_h2"] == ["CRM pricing plans per user"]
    assert pl["share"] == 1.0


def test_placement_slug_not_applicable_without_url():
    page = co.extract_document(GOOD_OWN, use_trafilatura=False)
    pl = co.keyword_placement("crm pricing", page)
    assert pl["checks"]["slug"]["applicable"] is False
    assert pl["applicable"] == 5


def test_density_and_stuffing_flag_zeroes_placement(competitors):
    stuffed = html_page("crm pricing", "crm pricing", [
        ("crm pricing", ("crm pricing is crm pricing. " * 40) + FILLER)])
    res = co.analyze("crm pricing", docs(stuffed)[0], competitors)
    assert res["density"]["stuffing_risk"] is True
    assert res["density"]["density_pct"] > co.STUFFING_DENSITY_PCT
    assert res["score"]["components"]["placement"]["value"] == 0.0
    assert "keyword_stuffing_risk" in res["flags"]
    assert any("stuffing" in r for r in res["recommendations"])


@pytest.mark.parametrize("own,band", [(100, "below_q1"), (400, "within_range"), (5000, "above_upper_fence")])
def test_length_fit_bands(own, band):
    lf = co.length_fit(own, [350, 400, 450])
    assert lf["band"] == band
    if band == "below_q1":
        assert lf["fit"] == pytest.approx(round(100 / lf["q1"], 3))
    elif band == "within_range":
        assert lf["fit"] == 1.0
    else:
        assert lf["fit"] == 0.6


def test_content_score_renormalizes_missing_components():
    s = co.content_score({"terms": 0.5, "headings": None, "questions": None, "length": 1.0, "placement": 1.0})
    assert s["score"] == round(100 * (35 * 0.5 + 15 * 1.0 + 15 * 1.0) / 65)
    assert s["excluded_as_na"] == ["headings", "questions"]
    assert s["completeness"] == 0.65
    assert s["interpretation"].startswith("correlational")


def _eval_expr(expr):
    return eval(expr, {"__builtins__": {"round": round}})


@pytest.mark.parametrize("comps", [
    {"terms": 0.125, "headings": None, "questions": None, "length": None, "placement": None},
    {"terms": 0.5, "headings": 1 / 3, "questions": None, "length": 1.0, "placement": 5 / 6},
    {"terms": 0.375, "headings": 0.625, "questions": 0.875, "length": 0.6, "placement": 0.0},
])
def test_content_score_expression_reproduces_score(comps):
    s = co.content_score(comps)
    assert _eval_expr(s["expression"]) == s["score"]


def test_content_score_expression_always_matches_score():
    rng = random.Random(2468)
    for _ in range(3000):
        comps = {}
        for name in co.WEIGHTS:
            roll = rng.random()
            comps[name] = (None if roll < 0.2 else
                           rng.choice([rng.random(), round(rng.random(), 3), rng.randint(0, 8) / 8,
                                       rng.randint(0, 6) / 6, 0.0, 1.0]))
        s = co.content_score(comps)
        if s["score"] is None:
            assert all(v is None for v in comps.values()) and s["expression"] is None
            continue
        assert _eval_expr(s["expression"]) == s["score"], s
        assert 0 <= s["score"] <= 100


# ---------------------------------------------------------------------------
# Whole analysis
# ---------------------------------------------------------------------------

def test_analysis_is_deterministic_and_correlational(competitors):
    page = docs(GOOD_OWN)[0]
    a = co.analyze("crm pricing", page, competitors)
    b = co.analyze("crm pricing", page, docs(*COMPETITORS))
    assert a == b
    assert 0 <= a["score"]["score"] <= 100
    assert a["score"]["interpretation"] == co.INTERPRETATION
    assert a["score"]["expression"].startswith("round(100 * (")
    thin = co.analyze("crm pricing", docs(THIN_OWN)[0], competitors)
    assert a["score"]["score"] > thin["score"]["score"]


def test_recommendations_never_prescribe_keyword_counts(competitors):
    res = co.analyze("crm pricing", docs(THIN_OWN)[0], competitors)
    assert res["recommendations"]
    for rec in res["recommendations"]:
        assert not re.search(r"\b\d+\s*(?:times|x)\b", rec, re.IGNORECASE)
        assert "add the keyword" not in rec.lower()


def fake_fetcher(pages):
    def fetch(url):
        if url not in pages:
            return {"url": url, "status_code": None, "content": None, "error": "Connection error: refused"}
        status, html = pages[url]
        return {"url": url, "status_code": status, "content": html, "error": None}
    return fetch


def test_run_with_fake_fetcher_skips_failures_and_same_site():
    pages = {
        "https://ex.com/blog/crm-pricing": (200, GOOD_OWN),
        "https://a.example/1": (200, COMPETITORS[0]),
        "https://b.example/2": (200, COMPETITORS[1]),
        "https://c.example/3": (200, COMPETITORS[2]),
        "https://d.example/404": (404, "<html></html>"),
        "https://e.example/js": (200, "<html><body><div id='root'></div></body></html>"),
    }
    res = co.run("crm pricing", "https://ex.com/blog/crm-pricing", None,
                 list(pages)[1:] + ["https://www.ex.com/other", "https://f.example/down"], [],
                 fetcher=fake_fetcher(pages))
    assert len(res["competitors"]) == 3
    reasons = {f["source"]: f["reason"] for f in res["failed_competitors"]}
    assert "HTTP 404" in reasons["https://d.example/404"]
    assert "words extracted" in reasons["https://e.example/js"]
    assert "same site" in reasons["https://www.ex.com/other"]
    assert "Connection error" in reasons["https://f.example/down"]
    assert res["page"]["slug"] == "crm-pricing"
    assert res["data_sources"] and res["limitations"]


def test_run_fails_clearly_below_min_competitors():
    pages = {"https://ex.com/p": (200, GOOD_OWN), "https://a.example/1": (200, COMPETITORS[0])}
    with pytest.raises(co.OptimizerError) as exc:
        co.run("crm pricing", "https://ex.com/p", None, ["https://a.example/1", "https://b.example/x"], [],
               fetcher=fake_fetcher(pages))
    assert exc.value.exit_code == 2
    assert "need at least 3" in str(exc.value)
    assert len(exc.value.detail["failed_competitors"]) == 1


def test_private_competitor_urls_are_refused_by_url_safety(tmp_path):
    own = tmp_path / "own.html"
    own.write_text(GOOD_OWN, encoding="utf-8")
    with pytest.raises(co.OptimizerError) as exc:
        co.run("crm pricing", None, str(own),
               ["http://169.254.169.254/latest/meta-data", "http://127.0.0.1:8080/x", "http://10.0.0.5/"],
               [], min_competitors=1)
    failed = exc.value.detail["failed_competitors"]
    assert len(failed) == 3
    assert all("url_safety" in f["reason"] for f in failed)


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

@pytest.fixture
def files(tmp_path):
    paths = []
    for i, html in enumerate(COMPETITORS):
        p = tmp_path / f"c{i}.html"
        p.write_text(html, encoding="utf-8")
        paths.append(str(p))
    own = tmp_path / "own.html"
    own.write_text(GOOD_OWN, encoding="utf-8")
    return str(own), paths


def test_cli_json_with_files(files):
    own, comps = files
    cmd = [PY, SCRIPT, "analyze", "--keyword", "crm pricing", "--page-file", own, "--json"]
    for c in comps:
        cmd += ["--competitor-file", c]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["score"]["interpretation"].startswith("correlational")
    assert set(out["score"]["components"]) == set(co.WEIGHTS)
    assert out["terms"]["expected_count"] > 0


def test_cli_too_few_competitors_exit_2(files):
    own, comps = files
    r = subprocess.run([PY, SCRIPT, "analyze", "--keyword", "crm pricing", "--page-file", own,
                        "--competitor-file", comps[0], "--competitor-file", comps[1], "--json"],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "need at least 3" in json.loads(r.stdout)["error"]


def test_cli_requires_exactly_one_page_source(files):
    own, comps = files
    r = subprocess.run([PY, SCRIPT, "analyze", "--keyword", "x", "--competitor-file", comps[0]],
                       capture_output=True, text=True)
    assert r.returncode == 2
