"""ucp_check endpoint probes and the CLAUDE_SEO_LOCAL_TARGETS allowlist.

Service endpoints come from the fetched UCP profile, i.e. from the audited
site, not from the operator. The local-target allowlist exists so the
operator can audit a named dev server; it must not let a public profile aim
``--probe-endpoints`` at that dev server. No network: DNS and HTTP are stubbed.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("requests")
import ucp_check  # noqa: E402
import url_safety  # noqa: E402

_DNS = {"store.example": "93.184.216.34", "localhost": "127.0.0.1"}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host not in _DNS:
            raise socket.gaierror(socket.EAI_NONAME, host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (_DNS[host], port or 0))]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setenv("CLAUDE_SEO_LOCAL_TARGETS", "localhost:3000")


def _profile(endpoint: str) -> str:
    return json.dumps({"ucp": {
        "version": "2026-08-25",
        "services": {"dev.ucp.shopping": [
            {"version": "2026-08-25", "transport": "rest", "endpoint": endpoint}]},
        "capabilities": {"dev.ucp.shopping.checkout": [
            {"version": "2026-08-25", "spec": "https://ucp.dev/c", "schema": "https://ucp.dev/s"}]},
    }})


def test_public_profile_cannot_aim_a_probe_at_an_allowlisted_local_target(monkeypatch):
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        if url.endswith("/.well-known/ucp"):
            return SimpleNamespace(status_code=200, headers={"Content-Type": "application/json"},
                                   content=_profile("http://localhost:3000/admin").encode())
        return SimpleNamespace(status_code=200, headers={}, content=b"")

    monkeypatch.setattr(ucp_check, "safe_requests_get", fake_get)
    report = ucp_check.audit_site("https://store.example", probe_endpoints=True)
    assert fetched == ["https://store.example/.well-known/ucp"]
    probe = report["endpoint_probes"][0]
    assert probe["reachable"] is False
    assert probe["error"].startswith("ssrf-blocked")


def test_a_local_target_may_probe_its_own_endpoints(monkeypatch):
    fetched = []

    def fake_get(url, **kwargs):
        fetched.append(url)
        if url.endswith("/.well-known/ucp"):
            return SimpleNamespace(status_code=200, headers={"Content-Type": "application/json"},
                                   content=_profile("http://localhost:3000/api/ucp").encode())
        return SimpleNamespace(status_code=204, headers={}, content=b"")

    monkeypatch.setattr(ucp_check, "safe_requests_get", fake_get)
    report = ucp_check.audit_site("http://localhost:3000", probe_endpoints=True)
    assert fetched == ["http://localhost:3000/.well-known/ucp", "http://localhost:3000/api/ucp"]
    assert report["endpoint_probes"][0]["reachable"] is True


def test_public_endpoint_is_probed_normally(monkeypatch):
    def fake_get(url, **kwargs):
        if url.endswith("/.well-known/ucp"):
            return SimpleNamespace(status_code=200, headers={},
                                   content=_profile("https://store.example/api/ucp").encode())
        return SimpleNamespace(status_code=405, headers={}, content=b"")

    monkeypatch.setattr(ucp_check, "safe_requests_get", fake_get)
    report = ucp_check.audit_site("https://store.example", probe_endpoints=True)
    assert report["endpoint_probes"][0]["reachable"] is True
    assert report["summary"].startswith("profile-found: UCP 2026-08-25, 1 capabilities")
