#!/usr/bin/env python3
"""
Referring-domain collection for the seo-links skill.

Fetches (DataForSEO, Moz) or imports (CSV exports from Ahrefs, Semrush, Search
Console or any tool) the domains that link to a target, normalizes them into one
record shape, and stores a dated snapshot per target in the links store (see
link_store.py). link_gap.py scores from these snapshots; nothing here scores.

Sources:
    dataforseo  POST /v3/backlinks/backlinks/live with mode one_per_domain: one
                backlink per referring domain (URL, anchor, title, rank). Paid:
                estimated with dataforseo_costs.py, hard-capped by --max-cost,
                actual cost logged to the shared ledger. Insufficient funds stops
                the run and keeps what was already collected.
    moz         Moz linking root domains (free tier: 50 rows per call, one
                request per 10 s, 2,500 rows a month). No sample URL or anchor.
    csv-<fmt>   An export file: --format ahrefs | semrush | gsc | generic.

Credentials: DataForSEO from DATAFORSEO_USERNAME / DATAFORSEO_PASSWORD, else the
dataforseo MCP entry in ~/.claude.json (backlinks_auth.dataforseo_credentials);
Moz from backlinks_auth.get_moz_api_key. Never printed.

Usage:
    python link_sources.py status --json
    python link_sources.py fetch --project acme.io --source dataforseo --dry-run --json
    python link_sources.py fetch --project acme.io --source dataforseo --max-cost 0.25 --json
    python link_sources.py fetch --project acme.io --targets acme.io rival.com --source moz --json
    python link_sources.py import --project acme.io --target rival.com --format ahrefs refdomains.csv --json

Exit codes: 0 ok; 1 finished with per-target errors; 2 usage, credential or
budget refusal; 3 stopped early (insufficient funds or --max-cost reached).
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
from typing import Callable, Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from backlinks_auth import dataforseo_credentials, dataforseo_status, get_moz_api_key  # noqa: E402
from dataforseo_costs import record_spend, unit_cost  # noqa: E402
from link_store import open_store, save_snapshot  # noqa: E402
from seo_project import load_profile  # noqa: E402
from seo_store import normalize_domain  # noqa: E402

API_BASE = "https://api.dataforseo.com"
DFS_PATH = "/v3/backlinks/backlinks/live"
DFS_COST_KEY = "backlinks_backlinks"
DEFAULT_LIMIT = {"dataforseo": 1000, "moz": 50}
CSV_FORMATS = ("ahrefs", "semrush", "gsc", "generic")

# Header aliases per export format, matched case-insensitively. Only "domain"
# is required; extra columns are ignored.
CSV_COLUMNS = {
    "ahrefs": {"domain": ("domain", "referring domain"), "authority": ("domain rating", "dr"),
               "first_seen": ("first seen",), "last_seen": ("last seen", "lost")},
    "semrush": {"domain": ("domain", "root domain", "source domain"),
                "authority": ("domain ascore", "authority score", "ascore", "as"),
                "first_seen": ("first seen",), "last_seen": ("last seen",)},
    "gsc": {"domain": ("site", "linking site", "top linking sites", "domain")},
    "generic": {"domain": ("domain",), "authority": ("authority",), "spam_score": ("spam_score",),
                "dofollow": ("dofollow",), "sample_url": ("sample_url", "url"),
                "sample_anchor": ("sample_anchor", "anchor"),
                "sample_title": ("sample_title", "title"),
                "first_seen": ("first_seen",), "last_seen": ("last_seen",)},
}
AUTHORITY_SCALE = {"ahrefs": "ahrefs_dr", "semrush": "semrush_as", "gsc": None,
                   "generic": "generic_0_100"}


class SourceError(RuntimeError):
    """A fetch failed for one target; recorded in that target's snapshot."""


class InsufficientFunds(SourceError):
    """DataForSEO refused for lack of funds. Fatal: the run stops."""


class CsvFormatError(ValueError):
    """The file lacks the required domain column for its declared format."""


def _tld(domain: str) -> str:
    return domain.rsplit(".", 1)[-1].lower() if "." in domain else ""


def _num(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").rstrip("%")
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _date(value) -> Optional[str]:
    text = str(value or "").strip()
    return text[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", text) else None


def _bool(value) -> Optional[bool]:
    text = str(value or "").strip().lower()
    if text in ("true", "1", "yes", "y", "dofollow"):
        return True
    if text in ("false", "0", "no", "n", "nofollow"):
        return False
    return None


def _record(domain, authority=None, scale=None, spam=None, dofollow=None, attributes=None,
            first_seen=None, last_seen=None, url=None, anchor=None, title=None,
            tld=None) -> Optional[dict]:
    dom = normalize_domain(domain or "")
    if not dom:
        return None
    return {"domain": dom, "authority": authority, "authority_scale": scale, "spam_score": spam,
            "dofollow": dofollow, "attributes": sorted({str(a).lower() for a in attributes or []}),
            "first_seen": first_seen, "last_seen": last_seen, "sample_url": url or None,
            "sample_anchor": anchor or None, "sample_title": title or None,
            "tld": str(tld).rsplit(".", 1)[-1].lower() if tld else _tld(dom)}


def normalize_dataforseo_item(item: dict) -> Optional[dict]:
    """One backlinks/backlinks item (mode one_per_domain) -> normalized record.

    Authority is domain_from_rank (0-1000) / 10. The backlink-level ``rank`` is
    never used as domain authority.
    """
    rank = _num(item.get("domain_from_rank"))
    dofollow = item.get("dofollow")
    return _record(item.get("domain_from"),
                   authority=round(rank / 10, 2) if rank is not None else None,
                   scale="dataforseo_domain_rank/10",
                   spam=_num(item.get("backlink_spam_score")),
                   dofollow=dofollow if isinstance(dofollow, bool) else None,
                   attributes=item.get("attributes") or [],
                   first_seen=_date(item.get("first_seen")), last_seen=_date(item.get("last_seen")),
                   url=item.get("url_from"), anchor=item.get("anchor"),
                   title=item.get("page_from_title"), tld=item.get("tld_from"))


def normalize_moz_item(item: dict) -> Optional[dict]:
    """One moz_api.get_linking_domains entry -> normalized record (no sample text)."""
    spam = _num(item.get("spam_score"))
    return _record(item.get("domain"), authority=_num(item.get("domain_authority")),
                   scale="moz_da", spam=spam if spam is not None and spam >= 0 else None)


def import_csv(path: str, fmt: str) -> list:
    """Read an export into normalized records. Raises CsvFormatError on a missing domain column."""
    if fmt not in CSV_COLUMNS:
        raise CsvFormatError(f"unknown format {fmt!r}; use one of {', '.join(CSV_FORMATS)}")
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = [h for h in (reader.fieldnames or []) if h]
        headers = {h.strip().lower(): h for h in fieldnames}
        mapping = {}
        for field, aliases in CSV_COLUMNS[fmt].items():
            for alias in aliases:
                if alias in headers:
                    mapping[field] = headers[alias]
                    break
        if "domain" not in mapping:
            raise CsvFormatError(
                f"{path}: no domain column for format {fmt!r}. Expected one of: "
                f"{', '.join(CSV_COLUMNS[fmt]['domain'])}. Found: {', '.join(fieldnames)}")
        records = []
        for row in reader:
            def get(field):
                return row.get(mapping[field]) if field in mapping else None
            rec = _record(get("domain"), authority=_num(get("authority")),
                          scale=AUTHORITY_SCALE[fmt] if "authority" in mapping else None,
                          spam=_num(get("spam_score")),
                          dofollow=_bool(get("dofollow")) if "dofollow" in mapping else None,
                          first_seen=_date(get("first_seen")), last_seen=_date(get("last_seen")),
                          url=get("sample_url"), anchor=get("sample_anchor"),
                          title=get("sample_title"))
            if rec:
                records.append(rec)
    return records


def _dfs_post(url: str, payload: list, credentials: tuple) -> tuple:
    """POST to the fixed DataForSEO API host; returns (http_status, json body or {})."""
    import requests  # local import: --help and the CSV path work without it
    token = base64.b64encode(f"{credentials[0]}:{credentials[1]}".encode()).decode()
    resp = requests.post(url, json=payload, timeout=60,
                         headers={"Authorization": f"Basic {token}",
                                  "Content-Type": "application/json"})
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return resp.status_code, body if isinstance(body, dict) else {}


def _is_insufficient_funds(code, message: str) -> bool:
    text = (message or "").lower()
    return (code == 402 or (isinstance(code, int) and 40200 <= code < 40300)
            or "insufficient" in text or "not enough funds" in text or "payment required" in text)


def fetch_dataforseo(target: str, limit: int, credentials: tuple,
                     post: Optional[Callable] = None) -> dict:
    """One one_per_domain backlinks call for ``target``.

    Returns {"records", "cost", "row_cap_hit", "total_count"}. Raises
    InsufficientFunds (fatal for the run) or SourceError (this target only).
    """
    post = post or _dfs_post
    payload = [{"target": target, "mode": "one_per_domain", "limit": int(limit),
                "order_by": ["domain_from_rank,desc"], "backlinks_status_type": "live",
                "include_subdomains": True, "exclude_internal_backlinks": True}]
    http_status, body = post(API_BASE + DFS_PATH, payload, credentials)
    code = body.get("status_code")
    message = str(body.get("status_message") or "")
    if _is_insufficient_funds(http_status, message) or _is_insufficient_funds(code, message):
        raise InsufficientFunds(f"DataForSEO: {message or 'HTTP ' + str(http_status)}")
    if http_status != 200 or code != 20000:
        raise SourceError(f"DataForSEO HTTP {http_status}, status {code}: {message}")
    tasks = body.get("tasks") or []
    task = tasks[0] if tasks else {}
    task_code = task.get("status_code")
    task_message = str(task.get("status_message") or "")
    if _is_insufficient_funds(task_code, task_message):
        raise InsufficientFunds(f"DataForSEO: {task_message}")
    if task_code != 20000:
        raise SourceError(f"DataForSEO task status {task_code}: {task_message}")
    result = (task.get("result") or [{}])[0] or {}
    items = result.get("items") or []
    records = [r for r in (normalize_dataforseo_item(i) for i in items) if r]
    total = result.get("total_count")
    cost = _num(task.get("cost"))
    if cost is None:
        cost = _num(body.get("cost"))
    return {"records": records, "cost": cost,
            "row_cap_hit": isinstance(total, int) and total > len(items), "total_count": total}


def fetch_moz(target: str, limit: int, api_key: str, get: Optional[Callable] = None) -> dict:
    """Moz linking root domains for ``target`` (at most 50 rows per call)."""
    if get is None:
        from moz_api import get_linking_domains as get
    limit = min(int(limit), 50)
    result = get(target, api_key, limit=limit)
    if result.get("status") != "success":
        raise SourceError(f"Moz: {result.get('error') or result.get('status')}")
    items = (result.get("data") or {}).get("referring_domains") or []
    records = [r for r in (normalize_moz_item(i) for i in items) if r]
    return {"records": records, "cost": None, "row_cap_hit": len(items) >= limit,
            "total_count": None}


def resolve_targets(project: str, targets: Optional[list], data_dir: Optional[str]) -> list:
    """Explicit targets, else the profile's domain plus its competitors (client first)."""
    if targets:
        wanted = [normalize_domain(t) for t in targets]
    else:
        profile = load_profile(normalize_domain(project), data_dir)
        if not profile:
            raise ValueError(f"no profile for {normalize_domain(project)}: pass --targets or run "
                             "seo_project.py init with --competitor")
        wanted = [normalize_domain(profile["domain"])] + [
            normalize_domain(c["domain"]) for c in profile.get("competitors") or [] if c.get("domain")]
    out, seen = [], set()
    for target in wanted:
        if target and target not in seen:
            seen.add(target)
            out.append(target)
    return out


def run_fetch(conn, project: str, targets: list, source: str, limit: int, max_cost: float,
              fetcher: Callable, unit_cost: float = 0.0, spend: Optional[Callable] = None) -> dict:
    """Fetch each target into a snapshot.

    Stops on InsufficientFunds, or before a call that would take the run past
    ``max_cost`` (only when ``unit_cost`` > 0). ``spend(amount, target, estimated)``
    is called once per paid call: the response's cost, or ``unit_cost`` flagged
    as an estimate when the response carried none.
    """
    spent = 0.0
    rows, stopped, errors = [], None, 0
    for target in targets:
        if unit_cost and spent + unit_cost > max_cost + 1e-9:
            stopped = "max_cost_reached"
            break
        try:
            got = fetcher(target, limit)
        except InsufficientFunds as exc:
            sid = save_snapshot(conn, project, target, source, [], error=str(exc))
            rows.append({"target": target, "snapshot_id": sid, "error": str(exc)})
            stopped = "insufficient_funds"
            break
        except SourceError as exc:
            sid = save_snapshot(conn, project, target, source, [], error=str(exc))
            rows.append({"target": target, "snapshot_id": sid, "error": str(exc)})
            errors += 1
            continue
        cost = got.get("cost")
        if unit_cost:
            amount = cost if cost is not None else unit_cost
            spent += amount
            if spend:
                spend(amount, target, cost is None)
        sid = save_snapshot(conn, project, target, source, got["records"],
                            row_cap_hit=got["row_cap_hit"], cost_usd=cost)
        rows.append({"target": target, "snapshot_id": sid, "rows": len(got["records"]),
                     "row_cap_hit": got["row_cap_hit"], "cost_usd": cost, "error": None})
    done = sum(1 for r in rows if not r.get("error"))
    return {"project": normalize_domain(project), "source": source, "targets": rows,
            "coverage": f"{done} of {len(targets)}", "spent_usd": round(spent, 4),
            "stopped": stopped, "errors": errors}


def _emit(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    for key, value in result.items():
        if key != "targets":
            print(f"{key}: {value}")
    for row in result.get("targets", []):
        if row.get("error"):
            print(f"  {row['target']}: ERROR {row['error']}")
        else:
            capped = " (row cap hit)" if row.get("row_cap_hit") else ""
            print(f"  {row['target']}: {row['rows']} referring domains{capped}")


def cmd_status(args) -> int:
    dfs = dataforseo_status()
    result = {"dataforseo": {k: dfs[k] for k in ("mcp_configured", "stale_config", "rest_credentials",
                                                  "rest_credentials_source", "fix")},
              "moz": {"available": bool(get_moz_api_key())},
              "csv": {"available": True, "formats": list(CSV_FORMATS)}}
    _emit(result, args.json)
    return 0


def cmd_fetch(args) -> int:
    try:
        targets = resolve_targets(args.project, args.targets, args.data_dir)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    limit = args.limit or DEFAULT_LIMIT[args.source]
    if args.source == "dataforseo":
        unit = unit_cost(DFS_COST_KEY) or 0.02
        estimate = round(unit * len(targets), 4)
        if args.dry_run:
            _emit({"source": "dataforseo", "calls": len(targets), "targets_planned": targets,
                   "unit_cost_usd": unit, "estimated_cost_usd": estimate,
                   "max_cost_usd": args.max_cost, "rows_per_target": limit}, args.json)
            return 0
        if estimate > args.max_cost + 1e-9:
            print(f"Error: estimated ${estimate:.2f} for {len(targets)} calls exceeds --max-cost "
                  f"${args.max_cost:.2f}. Raise --max-cost or pass fewer --targets.", file=sys.stderr)
            return 2
        creds = dataforseo_credentials()
        if not creds:
            print("Error: no DataForSEO credentials found. Run /seo links setup "
                  "(backlinks_auth.py --check dataforseo).", file=sys.stderr)
            return 2

        def fetcher(target, lim):
            return fetch_dataforseo(target, lim, creds)

        def spend(amount, target, estimated):
            note = f"link_sources {target}" + (" (estimated)" if estimated else "")
            record_spend(DFS_COST_KEY, amount, note=note)
    else:
        if args.dry_run:
            _emit({"source": "moz", "calls": len(targets), "targets_planned": targets,
                   "estimated_cost_usd": 0.0, "rows_per_target": min(limit, 50),
                   "note": "Moz free tier: 2,500 rows a month"}, args.json)
            return 0
        key = get_moz_api_key()
        if not key:
            print("Error: no Moz API key found. Run /seo links setup (backlinks_auth.py --setup).",
                  file=sys.stderr)
            return 2

        def fetcher(target, lim):
            return fetch_moz(target, lim, key)

        unit, spend = 0.0, None
    conn = open_store(args.data_dir)
    result = run_fetch(conn, args.project, targets, args.source, limit, args.max_cost, fetcher,
                       unit_cost=unit, spend=spend)
    if args.source == "moz":
        result["note"] = "Moz free tier: 2,500 rows a month; at most 50 rows per target"
    _emit(result, args.json)
    if result["stopped"]:
        return 3
    return 1 if result["errors"] else 0


def cmd_import(args) -> int:
    try:
        records = import_csv(args.file, args.format)
    except (CsvFormatError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    source = f"csv-{args.format}"
    conn = open_store(args.data_dir)
    sid = save_snapshot(conn, args.project, args.target, source, records)
    _emit({"project": normalize_domain(args.project), "source": source,
           "target": normalize_domain(args.target), "snapshot_id": sid, "rows": len(records)},
          args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", help="Storage root (default $CLAUDE_SEO_DATA_DIR or ~/.cache/claude-seo)")
    common.add_argument("--json", action="store_true", help="Output JSON")
    parser = argparse.ArgumentParser(description="Fetch or import referring domains into dated snapshots (seo-links)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", parents=[common], help="Which sources are usable now")
    f = sub.add_parser("fetch", parents=[common], help="Fetch referring domains for the client and competitors")
    f.add_argument("--project", required=True, help="Client domain (profile slug)")
    f.add_argument("--source", required=True, choices=("dataforseo", "moz"))
    f.add_argument("--targets", nargs="+", help="Domains to fetch (default: profile domain + competitors)")
    f.add_argument("--limit", type=int, help="Rows per target (default 1000 DataForSEO, 50 Moz)")
    f.add_argument("--max-cost", type=float, default=1.0, help="Hard USD cap for this run (DataForSEO)")
    f.add_argument("--dry-run", action="store_true", help="Print the cost estimate and exit")
    i = sub.add_parser("import", parents=[common], help="Import an export file as one snapshot")
    i.add_argument("--project", required=True, help="Client domain (profile slug)")
    i.add_argument("--target", required=True, help="The domain the export describes")
    i.add_argument("--format", required=True, choices=CSV_FORMATS)
    i.add_argument("file")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    return {"status": cmd_status, "fetch": cmd_fetch, "import": cmd_import}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
