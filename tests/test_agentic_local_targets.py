"""agentic_check never lets a fetched page aim a request at a local target.

CLAUDE_SEO_LOCAL_TARGETS lets the operator audit a named dev or staging host.
Markdown alternates and ai-catalog links come from the audited page, so a
cross-host one is fetched with allow_local_targets=False (ZYRA fork).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("requests")
import agentic_check as ac  # noqa: E402


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_get(url, **kwargs):
        seen.append((url, kwargs.get("allow_local_targets", True)))
        raise ac.URLSafetyError("stub")

    monkeypatch.setattr(ac, "safe_requests_get", fake_get)
    return seen


def test_cross_host_link_is_fetched_without_the_allowlist(calls):
    ac._fetch_found("http://localhost:3000/admin.md", "https://public.example/page")
    assert calls == [("http://localhost:3000/admin.md", False)]


def test_same_host_link_keeps_the_operator_allowlist(calls):
    ac._fetch_found("http://localhost:3000/page.md", "http://localhost:3000/page")
    assert calls == [("http://localhost:3000/page.md", True)]


def test_markdown_alternates_and_catalog_links_use_the_guard(calls):
    page = {"soup_links": {"markdown_alternates": ["http://localhost:3000/x.md"],
                           "ai_catalog_links": ["http://127.0.0.1:8080/ai-catalog.json"]}}
    ac.audit_markdown("https://public.example/page", page)
    ac.audit_ard("https://public.example", [], page)
    flags = dict(calls)
    assert flags["http://localhost:3000/x.md"] is False
    assert flags["http://127.0.0.1:8080/ai-catalog.json"] is False
    # The audited site's own sibling .md is fetched normally.
    assert flags["https://public.example/page.md"] is True
