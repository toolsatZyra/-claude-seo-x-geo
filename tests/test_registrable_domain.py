"""seo_store.registrable_domain: the organization-level key used for suppression and cooldown."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import seo_project  # noqa: E402
import seo_store  # noqa: E402


@pytest.mark.parametrize("host, expected", [
    ("example.org", "example.org"),
    ("blog.example.org", "example.org"),
    ("www2.news.example.org", "example.org"),
    ("https://www.Example.org/path", "example.org"),
    ("shop.globex.co.uk", "globex.co.uk"),
    ("globex.com.au", "globex.com.au"),
    ("iitb.ac.in", "iitb.ac.in"),
    ("localhost", "localhost"),
    ("", ""),
    # shared hosting: the tenant, not the platform, is the organization
    ("alice.blogspot.com", "alice.blogspot.com"),
    ("news.alice.blogspot.com", "alice.blogspot.com"),
    ("socialmediawidget.home.blog", "socialmediawidget.home.blog"),
    ("someone.github.io", "someone.github.io"),
])
def test_registrable_domain(host, expected):
    assert seo_store.registrable_domain(host) == expected


def test_same_organization_helper():
    assert seo_store.same_organization("blog.example.org", "example.org")
    assert not seo_store.same_organization("alice.blogspot.com", "bob.blogspot.com")
    assert not seo_store.same_organization("example.org", "example.com")
    assert not seo_store.same_organization("", "")


def test_registrable_label_still_agrees_on_country_suffixes():
    # seo_project shares the two-part suffix list with seo_store.
    assert seo_project.registrable_label("shop.globex.co.uk") == "globex"
    assert seo_store.registrable_domain("shop.globex.co.uk").split(".")[0] == "globex"
    assert seo_project._TWO_PART_SUFFIX_SLD is seo_store.TWO_PART_SUFFIX_SLD
