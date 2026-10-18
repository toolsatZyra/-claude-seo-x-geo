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


# ---- exclusions found by the live run (staging hosts, UGC portfolios, link-selling networks) ----

EXCLUDE = ("acme.in", ["rival.com", "other.in"])


@pytest.mark.parametrize("domain", [
    "agilityprstage.wpengine.com", "env-userp-newstaging.kinsta.cloud", "site.netlify.app",
    "site.vercel.app", "app.herokuapp.com", "site.pages.dev", "lightgreen-squid-731429.hostingersite.com",
    "staging.worklife.news", "stage.client.org", "dev.client.org", "dev2.client.org",
    "test.client.org", "uat.bank.in", "preview.client.io", "acme-staging.com", "new-stage-site.com",
])
def test_staging_and_dev_hosts_are_excluded(domain):
    assert lg.exclusion_reason(sig(domain, f"https://{domain}/post"), *EXCLUDE) == "staging_or_dev_host"


@pytest.mark.parametrize("domain", [
    "dev.to", "devops.com", "stage.com", "backstage.io", "testimonial.com", "latest.com",
    "blog.client.org", "developer.client.org", "stagecoach.co.uk",
])
def test_ordinary_hosts_that_only_look_like_staging_are_kept(domain):
    assert lg.exclusion_reason(sig(domain, f"https://{domain}/post"), *EXCLUDE) is None


@pytest.mark.parametrize("domain", ["behance.net", "dribbble.com"])
def test_portfolio_and_job_platforms_are_social_ugc(domain):
    assert lg.exclusion_reason(sig(domain, f"https://www.{domain}/joblist/1"), *EXCLUDE) == "social_ugc"


@pytest.mark.parametrize("url, title, anchor", [
    ("https://x.net/dir/website-ranking-links-78674", "Premium SEO Links for Websites", None),
    ("https://x.net/tg-seo-linkk-order-seo-backlinks-homepage-links-4", None, None),
    ("https://x.net/quarterlinks-dofollow-article-links-just-for-25", None, None),
    ("https://x.net/employer/high-quality-backlinks-158", None, None),
    ("https://x.net/a", "Buy Links from real sites", None),
    ("https://x.net/a", "Our link building services", None),
    ("https://x.net/a", "Guest post service: publish on 50 blogs", None),
    ("https://x.net/a", None, "Expert SEO Backlink Services galleri5.com"),
    ("https://x.net/a", None, "SEO links"),
    ("https://x.net/a", "Cheap DoFollow placements", None),
    ("https://x.net/advertorial-rates", None, None),
])
def test_link_scheme_tokens_are_excluded(url, title, anchor):
    s = sig("x.net", url, title=title, anchor=anchor)
    assert lg.exclusion_reason(s, *EXCLUDE) == "paid_or_scheme"


@pytest.mark.parametrize("url, title", [
    ("https://good.org/write-for-us", "Write for us"),
    ("https://good.org/blog/why-content-marketing-works", "Why content marketing works"),
    ("https://good.org/unsponsored-reviews", "Honest reviews"),  # "sponsored" only as a whole word
    ("https://good.org/our-links-page", "Our links page"),
])
def test_ordinary_pages_are_not_scheme_signals(url, title):
    assert lg.exclusion_reason(sig("good.org", url, title=title), *EXCLUDE) is None


def _farm(n, path="/dir/website-ranking-links-78674", title="Premium SEO Links for Websites Order Now"):
    return [{"domain": f"farm{i}.com", "sample_url": f"https://farm{i}.com{path}",
             "sample_title": title} for i in range(n)]


def test_footprint_rule_flags_five_or_more_domains_sharing_a_path_or_a_title():
    flagged = lg.link_network_domains({"rival.com": _farm(5)})
    assert set(flagged) == {f"farm{i}.com" for i in range(5)}
    assert lg.link_network_domains({"rival.com": _farm(4)}) == {}
    by_title = [{"domain": f"t{i}.com", "sample_url": f"https://t{i}.com/page-{i}-unique-slug",
                 "sample_title": "Premium SEO Links for Websites Order Now"} for i in range(5)]
    assert set(lg.link_network_domains({"rival.com": by_title})) == {f"t{i}.com" for i in range(5)}


def test_footprint_rule_is_per_snapshot_and_ignores_generic_pages():
    # 3 domains in one competitor's snapshot + 3 in another's: no snapshot reaches 5
    split = {"rival.com": _farm(3), "other.in": [{**r, "domain": r["domain"].replace("farm", "farmb")}
                                                  for r in _farm(3)]}
    assert lg.link_network_domains(split) == {}
    generic = ([{"domain": f"g{i}.com", "sample_url": f"https://g{i}.com/privacy-policy",
                 "sample_title": "Privacy Policy"} for i in range(8)]
               + [{"domain": f"w{i}.com", "sample_url": f"https://w{i}.com/en/privacy-policy",
                   "sample_title": "Just another WordPress site"} for i in range(8)]
               + [{"domain": f"h{i}.com", "sample_url": f"https://h{i}.com/",
                   "sample_title": "Home"} for i in range(8)])
    assert lg.link_network_domains({"rival.com": generic}) == {}


def test_analyze_drops_a_link_farm_and_reports_it_by_reason(tmp_path):
    data_dir = _store(tmp_path)
    conn = link_store.open_store(data_dir)
    neutral_farm = _farm(6, path="/dir/curated-pages-78674", title="Curated Website Hub Online Now")
    link_store.save_snapshot(conn, "acme.in", "rival.com", "csv-farm", neutral_farm
                             + [{"domain": "trainingmag.com", "authority": 80.0, "dofollow": True,
                                 "sample_url": "https://trainingmag.com/2025/03/best-training-video-studios/",
                                 "tld": "com"}])
    link_store.save_snapshot(conn, "acme.in", "acme.in", "csv-farm", [{"domain": "partner.in"}])
    out = lg.analyze_project("acme.in", "csv-farm", data_dir, use_sitemap=False)
    assert [p["domain"] for p in out["prospects"]] == ["trainingmag.com"]
    assert out["excluded_counts"] == {"link_network": 6}
    assert {e["reason"] for e in out["excluded"]} == {"link_network"}
    assert "curated-pages-78674" in out["excluded"][0]["detail"]


# ---- classification: first path segment, profile pages and hosts, no title tokens ----

LIVE_CLASSIFICATION = [
    # the 12 live quick wins that were wrong, as the review recorded them
    ("webnode.com", "https://webnode.com/blog/social-media-integration/",
     "Social Media Integration: Boost Your Website Success", "blog"),
    ("techwyse.com", "https://www.techwyse.com/blog/social-media-marketing/detecting-social-media-scams-how-"
     "marketers-can-protect-their-brands-and-customers", "Detecting Social Media Scams | TechWyse", "blog"),
    ("kingnewswire.com", "https://kingnewswire.com/gold-coast-city-lifestyle-magazine-welcomes-annette-patko-"
     "of-bordeaux-studio-as-featured-photographer-creative-partner-25071730823/",
     "Gold Coast City Lifestyle Magazine Welcomes Annette Patko - King Newswire", "publication"),
    ("teamwork.com", "https://www.teamwork.com/blog/kpis-content-marketing/",
     "12 content marketing KPIs agencies track | Teamwork.com", "blog"),
    ("planable.io", "https://planable.io/blog/social-media-management-tools-for-agencies/?ref=x.blog",
     "12 social media management tools for agencies in 2026", "blog"),
    ("learn.g2.com", "https://learn.g2.com/building-a-brand", "Building a Brand: The 7 Essential Steps", "blog"),
    ("sortlist.com", "https://www.sortlist.com/blog/importance-of-graphic-design/",
     "The Importance of Graphic Design", "blog"),
    ("antillesdigitalmedia.com", "https://antillesdigitalmedia.com/how-to-choose-brand-colors-that-convert/",
     "How To Choose Brand Colors | Antilles Digital Media", "unclassified"),
    ("socialmediawidget.home.blog", "https://socialmediawidget.home.blog/2025/08/01/best-ai-instagram-ads-generators/",
     "10 Best AI Instagram Ads Generators in 2025", "unclassified"),
    # the real gap domains: profile and listing pages
    ("cbinsights.com", "https://www.cbinsights.com/company/galleri5", "galleri5 - Products, Competitors", "directory"),
    ("uplers.com", "https://www.uplers.com/company/galleri5-9507", "Galleri5 Jobs & Careers", "directory"),
    ("golden.com", "https://golden.com/wiki/galleri5-NMMMND9", "galleri5 | Golden", "directory"),
    ("webcatalog.io", "https://webcatalog.io/id/apps/galleri5", "WebCatalog", "directory"),
    ("webcatalog.io", "https://webcatalog.io/en/apps/superside", "Superside - Desktop App", "directory"),
    ("yourstory.com", "https://yourstory.com/companies/galleri5", "galleri5 Company Profile", "directory"),
    ("crunchbase.com", "https://www.crunchbase.com/organization/galleri5", "galleri5 - Crunchbase", "directory"),
    ("oncely.com", "https://oncely.com/products/galleri5-discount", "Galleri5 Discount | Oncely", "unclassified"),
]


@pytest.mark.parametrize("domain, url, title, expected", LIVE_CLASSIFICATION)
def test_live_urls_classify_correctly(domain, url, title, expected):
    kind, _ = lg.classify(sig(domain, url, title=title))
    assert kind == expected


@pytest.mark.parametrize("url, title, expected", [
    ("https://x.org/profile/acme", None, "directory"),
    ("https://x.org/organizations/acme", None, "directory"),
    ("https://x.org/startups/acme", None, "directory"),
    ("https://x.org/en/resources/compliance", None, "resource"),
    ("https://x.org/useful-links", None, "resource"),
    ("https://x.org/recommended-tools", None, "resource"),
    ("https://x.org/links", None, "resource"),
    ("https://x.org/our-partners", None, "partner"),
    ("https://x.org/integrations", None, "partner"),
    ("https://x.org/podcast/episode-9", None, "event"),
    ("https://x.org/members/directory", None, "unclassified"),  # a token must be the first segment
    ("https://x.org/useful-tips", None, "unclassified"),         # "useful" alone is not a resource page
    ("https://x.org/blog/social-media-integration/", None, "blog"),
    ("https://x.org/blog/building-a-community", None, "blog"),
    ("https://x.org/how-to-pick-an-integration-partner-for-your-business", None, "unclassified"),  # long slug
    ("https://x.org/a", "Top 10 Video Production Companies in India", "directory"),
    ("https://x.org/a", "Top 10 tools for agencies", "unclassified"),
    ("https://x.org/a", "How agencies and companies pick vendors", "unclassified"),
    ("https://x.org/blog/top-10-ai-video-companies", None, "directory"),
    ("https://x.org/blog/top-10-tools-for-agencies", None, "blog"),
])
def test_first_segment_and_title_rules(url, title, expected):
    kind, _ = lg.classify(sig("x.org", url, title=title))
    assert kind == expected


@pytest.mark.parametrize("domain, kind", [
    ("dealroom.co", "directory"), ("wellfound.com", "directory"), ("tracxn.com", "directory"),
    ("owler.com", "directory"), ("zaubacorp.com", "directory"), ("cbinsights.com", "directory"),
    ("golden.com", "directory"),
])
def test_profile_hosts_are_directories(domain, kind):
    assert lg.classify(sig(domain, f"https://{domain}/x"))[0] == kind


def test_directory_host_blog_and_learn_pages_are_editorial():
    assert lg.classify(sig("g2.com", "https://www.g2.com/blog/best-tools"))[0] == "blog"
    assert lg.classify(sig("learn.g2.com", "https://learn.g2.com/x"))[0] == "blog"
    assert lg.classify(sig("g2.com", "https://www.g2.com/categories/video"))[0] == "directory"


def test_publication_domain_match_uses_label_boundaries():
    assert lg.classify(sig("hindustantimes.com", "https://hindustantimes.com/x"))[0] == "publication"
    assert lg.classify(sig("my-media.com", "https://my-media.com/x"))[0] == "publication"
    assert lg.classify(sig("antillesdigitalmedia.com", "https://antillesdigitalmedia.com/x"))[0] != "publication"
    assert lg.classify(sig("socialmediawidget.com", "https://socialmediawidget.com/x"))[0] != "publication"


def test_footprint_counts_distinct_organizations_not_country_domains():
    # Glassdoor serves the same company page on nine country domains: one organization.
    path = "/overview/working-at-superside-ei_ie1397130.11,20.htm"
    one_org = [{"domain": d, "sample_url": f"https://www.{d}{path}", "sample_title": "Working at Superside"}
               for d in ("glassdoor.ca", "glassdoor.co.in", "glassdoor.co.nz", "glassdoor.co.uk",
                         "glassdoor.com", "glassdoor.com.au", "glassdoor.com.hk", "glassdoor.ie",
                         "glassdoor.sg")]
    assert lg.link_network_domains({"superside.com": one_org}) == {}
    assert len(lg.link_network_domains({"superside.com": _farm(5)})) == 5
