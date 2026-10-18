"""link_gap: segmentation, exclusions, classification, scoring. No network."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import link_gap as lg  # noqa: E402
import link_store  # noqa: E402
import seo_kpi  # noqa: E402
import seo_project  # noqa: E402


def sig(domain, url=None, title=None, anchor=None, authority=None, spam=None, attrs=(), tld=None):
    texts = [t for t in (title, url, anchor) if t]
    return {"domain": domain, "sample_url": url, "sample_title": title, "sample_anchor": anchor,
            "authority": authority, "spam_score": spam, "attributes": list(attrs),
            "tld": tld or domain.rsplit(".", 1)[-1], "texts": texts, "quality": 0.5}


@pytest.mark.parametrize("s, expected", [
    (sig("clutch.co", "https://clutch.co/video-production/india"), "directory"),
    (sig("x.com.au", "https://x.com.au/top-video-production-companies"), "directory"),
    (sig("iitb.ac.in", "https://iitb.ac.in/news/x"), "association"),
    (sig("hr-society.org", "https://hr-society.org/members"), "association"),
    (sig("reddit.com", "https://reddit.com/r/elearning/comments/1"), "community"),
    (sig("ld-show.com", "https://ld-show.com/podcast/episode-12"), "event"),
    (sig("hrweekly.in", "https://hrweekly.in/resources/compliance-training-tools"), "resource"),
    (sig("lms.io", "https://lms.io/integrations/video"), "partner"),
    (sig("trainingmag.com", "https://trainingmag.com/2025/03/best-studios/", authority=80), "publication"),
    (sig("economictimes.com", "https://economictimes.com/tech/x"), "publication"),
    (sig("blog.vendor.io", "https://blog.vendor.io/post"), "blog"),
    (sig("random.net", "https://random.net/about"), "unclassified"),
])
def test_classification_rules(s, expected):
    kind, rule = lg.classify(s)
    assert kind == expected and rule.startswith("rule")


@pytest.mark.parametrize("s, reason", [
    (sig("acme.in"), "own_property"),
    (sig("shop.acme.in"), "own_property"),
    (sig("rival.com"), "competitor_property"),
    (sig("linkedin.com"), "social_ugc"),
    (sig("spam.biz", spam=60), "spam"),
    (sig("pr.net", "https://pr.net/sponsored-post/x"), "paid_or_scheme"),
    (sig("pr2.net", attrs=["sponsored"]), "paid_or_scheme"),
    (sig("good.org", "https://good.org/write-for-us"), None),
])
def test_exclusions(s, reason):
    assert lg.exclusion_reason(s, "acme.in", ["rival.com", "other.in"]) == reason


def test_segments():
    client = [{"domain": "a.org"}, {"domain": "b.org"}]
    comps = {"rival.com": [{"domain": "b.org"}, {"domain": "c.org"}, {"domain": "d.org"}],
             "other.in": [{"domain": "c.org"}, {"domain": "e.org"}]}
    merged = lg.segment_domains(client, comps)
    seg = {d: e["segment"] for d, e in merged.items()}
    assert seg == {"a.org": "moat", "b.org": "shared", "c.org": "gap", "d.org": "single",
                   "e.org": "single"}
    assert merged["c.org"]["competitors"] == ["other.in", "rival.com"] and merged["c.org"]["k"] == 2


def test_topic_matching_folds_plurals_and_never_spans_texts():
    terms = ["training video", "compliance training"]
    assert lg.topic_matches(terms, ["Best training videos for compliance training"]) == 2
    assert lg.topic_matches(terms, ["https://x.com/corporate-training-video-guide"]) == 1
    assert lg.topic_matches(terms, ["about training", "video tips"]) == 0


def test_market_fit():
    assert lg.market_fit("in", "IN") == 1.0
    assert lg.market_fit("com", "IN") == 0.5
    assert lg.market_fit("de", "IN") == 0.2
    assert lg.market_fit("uk", "GB") == 1.0


def test_score_golden_and_neutral_priors():
    score, comps = lg.score_prospect(2, 80.0, 2 / 3, 0.5, 1.0, "publication")
    assert score == 74 and comps["overlap"] == pytest.approx(0.6667, abs=1e-4)
    neutral, _ = lg.score_prospect(1, None, 0.5, 0.5, 0.5, "unclassified")
    assert neutral == 45


def test_round_half_up_not_bankers():
    # 10 + 10.5 + 10 + 5 + 5 + 6 = 46.5 -> 47 (Python round() would give 46)
    score, _ = lg.score_prospect(1, 52.5, 0.5, 0.5, 0.5, "blog")
    assert score == 47


@pytest.mark.parametrize("score, effort, bucket", [
    (75, "high", "high_value"), (70, "medium", "high_value"), (55, "low", "quick_win"),
    (50, "low", "quick_win"), (55, "medium", "backlog"), (49, "low", "backlog")])
def test_plan_buckets(score, effort, bucket):
    assert lg.plan_bucket(score, effort) == bucket


def test_resolve_topics():
    profile = {"domain": "acme.in", "brand_terms": ["acme"], "topics": ["Training Video"]}
    assert lg.resolve_topics(profile, None) == (["training video"], "profile")
    profile["topics"] = []
    urls = ["https://acme.in/solutions/compliance-training-video",
            "https://acme.in/solutions/safety-training-video", "https://acme.in/acme-story"]
    terms, origin = lg.resolve_topics(profile, urls)
    assert origin == "sitemap" and terms[:2] == ["training", "video"] and "acme" not in terms
    assert lg.resolve_topics(profile, []) == ([], "none")


def _store(tmp_path):
    data_dir = str(tmp_path)
    profile = seo_project.new_profile("acme.in", "Acme", ["acme"], ["rival.com", "other.in", "third.io"],
                                      topics=["training video", "compliance training"],
                                      markets={"country": "IN", "language": "en"})
    seo_project.save_profile(profile, data_dir)
    conn = link_store.open_store(data_dir)
    link_store.save_snapshot(conn, "acme.in", "acme.in", "csv-generic", [{"domain": "partner.in"}])
    pub = {"domain": "trainingmag.com", "authority": 80.0, "dofollow": True,
           "sample_url": "https://trainingmag.com/2025/03/best-training-video-studios/",
           "sample_title": "Best training video studios for compliance training", "tld": "com"}
    clutch = {"domain": "clutch.co", "authority": 70.0, "dofollow": True,
              "sample_url": "https://clutch.co/video-production/india", "tld": "co"}
    link_store.save_snapshot(conn, "acme.in", "rival.com", "csv-generic",
                             [pub, clutch, {"domain": "spamfarm.biz", "spam_score": 80.0},
                              {"domain": "partner.in"}])
    link_store.save_snapshot(conn, "acme.in", "other.in", "csv-generic",
                             [pub, {"domain": "hrweekly.in", "authority": 40.0, "dofollow": True,
                                    "sample_url": "https://hrweekly.in/resources/compliance-training-tools",
                                    "sample_title": "Compliance training tools", "tld": "in"},
                              {"domain": "linkedin.com"}])
    link_store.save_snapshot(conn, "acme.in", "third.io", "csv-generic",
                             [clutch, {"domain": "blogger.net",
                                       "sample_url": "https://blogger.net/blog/my-favourite-studios/"}])
    return data_dir


def test_analyze_project_end_to_end(tmp_path):
    data_dir = _store(tmp_path)
    out = lg.analyze_project("acme.in", "csv-generic", data_dir, use_sitemap=False)
    assert out["segments"] == {"gap": 2, "single": 4, "shared": 1, "moat": 0}
    ranked = [(p["domain"], p["score"], p["bucket"]) for p in out["prospects"]]
    assert ranked == [("trainingmag.com", 74, "high_value"), ("clutch.co", 55, "quick_win"),
                      ("hrweekly.in", 53, "backlog"), ("blogger.net", 36, "backlog")]
    assert {(e["domain"], e["reason"]) for e in out["excluded"]} == {
        ("spamfarm.biz", "spam"), ("linkedin.com", "social_ugc")}
    assert out["kpis"] == {"links.referring_domains": 1, "links.gap_domains": 2}
    assert out["topics_source"] == "profile" and not out["warnings"]


def test_coverage_gap_is_reported_not_filled(tmp_path):
    data_dir = _store(tmp_path)
    conn = link_store.open_store(data_dir)
    link_store.save_snapshot(conn, "acme.in", "acme.in", "moz", [])
    link_store.save_snapshot(conn, "acme.in", "rival.com", "moz", [{"domain": "x.org"}])
    out = lg.analyze_project("acme.in", "moz", data_dir, use_sitemap=False)
    assert out["coverage"]["missing"] == ["other.in", "third.io"]
    assert any("fewer than 2 competitors" in w for w in out["warnings"])


def test_missing_client_snapshot_is_an_error(tmp_path):
    data_dir = _store(tmp_path)
    with pytest.raises(lg.GapError):
        lg.analyze_project("acme.in", "dataforseo", data_dir, use_sitemap=False)


def test_cli_prospects_and_kpis(tmp_path):
    data_dir = _store(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = lg.main(["prospects", "--project", "acme.in", "--source", "csv-generic", "--no-sitemap",
                      "--top", "2", "--data-dir", data_dir, "--json"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert [p["domain"] for p in out["prospects"]] == ["trainingmag.com", "clutch.co"]
    kpi_path = tmp_path / "kpis-links-gap.json"
    with redirect_stdout(io.StringIO()):
        rc = lg.main(["kpis", "--project", "acme.in", "--source", "csv-generic", "--no-sitemap",
                      "--emit-kpis", str(kpi_path), "--data-dir", data_dir, "--json"])
    assert rc == 0
    env = json.loads(kpi_path.read_text())
    assert seo_kpi.validate_envelope(env)["ok"]
    assert env["metrics"] == {"links.referring_domains": 1, "links.gap_domains": 2}
    assert env["source"] == "link_gap.py (csv-generic)"


# ---- CLI errors are exit 2 with a message, never a traceback ----

def _foreign_profile(tmp_path):
    """A profile file for acme.in that was hand-renamed to other.io.json."""
    data_dir = _store(tmp_path)
    src = Path(data_dir) / "projects" / "acme.in.json"
    (Path(data_dir) / "projects" / "other.io.json").write_text(src.read_text())
    return data_dir


@pytest.mark.parametrize("cmd", ["gap", "prospects", "kpis"])
def test_cli_mismatched_profile_and_empty_project_exit_2(tmp_path, capsys, cmd):
    data_dir = _foreign_profile(tmp_path)
    for project in ("other.io", ""):
        argv = [cmd, "--project", project, "--source", "csv-generic", "--no-sitemap",
                "--data-dir", data_dir]
        if cmd == "kpis":
            argv += ["--emit-kpis", str(tmp_path / "k.json")]
        assert lg.main(argv) == 2
        err = capsys.readouterr().err
        assert err.startswith("Error:") and "Traceback" not in err
