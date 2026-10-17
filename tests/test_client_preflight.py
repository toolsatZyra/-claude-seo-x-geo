"""
Tests for scripts/client_preflight.py (v3.1 fixes).

- AI crawler access comes from aeo_score's evaluator, so the preflight and the
  AEO score cannot disagree, and training-only crawlers (GPTBot, ClaudeBot,
  Google-Extended) are no longer presented as AI-answer visibility blockers.
- Fetches go through url_safety (private/metadata hosts refused).
- The CrUX API key travels in a header, never in the URL.

No network: robots analysis is injected, url_safety refuses before any socket,
and urlopen is mocked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import aeo_score  # noqa: E402
import client_preflight as cp  # noqa: E402

ROBOTS = """\
User-agent: GPTBot
Disallow: /

User-agent: OAI-SearchBot
Disallow: /

User-agent: *
Allow: /
Sitemap: https://example.com/sitemap.xml
"""


def test_check_robots_uses_aeo_evaluator_and_separates_training():
    analysis = aeo_score.analyze_robots(ROBOTS, 200, robots_url="https://example.com/robots.txt")
    r = cp.check_robots("https://example.com/", analysis=analysis)
    assert r["present"] and r["robots_status"] == "ok"
    assert r["ai_crawlers"]["OAI-SearchBot"] == {
        **r["ai_crawlers"]["OAI-SearchBot"], "status": "BLOCKED", "answer_surface": True}
    assert r["ai_crawlers"]["GPTBot"]["status"] == "BLOCKED"
    assert r["ai_crawlers"]["GPTBot"]["answer_surface"] is False
    assert r["crawler_access_score"] == analysis["score"] < 100
    assert r["sitemaps"] == ["https://example.com/sitemap.xml"]
    assert r["blanket_disallow"] is False


def test_check_robots_unavailable_is_not_measured():
    analysis = aeo_score.analyze_robots(None, 503)
    r = cp.check_robots("https://example.com/", analysis=analysis)
    assert r["robots_status"] == "unavailable"
    assert r["crawler_access_score"] is None
    assert r["ai_crawlers"] == {}


def test_render_distinguishes_answer_blocks_from_training_blocks(capsys):
    analysis = aeo_score.analyze_robots(ROBOTS, 200)
    report = {
        "domain": "example.com", "verdict": "PARTIAL", "summary": "x",
        "reachable": {"ok": True, "final_url": "https://example.com/"},
        "robots": cp.check_robots("https://example.com/", analysis=analysis),
        "sitemap": {"present": True}, "llms_txt": {"present": False},
        "gsc": {"available": False, "accessible": []},
        "crux": {"has_field_data": False, "error": "n/a"},
    }
    try:
        cp.render(report, "ops@example.com")
    except (KeyError, TypeError):
        pass  # later sections may need more fields; the robots lines print first
    out = capsys.readouterr().out
    assert "AI answer crawlers BLOCKED: OAI-SearchBot" in out
    assert "Training-only crawlers blocked: GPTBot" in out


def test_get_refuses_private_hosts_without_a_socket():
    with mock.patch("socket.create_connection", side_effect=AssertionError("network used")):
        assert cp._get("http://169.254.169.254/latest/meta-data/") == (
            None, "http://169.254.169.254/latest/meta-data/", "")
        assert cp._get("http://127.0.0.1:6379/")[0] is None


def test_crux_key_is_sent_in_header_not_url(monkeypatch):
    import google_auth

    monkeypatch.setattr(google_auth, "get_api_key", lambda: "AIzaFAKEKEY1234567890123456789012345")
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _Resp()

    monkeypatch.setattr(cp.urllib.request, "urlopen", fake_urlopen)
    out = cp.check_crux("example.com")
    assert out["has_field_data"] is True
    assert "key=" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"].startswith("AIza")
    assert json.dumps(out).find("AIza") == -1


def test_normalize_strips_www_and_url_parts():
    assert cp.normalize("https://www.Example.com/path") == "example.com"
    assert cp.normalize("www.example.com") == "example.com"
    assert cp.normalize("example.com:443") == "example.com"
    assert cp.normalize("blog.example.com") == "blog.example.com"


def test_crux_uses_the_reached_origin(monkeypatch):
    import google_auth

    monkeypatch.setattr(google_auth, "get_api_key", lambda: "AIzaFAKEKEY1234567890123456789012345")
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, *a):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return _Resp()

    monkeypatch.setattr(cp.urllib.request, "urlopen", fake_urlopen)
    cp.check_crux("example.com", origin="https://example.com")
    assert seen["body"] == {"origin": "https://example.com"}


def test_unreachable_robots_is_not_called_absent(capsys):
    analysis = aeo_score.analyze_robots(None, 503)
    report = {
        "domain": "example.com", "verdict": "PARTIAL", "summary": "x",
        "reachable": {"ok": True, "final_url": "https://example.com/"},
        "robots": cp.check_robots("https://example.com/", analysis=analysis),
        "sitemap": {"present": True}, "llms_txt": {"present": False},
        "gsc": {"available": False, "accessible": []},
        "crux": {"has_field_data": False, "error": "n/a"},
    }
    try:
        cp.render(report, "ops@example.com")
    except (KeyError, TypeError):
        pass
    out = capsys.readouterr().out
    assert "unreachable" in out and "absent" not in out.split("robots.txt", 1)[1].splitlines()[0]
