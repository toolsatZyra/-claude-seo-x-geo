"""
seo-links quality fixes found in the live Zyra and Probbit runs (2026-10-26).

1. row_cap_hit compared DataForSEO's total_count (all backlinks) with the
   referring domains returned (one per domain), so small sites that returned
   32 domains against a 1,000-row limit were reported as capped.
2. The link-network footprint rejected one-segment and short numeric paths,
   the commonest link-farm footprints (/directory-website-list-1410/,
   /all/166/7.html, /report/21009), so 15-65 farm domains reached the list.
3. Press-release wires, data brokers, AI statistics farms, site-stats pages,
   job boards, URL shorteners and IP/example hosts were ranked as prospects.
4. Trade press, L&D publications, company databases and podcast platforms
   fell through to "unclassified".

Every host and path below is taken from the live data. No network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import link_gap as lg  # noqa: E402
import link_sources as ls  # noqa: E402

CLIENT, COMPETITORS = "acme.in", ["rival.com", "other.in"]


def sig(domain, url=None, title=None, anchor=None, authority=None, spam=None, attrs=()):
    return {"domain": domain, "sample_url": url, "sample_title": title, "sample_anchor": anchor,
            "authority": authority, "spam_score": spam, "attributes": list(attrs),
            "tld": domain.rsplit(".", 1)[-1], "texts": [t for t in (title, url, anchor) if t],
            "quality": 0.5}


# --- 1. row cap ------------------------------------------------------------------------

def _dfs(items, total):
    return 200, {"status_code": 20000, "status_message": "Ok.", "cost": 0.025, "tasks": [{
        "status_code": 20000, "status_message": "Ok.", "cost": 0.025,
        "result": [{"target": "x.com", "total_count": total, "items_count": len(items),
                    "items": items}]}]}


def _items(n):
    return [{"domain_from": f"d{i}.com", "domain_from_rank": 100, "url_from": f"https://d{i}.com/a"}
            for i in range(n)]


def test_row_cap_is_rows_reaching_the_limit_not_the_backlink_total():
    # artificiallabs.in in the live run: 32 domains back, 1,000 asked for, many more backlinks
    got = ls.fetch_dataforseo("x.com", 1000, ("u", "p", "env"), post=lambda *a: _dfs(_items(32), 400))
    assert got["row_cap_hit"] is False
    capped = ls.fetch_dataforseo("x.com", 32, ("u", "p", "env"), post=lambda *a: _dfs(_items(32), 400))
    assert capped["row_cap_hit"] is True


# --- 2. link-network footprint ------------------------------------------------------------

@pytest.mark.parametrize("path", ["/directory-website-list-1410/", "/most-visited-website-list-1410/",
                                  "/directory-website-list-1410-online-success-907/", "/all/166/7.html",
                                  "/report/21009", "/website-list-2265/"])
def test_live_link_farm_paths_are_footprints(path):
    farm = [{"domain": f"farm{i}.com", "sample_url": f"https://farm{i}.com{path}", "sample_title": None}
            for i in range(6)]
    assert len(lg.link_network_domains({"rival.com": farm})) == 6


@pytest.mark.parametrize("path", ["/resources/", "/partners", "/links", "/blog/page/2", "/2024/05/",
                                  "/privacy-policy"])
def test_ordinary_pages_shared_by_many_sites_are_not_footprints(path):
    sites = [{"domain": f"site{i}.com", "sample_url": f"https://site{i}.com{path}", "sample_title": None}
             for i in range(8)]
    assert lg.link_network_domains({"rival.com": sites}) == {}


# --- 3. hosts that are never prospects -----------------------------------------------------

@pytest.mark.parametrize("domain, url, reason", [
    ("signalnewschicago.com", "https://signalnewschicago.com/press-releases/96583/commlab-india-ranks-2",
     "press_release_wire"),
    ("lifestyle.bombreport.com", "https://lifestyle.bombreport.com/story/354689/commlab-india-ranks",
     "press_release_wire"),
    ("globenewswire.com", "https://globenewswire.com/news-release/2022/07/18/2481152/0/en/x",
     "press_release_wire"),
    ("itnewsonline.com", "https://itnewsonline.com/PR.com/CommLab-India-Launches", "press_release_wire"),
    ("zoominfo.com", "https://zoominfo.com/c/commlab-india-llp/48287454", "data_broker"),
    ("leadiq.com", "https://leadiq.com/c/superside/5d80d972408f0cc3d90154dd/email-format", "data_broker"),
    ("contactout.com", "https://contactout.com/company/CommLab-India-14069", "data_broker"),
    ("worldmetrics.org", "https://worldmetrics.org/service/video-training/", "content_farm"),
    ("wifitalents.com", "https://wifitalents.com/service/learning-content/", "content_farm"),
    ("archivemarketresearch.com", "https://archivemarketresearch.com/reports/corporate-e-learning-1",
     "content_farm"),
    ("grokipedia.com", "https://grokipedia.com/page/Clip_art", "content_farm"),
    ("siteprice.org", "https://siteprice.org/competitors/charcount.com", "site_stats"),
    ("bye.fyi", "https://bye.fyi/report/21008", "site_stats"),
    ("domains.tntcode.com", "https://domains.tntcode.com/ip/166.62.28.79", "site_stats"),
    ("sitelike.org", "https://sitelike.org/similar/trainingindustry.com/", "site_stats"),
    ("bebee.com", "https://bebee.com/ar/jobs/ai-creative-director", "job_board"),
    ("internshala.com", "https://internshala.com/internship/detail/research-and-strategy", "job_board"),
    ("glassdoor.co.in", "https://glassdoor.co.in/Overview/Working-at-CommLab-India.htm", "job_board"),
    ("bit.ly", "https://bit.ly/MYSDhQ", "url_shortener"),
    ("shortenurls.eu", "https://shortenurls.eu/share/21009", "url_shortener"),
    ("212.52.6.47", "https://212.52.6.47/create-engaging-elearning", "invalid_host"),
    ("example3.com", "https://www.example3.com/keyword/corporate-training", "invalid_host"),
    ("steemit.com", "https://steemit.com/writing/@markrmorrisjr/a-checklist", "social_ugc"),
    ("groups.diigo.com", "https://groups.diigo.com/group/edumooc/content/tag/elearning", "social_ugc"),
    ("dev.to", "https://dev.to/chintanuxteam/boring-elearning-apps", "social_ugc"),
    ("articles.abilogic.com", "https://articles.abilogic.com/264457/reasons-why-you-should", "content_farm"),
    ("reportwire.org", "https://reportwire.org/8-popular-microlearning-assets", "content_farm"),
    ("imagetou.com", "https://imagetou.com/my-img-training-online-software-design.html", "content_farm"),
    ("callupcontact.com", "https://www.callupcontact.com/b/businessprofile/AGENCY09/704", "content_farm"),
])
def test_non_prospect_hosts_are_excluded_with_a_reason(domain, url, reason):
    assert lg.exclusion_reason(sig(domain, url), CLIENT, COMPETITORS) == reason


@pytest.mark.parametrize("domain, url", [
    ("trainingindustry.com", "https://trainingindustry.com/articles/learning-technologies/ai-framework/"),
    ("socialsamosa.com", "https://www.socialsamosa.com/indian-agency-feature/all-you-need-9198527"),
    ("techrseries.com", "https://techrseries.com/artificial-intelligence/commlab-india-and-lancaster"),
    ("businessnewsdaily.com", "https://businessnewsdaily.com/10000-training-videos.html"),
])
def test_genuine_editorial_sites_are_not_excluded(domain, url):
    assert lg.exclusion_reason(sig(domain, url), CLIENT, COMPETITORS) is None


# --- 4. known publications, company databases, podcasts -------------------------------------

@pytest.mark.parametrize("domain, url, kind", [
    ("socialsamosa.com", "https://www.socialsamosa.com/indian-agency-feature/all-you-need-9198527",
     "publication"),
    ("mediainfoline.com", "https://www.mediainfoline.com/agency/agency09-wins-mandate", "publication"),
    ("indianbroadcastingworld.com", "https://www.indianbroadcastingworld.com/siyarams-coming-home/",
     "publication"),
    ("trainingindustry.com", "https://trainingindustry.com/articles/learning-technologies/x/",
     "publication"),
    ("learningguild.com", "https://www.learningguild.com/articles/turbocharge-your-development",
     "publication"),
    ("brandonhall.com", "https://brandonhall.com/to-scale-learning-quickly-learn-the-4rs/", "publication"),
    ("elearning.adobe.com", "https://elearning.adobe.com/2024/02/7-mistakes-video-learning/",
     "publication"),
    ("yourstory.com", "https://yourstory.com/2025/06/ai-studio-raises-funding", "publication"),
    ("podcasts.apple.com", "https://podcasts.apple.com/us/podcast/the-elearning-champion-pod/id1753",
     "event"),
    ("theorg.com", "https://theorg.com/org/agency09", "directory"),
    ("growjo.com", "https://growjo.com/company/galleri5", "directory"),
    ("clodura.ai", "https://www.clodura.ai/directory/company/agency09", "directory"),
    ("yourstory.com", "https://yourstory.com/companies/galleri5", "directory"),
])
def test_known_hosts_get_their_type(domain, url, kind):
    assert lg.classify(sig(domain, url, authority=35.0))[0] == kind


def test_link_hosts_cli_reports_reason_and_type(capsys):
    import json
    import link_hosts
    assert link_hosts.main(["check", "signalnewsmiami.com", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"domain": "signalnewsmiami.com", "excluded": "press_release_wire", "known_type": None}
    assert link_hosts.main(["check", "trainingindustry.com", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["known_type"] == "publication"
