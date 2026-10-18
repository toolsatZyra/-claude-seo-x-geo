"""links store: snapshots of referring domains, prospects and events."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import link_store  # noqa: E402


def test_roundtrip_dedup_and_types(tmp_path):
    conn = link_store.open_store(str(tmp_path))
    records = [
        {"domain": "https://www.Example.org/x", "authority": 54.0, "dofollow": True,
         "attributes": ["nofollow", "nofollow"], "sample_url": "https://example.org/a"},
        {"domain": "example.org", "authority": 1.0},
        {"domain": ""},
    ]
    sid = link_store.save_snapshot(conn, "acme.io", "comp.io", "dataforseo", records,
                                   row_cap_hit=True, cost_usd=0.02)
    snap = conn.execute("SELECT * FROM snapshots WHERE id = ?", (sid,)).fetchone()
    assert snap["row_count"] == 1 and snap["row_cap_hit"] == 1 and snap["cost_usd"] == 0.02
    [rec] = link_store.snapshot_records(conn, sid)
    assert rec["domain"] == "example.org" and rec["authority"] == 54.0
    assert rec["dofollow"] is True and rec["attributes"] == ["nofollow"]
    assert set(rec) == set(link_store.RECORD_FIELDS)


def test_latest_snapshot_ignores_errors_and_older(tmp_path):
    conn = link_store.open_store(str(tmp_path))
    old = link_store.save_snapshot(conn, "acme.io", "comp.io", "moz", [{"domain": "a.org"}],
                                   collected_at="2026-10-01T00:00:00Z")
    new = link_store.save_snapshot(conn, "acme.io", "comp.io", "moz", [{"domain": "b.org"}],
                                   collected_at="2026-10-02T00:00:00Z")
    link_store.save_snapshot(conn, "acme.io", "comp.io", "moz", [], error="HTTP 500",
                             collected_at="2026-10-03T00:00:00Z")
    link_store.save_snapshot(conn, "acme.io", "comp.io", "dataforseo", [{"domain": "c.org"}])
    latest = link_store.latest_snapshots(conn, "acme.io", "moz")
    assert old != new
    assert set(latest) == {"comp.io"} and latest["comp.io"]["id"] == new
    assert [r["domain"] for r in link_store.snapshot_records(conn, new)] == ["b.org"]


def test_failed_fetch_is_recorded_as_a_fact(tmp_path):
    conn = link_store.open_store(str(tmp_path))
    sid = link_store.save_snapshot(conn, "acme.io", "comp.io", "dataforseo", [], error="timeout")
    row = conn.execute("SELECT error, row_count FROM snapshots WHERE id = ?", (sid,)).fetchone()
    assert row["error"] == "timeout" and row["row_count"] == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_store_is_owner_only(tmp_path):
    link_store.open_store(str(tmp_path))
    db = tmp_path / "links" / "links.db"
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700
