"""Tests for scripts/brand_scanner.py — mirrors tests/test_url_safety.py's
pattern to prove the grafted scanner's only real network call
(check_wikipedia_presence) cannot reach private/loopback hosts."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import brand_scanner  # noqa: E402
import url_safety  # noqa: E402


def test_generate_brand_report_has_all_five_platforms():
    report = brand_scanner.generate_brand_report("Acme Corp", "acmecorp.com")
    assert set(report["platforms"].keys()) == {
        "youtube", "reddit", "wikipedia", "linkedin", "other",
    }


def test_check_wikipedia_presence_uses_safe_requests_get():
    """Confirm the rewired function goes through url_safety, not raw requests.

    brand_scanner.py does `from url_safety import safe_requests_get`, which
    binds a name in brand_scanner's own module namespace at import time.
    Patching url_safety.safe_requests_get would not affect that already-bound
    reference (a classic unittest.mock "patch where it's looked up, not
    where it's defined" gotcha) — so the mock target here must be
    brand_scanner.safe_requests_get, not url_safety.safe_requests_get.
    """
    with patch.object(brand_scanner, "safe_requests_get") as mock_get:
        mock_get.side_effect = url_safety.URLSafetyError("blocked for test")
        result = brand_scanner.check_wikipedia_presence("Acme Corp")
        assert mock_get.called
        assert result["has_wikipedia_page"] is False
        assert result["has_wikidata_entry"] is False


def test_check_wikipedia_presence_never_raises_on_unsafe_target():
    """Even if Wikipedia's own API URL construction were ever attacker-
    influenced, a URLSafetyError must be swallowed, not propagated."""
    with patch.object(
        brand_scanner, "safe_requests_get",
        side_effect=url_safety.URLSafetyError("blocked"),
    ):
        result = brand_scanner.check_wikipedia_presence("Acme Corp")
        assert isinstance(result, dict)
        assert result["platform"] == "Wikipedia"
