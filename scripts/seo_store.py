#!/usr/bin/env python3
"""
Shared local storage for claude-seo tracking scripts.

Rank tracking, AI share-of-voice tracking and KPI snapshots all need the same
thing: a small, durable, per-machine history that survives between Claude Code
sessions. This module is the one place that decides where that history lives
and how its SQLite connections are opened, so the three trackers cannot drift
apart on paths, permissions or pragmas.

Storage root (first match wins):
    1. --data-dir passed by the caller (``data_dir`` argument)
    2. CLAUDE_SEO_DATA_DIR environment variable
    3. ~/.cache/claude-seo

Each store is a single SQLite file: ``<root>/<store>/<store>.db``. Directories
are created with 0700 permissions because the files hold client data (search
queries, AI answers, traffic figures).

Per-client isolation: point CLAUDE_SEO_DATA_DIR at a per-client folder, or keep
one store and separate clients by the ``project`` column every tracker uses.

Usage:
    python seo_store.py                 # show storage root and existing stores
    python seo_store.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

DEFAULT_ROOT = Path.home() / ".cache" / "claude-seo"
ENV_VAR = "CLAUDE_SEO_DATA_DIR"
_STORE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


def data_root(data_dir: Optional[str] = None) -> Path:
    """Return the storage root directory (not created)."""
    if data_dir:
        return Path(data_dir).expanduser()
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    return DEFAULT_ROOT


def db_path(store: str, data_dir: Optional[str] = None) -> Path:
    """Return the SQLite path for a named store (not created)."""
    if not _STORE_NAME_RE.match(store):
        raise ValueError(f"invalid store name: {store!r}")
    return data_root(data_dir) / store / f"{store}.db"


def connect(store: str, schema: str, data_dir: Optional[str] = None) -> sqlite3.Connection:
    """Open (creating if needed) a store and apply its idempotent schema.

    ``schema`` must be ``CREATE ... IF NOT EXISTS`` statements so repeated
    calls are safe.
    """
    path = db_path(store, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema)
    conn.commit()
    return conn


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string with a Z suffix (second precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    """Current UTC date as YYYY-MM-DD."""
    return datetime.now(timezone.utc).date().isoformat()


def normalize_domain(value: str) -> str:
    """Reduce a URL, host or ``sc-domain:`` property to a bare lowercase host.

    >>> normalize_domain("https://www.Example.com/path?q=1")
    'example.com'
    >>> normalize_domain("sc-domain:example.com")
    'example.com'
    """
    value = (value or "").strip().lower()
    if value.startswith("sc-domain:"):
        value = value[len("sc-domain:"):]
    if "://" not in value:
        value = "https://" + value
    host = urlparse(value).hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host.rstrip(".")


def host_matches(url_or_host: str, domain: str) -> bool:
    """True when ``url_or_host`` is ``domain`` or one of its subdomains."""
    host = normalize_domain(url_or_host)
    dom = normalize_domain(domain)
    return bool(host) and bool(dom) and (host == dom or host.endswith("." + dom))


def list_stores(data_dir: Optional[str] = None) -> list[dict]:
    """List existing stores under the root with their size in bytes."""
    root = data_root(data_dir)
    out = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            db = child / f"{child.name}.db"
            if child.is_dir() and db.is_file():
                out.append({"store": child.name, "path": str(db), "bytes": db.stat().st_size})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Show claude-seo local storage locations")
    parser.add_argument("--data-dir", help=f"Override storage root (default: ${ENV_VAR} or {DEFAULT_ROOT})")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    info = {"root": str(data_root(args.data_dir)), "env_var": ENV_VAR, "stores": list_stores(args.data_dir)}
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"Storage root: {info['root']}  (override with ${ENV_VAR} or --data-dir)")
        for s in info["stores"] or []:
            print(f"  {s['store']:<20} {s['bytes']:>10,} bytes  {s['path']}")
        if not info["stores"]:
            print("  (no stores yet)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
