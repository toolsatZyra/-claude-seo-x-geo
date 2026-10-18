#!/usr/bin/env python3
"""
Shared SQLite store for the seo-links scripts.

link_sources.py writes referring-domain snapshots here, link_gap.py reads them,
and link_outreach.py keeps the prospect pipeline and its audit trail. Keeping
the schema in one module means the three scripts cannot drift apart.

Location: <root>/links/links.db, where <root> is --data-dir, $CLAUDE_SEO_DATA_DIR
or ~/.cache/claude-seo (see seo_store.py). Client data: directory 0700, file 0600.

Usage:
    python link_store.py              # print the store path and table row counts
    python link_store.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from typing import Iterable, Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_store import connect, db_path, normalize_domain, utc_now  # noqa: E402

STORE = "links"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    target TEXT NOT NULL,
    source TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    row_cap_hit INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS ix_snapshots_lookup ON snapshots(project, source, target, collected_at);
CREATE TABLE IF NOT EXISTS referring_domains (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    domain TEXT NOT NULL,
    authority REAL,
    authority_scale TEXT,
    spam_score REAL,
    dofollow INTEGER,
    attributes TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT,
    last_seen TEXT,
    sample_url TEXT,
    sample_anchor TEXT,
    sample_title TEXT,
    tld TEXT,
    PRIMARY KEY (snapshot_id, domain)
);
CREATE TABLE IF NOT EXISTS prospects (
    project TEXT NOT NULL,
    domain TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT,
    segment TEXT,
    type TEXT,
    matched_rule TEXT,
    score INTEGER,
    effort TEXT,
    bucket TEXT,
    tactic TEXT,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    brief_json TEXT,
    brief_hash TEXT,
    draft_subject TEXT,
    draft_body TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    contacted_at TEXT,
    followup_at TEXT,
    outcome_at TEXT,
    link_url TEXT,
    verified_at TEXT,
    verified_status TEXT,
    link_rel TEXT,
    cooldown_until TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project, domain)
);
CREATE TABLE IF NOT EXISTS topics (
    project TEXT PRIMARY KEY,
    terms_json TEXT NOT NULL,
    origin TEXT NOT NULL,
    derived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    domain TEXT NOT NULL,
    at TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT,
    note TEXT
);
"""

RECORD_FIELDS = ("domain", "authority", "authority_scale", "spam_score", "dofollow", "attributes",
                 "first_seen", "last_seen", "sample_url", "sample_anchor", "sample_title", "tld")


def open_store(data_dir: Optional[str] = None) -> sqlite3.Connection:
    """Open (creating if needed) the links store."""
    return connect(STORE, SCHEMA, data_dir)


def save_topics(conn: sqlite3.Connection, project: str, terms: Iterable[str], origin: str,
                derived_at: Optional[str] = None) -> None:
    """Remember the topic terms derived for a project (e.g. from its sitemap), replacing older ones.

    These live in the links store only. They are never written to the user's profile file, which
    holds what the user chose; a profile ``topics`` list always wins over what is stored here.
    """
    conn.execute(
        "INSERT INTO topics (project, terms_json, origin, derived_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT(project) DO UPDATE SET terms_json = excluded.terms_json,"
        " origin = excluded.origin, derived_at = excluded.derived_at",
        (normalize_domain(project), json.dumps(list(terms)), origin, derived_at or utc_now()))
    conn.commit()


def load_topics(conn: sqlite3.Connection, project: str) -> Optional[dict]:
    """{"terms", "origin", "derived_at"} stored for a project, or None."""
    row = conn.execute("SELECT * FROM topics WHERE project = ?", (normalize_domain(project),)).fetchone()
    if row is None:
        return None
    return {"terms": json.loads(row["terms_json"]), "origin": row["origin"],
            "derived_at": row["derived_at"]}


def _unique_records(records: Iterable[dict]) -> list:
    out, seen = [], set()
    for rec in records:
        dom = normalize_domain((rec or {}).get("domain", ""))
        if not dom or dom in seen:
            continue
        seen.add(dom)
        out.append({**rec, "domain": dom})
    return out


def save_snapshot(conn: sqlite3.Connection, project: str, target: str, source: str,
                  records: Iterable[dict], row_cap_hit: bool = False,
                  cost_usd: Optional[float] = None, error: Optional[str] = None,
                  collected_at: Optional[str] = None) -> int:
    """Store one dated snapshot (records deduplicated by domain); returns its id.

    A failed fetch is stored too, with ``error`` set and no records, so the
    failure is a recorded fact rather than a silent gap.
    """
    rows = _unique_records(records)
    cur = conn.execute(
        "INSERT INTO snapshots (project, target, source, collected_at, row_count, row_cap_hit,"
        " cost_usd, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (normalize_domain(project), normalize_domain(target), source, collected_at or utc_now(),
         len(rows), int(bool(row_cap_hit)), cost_usd, error))
    snapshot_id = cur.lastrowid
    for rec in rows:
        dofollow = rec.get("dofollow")
        conn.execute(
            "INSERT INTO referring_domains (snapshot_id, domain, authority, authority_scale,"
            " spam_score, dofollow, attributes, first_seen, last_seen, sample_url, sample_anchor,"
            " sample_title, tld) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (snapshot_id, rec["domain"], rec.get("authority"), rec.get("authority_scale"),
             rec.get("spam_score"), None if dofollow is None else int(bool(dofollow)),
             json.dumps(sorted(set(rec.get("attributes") or []))), rec.get("first_seen"),
             rec.get("last_seen"), rec.get("sample_url"), rec.get("sample_anchor"),
             rec.get("sample_title"), rec.get("tld")))
    conn.commit()
    return snapshot_id


def latest_snapshots(conn: sqlite3.Connection, project: str, source: str) -> dict:
    """Latest successful snapshot per target for one project and source: {target: row}."""
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE project = ? AND source = ? AND error IS NULL"
        " ORDER BY collected_at, id", (normalize_domain(project), source)).fetchall()
    latest: dict = {}
    for row in rows:
        latest[row["target"]] = row
    return latest


def snapshot_records(conn: sqlite3.Connection, snapshot_id: int) -> list:
    """The normalized records stored for one snapshot, ordered by domain."""
    out = []
    for row in conn.execute("SELECT * FROM referring_domains WHERE snapshot_id = ? ORDER BY domain",
                            (snapshot_id,)):
        rec = {field: row[field] for field in RECORD_FIELDS}
        rec["attributes"] = json.loads(rec["attributes"] or "[]")
        rec["dofollow"] = None if rec["dofollow"] is None else bool(rec["dofollow"])
        out.append(rec)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the seo-links store location and table sizes")
    parser.add_argument("--data-dir", help="Override storage root (see seo_store.py)")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()
    conn = open_store(args.data_dir)
    counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
              for table in ("snapshots", "referring_domains", "prospects", "topics", "events")}
    result = {"path": str(db_path(STORE, args.data_dir)), "tables": counts}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["path"])
        for table, count in counts.items():
            print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
