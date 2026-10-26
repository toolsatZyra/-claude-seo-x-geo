#!/usr/bin/env python3
"""
Host knowledge for the seo-links skill.

Two kinds of list, used by link_gap.py:

* Hosts that are never link prospects, each with the reason reported to the
  user: press-release wires, data brokers, content and statistics farms,
  site-statistics pages, job boards, URL shorteners, user-generated hosting,
  and IP-address or example hosts. Linking from these is either not earnable
  editorially, worthless, or paid.
* Well-known editorial and listing hosts that the generic classification rules
  miss: trade press and industry publications (advertising and marketing,
  learning and HR, business and tech), company databases, and podcast
  platforms.

The lists are deliberately short and editable: add a host to the matching
tuple when a live run shows a miss, with a test in tests/test_link_tool_quality.py.
Every list was seeded from the 2026-10-26 Zyra and Probbit runs.

Usage:
    python link_hosts.py check <domain> [<url>] [--json]   # category and type hint for one host
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Optional
from urllib.parse import urlparse

# --- never prospects -------------------------------------------------------------------

PRESS_RELEASE_WIRE_HOSTS = (
    "prnewswire.com", "businesswire.com", "globenewswire.com", "einpresswire.com", "newswire.com",
    "prweb.com", "openpr.com", "prlog.org", "releasewire.com", "issuewire.com", "pr.com",
    "24-7pressrelease.com", "accesswire.com", "itnewsonline.com", "theworldnewswire.com",
    "businesstimesjournal.com", "journalofbusinessnews.com", "newsblaze.com", "pressreleasepoint.com",
)
PRESS_RELEASE_HOST_RE = re.compile(r"^signalnews[a-z]+\.com$")  # one wire's dozens of city sites
PRESS_RELEASE_PATH_RE = re.compile(r"/(?:press-releases?|news-releases?)(?:/|$)")
SYNDICATED_STORY_RE = re.compile(r"^/story/\d+/")  # with a "lifestyle." host: wire syndication

DATA_BROKER_HOSTS = (
    "zoominfo.com", "leadiq.com", "lusha.com", "contactout.com", "datanyze.com", "prospeo.io",
    "rocketreach.co", "apollo.io", "signalhire.com", "findmassleads.com", "seamless.ai",
    "lead411.com", "adapt.io", "aeroleads.com", "getemail.io", "kaspr.io", "salesintel.io",
)
CONTENT_FARM_HOSTS = (
    "worldmetrics.org", "wifitalents.com", "zipdo.co", "gitnux.org", "archivemarketresearch.com",
    "datainsightsmarket.com", "marketreportanalytics.com", "promarketreports.com",
    "grokipedia.com", "wikiwand.com", "sweetstudy.com",
    # article directories, scraped-news aggregators and fake business directories
    "abilogic.com", "reportwire.org", "imagetou.com", "callupcontact.com",
)
SITE_STATS_HOSTS = (
    "siteprice.org", "sitelike.org", "similarsites.com", "hypestat.com", "websiteoutlook.com",
    "statshow.com", "siteindices.com", "webrankstats.com", "reviewbolt.com", "tntcode.com",
    "drjack.world", "anchorurl.cloud", "bye.fyi", "screenshots.wiki", "ready.pro", "prlog.ru",
    "webranksite.com", "siteslike.com", "sitesimilar.net",
)
# /report/21009, /ip/166.62.28.79, /competitors/charcount.com, /similar/trainingindustry.com/
SITE_STATS_PATH_RE = re.compile(r"^/(?:report|share|stats|ip|analysis|competitors|similar|whois|"
                                r"site|domain|website)/(?:[0-9.]+|[a-z0-9-]+(?:\.[a-z0-9-]+)+)/?$")
JOB_BOARD_HOSTS = (
    "bebee.com", "remoteok.com", "internshala.com", "glassdoor.com", "glassdoor.co.in", "indeed.com",
    "naukri.com", "foundit.in", "monster.com", "ziprecruiter.com", "iimjobs.com", "instahyre.com",
    "cutshort.io", "weekday.works", "hirist.tech", "apna.co",
)
URL_SHORTENER_HOSTS = (
    "bit.ly", "tinyurl.com", "shorturl.at", "rebrand.ly", "cutt.ly", "ow.ly", "buff.ly", "is.gd",
    "s.id", "shortenurls.eu", "urls-shortener.eu", "t.ly",
)
UGC_HOSTING_HOSTS = (
    "steemit.com", "scoop.it", "about.me", "issuu.com", "slideshare.net", "diigo.com",
    "blogger.com", "tumblr.com", "sites.google.com", "notion.site", "dev.to",
)

# --- known editorial and listing hosts --------------------------------------------------

PUBLICATION_HOSTS = (
    # advertising and marketing trade press (India, then global)
    "socialsamosa.com", "exchange4media.com", "afaqs.com", "campaignindia.in", "bestmediainfo.com",
    "mediainfoline.com", "indiantelevision.com", "medianews4u.com", "storyboard18.com", "adgully.com",
    "passionateinmarketing.com", "indianbroadcastingworld.com", "brandinginasia.com", "mediabrief.com",
    "buzzincontent.com", "agencyreporter.com", "impactonnet.com", "lbbonline.com", "campaignasia.com",
    "thedrum.com", "adage.com", "adweek.com", "campaignlive.co.uk", "marketingweek.com",
    # learning, training and HR
    "trainingindustry.com", "learningguild.com", "trainingjournal.com", "trainingzone.co.uk",
    "trainingmag.com", "elearningindustry.com", "edtechreview.in", "chieflearningofficer.com",
    "brandonhall.com", "learningnews.com", "td.org", "elearning.adobe.com", "elearninginfographics.com",
    "hrkatha.com", "peoplematters.in", "hrexecutive.com", "techrseries.com", "learninglight.com",
    "checkpoint-elearning.com", "checkpoint-elearning.de", "hcamag.com", "shrm.org",
    # business and tech press (India, then global)
    "yourstory.com", "inc42.com", "entrackr.com", "vccircle.com", "livemint.com",
    "business-standard.com", "forbesindia.com", "analyticsindiamag.com", "theprint.in",
    "moneycontrol.com", "financialexpress.com", "thehindubusinessline.com", "techcrunch.com",
    "venturebeat.com",
)
COMPANY_DATABASE_HOSTS = (
    "theorg.com", "growjo.com", "craft.co", "webcatalog.io", "clodura.ai", "edgeinsights.in",
    "techbehemoths.com", "f6s.com", "tofler.in", "provenexpert.com",
)
PODCAST_HOSTS = (
    "podcasts.apple.com", "open.spotify.com", "podcasters.spotify.com", "podbean.com", "buzzsprout.com",
    "anchor.fm", "iheart.com", "castbox.fm", "podchaser.com", "listennotes.com",
)

IP_HOST_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
EXAMPLE_LABEL_RE = re.compile(r"^example\d*$")


def host_in(domain: str, hosts) -> bool:
    """True when ``domain`` is one of ``hosts`` or a subdomain of one."""
    return any(domain == h or domain.endswith("." + h) for h in hosts)


def _path(url: Optional[str]) -> str:
    try:
        return urlparse((url or "").lower()).path
    except ValueError:
        return ""


def excluded_category(domain: str, url: Optional[str] = None) -> Optional[str]:
    """The never-a-prospect reason for a host (and its sample URL), or None.

    Reasons: invalid_host, url_shortener, press_release_wire, data_broker, content_farm,
    site_stats, job_board, social_ugc.
    """
    dom = (domain or "").lower().strip(".")
    path = _path(url)
    labels = dom.split(".")
    if IP_HOST_RE.match(dom) or ":" in dom or (len(labels) >= 2 and EXAMPLE_LABEL_RE.match(labels[-2])):
        return "invalid_host"
    if host_in(dom, URL_SHORTENER_HOSTS):
        return "url_shortener"
    if (host_in(dom, PRESS_RELEASE_WIRE_HOSTS) or PRESS_RELEASE_HOST_RE.match(".".join(labels[-2:]))
            or PRESS_RELEASE_PATH_RE.search(path)
            or (labels[0] == "lifestyle" and SYNDICATED_STORY_RE.match(path))):
        return "press_release_wire"
    if host_in(dom, DATA_BROKER_HOSTS):
        return "data_broker"
    if host_in(dom, CONTENT_FARM_HOSTS):
        return "content_farm"
    if host_in(dom, SITE_STATS_HOSTS) or SITE_STATS_PATH_RE.match(path):
        return "site_stats"
    if host_in(dom, JOB_BOARD_HOSTS):
        return "job_board"
    if host_in(dom, UGC_HOSTING_HOSTS):
        return "social_ugc"
    return None


def known_type(domain: str) -> Optional[str]:
    """A type hint for a well-known host: publication, directory or event (podcast), or None."""
    dom = (domain or "").lower().strip(".")
    if host_in(dom, COMPANY_DATABASE_HOSTS):
        return "directory"
    if host_in(dom, PODCAST_HOSTS):
        return "event"
    if host_in(dom, PUBLICATION_HOSTS):
        return "publication"
    return None


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Check how seo-links treats a referring host")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="Exclusion reason and type hint for one host")
    c.add_argument("domain")
    c.add_argument("url", nargs="?", default=None, help="A sample linking URL on that host")
    c.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args(argv)
    result = {"domain": args.domain, "excluded": excluded_category(args.domain, args.url),
              "known_type": known_type(args.domain)}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['domain']}: excluded={result['excluded']} known_type={result['known_type']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
