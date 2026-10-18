"""link_outreach: pipeline rules, brief, draft lint, verification, KPIs. No network."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import link_outreach as lo  # noqa: E402
import link_store  # noqa: E402
import seo_kpi  # noqa: E402

PROJECT = "acme.in"
PROFILE = {"domain": PROJECT, "name": "Acme", "topics": ["training video"],
           "money_pages": ["/solutions/compliance-training-video", "https://acme.in/pricing"],
           "notes": [{"text": "Produced 40 compliance modules in 2025", "approved_by": "user"},
                     {"text": "Probably the best studio", "approved_by": "inferred"}]}
EVIDENCE = [{"competitor": "rival.com", "authority": 80.0, "spam_score": None, "dofollow": True,
             "attributes": [], "sample_url": "https://trainingmag.com/2025/03/compliance-training-video-studios/",
             "sample_anchor": "Rival", "sample_title": "Compliance training video studios", "tld": "com"}]


def prospect(domain="trainingmag.com", score=74, bucket="high_value"):
    return {"domain": domain, "segment": "gap", "type": "publication", "matched_rule": "rule7:publication",
            "score": score, "effort": "high", "bucket": bucket,
            "tactic": "Pitch expert commentary or an original data point", "evidence": EVIDENCE}


@pytest.fixture
def conn(tmp_path):
    c = link_store.open_store(str(tmp_path))
    lo.add_prospects(c, PROJECT, [prospect()], "dataforseo")
    return c


def row(conn, domain="trainingmag.com"):
    return conn.execute("SELECT * FROM prospects WHERE project = ? AND domain = ?",
                        (PROJECT, domain)).fetchone()


def drafted(conn):
    brief = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    lo.store_brief(conn, PROJECT, "trainingmag.com", brief)
    body = ("Your list of compliance training video studios is useful. Acme produced 40 compliance "
            f"modules in 2025; our approach is here: {brief['asset_url']} Would it fit your next update?")
    res = lo.save_draft(conn, PROJECT, "trainingmag.com", "Compliance training video studios",
                        body, brief["brief_hash"])
    assert res["ok"], res
    return brief


def test_add_dedup_suppression_and_cooldown(conn):
    out = lo.add_prospects(conn, PROJECT, [prospect()], "dataforseo")
    assert out["added"] == [] and "already tracked" in out["skipped"][0]["reason"]
    lo.mark(conn, PROJECT, "trainingmag.com", "do_not_contact")
    out = lo.add_prospects(conn, PROJECT, [prospect()], "dataforseo")
    assert out["skipped"][0]["reason"] == "do_not_contact"


def test_lost_sets_cooldown_and_readd_after_it(tmp_path):
    c = link_store.open_store(str(tmp_path))
    lo.add_prospects(c, PROJECT, [prospect()], "dataforseo")
    drafted(c)
    lo.approve(c, PROJECT, "trainingmag.com", "Riya")
    lo.mark(c, PROJECT, "trainingmag.com", "contacted")
    lo.mark(c, PROJECT, "trainingmag.com", "lost", today=date(2026, 10, 17))
    assert row(c)["cooldown_until"] == "2027-01-15"
    early = lo.add_prospects(c, PROJECT, [prospect()], "dataforseo", today=date(2026, 12, 1))
    assert "cooldown" in early["skipped"][0]["reason"]
    later = lo.add_prospects(c, PROJECT, [prospect()], "dataforseo", today=date(2027, 1, 16))
    assert later["added"] == ["trainingmag.com"] and row(c)["status"] == "new"


def test_brief_asset_claims_and_hash(conn):
    brief = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    assert brief["asset_url"] == "https://acme.in/solutions/compliance-training-video"
    assert "Produced 40 compliance modules in 2025" in brief["allowed_claims"]
    assert "Probably the best studio" not in brief["allowed_claims"]
    assert brief["competitors_linked"] == ["rival.com"] and brief["contact_path"] is None
    again = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    assert again["brief_hash"] == brief["brief_hash"]


@pytest.mark.parametrize("text, rule", [
    ("We can pay for a placement.", "banned_term"),
    ("Happy to discuss a link exchange", "banned_term"),
    ("Could it be a do-follow link?", "banned_term"),
    ("Open to a sponsorship?", "banned_term"),
    ("See https://evil.example.com/x", "unbriefed_url"),
])
def test_lint_rejects(conn, text, rule):
    brief = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    problems = lo.lint_draft("Hello", text, brief)
    assert rule in {p["rule"] for p in problems}


def test_lint_accepts_clean_and_whole_words_only(conn):
    brief = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    body = f"Payroll teams liked it. More at {brief['asset_url']}/ and https://acme.in"
    assert lo.lint_draft("A fit for your list?", body, brief) == []
    long_body = "word " * 151
    assert {p["rule"] for p in lo.lint_draft("x" * 91, long_body, brief)} == {
        "body_too_long", "subject_too_long"}


def test_stale_brief_rejected(conn):
    brief = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    lo.store_brief(conn, PROJECT, "trainingmag.com", brief)
    res = lo.save_draft(conn, PROJECT, "trainingmag.com", "Hi", "Short note.", "0000000000000000")
    assert not res["ok"] and res["problems"][0]["rule"] == "stale_brief"


def test_approval_gate_and_contacted(conn):
    with pytest.raises(lo.TransitionError):
        lo.mark(conn, PROJECT, "trainingmag.com", "contacted")
    drafted(conn)
    with pytest.raises(lo.TransitionError):
        lo.approve(conn, PROJECT, "trainingmag.com", "  ")
    lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    assert row(conn)["reviewed_by"] == "Riya"
    lo.mark(conn, PROJECT, "trainingmag.com", "contacted")
    assert row(conn)["status"] == "contacted" and row(conn)["contacted_at"]


def test_one_followup_after_seven_days(conn):
    brief = drafted(conn)
    lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    lo.mark(conn, PROJECT, "trainingmag.com", "contacted", now="2026-10-01T09:00:00Z")
    body = f"Following up on my note about your studios list: {brief['asset_url']}"
    with pytest.raises(lo.TransitionError):
        lo.save_draft(conn, PROJECT, "trainingmag.com", "Following up", body, brief["brief_hash"],
                      today=date(2026, 10, 5))
    assert lo.save_draft(conn, PROJECT, "trainingmag.com", "Following up", body, brief["brief_hash"],
                         today=date(2026, 10, 8))["ok"]
    lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    lo.mark(conn, PROJECT, "trainingmag.com", "contacted", now="2026-10-08T09:00:00Z")
    assert row(conn)["followup_at"] == "2026-10-08T09:00:00Z"
    with pytest.raises(lo.TransitionError):
        lo.save_draft(conn, PROJECT, "trainingmag.com", "Again", body, brief["brief_hash"],
                      today=date(2026, 10, 30))


def test_won_requires_link_on_prospect_domain(conn):
    drafted(conn)
    lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    lo.mark(conn, PROJECT, "trainingmag.com", "contacted")
    with pytest.raises(lo.TransitionError):
        lo.mark(conn, PROJECT, "trainingmag.com", "won")
    with pytest.raises(lo.TransitionError):
        lo.mark(conn, PROJECT, "trainingmag.com", "won", link_url="https://other.org/x")
    lo.mark(conn, PROJECT, "trainingmag.com", "won", link_url="https://trainingmag.com/2025/03/x/")
    assert row(conn)["status"] == "won"
    with pytest.raises(lo.TransitionError):
        lo.save_draft(conn, PROJECT, "trainingmag.com", "x", "y", "z")


@pytest.mark.parametrize("checker, verified, rel", [
    ({"status": "verified", "rel_attributes": ["nofollow"]}, "live", "nofollow"),
    ({"status": "verified", "rel_attributes": ["follow"]}, "live", "dofollow"),
    ({"status": "link_removed"}, "missing", None),
    ({"status": "error", "error": "timeout"}, "unreachable", None),
])
def test_verify_mapping(conn, checker, verified, rel):
    drafted(conn)
    lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    lo.mark(conn, PROJECT, "trainingmag.com", "contacted")
    lo.mark(conn, PROJECT, "trainingmag.com", "won", link_url="https://trainingmag.com/2025/03/x/")
    seen = {}

    def fake(source_url, target_url):
        seen.update(source=source_url, target=target_url)
        return checker

    [out] = lo.verify(conn, PROJECT, verifier=fake)
    assert seen == {"source": "https://trainingmag.com/2025/03/x/", "target": "https://acme.in/"}
    assert out["verified_status"] == verified and out["link_rel"] == rel
    assert row(conn)["status"] == "won"


def test_kpis_and_win_rate_threshold(tmp_path):
    c = link_store.open_store(str(tmp_path))
    domains = [f"site{i}.org" for i in range(6)]
    lo.add_prospects(c, PROJECT, [prospect(d) for d in domains], "dataforseo")
    for d in domains[:5]:
        c.execute("UPDATE prospects SET status = 'contacted', contacted_at = '2026-10-01T00:00:00Z'"
                  " WHERE domain = ?", (d,))
    for d in domains[:2]:
        c.execute("UPDATE prospects SET status = 'won', verified_status = 'live' WHERE domain = ?", (d,))
    c.commit()
    k = lo.outreach_kpis(c, PROJECT)
    assert k == {"links.prospects": 4, "links.contacted": 5, "links.won": 2,
                 "links.won_verified": 2, "links.win_rate": 0.4}
    c.execute("UPDATE prospects SET contacted_at = NULL WHERE domain = 'site4.org'")
    c.commit()
    assert lo.outreach_kpis(c, PROJECT)["links.win_rate"] is None
    env = seo_kpi.build_envelope(PROJECT, "link_outreach.py", lo.outreach_kpis(c, PROJECT))
    assert env["metrics"]["links.won"] == 2


def test_every_transition_is_logged(conn):
    drafted(conn)
    lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    events = [(e["from_status"], e["to_status"]) for e in conn.execute(
        "SELECT * FROM events WHERE domain = 'trainingmag.com' ORDER BY id")]
    assert events == [(None, "new"), ("new", "drafted"), ("drafted", "approved")]


def test_export_only_approved_by_default(conn):
    drafted(conn)
    assert lo.export_rows(conn, PROJECT) == []
    lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    [exported] = lo.export_rows(conn, PROJECT)
    assert exported["to_address"] == "" and exported["subject"] == "Compliance training video studios"
    assert json.dumps(exported)
