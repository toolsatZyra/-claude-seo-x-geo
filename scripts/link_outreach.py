#!/usr/bin/env python3
"""
Link-earning pipeline for the seo-links skill: tracker, briefs, drafts, verification.

Nothing is ever sent. Claude writes outreach drafts from a structured brief;
this script lints them, a named person approves them, that person sends them
from their own email and marks the outcome here. Won links are checked on the
linking page before they count as verified.

States:
    new -> drafted -> approved -> contacted -> won | lost | no_reply
    any -> do_not_contact (permanent)        any non-terminal -> skipped
    contacted -> drafted (one follow-up, at least 7 days after first contact)
    lost / no_reply start a 90-day cooldown before the domain can be re-added.

Usage:
    python link_outreach.py add --project acme.io --source dataforseo --top 20 --json
    python link_outreach.py brief --project acme.io --domain trainingmag.com --json
    python link_outreach.py save-draft --project acme.io --domain trainingmag.com \
        --brief-hash HASH --subject "..." --body-file draft.txt --json
    python link_outreach.py approve --project acme.io --domain trainingmag.com --reviewed-by "Name"
    python link_outreach.py mark --project acme.io --domain trainingmag.com --status contacted
    python link_outreach.py mark --project acme.io --domain trainingmag.com --status won --link-url URL
    python link_outreach.py verify --project acme.io --json
    python link_outreach.py board --project acme.io --json
    python link_outreach.py export --project acme.io --out outreach.csv
    python link_outreach.py kpis --project acme.io --emit-kpis kpis-links.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from link_gap import GapError, analyze_project, fold_words  # noqa: E402
from link_store import open_store  # noqa: E402
from seo_kpi import EnvelopeError, write_envelope  # noqa: E402
from seo_project import load_profile  # noqa: E402
from seo_store import host_matches, normalize_domain, utc_now  # noqa: E402

ACTIVE = ("new", "drafted", "approved", "contacted")
TERMINAL = ("won", "lost", "no_reply", "skipped", "do_not_contact")
TRANSITIONS = {
    "new": {"drafted", "skipped", "do_not_contact"},
    "drafted": {"drafted", "approved", "skipped", "do_not_contact"},
    "approved": {"drafted", "contacted", "skipped", "do_not_contact"},
    "contacted": {"drafted", "won", "lost", "no_reply", "skipped", "do_not_contact"},
    "won": {"do_not_contact"},
    "lost": {"do_not_contact"},
    "no_reply": {"do_not_contact"},
    "skipped": {"do_not_contact"},
    "do_not_contact": set(),
}
FOLLOWUP_MIN_DAYS = 7
COOLDOWN_DAYS = 90
MAX_BODY_WORDS = 150
MAX_SUBJECT_CHARS = 90
MIN_CONTACTS_FOR_RATE = 5
BANNED_TERMS = ("pay", "payment", "paid", "sponsor", "sponsored", "sponsorship", "link exchange",
                "swap links", "reciprocal", "guest post fee", "dofollow", "do-follow")
REL_ORDER = ("sponsored", "ugc", "nofollow")
VERIFY_MAP = {"verified": "live", "link_removed": "missing", "lost": "missing"}
MARK_STATUSES = ("contacted", "won", "lost", "no_reply", "skipped", "do_not_contact")


class TransitionError(ValueError):
    """An action that the pipeline rules do not allow. Nothing was changed."""


def _today(today: Optional[date] = None) -> date:
    return today or datetime.now(timezone.utc).date()


def _get(conn, project: str, domain: str):
    return conn.execute("SELECT * FROM prospects WHERE project = ? AND domain = ?",
                        (project, domain)).fetchone()


def _event(conn, project, domain, frm, to, actor=None, note=None, at=None) -> None:
    conn.execute("INSERT INTO events (project, domain, at, from_status, to_status, actor, note)"
                 " VALUES (?, ?, ?, ?, ?, ?, ?)", (project, domain, at or utc_now(), frm, to, actor, note))


def _update(conn, project: str, domain: str, fields: dict) -> None:
    sets = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(f"UPDATE prospects SET {sets} WHERE project = ? AND domain = ?",
                 (*fields.values(), project, domain))


def transition(conn, project: str, domain: str, to_status: str, actor: Optional[str] = None,
               note: Optional[str] = None, fields: Optional[dict] = None,
               now: Optional[str] = None) -> dict:
    """Move one prospect to ``to_status`` if TRANSITIONS allows it; log the event."""
    row = _get(conn, project, domain)
    if row is None:
        raise TransitionError(f"{domain} is not tracked for {project}; run add first")
    frm = row["status"]
    if to_status not in TRANSITIONS[frm]:
        raise TransitionError(f"{domain}: cannot go from {frm} to {to_status}")
    at = now or utc_now()
    _update(conn, project, domain, {"status": to_status, "updated_at": at, **(fields or {})})
    _event(conn, project, domain, frm, to_status, actor, note, at)
    conn.commit()
    return dict(_get(conn, project, domain))


def add_prospects(conn, project: str, prospects: list, source: str,
                  today: Optional[date] = None, now: Optional[str] = None) -> dict:
    """Track new prospects; respects suppression, active status and cooldown."""
    day = _today(today).isoformat()
    at = now or utc_now()
    added, skipped = [], []
    for p in prospects:
        dom = p["domain"]
        values = {"source": source, "segment": p["segment"], "type": p["type"],
                  "matched_rule": p["matched_rule"], "score": p["score"], "effort": p["effort"],
                  "bucket": p["bucket"], "tactic": p["tactic"],
                  "evidence_json": json.dumps(p["evidence"], sort_keys=True)}
        row = _get(conn, project, dom)
        if row is None:
            conn.execute(
                "INSERT INTO prospects (project, domain, status, source, segment, type, matched_rule,"
                " score, effort, bucket, tactic, evidence_json, created_at, updated_at)"
                " VALUES (?, ?, 'new', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project, dom, *values.values(), at, at))
            _event(conn, project, dom, None, "new", "link_outreach.py add", None, at)
            added.append(dom)
            continue
        status = row["status"]
        if status == "do_not_contact":
            skipped.append({"domain": dom, "reason": "do_not_contact"})
        elif status in ACTIVE:
            skipped.append({"domain": dom, "reason": f"already tracked ({status})"})
        elif status == "won":
            skipped.append({"domain": dom, "reason": "already won"})
        elif row["cooldown_until"] and row["cooldown_until"] > day:
            skipped.append({"domain": dom, "reason": f"cooldown until {row['cooldown_until']}"})
        else:
            _update(conn, project, dom, {
                **values, "status": "new", "brief_json": None, "brief_hash": None,
                "draft_subject": None, "draft_body": None, "reviewed_by": None,
                "reviewed_at": None, "contacted_at": None, "followup_at": None,
                "outcome_at": None, "link_url": None, "verified_at": None,
                "verified_status": None, "link_rel": None, "cooldown_until": None,
                "updated_at": at})
            _event(conn, project, dom, status, "new", "link_outreach.py add", "re-added", at)
            added.append(dom)
    conn.commit()
    return {"added": added, "skipped": skipped}


def _norm_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return f"{parsed.scheme.lower()}://{normalize_domain(parsed.netloc)}{parsed.path.rstrip('/') or '/'}"


def best_asset(client: str, pages: list, evidence: list) -> str:
    """The client page whose path words overlap the evidence most; the homepage if none do."""
    words: set = set()
    for e in evidence:
        for text in (e.get("sample_title"), e.get("sample_url"), e.get("sample_anchor")):
            words.update(fold_words(text or ""))
    best, best_key = f"https://{client}/", None
    for page in sorted(set(pages or [])):
        url = page if page.startswith("http") else f"https://{client}/{page.lstrip('/')}"
        if not host_matches(url, client):
            continue
        overlap = len(set(fold_words(urlparse(url).path)) & words)
        key = (overlap, -len(url))
        if overlap and (best_key is None or key > best_key):
            best, best_key = url, key
    return best


def build_brief(profile: dict, row, pages: list) -> dict:
    """Everything a draft may use. Claims and URLs outside the brief fail the lint."""
    client = normalize_domain(profile["domain"])
    name = profile.get("name") or client
    evidence = json.loads(row["evidence_json"] or "[]")
    notes = [n["text"] for n in profile.get("notes") or []
             if isinstance(n, dict) and n.get("approved_by") == "user" and n.get("text")]
    contact = next((e["sample_url"] for e in evidence if e.get("sample_url") and re.search(
        r"/(?:contact|write-for-us|about)(?:/|$)", urlparse(e["sample_url"]).path.lower())), None)
    brief = {
        "project": client, "client_name": name, "prospect": row["domain"], "type": row["type"],
        "matched_rule": row["matched_rule"], "segment": row["segment"], "tactic": row["tactic"],
        "competitors_linked": sorted({e["competitor"] for e in evidence}),
        "evidence": [{k: e.get(k) for k in ("competitor", "sample_url", "sample_anchor", "sample_title")}
                     for e in evidence],
        "asset_url": best_asset(client, pages, evidence),
        "client_home": f"https://{client}/",
        "allowed_claims": [f"{name} ({client})", *[f"Works on: {t}" for t in profile.get("topics") or []],
                           *notes],
        "contact_path": contact,
        "followup": row["status"] == "contacted",
        "rules": [
            f"One ask, at most {MAX_BODY_WORDS} words, subject at most {MAX_SUBJECT_CHARS} characters.",
            "Claim only what is in allowed_claims; never invent clients, results or numbers.",
            "Never offer or mention payment, sponsorship, link swaps, reciprocal links or dofollow.",
            "Link only to asset_url or client_home; no other URLs.",
            "Personalize from the evidence: say why the page fits their readers.",
        ],
    }
    brief["brief_hash"] = hashlib.sha256(json.dumps(brief, sort_keys=True).encode()).hexdigest()[:16]
    return brief


def store_brief(conn, project: str, domain: str, brief: dict) -> None:
    """Save the brief on the prospect (no status change). Only active prospects get briefs."""
    row = _get(conn, project, domain)
    if row is None:
        raise TransitionError(f"{domain} is not tracked for {project}; run add first")
    if row["status"] not in ACTIVE:
        raise TransitionError(f"{domain} is {row['status']}; briefs are only for active prospects")
    _update(conn, project, domain, {"brief_json": json.dumps(brief, sort_keys=True),
                                    "brief_hash": brief["brief_hash"], "updated_at": utc_now()})
    conn.commit()


def lint_draft(subject: str, body: str, brief: dict) -> list:
    """Deterministic draft checks: banned asks, unbriefed URLs, length."""
    problems = []
    text = f"{subject}\n{body}".lower()
    for term in BANNED_TERMS:
        pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(w) for w in term.split()) + r"(?![a-z0-9])"
        for m in re.finditer(pattern, text):
            span = text[max(0, m.start() - 25): m.end() + 25].replace("\n", " ")
            problems.append({"rule": "banned_term", "term": term, "span": span})
    allowed = {_norm_url(u) for u in [brief.get("asset_url"), brief.get("client_home"),
                                       brief.get("contact_path"),
                                       *[e.get("sample_url") for e in brief.get("evidence", [])]] if u}
    for url in re.findall(r"https?://[^\s<>()\"']+", f"{subject} {body}"):
        url = url.rstrip(".,;:!?")
        if _norm_url(url) not in allowed:
            problems.append({"rule": "unbriefed_url", "url": url})
    words = len(body.split())
    if words > MAX_BODY_WORDS:
        problems.append({"rule": "body_too_long", "words": words, "max": MAX_BODY_WORDS})
    if len(subject) > MAX_SUBJECT_CHARS:
        problems.append({"rule": "subject_too_long", "chars": len(subject), "max": MAX_SUBJECT_CHARS})
    if not subject.strip() or not body.strip():
        problems.append({"rule": "empty"})
    return problems


def save_draft(conn, project: str, domain: str, subject: str, body: str, brief_hash: str,
               today: Optional[date] = None, now: Optional[str] = None) -> dict:
    """Lint and store a draft; any edit clears a previous approval."""
    row = _get(conn, project, domain)
    if row is None:
        raise TransitionError(f"{domain} is not tracked for {project}; run add first")
    if row["status"] not in ACTIVE:
        raise TransitionError(f"{domain} is {row['status']}; drafts are only for active prospects")
    if not row["brief_json"]:
        raise TransitionError(f"{domain} has no brief; run brief first")
    if brief_hash != row["brief_hash"]:
        return {"ok": False, "problems": [{"rule": "stale_brief", "expected": row["brief_hash"],
                                           "got": brief_hash}]}
    problems = lint_draft(subject, body, json.loads(row["brief_json"]))
    if problems:
        return {"ok": False, "problems": problems}
    if row["status"] == "contacted":
        if row["followup_at"]:
            raise TransitionError(f"{domain}: one follow-up only, and it was already sent")
        first = date.fromisoformat(row["contacted_at"][:10])
        if (_today(today) - first).days < FOLLOWUP_MIN_DAYS:
            raise TransitionError(f"{domain}: follow-up allowed from "
                                  f"{first + timedelta(days=FOLLOWUP_MIN_DAYS)}")
    updated = transition(conn, project, domain, "drafted", actor="link_outreach.py save-draft",
                         fields={"draft_subject": subject, "draft_body": body,
                                 "reviewed_by": None, "reviewed_at": None}, now=now)
    return {"ok": True, "prospect": _public(updated)}


def approve(conn, project: str, domain: str, reviewed_by: str, now: Optional[str] = None) -> dict:
    """Record a named human approval of the current draft."""
    name = (reviewed_by or "").strip()
    if not name:
        raise TransitionError("--reviewed-by is required: a named person must approve each draft")
    row = _get(conn, project, domain)
    if row is not None and row["status"] != "drafted":
        raise TransitionError(f"{domain}: only a drafted prospect can be approved (status {row['status']})")
    at = now or utc_now()
    return transition(conn, project, domain, "approved", actor=name,
                      fields={"reviewed_by": name, "reviewed_at": at}, now=at)


def mark(conn, project: str, domain: str, status: str, link_url: Optional[str] = None,
         note: Optional[str] = None, today: Optional[date] = None, now: Optional[str] = None) -> dict:
    """Record what happened after a person acted (sent, won, lost, ...)."""
    row = _get(conn, project, domain)
    if row is None:
        raise TransitionError(f"{domain} is not tracked for {project}; run add first")
    at = now or utc_now()
    if status == "contacted":
        if row["status"] != "approved":
            raise TransitionError(f"{domain}: mark contacted only after approval "
                                  "(approve --reviewed-by NAME)")
        fields = {"contacted_at": at} if not row["contacted_at"] else {"followup_at": at}
    elif status == "won":
        if not link_url:
            raise TransitionError("--link-url is required for won (the page that now links to you)")
        if not host_matches(link_url, domain):
            raise TransitionError(f"--link-url must be a page on {domain}")
        fields = {"link_url": link_url, "outcome_at": at, "verified_status": None,
                  "verified_at": None, "link_rel": None}
    elif status in ("lost", "no_reply"):
        fields = {"outcome_at": at,
                  "cooldown_until": (_today(today) + timedelta(days=COOLDOWN_DAYS)).isoformat()}
    elif status in ("skipped", "do_not_contact"):
        fields = {"outcome_at": at}
    else:
        raise TransitionError(f"unknown status {status!r}; use one of {', '.join(MARK_STATUSES)}")
    return transition(conn, project, domain, status, actor="link_outreach.py mark", note=note,
                      fields=fields, now=at)


def verify(conn, project: str, domain: Optional[str] = None, verifier: Optional[Callable] = None,
           now: Optional[str] = None) -> list:
    """Check won links on their pages; an unreachable page stays won, marked unverified."""
    if verifier is None:
        from verify_backlinks import verify_single_backlink as verifier
    query = "SELECT * FROM prospects WHERE project = ? AND status = 'won' AND link_url IS NOT NULL"
    params: tuple = (project,)
    if domain:
        query += " AND domain = ?"
        params = (project, domain)
    out = []
    for row in conn.execute(query + " ORDER BY domain", params).fetchall():
        result = verifier(row["link_url"], f"https://{project}/")
        status = VERIFY_MAP.get(result.get("status"), "unreachable")
        rels = [str(r).lower() for r in result.get("rel_attributes") or []]
        rel = next((r for r in REL_ORDER if r in rels), "dofollow") if status == "live" else None
        at = now or utc_now()
        _update(conn, project, row["domain"], {"verified_status": status, "verified_at": at,
                                               "link_rel": rel, "updated_at": at})
        _event(conn, project, row["domain"], "won", "won", "link_outreach.py verify",
               f"verified_status={status}", at)
        out.append({"domain": row["domain"], "link_url": row["link_url"], "verified_status": status,
                    "link_rel": rel, "checker_status": result.get("status")})
    conn.commit()
    return out


def outreach_kpis(conn, project: str) -> dict:
    rows = conn.execute("SELECT status, contacted_at, verified_status FROM prospects WHERE project = ?",
                        (project,)).fetchall()
    contacted = sum(1 for r in rows if r["contacted_at"])
    won = sum(1 for r in rows if r["status"] == "won")
    return {"links.prospects": sum(1 for r in rows if r["status"] in ACTIVE),
            "links.contacted": contacted, "links.won": won,
            "links.won_verified": sum(1 for r in rows if r["status"] == "won"
                                      and r["verified_status"] == "live"),
            "links.win_rate": round(won / contacted, 4) if contacted >= MIN_CONTACTS_FOR_RATE else None}


def export_rows(conn, project: str, include_all: bool = False) -> list:
    """Rows for the person's own email tool or CRM. The address column is left blank."""
    query = "SELECT * FROM prospects WHERE project = ?" + ("" if include_all else " AND status = 'approved'")
    out = []
    for r in conn.execute(query + " ORDER BY score DESC, domain", (project,)):
        brief = json.loads(r["brief_json"] or "{}")
        out.append({"domain": r["domain"], "contact_path": brief.get("contact_path") or "",
                    "to_address": "", "subject": r["draft_subject"] or "",
                    "body": r["draft_body"] or "", "status": r["status"],
                    "reviewed_by": r["reviewed_by"] or ""})
    return out


def _public(row: dict) -> dict:
    out = {k: v for k, v in dict(row).items() if k not in ("evidence_json", "brief_json")}
    out["evidence_count"] = len(json.loads(dict(row).get("evidence_json") or "[]"))
    return out


def board(conn, project: str) -> dict:
    order = {s: i for i, s in enumerate(ACTIVE + TERMINAL)}
    rows = [_public(r) for r in conn.execute("SELECT * FROM prospects WHERE project = ?", (project,))]
    rows.sort(key=lambda r: (order.get(r["status"], 99), -(r["score"] or 0), r["domain"]))
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"project": project, "counts": counts, "prospects": rows}


def _emit(result, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps(result, indent=2, default=str) if not isinstance(result, str) else result)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True, help="Client domain (profile slug)")
    common.add_argument("--data-dir", help="Storage root (default $CLAUDE_SEO_DATA_DIR or ~/.cache/claude-seo)")
    common.add_argument("--json", action="store_true", help="Output JSON")
    parser = argparse.ArgumentParser(description="Link-earning pipeline: nothing is ever sent (seo-links)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", parents=[common], help="Track top prospects from link_gap")
    a.add_argument("--source", required=True, help="Snapshot source used by link_gap.py")
    a.add_argument("--top", type=int, default=20)
    a.add_argument("--buckets", default="high_value,quick_win",
                   help="Comma-separated buckets, or 'all' (default high_value,quick_win)")
    a.add_argument("--min-score", type=int, default=0)
    a.add_argument("--no-sitemap", action="store_true")
    b = sub.add_parser("brief", parents=[common], help="Build and store the brief for one prospect")
    b.add_argument("--domain", required=True)
    b.add_argument("--pages", nargs="*", default=None, help="Client pages to choose the asset from")
    b.add_argument("--sitemap", action="store_true", help="Also read the client sitemap for pages")
    d = sub.add_parser("save-draft", parents=[common], help="Lint and store a draft")
    d.add_argument("--domain", required=True)
    d.add_argument("--brief-hash", required=True)
    d.add_argument("--subject", required=True)
    d.add_argument("--body-file", required=True, help="UTF-8 text file with the email body")
    p = sub.add_parser("approve", parents=[common], help="Named human approval of the current draft")
    p.add_argument("--domain", required=True)
    p.add_argument("--reviewed-by", required=True)
    m = sub.add_parser("mark", parents=[common], help="Record an outcome after a person acted")
    m.add_argument("--domain", required=True)
    m.add_argument("--status", required=True, choices=MARK_STATUSES)
    m.add_argument("--link-url")
    m.add_argument("--note")
    v = sub.add_parser("verify", parents=[common], help="Check won links on their pages")
    v.add_argument("--domain")
    sub.add_parser("board", parents=[common], help="Pipeline status board")
    e = sub.add_parser("export", parents=[common], help="CSV for your own email tool or CRM")
    e.add_argument("--out", required=True)
    e.add_argument("--all", action="store_true", help="All statuses, not only approved")
    k = sub.add_parser("kpis", parents=[common], help="Write links.* pipeline KPIs")
    k.add_argument("--emit-kpis", required=True)
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    project = normalize_domain(args.project)
    conn = open_store(args.data_dir)
    try:
        if args.cmd == "add":
            analysis = analyze_project(project, args.source, args.data_dir,
                                       use_sitemap=not args.no_sitemap)
            wanted = None if args.buckets == "all" else set(args.buckets.split(","))
            picked = [p for p in analysis["prospects"]
                      if (wanted is None or p["bucket"] in wanted) and p["score"] >= args.min_score]
            result = add_prospects(conn, project, picked[:args.top], args.source)
            result["warnings"] = analysis["warnings"]
        elif args.cmd == "brief":
            profile = load_profile(project, args.data_dir)
            if not profile:
                raise TransitionError(f"no profile for {project}")
            row = _get(conn, project, normalize_domain(args.domain))
            if row is None:
                raise TransitionError(f"{args.domain} is not tracked for {project}; run add first")
            pages = list(args.pages or []) + list(profile.get("money_pages") or [])
            if args.sitemap:
                from competitor_gap import crawl_domain
                pages += crawl_domain(project).get("urls") or []
            result = build_brief(profile, row, pages)
            store_brief(conn, project, row["domain"], result)
        elif args.cmd == "save-draft":
            with open(args.body_file, encoding="utf-8") as handle:
                body = handle.read().strip()
            result = save_draft(conn, project, normalize_domain(args.domain), args.subject, body,
                                args.brief_hash)
            _emit(result, args.json)
            return 0 if result["ok"] else 1
        elif args.cmd == "approve":
            result = _public(approve(conn, project, normalize_domain(args.domain), args.reviewed_by))
        elif args.cmd == "mark":
            result = _public(mark(conn, project, normalize_domain(args.domain), args.status,
                                  link_url=args.link_url, note=args.note))
        elif args.cmd == "verify":
            result = verify(conn, project, normalize_domain(args.domain) if args.domain else None)
        elif args.cmd == "board":
            result = board(conn, project)
        elif args.cmd == "export":
            rows = export_rows(conn, project, include_all=args.all)
            with open(args.out, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["domain", "contact_path", "to_address",
                                                            "subject", "body", "status", "reviewed_by"])
                writer.writeheader()
                writer.writerows(rows)
            result = {"out": args.out, "rows": len(rows)}
        else:
            result = write_envelope(args.emit_kpis, project, "link_outreach.py",
                                    outreach_kpis(conn, project))
    except (TransitionError, GapError, EnvelopeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    _emit(result, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
