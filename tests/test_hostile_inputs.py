"""Hostile or malformed input must yield a finding, never a traceback (audit 2026-09-23).

Each case was reproduced by the post-release code audit against the scripts
added or changed on the v2.4.0 branch.

ZYRA port: the keywordseverywhere_api.py cases are omitted because that
upstream v2.3.1 backlinks fallback is not part of this fork.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("requests")
pytest.importorskip("bs4")
import agentic_check as ac  # noqa: E402
import lighthouse_agentic as la  # noqa: E402
import ucp_check  # noqa: E402

DEEP = "[" * 100000 + "]" * 100000


def _rec(status, text="", headers=None):
    return {"url": "u", "status": status, "headers": headers or {}, "text": text,
            "final_url": "https://e.test/", "error": None}


def test_deeply_nested_catalog_is_a_finding_not_a_crash():
    result = ac.validate_ai_catalog(DEEP)
    assert result["errors"]


def test_deeply_nested_well_known_document_is_a_finding(monkeypatch):
    monkeypatch.setattr(ac, "fetch", lambda url, headers=None: _rec(200, DEEP, {"content-type": "application/json"}))
    checks, _ = ac.audit_well_known("https://e.test")
    assert all(c["status"] == "fail" for c in checks)


def test_ucp_profile_hostile_shapes_do_not_crash():
    assert ucp_check.parse_profile(DEEP)["issues"]
    profile = {"ucp": {"version": "2026-08-25", "services": {"dev.ucp.shopping": [
        {"version": "2026-08-25", "transport": "rest", "endpoint": {"url": "x"}},
        {"version": "2026-08-25", "transport": "rest", "endpoint": "https://e.test/api"}]},
        "capabilities": {"dev.ucp.shopping.cart": [{"version": "v", "spec": "s", "schema": "s"}]}}}
    parsed = ucp_check.parse_profile(json.dumps(profile))
    assert "endpoint-not-a-string" in parsed["services"][0]["issues"]
    with patch.object(ucp_check, "safe_requests_get") as get, \
         patch.object(ucp_check, "validate_url_strict", return_value=("https://e.test/.well-known/ucp", "1.2.3.4")), \
         patch.object(ucp_check, "probe_endpoint", return_value={"url": "p"}):
        get.return_value.status_code = 200
        get.return_value.content = json.dumps(profile).encode()
        get.return_value.headers = {"Content-Type": "application/json"}
        report = ucp_check.audit_site("https://e.test", probe_endpoints=True)
    assert report["profile_present"]











@pytest.mark.parametrize("category", [
    {"auditRefs": None}, {"auditRefs": ["x", 3]}, ["not", "a", "dict"],
])
def test_lighthouse_malformed_category_shapes(category):
    report = la.summarize(la.extract_lhr({"categories": {"agentic-browsing": category},
                                          "audits": {}}), "file")
    assert isinstance(report, dict)


def test_robots_colon_only_line_ends_a_user_agent_block_in_both_tools():
    import agentic_fix as af
    robots = "User-agent: A\n: junk\nUser-agent: B\nDisallow: /\n"
    draft = af.add_content_signal(robots, "search=yes")["robots_txt"]
    groups = ac.parse_robots(draft)["groups"]
    assert all(g["content_signal"] for g in groups), draft


def test_robots_unicode_line_separator_inside_a_comment_stays_a_comment():
    import agentic_fix as af
    robots = "User-agent: *\n# note Disallow: /\nAllow: /\n"
    draft = af.add_content_signal(robots, "search=yes")["robots_txt"]
    assert " " in draft  # the comment is not split into a live rule
    parsed = ac.parse_robots(robots)
    assert ac.is_allowed(ac.select_group(parsed, "GPTBot")["rules"], "/")


# Found by a random-shape fuzz after the second verification pass.

def test_ard_non_string_type_is_an_error():
    catalog = {"specVersion": "1.0", "entries": [{"identifier": "urn:air:p:n", "displayName": "d",
                                                  "type": ["application/ai-catalog+json"], "url": "u"}]}
    assert "'type' must be a string" in " ".join(ac.validate_ai_catalog(json.dumps(catalog))["errors"])


def test_lighthouse_non_string_audit_id_is_ignored():
    lhr = {"categories": {"agentic-browsing": {"auditRefs": [{"id": ["x"]}, {"id": "y"}]}},
           "audits": {"y": {"scoreDisplayMode": "binary", "score": 1}}}
    assert la.calculate_fraction(la.extract_lhr(lhr))["display"] == "1/1"


def test_seeded_shape_fuzz_never_raises():
    """Random JSON shapes through every parser of site- or API-controlled data.

    A longer run of this fuzz (5 seeds x 3000 shapes) found two crash sites after
    both audit passes; this seeded slice keeps them from coming back.
    """
    import random

    rng = random.Random(20260923)
    keys = ["ucp", "version", "services", "capabilities", "transport", "endpoint", "spec",
            "schema", "categories", "agentic-browsing", "auditRefs", "audits", "id", "score",
            "scoreDisplayMode", "group", "details", "items", "value", "results", "error",
            "specVersion", "entries", "identifier", "displayName", "type", "url", "data",
            "representativeQueries", "trustManifest", "lighthouseResult", "collections"]

    def rnd(depth=0):
        roll = rng.random()
        if depth > 4 or roll < 0.3:
            return rng.choice([None, True, 0, 1.5, "x", "", [], {}, ["a"], {"k": [1]}])
        if roll < 0.6:
            return [rnd(depth + 1) for _ in range(rng.randint(0, 3))]
        return {rng.choice(keys): rnd(depth + 1) for _ in range(rng.randint(0, 4))}

    for _ in range(400):
        obj = rnd()
        for wrapped in (obj, {"ucp": obj}, {"specVersion": "1.0", "entries": [obj]},
                        {"categories": {"agentic-browsing": {"auditRefs": obj}}, "audits": {"a": obj}},
                        {"lighthouseResult": {"categories": {"agentic-browsing": obj}}}):
            raw = json.dumps(wrapped)
            ac.validate_ai_catalog(raw)
            ucp_check.parse_profile(raw)
            la.explain(la.extract_lhr(wrapped))
            la.summarize(la.extract_lhr(wrapped), "fuzz")
