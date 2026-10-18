"""Shared-core additions used by the seo-links scripts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import dataforseo_costs  # noqa: E402
import seo_kpi  # noqa: E402
import seo_project  # noqa: E402


def test_profile_topics_default_and_validation():
    profile = seo_project.new_profile("acme.in", "Acme", ["acme"], ["rival.com"])
    assert profile["topics"] == []
    profile["topics"] = ["training video", "compliance training"]
    assert not [p for p in seo_project.validate_profile(profile) if p["level"] == "error"]
    profile["topics"] = ["ok", ""]
    errors = [p["message"] for p in seo_project.validate_profile(profile) if p["level"] == "error"]
    assert any("topics" in m for m in errors)
    profile["topics"] = "training video"
    errors = [p["message"] for p in seo_project.validate_profile(profile) if p["level"] == "error"]
    assert any("topics" in m for m in errors)


def test_links_metrics_are_reserved_and_validated():
    for name in ("links.referring_domains", "links.gap_domains", "links.prospects",
                 "links.contacted", "links.won", "links.won_verified"):
        assert seo_kpi.RESERVED_METRICS[name] == "count"
    assert seo_kpi.RESERVED_METRICS["links.win_rate"] == "fraction"
    ok = seo_kpi.build_envelope("acme.in", "link_outreach.py",
                                {"links.won": 2, "links.win_rate": 0.4, "links.contacted": 5})
    assert ok["metrics"]["links.won"] == 2
    with pytest.raises(seo_kpi.EnvelopeError):
        seo_kpi.build_envelope("acme.in", "x", {"links.win_rate": 40})
    with pytest.raises(seo_kpi.EnvelopeError):
        seo_kpi.build_envelope("acme.in", "x", {"links.won": -1})


def test_cost_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(dataforseo_costs, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(dataforseo_costs, "LEDGER_FILE", tmp_path / "dataforseo-ledger.json")
    monkeypatch.setattr(dataforseo_costs, "LOCK_FILE", tmp_path / "dataforseo-ledger.lock")
    assert dataforseo_costs.unit_cost("backlinks_backlinks") == 0.02
    assert dataforseo_costs.unit_cost("no_such_endpoint") is None
    entry = dataforseo_costs.record_spend("backlinks_backlinks", 0.0215, note="link_sources rival.com")
    assert entry["cost"] == 0.0215 and entry["note"] == "link_sources rival.com"
    ledger = json.loads((tmp_path / "dataforseo-ledger.json").read_text())
    assert ledger["entries"][-1]["endpoint"] == "backlinks_backlinks"
