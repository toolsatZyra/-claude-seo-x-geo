"""Tests for scripts/aeo_score.py: the one AEO Readiness Score + crawler access.

Offline: robots.txt fetches go through a monkeypatched
url_safety.safe_requests_get; KPI envelopes are written under tmp_path.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import aeo_score  # noqa: E402
import url_safety  # noqa: E402

FULL = {"citability": 62, "brand_authority": 40, "content_eeat": 71,
        "crawler_access": 78, "schema": 55, "platform": 48}


# ---------------------------------------------------------------------------
# compute
# ---------------------------------------------------------------------------

def _eval_expression(expr: str):
    """Evaluate exactly as a reader would: python3 -c "print(<expression>)"."""
    out = subprocess.run([sys.executable, "-c", f"print({expr})"], capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def test_weights_match_geo_seo_claude_composite():
    assert aeo_score.WEIGHTS == {"citability": 25, "brand_authority": 20, "content_eeat": 20,
                                 "crawler_access": 15, "schema": 10, "platform": 10}
    assert sum(aeo_score.WEIGHTS.values()) == 100


def test_full_score_expression_reproduces_score():
    res = aeo_score.compute_aeo_score(FULL)
    expected = round((62 * 25 + 40 * 20 + 71 * 20 + 78 * 15 + 55 * 10 + 48 * 10) / 100)
    assert res["score"] == expected == 60
    assert res["rating"] == "Fair"
    assert res["completeness"] == 1.0
    assert _eval_expression(res["expression"]) == res["score"]
    assert abs(sum(res["weights_used"].values()) - 1) < 1e-9
    assert res["warnings"] == []


def test_missing_components_renormalize_and_report_completeness():
    res = aeo_score.compute_aeo_score({"citability": 62.3, "crawler_access": 78, "schema": None})
    assert res["score"] == round((62.3 * 25 + 78 * 15) / 40)
    assert res["completeness"] == 0.4
    assert res["components"]["schema"]["value"] is None
    assert "N/A" in res["components"]["brand_authority"]["status"]
    assert res["weights_used"] == {"citability": 0.625, "crawler_access": 0.375}
    assert res["component_set"] == ["citability", "crawler_access"]
    assert any("completeness" in w for w in res["warnings"])
    assert _eval_expression(res["expression"]) == res["score"]


def test_expression_always_matches_score():
    rng = random.Random(1234)
    for _ in range(150):
        comps = {}
        for name in aeo_score.WEIGHTS:
            roll = rng.random()
            if roll < 0.2:
                continue
            comps[name] = rng.choice([rng.randint(0, 100), round(rng.uniform(0, 100), rng.randint(1, 3))])
        res = aeo_score.compute_aeo_score(comps)
        if res["score"] is None:
            assert not comps
            continue
        assert eval(res["expression"], {"__builtins__": {"round": round}}) == res["score"]


@pytest.mark.parametrize("score,label", [(100, "Excellent"), (90, "Excellent"), (89, "Good"),
                                         (75, "Good"), (74, "Fair"), (60, "Fair"), (59, "Poor"),
                                         (40, "Poor"), (39, "Critical"), (0, "Critical")])
def test_rating_bands(score, label):
    assert aeo_score.rating_for(score) == label


@pytest.mark.parametrize("bad", [
    {"citability": 101}, {"citability": -1}, {"citability": True}, {"citability": "70"},
    {"citability": float("nan")}, {"geo_health": 50}, {"schema": {"nope": 1}},
])
def test_invalid_components_are_rejected(bad):
    with pytest.raises(ValueError):
        aeo_score.compute_aeo_score(bad)


def test_component_objects_pass_through():
    res = aeo_score.compute_aeo_score({"citability": {"average_citability_score": 70.5},
                                       "crawler_access": {"score": 80}})
    assert res["components"]["citability"]["value"] == 70.5
    assert res["components"]["crawler_access"]["value"] == 80


def test_no_components_is_not_measured(capsys):
    res = aeo_score.compute_aeo_score({})
    assert res["score"] is None and res["expression"] is None and res["completeness"] == 0.0
    assert aeo_score.main(["compute", "--json"]) == 1


def test_compute_cli_input_file_flags_override_and_kpis(tmp_path, capsys):
    comp = tmp_path / "components.json"
    comp.write_text(json.dumps({"components": {"citability": 10, "schema": 55}}))
    out = tmp_path / "kpis.json"
    rc = aeo_score.main(["compute", "--input", str(comp), "--citability", "62", "--project",
                         "https://www.Example.com/", "--date", "2026-10-17", "--emit-kpis", str(out), "--json"])
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["components"]["citability"]["value"] == 62
    assert printed["data_sources"] and printed["limitations"]
    env = json.loads(out.read_text())
    assert env["project"] == "example.com" and env["date"] == "2026-10-17" and env["source"] == "aeo_score.py"
    assert env["metrics"]["aeo.score"] == printed["score"]
    assert env["metrics"]["aeo.citability"] == 62 and env["metrics"]["aeo.brand_authority"] is None
    assert set(env["metrics"]) == {"aeo.score", "aeo.citability", "aeo.brand_authority", "aeo.content_eeat",
                                   "aeo.crawler_access", "aeo.schema", "aeo.platform"}
    tracker = pytest.importorskip("performance_tracker")
    validate = getattr(tracker, "validate_envelope", None)
    if validate is None:
        pytest.skip("performance_tracker.validate_envelope not available")
    result = validate(env)
    assert result["ok"], result["errors"]
    assert not result["warnings"], result["warnings"]


def test_compute_cli_errors():
    assert aeo_score.main(["compute", "--citability", "150"]) == 2
    assert aeo_score.main(["compute", "--citability", "50", "--emit-kpis", "x.json"]) == 2


# ---------------------------------------------------------------------------
# robots.txt evaluation (RFC 9309)
# ---------------------------------------------------------------------------

def _analyze(text, paths=None):
    return aeo_score.analyze_robots(text, 200, paths)


def _status(result, agent):
    for row in result["answer_surface"] + result["training"]:
        if row["agent"] == agent:
            return row["status"]
    raise KeyError(agent)


def test_blocking_training_crawlers_does_not_cost_points():
    text = """User-agent: GPTBot
User-agent: ClaudeBot
User-agent: Google-Extended
User-agent: Applebot-Extended
User-agent: CCBot
Disallow: /

User-agent: *
Allow: /
"""
    res = _analyze(text)
    assert res["score"] == 100 and res["allowed"] == res["total"] == 9
    for agent in ("GPTBot", "ClaudeBot", "Google-Extended", "Applebot-Extended", "CCBot"):
        assert _status(res, agent) == "blocked"
    assert _status(res, "OAI-SearchBot") == "allowed"
    assert eval(res["expression"]) == res["score"]


def test_answer_surface_blocks_reduce_score_with_quoted_evidence():
    text = """# comment line
Disallow: /ignored-before-any-group
User-agent: OAI-SearchBot
User-agent: Claude-SearchBot  # trailing comment
Disallow: /

User-agent: *
Disallow:
"""
    res = _analyze(text)
    assert _status(res, "OAI-SearchBot") == "blocked"
    assert _status(res, "Claude-SearchBot") == "blocked"
    assert _status(res, "PerplexityBot") == "allowed"     # empty Disallow allows everything
    row = next(r for r in res["answer_surface"] if r["agent"] == "OAI-SearchBot")
    assert row["evidence"] == "line 5: Disallow: /" and row["matched_group"] == "oai-searchbot"
    assert res["score"] == round(100 * 7 / 9)
    assert res["expression"] == "round(100 * 7 / 9)"


def test_specific_group_replaces_star_group_entirely():
    text = """User-agent: *
Disallow: /

User-agent: Googlebot
Disallow: /private/
"""
    res = _analyze(text)
    assert _status(res, "Googlebot") == "allowed"
    assert _status(res, "Bingbot") == "blocked"
    assert _status(res, "Applebot") == "allowed"     # Applebot follows Googlebot rules when unnamed


def test_applebot_own_group_beats_googlebot_fallback():
    text = "User-agent: Googlebot\nAllow: /\n\nUser-agent: Applebot\nDisallow: /\n"
    assert _status(_analyze(text), "Applebot") == "blocked"


def test_longest_match_wildcards_anchor_and_allow_tie():
    text = """User-agent: Bingbot
Disallow: /
Allow: /$
Allow: /blog/
Disallow: /blog/*.pdf$
Disallow: /tie
Allow: /tie
"""
    groups, _ = aeo_score._select_groups(aeo_score.parse_robots(text), ("bingbot",))
    ev = aeo_score.evaluate_path
    assert ev(groups, "/")["allowed"] is True
    assert ev(groups, "/pricing")["allowed"] is False
    assert ev(groups, "/blog/post")["allowed"] is True
    assert ev(groups, "/blog/file.pdf")["allowed"] is False
    assert ev(groups, "/blog/file.pdf?x=1")["allowed"] is True
    assert ev(groups, "/tie")["allowed"] is True
    res = _analyze(text, ["/", "/pricing"])
    assert _status(res, "Bingbot") == "partial"
    assert res["paths"] == ["/", "/pricing"]


def test_duplicate_groups_for_one_agent_are_combined():
    text = "User-agent: PerplexityBot\nDisallow: /a\n\nUser-agent: perplexitybot\nDisallow: /\n"
    assert _status(_analyze(text), "PerplexityBot") == "blocked"


def test_user_agent_product_token_and_case():
    text = "User-agent: GOOGLEBOT/2.1 (+http://www.google.com/bot.html)\nDisallow: /\n"
    assert _status(_analyze(text), "Googlebot") == "blocked"


def test_content_signal_and_undocumented_tokens_are_reported_not_scored():
    text = """User-agent: *
Content-Signal: search=yes, ai-input=yes, ai-train=no
Allow: /

User-agent: anthropic-ai
Disallow: /
"""
    res = _analyze(text)
    assert res["score"] == 100
    assert res["content_signals"][0]["parsed"] == {"search": "yes", "ai-input": "yes", "ai-train": "no"}
    assert [u["token"] for u in res["undocumented_tokens"]] == ["anthropic-ai"]


def test_user_triggered_agents_get_a_robots_caveat():
    res = _analyze("User-agent: Perplexity-User\nDisallow: /\n")
    assert _status(res, "Perplexity-User") == "blocked"
    assert any("Perplexity-User" in n and "may not obey" in n for n in res["notes"])


# Ported from zubair-trabzada/geo-seo-claude tests/test_fetch_robots_cloudflare.py (MIT).
CLOUDFLARE_MANAGED_ROBOTS = """# BEGIN Cloudflare Managed content

User-agent: GPTBot
Disallow: /

User-agent: ClaudeBot
Disallow: /

User-agent: Google-Extended
Disallow: /

# END Cloudflare Managed Content

User-agent: *
Allow: /

Sitemap: https://example.com/sitemap.xml
"""

PLAIN_ROBOTS = """User-agent: *
Allow: /

Sitemap: https://example.com/sitemap.xml
"""


class _FakeResponse:
    def __init__(self, status_code=200, body=b"", content_type="text/plain"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        self.closed = True


def _patch_get(monkeypatch, response=None, exc=None):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        if exc is not None:
            raise exc
        return response

    monkeypatch.setattr(url_safety, "safe_requests_get", fake_get)
    return calls


class TestCloudflareManagedRobots:
    def test_detects_cloudflare_managed_block(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(body=CLOUDFLARE_MANAGED_ROBOTS.encode()))
        result = aeo_score.check_crawlers("https://example.com/")
        assert result["cloudflare_managed"] is True
        assert _status(result, "GPTBot") == "blocked"
        assert _status(result, "ClaudeBot") == "blocked"
        assert set(result["cloudflare_injected_agents"]) == {"GPTBot", "ClaudeBot", "Google-Extended"}
        assert result["score"] == 100          # only training crawlers were blocked
        assert any("Cloudflare managed robots.txt" in n for n in result["notes"])

    def test_plain_robots_is_not_flagged(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(body=PLAIN_ROBOTS.encode()))
        result = aeo_score.check_crawlers("https://example.com/")
        assert result["cloudflare_managed"] is False
        assert result["sitemaps"] == ["https://example.com/sitemap.xml"]

    def test_missing_robots_is_not_flagged(self, monkeypatch):
        _patch_get(monkeypatch, _FakeResponse(status_code=404))
        result = aeo_score.check_crawlers("https://example.com/")
        assert result["cloudflare_managed"] is False


def test_fetch_goes_through_url_safety_at_the_robots_path(monkeypatch):
    calls = _patch_get(monkeypatch, _FakeResponse(body=PLAIN_ROBOTS.encode()))
    aeo_score.check_crawlers("example.com/some/page?x=1")
    assert calls[0][0] == "https://example.com/robots.txt"
    assert calls[0][1]["stream"] is True


@pytest.mark.parametrize("status", [404, 410, 401, 403])
def test_4xx_means_everything_allowed(monkeypatch, status):
    _patch_get(monkeypatch, _FakeResponse(status_code=status))
    result = aeo_score.check_crawlers("https://example.com")
    assert result["robots_status"] == "missing" and result["score"] == 100


@pytest.mark.parametrize("status", [500, 503, 429])
def test_5xx_and_429_are_not_measured_never_zero(monkeypatch, status):
    _patch_get(monkeypatch, _FakeResponse(status_code=status))
    result = aeo_score.check_crawlers("https://example.com")
    assert result["robots_status"] == "unavailable"
    assert result["score"] is None and result["expression"] is None
    assert "NOT MEASURED" in result["notes"][0]


@pytest.mark.parametrize("exc", [url_safety.URLSafetyError("private address"),
                                 requests.ConnectionError("down"), requests.Timeout("slow")])
def test_fetch_failures_are_not_measured(monkeypatch, exc):
    _patch_get(monkeypatch, exc=exc)
    result = aeo_score.check_crawlers("https://example.com")
    assert result["score"] is None and result["http_status"] is None


def test_oversize_robots_is_truncated_at_500_kib(monkeypatch):
    filler = ("# " + "x" * 98 + "\n") * (aeo_score.MAX_ROBOTS_BYTES // 100 + 10)
    body = ("User-agent: *\nAllow: /\n" + filler + "User-agent: OAI-SearchBot\nDisallow: /\n").encode()
    _patch_get(monkeypatch, _FakeResponse(body=body))
    result = aeo_score.check_crawlers("https://example.com")
    assert result["truncated"] is True
    assert _status(result, "OAI-SearchBot") == "allowed"   # the rule past 500 KiB is ignored
    assert any("larger than" in n for n in result["notes"])


def test_html_soft_404_is_noted(monkeypatch):
    _patch_get(monkeypatch, _FakeResponse(body=b"<html><body>Not found</body></html>",
                                          content_type="text/html; charset=utf-8"))
    result = aeo_score.check_crawlers("https://example.com")
    assert result["score"] == 100 and any("soft-404" in n for n in result["notes"])


def test_crawlers_cli_robots_file_and_kpis(tmp_path, capsys):
    robots = tmp_path / "robots.txt"
    robots.write_text("User-agent: OAI-SearchBot\nDisallow: /\n")
    out = tmp_path / "kpis.json"
    rc = aeo_score.main(["crawlers", "www.example.com", "--robots-file", str(robots),
                         "--emit-kpis", str(out), "--json"])
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["score"] == round(100 * 8 / 9)
    assert "local robots.txt file" in printed["data_sources"][0]
    env = json.loads(out.read_text())
    assert env["project"] == "example.com" and env["metrics"] == {"aeo.crawler_access": printed["score"]}


def test_crawlers_cli_unavailable_exits_1(monkeypatch):
    _patch_get(monkeypatch, _FakeResponse(status_code=503))
    assert aeo_score.main(["crawlers", "https://example.com", "--json"]) == 1


def test_vendor_matrix_classification():
    answer = {a["agent"] for a in aeo_score.ANSWER_SURFACE_AGENTS}
    training = {a["agent"] for a in aeo_score.TRAINING_AGENTS}
    assert {"OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "PerplexityBot",
            "Perplexity-User", "Googlebot", "Bingbot", "Applebot"} == answer
    assert {"GPTBot", "ClaudeBot", "Google-Extended", "Applebot-Extended", "CCBot"} <= training
    assert not answer & training
    assert "anthropic-ai" not in {t for a in aeo_score.ANSWER_SURFACE_AGENTS + aeo_score.TRAINING_AGENTS
                                  for t in a["tokens"]}


# ---------------------------------------------------------------------------
# One AEO score everywhere (spec section 2.2 items 1-4, section 5)
# ---------------------------------------------------------------------------

_DOCS = sorted([*(REPO_ROOT / "skills").glob("*/SKILL.md"), *(REPO_ROOT / "agents").glob("*.md")])


def _text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", _DOCS, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_dead_geo_commands(path):
    text = path.read_text(encoding="utf-8")
    assert "/geo quick" not in text
    assert "/geo report-pdf" not in text


def test_competing_aeo_score_definitions_are_gone():
    assert "Combined GEO Score" not in _text("skills/geo-platform-optimizer/SKILL.md")
    assert "Platform Readiness Score" in _text("skills/geo-platform-optimizer/SKILL.md")
    agent = _text("agents/seo-geo.md")
    assert "GEO Health Score" not in agent and "Multi-Modal Content | 15%" not in agent
    assert "11% of domains" not in agent
    assert "aeo_score.py compute" in agent
    visibility = _text("agents/geo-ai-visibility.md")
    assert "AI_Visibility = (Citability * 0.39)" not in visibility
    assert "aeo_score.py compute" in visibility
    for rel in ("skills/geo-proposal/SKILL.md", "skills/geo-prospect/SKILL.md", "skills/geo-compare/SKILL.md"):
        text = _text(rel)
        for line in text.splitlines():
            if "GEO Score" in line or "geo_score" in line:   # only allowed when describing the retired score
                assert "retired" in line.lower() or "legacy" in line.lower(), f"{rel}: {line}"
        assert "aeo_score.py" in text or "performance_tracker.py" in text, rel


def test_seo_audit_uses_the_composite_and_keeps_citability_as_a_component():
    text = _text("skills/seo-audit/SKILL.md")
    fanout = text[text.index("## AEO fan-out"):text.index("## Priority Definitions")]
    assert "aeo_score.py compute" in fanout
    assert "## AEO Score: <score from aeo_score.py compute>" in fanout
    assert "AEO Score: <0-100 citability figure" not in text
    assert "`citability`" in fanout and "completeness" in fanout
    assert "never averaged, weighted together, or presented as a" in fanout


def test_geo_compare_is_deterministic():
    text = _text("skills/geo-compare/SKILL.md")
    assert "contextual analysis" not in re.sub(r"\s+", " ", text).lower()
    assert "Never fill it from prose" in text
    assert "estimate approximate scores" not in text
    assert "performance_tracker.py export" in text and "--compare" in text
    assert "6 categories" not in text and "14 crawlers" not in text and "/14" not in text
    assert "AEO Score:\\**\\s*(\\d{1,3})/100" in text   # the only legacy line it may parse


def test_router_routes_share_of_voice_score_crawlers_and_measurement():
    text = _text("skills/seo-geo/SKILL.md")
    for needle in ("geo-share-of-voice", "aeo_score.py compute", "aeo_score.py crawlers", "seo-track"):
        assert needle in text


def test_citability_and_brand_skills_declare_component_role():
    assert "`citability` component" in _text("skills/geo-citability/SKILL.md")
    assert "`brand_authority` component" in _text("skills/geo-brand-mentions/SKILL.md")
