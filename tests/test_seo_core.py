"""
Tests for the shared hub core used by every v3.1 research/tracking script:
    scripts/seo_metrics.py  — intent, CTR, opportunity, stats, cannibalization
    scripts/seo_store.py    — storage root + SQLite connections
    scripts/seo_project.py  — client/project profiles

All pure: no network. Storage tests run under tmp_path via --data-dir /
CLAUDE_SEO_DATA_DIR so they never touch the operator's real cache.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import seo_metrics as m  # noqa: E402
import seo_project as proj  # noqa: E402
import seo_store as store  # noqa: E402


# ---------------------------------------------------------------------------
# Intent classification
# ---------------------------------------------------------------------------

INTENT_CASES = [
    ("crm pricing", "transactional", "BOFU"),
    ("buy running shoes", "transactional", "BOFU"),
    ("plumber near me", "transactional", "BOFU"),
    ("hubspot vs salesforce", "commercial", "BOFU"),
    ("salesforce alternatives", "commercial", "BOFU"),
    ("best crm for small business", "commercial", "MOFU"),
    ("how to choose a crm", "commercial", "MOFU"),
    ("what is a crm", "informational", "TOFU"),
    ("how does lead scoring work", "informational", "TOFU"),
    ("crm", "informational", "TOFU"),
]


@pytest.mark.parametrize("keyword,intent,funnel", INTENT_CASES)
def test_classify_intent_labeled_fixture(keyword, intent, funnel):
    r = m.classify_intent(keyword)
    assert (r["intent"], r["funnel"]) == (intent, funnel), r


def test_own_brand_is_navigational_with_defend_value():
    r = m.classify_intent("acme login", brand_terms=["acme"])
    assert r["intent"] == "navigational"
    assert r["brand"] is True
    assert r["lead_value"] == m.OWN_BRAND_LEAD_VALUE


def test_competitor_brand_query_is_bofu_commercial():
    r = m.classify_intent("salesforce review", competitor_terms=["salesforce"])
    assert r["intent"] == "commercial" and r["funnel"] == "BOFU"
    assert r["competitor"] == ["salesforce"]


def test_term_matching_respects_word_boundaries():
    # "vs" must not match inside "canvas"; "top" must not match "laptop"
    r = m.classify_intent("canvas laptop bag")
    assert r["intent"] == "informational" and r["confidence"] == "low"


def test_local_flag_and_zip():
    assert m.classify_intent("dentist 94107")["local"] is True
    assert m.classify_intent("dentist open now")["local"] is True
    assert m.classify_intent("dentist")["local"] is False


def test_classification_is_deterministic():
    assert m.classify_intent("best crm vs hubspot") == m.classify_intent("best crm vs hubspot")


# ---------------------------------------------------------------------------
# CTR, bands, opportunity
# ---------------------------------------------------------------------------

def test_expected_ctr_monotonic_and_interpolates():
    vals = [m.expected_ctr(p) for p in range(1, 11)]
    assert vals == sorted(vals, reverse=True)
    mid = m.expected_ctr(1.5)
    assert m.expected_ctr(2) < mid < m.expected_ctr(1)
    assert m.expected_ctr(15) == m.PAGE2_CTR
    assert m.expected_ctr(35) == m.DEEP_CTR_ASSUMPTION
    assert m.expected_ctr(None) == 0.0


def test_calibrated_curve_overrides_default():
    rows = [{"position": 1.2, "clicks": 50, "impressions": 1000},
            {"position": 0.9, "clicks": 50, "impressions": 1000},
            {"position": 7, "clicks": 1, "impressions": 10}]  # below min_impressions
    cal = m.calibrate_ctr_curve(rows, min_impressions=50)
    assert cal["curve"] == {1: 0.05}
    assert cal["source"].startswith("site-calibrated")
    assert m.expected_ctr(1, cal["curve"]) == 0.05
    assert m.expected_ctr(2, cal["curve"]) == m.DEFAULT_CTR_CURVE[2]


def test_position_bands_and_striking_distance():
    assert m.position_band(1) == "top3"
    assert m.position_band(3) == "top3"
    assert m.position_band(3.4) == "page1"
    assert m.position_band(12) == "striking"
    assert m.position_band(None) == "unranked"
    assert m.is_striking_distance(4) and m.is_striking_distance(20)
    assert not m.is_striking_distance(3.9) and not m.is_striking_distance(20.1)


def test_opportunity_score_bounds_and_renormalization():
    full = m.opportunity_score(volume=2400, difficulty=35, position=8, lead_value=1.0)
    assert 0 <= full["score"] <= 100 and full["completeness"] == 1.0
    partial = m.opportunity_score(lead_value=1.0)
    # only lead_value known -> renormalized to 100 * 1.0
    assert partial["score"] == 100.0
    assert partial["completeness"] == pytest.approx(0.3)
    none = m.opportunity_score()
    assert none["score"] == 0.0


def test_opportunity_relevance_multiplier_and_ordering():
    a = m.opportunity_score(volume=1000, difficulty=20, lead_value=1.0)
    b = m.opportunity_score(volume=1000, difficulty=20, lead_value=0.25)
    assert a["score"] > b["score"]
    zero = m.opportunity_score(volume=1000, difficulty=20, lead_value=1.0, relevance=0)
    assert zero["score"] == 0.0


def test_scenario_bucket():
    assert m.scenario_bucket(80, 1.0, position=9) == "quick_win"
    assert m.scenario_bucket(20, 1.0) == "quick_win"
    assert m.scenario_bucket(45, 0.6) == "growth"
    assert m.scenario_bucket(75, 1.0) == "long_term"
    assert m.scenario_bucket(10, 0.25) == "awareness"


def test_geo_flags():
    assert set(m.geo_flags("what is a crm")) >= {"question", "definition"}
    assert "comparison" in m.geo_flags("hubspot vs salesforce")
    assert "how_to" in m.geo_flags("how to migrate crm data")
    assert m.geo_flags("crm") == []


def test_striking_distance_opportunity():
    r = m.striking_distance_opportunity(position=9, ctr=0.01, impressions=10_000)
    assert r["target_position"] == 4
    assert r["opp_clicks"] == pytest.approx(10_000 * (m.DEFAULT_CTR_CURVE[4] - 0.01), abs=0.1)
    capped = m.striking_distance_opportunity(position=2, ctr=0.5, impressions=100)
    assert capped["target_position"] == 1 and capped["opp_clicks"] == 0.0


def test_ctr_gap():
    g = m.ctr_gap(position=1, actual_ctr=0.05, impressions=1000)
    assert g["click_shortfall"] > 0 and g["ctr_ratio"] < 1


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def test_wilson_interval():
    lo, hi = m.wilson_interval(0, 10)
    assert lo == 0.0 and 0.2 < hi < 0.35
    lo, hi = m.wilson_interval(10, 10)
    assert hi == 1.0 and 0.65 < lo < 0.8
    assert m.wilson_interval(0, 0) == (0.0, 0.0)


def test_sign_test_and_holm():
    assert m.sign_test_p(0, 0) == 1.0
    assert m.sign_test_p(10, 0) == pytest.approx(2 / 1024, rel=1e-3)
    assert m.sign_test_p(5, 5) == 1.0
    adj = m.holm_adjust([0.01, 0.04, 0.03])
    assert adj[0] == pytest.approx(0.03)
    assert adj[2] == pytest.approx(0.06)
    assert adj[1] == pytest.approx(0.06)  # monotone step-down
    assert m.pct_change(0, 5) is None and m.pct_change(100, 80) == -20.0


# ---------------------------------------------------------------------------
# Cannibalization
# ---------------------------------------------------------------------------

def test_cannibalization_flags_real_split_only():
    rows = [
        {"query": "crm pricing", "page": "/pricing", "clicks": 60, "impressions": 900},
        {"query": "crm pricing", "page": "/blog/crm-cost", "clicks": 40, "impressions": 700},
        {"query": "crm pricing", "page": "/features", "clicks": 1, "impressions": 50},
        {"query": "what is crm", "page": "/blog/what-is-crm", "clicks": 30, "impressions": 500},
        {"query": "acme crm", "page": "/", "clicks": 90, "impressions": 900},
        {"query": "acme crm", "page": "/pricing", "clicks": 40, "impressions": 400},
    ]
    out = m.detect_cannibalization(rows, brand_terms=["acme"])
    assert [c["query"] for c in out] == ["crm pricing"]
    pages = [p["page"] for p in out[0]["pages"]]
    assert pages == ["/pricing", "/blog/crm-cost"]  # /features below 10% share


def test_cannibalization_impression_basis_when_no_clicks():
    rows = [{"query": "x tool", "page": "/a", "clicks": 0, "impressions": 100},
            {"query": "x tool", "page": "/b", "clicks": 0, "impressions": 100}]
    out = m.detect_cannibalization(rows)
    assert out and out[0]["basis"] == "impressions"


def test_tokenize_and_ngrams():
    toks = m.tokenize("The Best CRM for B2B teams — C++ and node.js!")
    assert "the" not in toks and "crm" in toks and "c++" in toks
    assert m.ngrams(["a", "b", "c"], 2) == ["a b", "b c"]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def test_store_root_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv(store.ENV_VAR, str(tmp_path / "env"))
    assert store.data_root() == tmp_path / "env"
    assert store.data_root(str(tmp_path / "flag")) == tmp_path / "flag"
    monkeypatch.delenv(store.ENV_VAR)
    assert store.data_root() == store.DEFAULT_ROOT


def test_store_connect_creates_private_db(tmp_path):
    conn = store.connect("rankings", "CREATE TABLE IF NOT EXISTS t (x INTEGER);", str(tmp_path))
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    path = store.db_path("rankings", str(tmp_path))
    assert path.is_file()
    if os.name == "posix":
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    # idempotent schema
    store.connect("rankings", "CREATE TABLE IF NOT EXISTS t (x INTEGER);", str(tmp_path))
    assert store.list_stores(str(tmp_path))[0]["store"] == "rankings"


def test_store_rejects_path_traversal_names(tmp_path):
    for bad in ("../x", "a/b", "", "A", "x" * 60):
        with pytest.raises(ValueError):
            store.db_path(bad, str(tmp_path))


@pytest.mark.parametrize("value,expected", [
    ("https://www.Example.com/path?q=1", "example.com"),
    ("sc-domain:example.com", "example.com"),
    ("example.com", "example.com"),
    ("http://blog.example.co.uk:8080/", "blog.example.co.uk"),
    ("", ""),
])
def test_normalize_domain(value, expected):
    assert store.normalize_domain(value) == expected


def test_host_matches_subdomains_only():
    assert store.host_matches("https://blog.example.com/x", "example.com")
    assert store.host_matches("example.com", "www.example.com")
    assert not store.host_matches("https://notexample.com", "example.com")
    assert not store.host_matches("", "example.com")


# ---------------------------------------------------------------------------
# Project profiles
# ---------------------------------------------------------------------------

def test_profile_roundtrip_and_permissions(tmp_path):
    p = proj.new_profile("https://www.Example.com", name="Example", brand_terms=["example"],
                         competitors=["rival.com", "https://www.other.io/"],
                         gsc_property="sc-domain:example.com")
    path = proj.save_profile(p, str(tmp_path))
    assert path.name == "example-com.json"
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    loaded = proj.load_profile("example.com", str(tmp_path))
    assert loaded["domain"] == "example.com"
    assert [c["domain"] for c in loaded["competitors"]] == ["rival.com", "other.io"]
    assert proj.load_profile("example-com", str(tmp_path))["slug"] == "example-com"
    assert proj.load_profile("missing.com", str(tmp_path)) is None


def test_profile_validation(tmp_path):
    p = proj.new_profile("example.com")
    with pytest.raises(ValueError):
        proj.add_competitor(p, "https://www.example.com/")
    # a hand-edited profile listing itself is still rejected at save time
    p["competitors"].append({"name": "self", "domain": "www.example.com", "aliases": []})
    with pytest.raises(ValueError):
        proj.save_profile(p, str(tmp_path))
    p2 = proj.new_profile("example.com", gsc_property="example.com")
    with pytest.raises(ValueError):
        proj.save_profile(p2, str(tmp_path))
    warn = proj.validate_profile(proj.new_profile("example.com", competitors=["a.com"]))
    assert any(w["level"] == "warning" for w in warn)


def test_profile_set_field_prompts_notes(tmp_path):
    p = proj.new_profile("example.com")
    proj.set_field(p, "markets.country", "GB")
    proj.set_field(p, "money_pages", '["/pricing", "/demo"]')
    assert p["markets"]["country"] == "GB" and p["money_pages"] == ["/pricing", "/demo"]
    with pytest.raises(KeyError):
        proj.set_field(p, "slug", "x")
    with pytest.raises(KeyError):
        proj.set_field(p, "nonsense", "x")
    proj.add_prompt(p, "best crm  for startups", group="treatment")
    proj.add_prompt(p, "Best CRM for startups")  # duplicate, case-insensitive
    assert len(p["ai_visibility"]["prompts"]) == 1
    proj.add_note(p, "plan approved", approved_by="user")
    with pytest.raises(ValueError):
        proj.add_note(p, "x", approved_by="someone")
    proj.save_profile(p, str(tmp_path))


def test_brand_and_competitor_terms():
    p = proj.new_profile("acme.io", brand_terms=["acme", "acme crm"],
                         competitors=["rival.com"])
    p["competitors"][0]["aliases"] = ["Rival CRM"]
    assert proj.all_brand_terms(p) == ["acme", "acme crm"]
    assert proj.competitor_terms(p) == ["rival", "rival crm"]


def test_project_cli_init_and_show(tmp_path):
    import subprocess
    py = sys.executable
    script = str(REPO_ROOT / "scripts" / "seo_project.py")
    r = subprocess.run([py, script, "--data-dir", str(tmp_path), "init", "example.com",
                        "--competitor", "rival.com"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([py, script, "--data-dir", str(tmp_path), "show", "example.com", "--json"],
                       capture_output=True, text=True)
    data = json.loads(r.stdout)
    assert data["profile"]["domain"] == "example.com"
    r = subprocess.run([py, script, "--data-dir", str(tmp_path), "init", "example.com"],
                       capture_output=True, text=True)
    assert r.returncode == 1  # refuses to overwrite without --force
