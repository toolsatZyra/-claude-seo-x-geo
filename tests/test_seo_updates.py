"""Ledger and CLI guards for scripts/seo_updates.py + data/google-updates.json.

Ported from AgriciDaniel/claude-seo (MIT) tests/test_content_quality.py
(seo_updates section, v2.4.1), plus regression guards for the ledger
corrections that upstream made against primary sources between v2.2.1 and
v2.4.1. Every assertion here is about the two files this module owns; skill
text is guarded separately (tests/test_canonical_facts.py).

Note for the integrator: tests/test_content_quality.py still carries the
pre-port v2.2.0 copies of ``test_seo_updates_every_entry_has_google_owned_source``
and ``test_seo_updates_filter_by_kind``. Those two encode the old behaviour
(narrower host list; ``--kind core`` excluding the combined March 2024
core+spam rollout) and are superseded by the tests below.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "google-updates.json"
SCRIPT = ROOT / "scripts" / "seo_updates.py"
sys.path.insert(0, str(ROOT / "scripts"))

import seo_updates  # noqa: E402

GOOGLE_HOSTS = {
    "developers.google.com",
    "developer.chrome.com",
    "blog.google",
    "status.search.google.com",
    "web.dev",
    "static.googleusercontent.com",  # full Search Quality Rater Guidelines PDF
    "services.google.com",
    "support.google.com",
}
ALLOWED_KINDS = {
    "core", "spam", "core+spam", "policy", "qrg", "product", "schema", "cwv",
    "discover", "documentation",
}


@pytest.fixture(scope="module")
def ledger() -> dict:
    with DATA.open(encoding="utf-8") as fh:
        return json.load(fh)


def _by_name(ledger: dict, name: str) -> dict:
    matches = [u for u in ledger["updates"] if u["name"] == name]
    assert len(matches) == 1, f"expected exactly one ledger entry named {name!r}"
    return matches[0]


# ---------------------------------------------------------------------------
# Schema, ordering, sourcing policy
# ---------------------------------------------------------------------------


def test_ledger_top_level_shape(ledger):
    assert ledger["source_of_truth"].startswith("https://status.search.google.com/")
    assert isinstance(ledger["updates"], list) and ledger["updates"]
    assert isinstance(ledger["unverified"], list)


def test_every_entry_cites_an_https_google_owned_source(ledger):
    for entry in ledger["updates"]:
        parsed = urlsplit(entry.get("source", ""))
        assert parsed.scheme == "https", entry["name"]
        assert parsed.hostname in GOOGLE_HOSTS, (
            f"{entry['name']!r} cites non-Google URL {entry['source']}; "
            "third-party-only claims belong in unverified[]"
        )
        assert parsed.username is None and parsed.password is None


def test_schema_and_order_are_enforced(ledger):
    updates = ledger["updates"]
    dates = [u["date"] for u in updates]
    names = [u["name"] for u in updates]
    assert dates == sorted(dates), "updates[] must be chronological"
    assert len(names) == len(set(names)), "update names must be unique"
    assert set(seo_updates.KNOWN_KINDS) == ALLOWED_KINDS, "CLI --kind choices drifted"
    assert all(u["kind"] in ALLOWED_KINDS for u in updates)
    assert all(u.get("notes", "").strip() for u in updates)
    assert all(date.fromisoformat(d) for d in dates)
    for kind in ALLOWED_KINDS:
        assert kind in ledger["_schema_doc"]["updates[]"]["kind"], kind

    verified = date.fromisoformat(ledger["last_verified"])
    assert verified >= date.fromisoformat(dates[-1]), "bump last_verified with new entries"
    assert verified <= date.today()


def test_primary_ledger_does_not_embed_third_party_sources(ledger):
    for entry in ledger["updates"]:
        assert "third_party_sources" not in entry
        notes = entry["notes"].lower()
        assert "unconfirmed" not in notes
        assert "reported" not in notes


def test_unverified_entries_point_at_the_status_dashboard(ledger):
    for entry in ledger["unverified"]:
        assert entry["primary_source_check"].startswith("https://status.search.google.com/")
        assert entry["status"].strip()
        assert entry["claim"].strip()
        assert entry["third_party_sources"], "an unverified claim must name its sources"


# ---------------------------------------------------------------------------
# Filtering and CLI
# ---------------------------------------------------------------------------


def test_core_filter_includes_combined_core_spam_rollouts():
    data = seo_updates._load()
    cores = seo_updates._filter(data["updates"], kinds={"core"})
    assert all(u["kind"] in {"core", "core+spam"} for u in cores)
    assert any(u["kind"] == "core+spam" for u in cores)
    assert any(u["name"] == "December 2025 Core Update" for u in cores)


def test_spam_filter_includes_combined_rollouts_and_policy_stays_exact():
    data = seo_updates._load()
    spam = seo_updates._filter(data["updates"], kinds={"spam"})
    assert all(u["kind"] in {"spam", "core+spam"} for u in spam)
    assert any(u["kind"] == "core+spam" for u in spam)
    policy = seo_updates._filter(data["updates"], kinds={"policy"})
    assert policy and all(u["kind"] == "policy" for u in policy)


def test_since_filter_accepts_year_month_and_full_dates():
    data = seo_updates._load()
    assert all(u["date"] >= "2025-01-01" for u in seo_updates._filter(data["updates"], since="2025"))
    assert all(u["date"] >= "2026-06-01" for u in seo_updates._filter(data["updates"], since="2026-06"))
    newest_first = seo_updates._filter(data["updates"], since="2026-09-01")
    assert [u["date"] for u in newest_first] == sorted((u["date"] for u in newest_first), reverse=True)


def test_cli_accepts_every_known_kind_and_reports_freshness():
    for kind in seo_updates.KNOWN_KINDS:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--kind", kind, "--json", "--limit", "1"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0, f"--kind {kind} failed: {proc.stderr}"
        payload = json.loads(proc.stdout)
        assert set(payload["freshness"]) == {"age_days", "stale", "warning"}


def test_cli_unverified_json_carries_claims_and_freshness():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--unverified", "--json"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["unverified"] and "freshness" in payload


# ---------------------------------------------------------------------------
# Freshness flag
# ---------------------------------------------------------------------------


def test_freshness_flags_a_stale_ledger():
    fresh = seo_updates.freshness("2026-09-10", today=date(2026, 9, 23))
    assert fresh == {"age_days": 13, "stale": False, "warning": None}
    stale = seo_updates.freshness("2026-07-01", today=date(2026, 9, 23))
    assert stale["stale"] and "status.search.google.com" in stale["warning"]
    assert seo_updates.freshness("not-a-date")["stale"] is True
    assert seo_updates.freshness(None)["stale"] is True
    boundary = seo_updates.freshness("2026-09-01", today=date(2026, 10, 1))
    assert boundary["age_days"] == 30 and boundary["stale"] is False


def test_stale_ledger_warns_on_stderr_in_text_mode_only(monkeypatch, capsys):
    stale = {"source_of_truth": "https://status.search.google.com/x",
             "last_verified": "2000-01-01", "updates": [], "unverified": []}
    monkeypatch.setattr(seo_updates, "_load", lambda: stale)

    monkeypatch.setattr(sys, "argv", ["seo_updates.py"])
    assert seo_updates.main() == 0
    assert "WARNING: Ledger last verified" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", ["seo_updates.py", "--json"])
    assert seo_updates.main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["freshness"]["stale"] is True


# ---------------------------------------------------------------------------
# Regression guards for primary-source corrections (upstream v2.2.1 - v2.4.1)
# ---------------------------------------------------------------------------


def test_corrected_dates_do_not_regress(ledger):
    # INP became a Core Web Vital on 2024-03-12 (web.dev/articles/inp).
    assert _by_name(ledger, "INP replaces FID")["date"] == "2024-03-12"
    # Google's "simplifying search results" post is dated 2025-06-12.
    assert _by_name(ledger, "Structured data deprecation")["date"] == "2025-06-12"


def test_regional_site_reputation_change_is_effective_august_30(ledger):
    entry = _by_name(ledger, "Site reputation abuse enforcement differs inside the EEA")
    assert entry["date"] == "2026-08-28"
    assert "effective August 30" in entry["notes"]


def test_august_2026_spam_update_completed_august_21(ledger):
    entry = _by_name(ledger, "August 2026 Spam Update")
    assert "completed August 21, 2026" in entry["notes"]


def test_primary_ledger_carries_no_third_party_attributions(ledger):
    # Earlier notes named publishers hit by enforcement and a vendor analysis;
    # none of that is in Google's own sources.
    banned = ("Forbes", "CNN", "WSJ", "Amsive", "Sterling Sky", "Semrush")
    for entry in ledger["updates"]:
        for word in banned:
            assert word not in entry["notes"], f"{entry['name']!r} cites {word}"


def test_faq_entry_makes_no_ai_citation_claim(ledger):
    notes = _by_name(ledger, "FAQ rich results retired")["notes"].lower()
    assert "citation" not in notes and "llm" not in notes


def test_retired_or_unsupported_sources_are_not_cited(ledger):
    sources = [u["source"] for u in ledger["updates"]]
    assert not any("hsw-sqrg.pdf" in s for s in sources), "QRG moved to guidelines.raterhub.com PDF"
    assert not any(s.endswith("/search/updates/ranking-update-history") for s in sources)


def test_unverifiable_claims_stay_out_of_the_primary_ledger(ledger):
    for entry in ledger["updates"]:
        text = f"{entry['name']} {entry['notes']}"
        assert "SAFE" not in text and "Scaled Abuse Forensics" not in text
        assert "Authority Signals" not in text
    claims = " ".join(e["claim"] for e in ledger["unverified"])
    assert "SAFE (Scaled Abuse Forensics Examiner)" in claims


def test_script_docstring_drops_the_promoted_march_2026_claim():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "gap-analysis-flagged" not in text
