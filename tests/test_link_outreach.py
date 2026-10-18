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
    # the page answered but the link cannot be confirmed over plain HTTP: not "unreachable"
    ({"status": "unverifiable_js"}, "unverifiable", None),
    ({"status": "moved"}, "unverifiable", None),
    ({"status": "exists"}, "unverifiable", None),
    ({"status": "lost"}, "missing", None),
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


# ---- CLI errors are exit 2 with a message, never a traceback ----

def _cli_data(tmp_path):
    import seo_project
    data_dir = str(tmp_path)
    profile = seo_project.new_profile("acme.in", "Acme", ["acme"], ["rival.com"])
    seo_project.save_profile(profile, data_dir)
    src = tmp_path / "projects" / "acme.in.json"
    (tmp_path / "projects" / "other.io.json").write_text(src.read_text())  # belongs to acme.in
    return data_dir


@pytest.mark.parametrize("argv, projects", [
    (["add", "--source", "csv-generic", "--no-sitemap"], ("other.io", "")),
    (["brief", "--domain", "trainingmag.com"], ("other.io", "")),
    (["board"], ("",)),  # board never loads a profile, so only the empty project is an error
])
def test_cli_mismatched_profile_and_empty_project_exit_2(tmp_path, capsys, argv, projects):
    data_dir = _cli_data(tmp_path)
    for project in projects:
        assert lo.main([argv[0], "--project", project, "--data-dir", data_dir, *argv[1:]]) == 2
        err = capsys.readouterr().err
        assert err.startswith("Error:") and "Traceback" not in err


def test_lint_survives_a_malformed_url(conn):
    brief = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    problems = lo.lint_draft("Hello", "See https://[x for details", brief)
    assert {"rule": "unbriefed_url", "url": "https://[x"} in problems


# ---- add --segment: gap ahead within the selection ----

def _ranked(domain, segment, score, bucket="backlog"):
    return {**prospect(domain, score, bucket), "segment": segment, "k": 2 if segment == "gap" else 1}


def test_select_for_add_puts_gap_ahead_and_filters_by_segment():
    ranked = [_ranked("big.com", "single", 64), _ranked("a.org", "gap", 55), _ranked("b.org", "single", 50),
              _ranked("c.org", "gap", 40)]
    doms = lambda sel: [p["domain"] for p in sel]  # noqa: E731
    assert doms(lo.select_for_add(ranked, "all", None, 0, 10)) == ["a.org", "c.org", "big.com", "b.org"]
    assert doms(lo.select_for_add(ranked, "all", None, 0, 3)) == ["a.org", "c.org", "big.com"]
    assert doms(lo.select_for_add(ranked, "gap", None, 0, 10)) == ["a.org", "c.org"]
    assert doms(lo.select_for_add(ranked, "single", None, 0, 10)) == ["big.com", "b.org"]
    assert doms(lo.select_for_add(ranked, "all", None, 45, 10)) == ["a.org", "big.com", "b.org"]
    only_hv = [_ranked("h.org", "single", 80, "high_value"), *ranked]
    assert doms(lo.select_for_add(only_hv, "all", {"high_value"}, 0, 10)) == ["h.org"]


def test_cli_add_segment_option(tmp_path):
    import link_gap
    import seo_project
    data_dir = str(tmp_path)
    profile = seo_project.new_profile("acme.in", "Acme", ["acme"], ["rival.com", "other.in"],
                                      topics=["training video"])
    seo_project.save_profile(profile, data_dir)
    c = link_store.open_store(data_dir)
    link_store.save_snapshot(c, "acme.in", "acme.in", "csv-generic", [{"domain": "partner.in"}])
    link_store.save_snapshot(c, "acme.in", "rival.com", "csv-generic",
                             [{"domain": "plain.org"}, {"domain": "bignews.com", "authority": 95.0,
                                                        "dofollow": True}])
    link_store.save_snapshot(c, "acme.in", "other.in", "csv-generic", [{"domain": "plain.org"}])
    common = ["add", "--project", "acme.in", "--source", "csv-generic", "--no-sitemap", "--buckets", "all",
              "--data-dir", data_dir, "--json"]
    assert link_gap and lo.main(common + ["--segment", "gap", "--top", "5"]) == 0
    assert [r["domain"] for r in c.execute("SELECT domain FROM prospects")] == ["plain.org"]
    assert lo.main(common + ["--top", "5"]) == 0  # default: all segments, the gap domain already tracked
    assert {r["domain"] for r in c.execute("SELECT domain FROM prospects")} == {"plain.org", "bignews.com"}


# ---- pipeline guardrails: whole-organization suppression, cooldown, skipped, follow-up outcomes ----

def contacted(c, domain="trainingmag.com"):
    """Drive one tracked prospect to `contacted` through the real gates."""
    brief = lo.build_brief(PROFILE, row(c, domain), PROFILE["money_pages"])
    lo.store_brief(c, PROJECT, domain, brief)
    body = f"Your studios list is useful. Our approach: {brief['asset_url']} Would it fit?"
    assert lo.save_draft(c, PROJECT, domain, "Studios list", body, brief["brief_hash"])["ok"]
    lo.approve(c, PROJECT, domain, "Riya")
    lo.mark(c, PROJECT, domain, "contacted", now="2026-10-01T09:00:00Z")
    return brief


def reasons(out):
    return {s["domain"]: s["reason"] for s in out["skipped"]}


def test_do_not_contact_covers_the_whole_registrable_domain(conn):
    lo.mark(conn, PROJECT, "trainingmag.com", "do_not_contact")
    out = lo.add_prospects(conn, PROJECT, [prospect("blog.trainingmag.com"), prospect("www2.trainingmag.com"),
                                           prospect("trainingmag.org")], "dataforseo")
    assert out["added"] == ["trainingmag.org"]  # a different organization is unaffected
    assert reasons(out)["blog.trainingmag.com"].startswith("do_not_contact")
    assert "trainingmag.com" in reasons(out)["www2.trainingmag.com"]


def test_a_subdomain_marked_do_not_contact_blocks_the_parent_domain(conn):
    lo.add_prospects(conn, PROJECT, [prospect("news.example.org")], "dataforseo")
    lo.mark(conn, PROJECT, "news.example.org", "do_not_contact")
    out = lo.add_prospects(conn, PROJECT, [prospect("example.org")], "dataforseo")
    assert out["added"] == [] and reasons(out)["example.org"].startswith("do_not_contact")


def test_an_active_sibling_blocks_the_rest_of_the_organization(conn):
    out = lo.add_prospects(conn, PROJECT, [prospect("blog.trainingmag.com")], "dataforseo")
    assert out["added"] == [] and "already tracked" in reasons(out)["blog.trainingmag.com"]
    # and inside one batch only the first sibling is taken
    out = lo.add_prospects(conn, PROJECT, [prospect("a.newsite.io"), prospect("newsite.io")], "dataforseo")
    assert out["added"] == ["a.newsite.io"] and "already tracked" in reasons(out)["newsite.io"]


def test_shared_hosting_tenants_are_different_organizations(conn):
    lo.add_prospects(conn, PROJECT, [prospect("alice.blogspot.com")], "dataforseo")
    lo.mark(conn, PROJECT, "alice.blogspot.com", "do_not_contact")
    out = lo.add_prospects(conn, PROJECT, [prospect("bob.blogspot.com")], "dataforseo")
    assert out["added"] == ["bob.blogspot.com"]


def test_cooldown_covers_subdomains_of_the_domain(tmp_path):
    c = link_store.open_store(str(tmp_path))
    lo.add_prospects(c, PROJECT, [prospect()], "dataforseo")
    contacted(c)
    lo.mark(c, PROJECT, "trainingmag.com", "no_reply", today=date(2026, 10, 17))
    out = lo.add_prospects(c, PROJECT, [prospect("blog.trainingmag.com")], "dataforseo",
                           today=date(2026, 12, 1))
    assert out["added"] == [] and "cooldown until 2027-01-15" in reasons(out)["blog.trainingmag.com"]
    later = lo.add_prospects(c, PROJECT, [prospect("blog.trainingmag.com")], "dataforseo",
                             today=date(2027, 1, 16))
    assert later["added"] == ["blog.trainingmag.com"]


@pytest.mark.parametrize("outcome", ["skipped", "do_not_contact"])
def test_leaving_the_pipeline_after_contact_starts_the_cooldown(tmp_path, outcome):
    c = link_store.open_store(str(tmp_path))
    lo.add_prospects(c, PROJECT, [prospect()], "dataforseo")
    contacted(c)
    lo.mark(c, PROJECT, "trainingmag.com", outcome, today=date(2026, 10, 17))
    assert row(c)["cooldown_until"] == "2027-01-15" and row(c)["contacted_at"]
    # the old bypass: choose "skipped" instead of "no_reply" and be re-added at once with a clean slate
    out = lo.add_prospects(c, PROJECT, [prospect()], "dataforseo", today=date(2026, 10, 18),
                           include_skipped=True)
    assert out["added"] == [] and row(c)["contacted_at"]  # nothing was reset


def test_skipped_before_contact_has_no_cooldown_but_is_not_readded_by_default(conn):
    lo.mark(conn, PROJECT, "trainingmag.com", "skipped")
    assert row(conn)["cooldown_until"] is None
    out = lo.add_prospects(conn, PROJECT, [prospect()], "dataforseo")
    assert out["added"] == [] and "skipped" in reasons(out)["trainingmag.com"]
    assert "--include-skipped" in reasons(out)["trainingmag.com"]
    assert row(conn)["status"] == "skipped"
    out = lo.add_prospects(conn, PROJECT, [prospect()], "dataforseo", include_skipped=True)
    assert out["added"] == ["trainingmag.com"] and row(conn)["status"] == "new"


def test_include_skipped_flag_is_exposed_on_the_cli(tmp_path):
    parser = lo.build_parser()
    args = parser.parse_args(["add", "--project", "acme.in", "--source", "dataforseo", "--include-skipped"])
    assert args.include_skipped is True
    assert parser.parse_args(["add", "--project", "acme.in", "--source", "x"]).include_skipped is False


# ---- an outcome can be recorded while a follow-up draft is pending ----

@pytest.mark.parametrize("pending", ["drafted", "approved"])
@pytest.mark.parametrize("outcome", ["won", "lost", "no_reply"])
def test_outcome_is_recordable_while_a_followup_is_pending(tmp_path, pending, outcome):
    c = link_store.open_store(str(tmp_path))
    lo.add_prospects(c, PROJECT, [prospect()], "dataforseo")
    brief = contacted(c)
    body = f"Following up on my note: {brief['asset_url']}"
    assert lo.save_draft(c, PROJECT, "trainingmag.com", "Following up", body, brief["brief_hash"],
                         today=date(2026, 10, 9))["ok"]
    if pending == "approved":
        lo.approve(c, PROJECT, "trainingmag.com", "Riya")
    assert row(c)["status"] == pending
    kwargs = {"link_url": "https://trainingmag.com/2026/10/x/"} if outcome == "won" else {}
    lo.mark(c, PROJECT, "trainingmag.com", outcome, today=date(2026, 10, 17), **kwargs)
    assert row(c)["status"] == outcome and row(c)["followup_at"] is None  # no follow-up was ever sent
    events = [(e["from_status"], e["to_status"]) for e in c.execute(
        "SELECT * FROM events WHERE domain = 'trainingmag.com' ORDER BY id")]
    assert events[-1] == (pending, outcome) and ("contacted", "contacted") not in events
    if outcome != "won":
        assert row(c)["cooldown_until"] == "2027-01-15"


@pytest.mark.parametrize("status", ["won", "lost", "no_reply"])
def test_outcome_without_prior_contact_is_still_illegal(conn, status):
    drafted(conn)
    with pytest.raises(lo.TransitionError):
        lo.mark(conn, PROJECT, "trainingmag.com", status, link_url="https://trainingmag.com/x")
    assert row(conn)["status"] == "drafted"


# ---- the approved draft is the one that was linted against the current brief ----

def test_approval_refuses_a_draft_linted_against_a_replaced_brief(conn):
    drafted(conn)
    assert row(conn)["draft_brief_hash"] == row(conn)["brief_hash"]
    changed = {**PROFILE, "notes": [*PROFILE["notes"], {"text": "Won an award in 2026", "approved_by": "user"}]}
    new_brief = lo.build_brief(changed, row(conn), PROFILE["money_pages"])
    assert new_brief["brief_hash"] != row(conn)["brief_hash"]
    lo.store_brief(conn, PROJECT, "trainingmag.com", new_brief)
    with pytest.raises(lo.TransitionError) as exc:
        lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    assert "save-draft" in str(exc.value) and row(conn)["status"] == "drafted"
    body = f"Your list helps teams. See {new_brief['asset_url']} for our approach to training video."
    assert lo.save_draft(conn, PROJECT, "trainingmag.com", "Studios list", body, new_brief["brief_hash"])["ok"]
    assert lo.approve(conn, PROJECT, "trainingmag.com", "Riya")["status"] == "approved"


def test_a_regenerated_identical_brief_does_not_block_approval(conn):
    brief = drafted(conn)
    again = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    assert again["brief_hash"] == brief["brief_hash"]
    lo.store_brief(conn, PROJECT, "trainingmag.com", again)
    assert lo.approve(conn, PROJECT, "trainingmag.com", "Riya")["status"] == "approved"


def test_an_old_store_without_the_column_is_migrated(tmp_path):
    import sqlite3
    path = tmp_path / "links" / "links.db"
    path.parent.mkdir(parents=True)
    old = sqlite3.connect(str(path))
    old.execute("CREATE TABLE prospects (project TEXT NOT NULL, domain TEXT NOT NULL, status TEXT NOT NULL,"
                " source TEXT, segment TEXT, type TEXT, matched_rule TEXT, score INTEGER, effort TEXT,"
                " bucket TEXT, tactic TEXT, evidence_json TEXT NOT NULL DEFAULT '[]', brief_json TEXT,"
                " brief_hash TEXT, draft_subject TEXT, draft_body TEXT, reviewed_by TEXT, reviewed_at TEXT,"
                " contacted_at TEXT, followup_at TEXT, outcome_at TEXT, link_url TEXT, verified_at TEXT,"
                " verified_status TEXT, link_rel TEXT, cooldown_until TEXT, notes TEXT,"
                " created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (project, domain))")
    old.commit()
    old.close()
    c = link_store.open_store(str(tmp_path))
    cols = {r["name"] for r in c.execute("PRAGMA table_info(prospects)")}
    assert "draft_brief_hash" in cols


# ---- lint: normalization, inflections, case-insensitive and bare URLs, emails ----

def _lint(conn, body, subject="Hello"):
    brief = lo.build_brief(PROFILE, row(conn), PROFILE["money_pages"])
    return lo.lint_draft(subject, body, brief)


def _rules(problems):
    return [(p["rule"], p.get("term") or p.get("url")) for p in problems]


@pytest.mark.parametrize("text, term", [
    # every term the spec lists, in plain form
    ("We can pay you", "pay"), ("a payment of $50", "pay"), ("it was paid", "paid"),
    ("a sponsor", "sponsor"), ("sponsored post", "sponsor"), ("open to sponsorship", "sponsor"),
    ("a link exchange", "link exchange"), ("we could swap links", "swap links"),
    ("a reciprocal arrangement", "reciprocal"), ("a guest post fee", "guest post fee"),
    ("a dofollow link", "dofollow"), ("a do-follow link", "dofollow"),
    # the bypasses the final review reproduced
    ("a link-exchange?", "link exchange"), ("link exchanges are fine", "link exchange"),
    ("we are paying for it", "pay"), ("payments, payouts", "pay"), ("it pays well", "pay"),
    ("Is it do follow?", "dofollow"), ("Please exchange links with us", "link exchange"),
    ("a quick link swap", "swap links"), ("link swapping is common", "swap links"),
    ("swapping links", "swap links"), ("a guest-post fee applies", "guest post fee"),
    ("guest post fees", "guest post fee"), ("reciprocal links", "reciprocal"),
    ("some compensation", "compensation"), ("sponsors welcome", "sponsor"),
    ("A DOFOLLOW LINK", "dofollow"), ("link_exchange", "link exchange"),
    # Unicode tricks: fullwidth letters, soft hyphen, zero-width space, non-breaking hyphen
    ("Ｐａｙ you well", "pay"), ("pa­y you", "pay"), ("do​follow", "dofollow"),
    ("do‑follow", "dofollow"),
])
def test_lint_catches_banned_asks_in_every_form(conn, text, term):
    problems = _lint(conn, text)
    assert ("banned_term", term) in _rules(problems), problems


@pytest.mark.parametrize("text", [
    "PayPal and Payroll teams liked it.", "Repay and display are fine words.",
    "Payne and Paylocity are names.", "We followed up on your list.", "An unpaid hobby site.",
    "Unsponsored content and a nonreciprocal arrangement are fine words.",
])
def test_lint_has_no_false_positives_on_whole_words(conn, text):
    # "do follow" as two English words IS flagged on purpose: the ask "do follow" is a common bypass.
    assert [p for p in _lint(conn, text) if p["rule"] == "banned_term"] == []


def test_lint_paypal_and_payroll_alone_are_clean(conn):
    assert _lint(conn, "PayPal and payroll teams liked your list.") == []


@pytest.mark.parametrize("text, url", [
    ("See HTTPS://evil.com/x today", "HTTPS://evil.com/x"),
    ("See www.evil.com/promo today", "www.evil.com/promo"),
    ("See evil.com/offer today", "evil.com/offer"),
    ("Visit evil.com for details", "evil.com"),
    ("Visit evil.xyz.", "evil.xyz"),
    ("Visit http://evil.com:8080/a?b=1.", "http://evil.com:8080/a?b=1"),
    ("A page at https://acme.in/other-page", "https://acme.in/other-page"),  # not the briefed asset
])
def test_lint_finds_unbriefed_urls_in_every_form(conn, text, url):
    assert ("unbriefed_url", url) in _rules(_lint(conn, text))


@pytest.mark.parametrize("text", [
    "More at https://acme.in/", "More at HTTPS://ACME.IN", "More at acme.in", "More at www.acme.in/",
    "More at http://acme.in", "More at acme.in/solutions/compliance-training-video",
    "More at https://acme.in/solutions/compliance-training-video/",
    "We use Node.js, e.g. for tooling, i.e. daily.", "Version 3.5 shipped in Q3.",
])
def test_lint_allows_briefed_urls_and_ordinary_text(conn, text):
    assert [p for p in _lint(conn, text) if p["rule"] == "unbriefed_url"] == []


def test_lint_reads_a_name_that_looks_like_a_domain_as_a_url(conn):
    # Conservative on purpose: "ASP.NET" cannot be told from a host, so the writer rephrases it.
    assert ("unbriefed_url", "ASP.NET") in _rules(_lint(conn, "We build on ASP.NET."))


@pytest.mark.parametrize("text", ["Write to bob@example.com please", "mailto:bob@example.com",
                                  "bob.smith+x@mail.example.co.uk"])
def test_lint_flags_email_addresses(conn, text):
    problems = _lint(conn, text)
    assert "email_address" in {p["rule"] for p in problems}
    assert not [p for p in problems if p["rule"] == "unbriefed_url"]  # the domain part is not a link


# ---- the export CSV is safe to open in a spreadsheet ----

def test_export_csv_escapes_formula_cells(conn, tmp_path):
    drafted(conn)
    conn.execute("UPDATE prospects SET draft_subject = '=1+1', draft_body = '-cmd' WHERE domain = 'trainingmag.com'")
    conn.execute("UPDATE prospects SET status = 'approved' WHERE domain = 'trainingmag.com'")
    conn.commit()
    out = tmp_path / "out.csv"
    n = lo.write_export_csv(str(out), lo.export_rows(conn, PROJECT))
    import csv as csvmod
    [r] = list(csvmod.DictReader(out.open(encoding="utf-8")))
    assert n == 1 and r["subject"] == "'=1+1" and r["body"] == "'-cmd" and r["to_address"] == ""


# ---- every (from, to) transition, pinned against the spec ----

ALL_STATUSES = ("new", "drafted", "approved", "contacted", "won", "lost", "no_reply", "skipped",
                "do_not_contact")
OUTCOME_STATUSES = {"won", "lost", "no_reply"}
SPEC_LEGAL = {  # written out by hand from the spec (section 7.3), not derived from lo.TRANSITIONS
    "new": {"drafted", "skipped", "do_not_contact"},
    "drafted": {"drafted", "approved", "skipped", "do_not_contact"},
    "approved": {"drafted", "contacted", "skipped", "do_not_contact"},
    "contacted": {"drafted", "won", "lost", "no_reply", "skipped", "do_not_contact"},
    "won": {"do_not_contact"}, "lost": {"do_not_contact"}, "no_reply": {"do_not_contact"},
    "skipped": {"do_not_contact"}, "do_not_contact": set(),
}


@pytest.mark.parametrize("was_contacted", [False, True])
@pytest.mark.parametrize("frm", ALL_STATUSES)
def test_transition_table_is_exactly_the_spec(conn, frm, was_contacted):
    for to in ALL_STATUSES:
        conn.execute("UPDATE prospects SET status = ?, contacted_at = ?, updated_at = 'x' WHERE domain = ?",
                     (frm, "2026-10-01T09:00:00Z" if was_contacted else None, "trainingmag.com"))
        conn.commit()
        events_before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        legal = set(SPEC_LEGAL[frm])
        if frm in ("drafted", "approved") and was_contacted:
            legal |= OUTCOME_STATUSES  # a reply can arrive while a follow-up draft is pending
        if legal >= {to}:
            lo.transition(conn, PROJECT, "trainingmag.com", to, actor="test")
            assert row(conn)["status"] == to
            assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events_before + 1
        else:
            with pytest.raises(lo.TransitionError):
                lo.transition(conn, PROJECT, "trainingmag.com", to, actor="test")
            assert row(conn)["status"] == frm  # an illegal transition changes nothing
            assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events_before


@pytest.mark.parametrize("frm", [s for s in ALL_STATUSES if s != "drafted"])
def test_approve_only_from_drafted(conn, frm):
    conn.execute("UPDATE prospects SET status = ? WHERE domain = 'trainingmag.com'", (frm,))
    conn.commit()
    with pytest.raises(lo.TransitionError):
        lo.approve(conn, PROJECT, "trainingmag.com", "Riya")
    assert row(conn)["status"] == frm


@pytest.mark.parametrize("frm", [s for s in ALL_STATUSES if s != "approved"])
def test_contacted_only_from_approved(conn, frm):
    conn.execute("UPDATE prospects SET status = ? WHERE domain = 'trainingmag.com'", (frm,))
    conn.commit()
    with pytest.raises(lo.TransitionError):
        lo.mark(conn, PROJECT, "trainingmag.com", "contacted")
    assert row(conn)["status"] == frm


def test_mark_rejects_unknown_statuses_and_untracked_domains(conn):
    with pytest.raises(lo.TransitionError):
        lo.mark(conn, PROJECT, "trainingmag.com", "teleported")
    with pytest.raises(lo.TransitionError):
        lo.mark(conn, PROJECT, "untracked.org", "skipped")
    with pytest.raises(lo.TransitionError):
        lo.approve(conn, PROJECT, "untracked.org", "Riya")
