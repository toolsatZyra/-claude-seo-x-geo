"""Public contract of gsc_query.query_search_analytics (ZYRA v3.1 hub).

keyword_research.py, rank_tracker.py, performance_tracker.py and
content_decay.py call ``query_search_analytics`` directly. The upstream port
(v2.2.4 exact row limits, pagination, totals provenance) may add keys but must
keep the keyword signature and the row/totals shape these callers read:
ctr is a PERCENT rounded to 2 dp, position is rounded to 1 dp, and every row
carries its keys plus one entry per dimension name.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("googleapiclient")

import gsc_query  # noqa: E402


class _Exec:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class _Analytics:
    def __init__(self, rows, aggregate):
        self.rows = rows
        self.aggregate = aggregate
        self.calls = []

    def query(self, siteUrl=None, body=None):
        self.calls.append(dict(body))
        if body.get("dimensions") == []:
            return _Exec({"rows": [self.aggregate]})
        start = body.get("startRow", 0)
        return _Exec({"rows": self.rows[start:start + body["rowLimit"]]})


class _Service:
    def __init__(self, analytics):
        self.analytics = analytics

    def searchanalytics(self):
        return self.analytics


def test_signature_keywords_and_defaults_are_stable():
    sig = inspect.signature(gsc_query.query_search_analytics)
    expected = {
        "site_url": inspect.Parameter.empty,
        "start_date": None,
        "end_date": None,
        "dimensions": None,
        "search_type": "web",
        "row_limit": 1000,
        "filters": None,
        "data_state": "final",
    }
    assert list(sig.parameters) == list(expected)
    for name, default in expected.items():
        assert sig.parameters[name].default == default, name


def test_row_and_totals_shape():
    rows = [
        {"keys": ["blue widgets", "https://example.com/a"], "clicks": 12,
         "impressions": 400, "ctr": 0.03, "position": 6.4567},
        {"keys": ["red widgets", "https://example.com/b"], "clicks": 0,
         "impressions": 90, "ctr": 0.0, "position": 8.04},
    ]
    aggregate = {"clicks": 40, "impressions": 1000, "ctr": 0.04, "position": 7.25}
    analytics = _Analytics(rows, aggregate)
    with mock.patch.object(gsc_query, "_build_gsc_service", return_value=_Service(analytics)):
        result = gsc_query.query_search_analytics(
            site_url="sc-domain:example.com",
            start_date="2026-09-01",
            end_date="2026-09-28",
            dimensions=["query", "page"],
            search_type="web",
            row_limit=1000,
            filters=None,
            data_state="final",
        )

    assert result["error"] is None
    assert result["row_count"] == 2
    first = result["rows"][0]
    assert first["keys"] == ["blue widgets", "https://example.com/a"]
    assert first["query"] == "blue widgets"
    assert first["page"] == "https://example.com/a"
    assert first["clicks"] == 12 and first["impressions"] == 400
    assert first["ctr"] == 3.0          # percent, 2 dp
    assert first["position"] == 6.5     # 1 dp
    assert result["totals"] == {"clicks": 40, "impressions": 1000, "ctr": 4.0, "position": 7.2}
    assert isinstance(result["quick_wins"], list)
    assert result["quick_wins"][0]["keys"] == ["blue widgets", "https://example.com/a"]
    # Additive provenance keys from the upstream port.
    assert result["totals_source"] == "dimensionless_aggregate"
    assert result["totals_complete"] is True
    assert isinstance(result["warnings"], list)


def test_private_helpers_other_workstreams_use_still_exist():
    for name in ("_query_site_totals", "list_sites", "list_sitemaps"):
        assert callable(getattr(gsc_query, name)), name


def test_403_message_does_not_point_at_an_unported_auth_mode():
    class _Denied:
        def query(self, siteUrl=None, body=None):
            raise Exception("HttpError 403 forbidden")

    with mock.patch.object(gsc_query, "_build_gsc_service", return_value=_Service(_Denied())):
        result = gsc_query.query_search_analytics("example.com", dimensions=["query"])
    assert "Permission denied" in result["error"]
    assert "sc-domain:example.com" in result["error"]
    assert "CLAUDE_SEO_GOOGLE_AUTH" not in result["error"]
