#!/usr/bin/env python3
"""
Client / project profile shared by every research, content and tracking skill.

One JSON file per client holds the facts every skill otherwise re-asks for:
domain, brand terms, 3-7 competitors, target audiences, market, the exact
Search Console property string, the GA4 property ID, money pages, conversion
events, brand-voice samples and the AI-visibility prompt panel. Skills read it
with ``load_profile()``; operators edit it with this CLI or by hand.

Files live at ``<data root>/projects/<host>.json`` (see seo_store.py for the
root), named by the normalized host itself so two clients can never share a
file (``my-site.com`` and ``my.site.com`` stay distinct). They contain client data, so they are written with 0600 permissions and
never belong in the repository.

Usage:
    python seo_project.py init example.com --name "Example Co" \
        --brand "example" --competitor rival.com --competitor other.io \
        --gsc-property sc-domain:example.com --ga4-property 123456789
    python seo_project.py show example.com [--json]
    python seo_project.py set example.com markets.country GB
    python seo_project.py set example.com money_pages '["/pricing", "/demo"]'
    python seo_project.py add-competitor example.com rival.com --name Rival
    python seo_project.py add-prompt example.com "best crm for startups" --group treatment
    python seo_project.py note example.com "Client approved BOFU-first plan" --approved-by user
    python seo_project.py list
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_store import data_root, normalize_domain, utc_now  # noqa: E402

SCHEMA_VERSION = 1
MAX_COMPETITORS = 10
RECOMMENDED_COMPETITORS = (3, 7)
MAX_PROMPTS = 200

DEFAULT_PROFILE: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "slug": "",
    "domain": "",
    "name": "",
    "business_type": "",          # saas | ecommerce | local | publisher | agency | other
    "brand_terms": [],            # strings that identify the client in queries / AI answers
    "competitors": [],            # [{"name", "domain", "aliases": []}]
    "audiences": [],              # free-text personas
    "markets": {"country": "US", "language": "en"},
    "gsc_property": "",           # exact string, e.g. "sc-domain:example.com"
    "ga4_property": "",
    "money_pages": [],            # paths/URLs that convert (pricing, demo, contact)
    "conversion_events": [],      # GA4 key event names (generate_lead, form_submit ...)
    "voice_samples": [],          # URLs or local paths of on-brand published posts
    "content": {
        "cadence_per_week": 2,
        "default_status": "draft",   # export adapters never publish unless reviewed
        "cms": "",                   # wordpress | webhook | markdown
    },
    "ai_visibility": {"prompts": []},  # [{"prompt", "group", "funnel", "added_at"}]
    "notes": [],                  # [{"at", "text", "approved_by": "user"|"inferred"}]
    "created_at": "",
    "updated_at": "",
}


_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$")


def slugify(domain: str) -> str:
    """Collision-free filename key for a domain: the normalized host itself.

    Hostnames only contain [a-z0-9.-], which are safe in filenames, so no
    lossy transformation is needed (an earlier dash-joined scheme mapped
    my-site.com and my.site.com to the same file).
    """
    host = normalize_domain(domain)
    if not host or not _HOST_RE.match(host):
        raise ValueError(f"not a domain: {domain!r}")
    return host


def projects_dir(data_dir: Optional[str] = None) -> Path:
    return data_root(data_dir) / "projects"


def profile_path(domain: str, data_dir: Optional[str] = None) -> Path:
    """Path of a domain's profile file. Raises ValueError for non-domains."""
    return projects_dir(data_dir) / f"{slugify(domain)}.json"


def _merge_defaults(profile: dict) -> dict:
    merged = copy.deepcopy(DEFAULT_PROFILE)
    for key, value in profile.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def load_profile(domain: str, data_dir: Optional[str] = None) -> Optional[dict]:
    """Return the profile dict (defaults filled in) or None if none exists.

    Raises ValueError for a non-domain argument, or when the file on disk
    belongs to a different domain (a hand-renamed file): one client's
    properties must never be returned for another.
    """
    path = profile_path(domain, data_dir)
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        profile = _merge_defaults(json.load(fh))
    if normalize_domain(profile.get("domain", "")) != slugify(domain):
        raise ValueError(f"{path} belongs to {profile.get('domain')!r}, not {domain!r}")
    return profile


def save_profile(profile: dict, data_dir: Optional[str] = None) -> Path:
    """Validate and atomically write a profile; returns its path."""
    problems = validate_profile(profile)
    errors = [p for p in problems if p["level"] == "error"]
    if errors:
        raise ValueError("; ".join(p["message"] for p in errors))
    profile["updated_at"] = utc_now()
    path = profile_path(profile["slug"], data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(profile, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def validate_profile(profile: dict) -> list[dict]:
    """Return a list of {level: error|warning, message} problems."""
    out: list[dict] = []
    if not profile.get("domain"):
        out.append({"level": "error", "message": "domain is required"})
    comps = profile.get("competitors") or []
    if len(comps) > MAX_COMPETITORS:
        out.append({"level": "error", "message": f"at most {MAX_COMPETITORS} competitors"})
    lo, hi = RECOMMENDED_COMPETITORS
    if comps and not lo <= len(comps) <= hi:
        out.append({"level": "warning",
                    "message": f"{len(comps)} competitors; {lo}-{hi} gives the most useful gap analysis"})
    own = normalize_domain(profile.get("domain", ""))
    for c in comps:
        if not isinstance(c, dict) or not c.get("domain"):
            out.append({"level": "error", "message": f"competitor entry needs a domain: {c!r}"})
        elif normalize_domain(c["domain"]) == own:
            out.append({"level": "error", "message": "a competitor cannot be the client's own domain"})
    prompts = (profile.get("ai_visibility") or {}).get("prompts") or []
    if len(prompts) > MAX_PROMPTS:
        out.append({"level": "error", "message": f"at most {MAX_PROMPTS} AI-visibility prompts"})
    gsc = profile.get("gsc_property") or ""
    if gsc and not (gsc.startswith("sc-domain:") or gsc.startswith("http://") or gsc.startswith("https://")):
        out.append({"level": "error",
                    "message": "gsc_property must be 'sc-domain:<host>' or a URL-prefix property"})
    if not profile.get("brand_terms"):
        out.append({"level": "warning",
                    "message": "no brand_terms: navigational intent and AI mention detection will be weak"})
    for key, default in DEFAULT_PROFILE.items():
        if key in profile and isinstance(default, (dict, list)) and not isinstance(profile[key], type(default)):
            out.append({"level": "error", "message": f"{key} must be a {type(default).__name__}"})
    content = profile.get("content") if isinstance(profile.get("content"), dict) else {}
    if content.get("default_status") not in ("draft", "pending", "publish"):
        out.append({"level": "error", "message": "content.default_status must be draft|pending|publish"})
    return out


def new_profile(domain: str, name: str = "", brand_terms: Optional[list] = None,
                competitors: Optional[list] = None, **fields: Any) -> dict:
    host = normalize_domain(domain)
    profile = copy.deepcopy(DEFAULT_PROFILE)
    profile.update({
        "slug": slugify(host),
        "domain": host,
        "name": name or host,
        "brand_terms": brand_terms or [t for t in [registrable_label(host)] if t],
        "competitors": [],
        "created_at": utc_now(),
    })
    for comp in competitors or []:
        add_competitor(profile, comp)
    for key, value in fields.items():
        if value not in (None, "", []):
            profile[key] = value
    return profile


def add_competitor(profile: dict, domain: str, name: str = "", aliases: Optional[list] = None) -> dict:
    host = normalize_domain(domain)
    if host and host == normalize_domain(profile.get("domain", "")):
        raise ValueError("a competitor cannot be the client's own domain")
    if not host:
        return profile
    for comp in profile.setdefault("competitors", []):
        if normalize_domain(comp.get("domain", "")) == host:
            # Already listed: merge new aliases (case-insensitively) and fill a
            # missing name instead of silently dropping what the caller passed.
            known = {a.lower() for a in comp.setdefault("aliases", [])}
            for alias in aliases or []:
                if alias and alias.lower() not in known:
                    comp["aliases"].append(alias)
                    known.add(alias.lower())
            if name and not comp.get("name"):
                comp["name"] = name
            return profile
    profile["competitors"].append(
        {"name": name or registrable_label(host) or host, "domain": host, "aliases": list(aliases or [])})
    return profile


def add_prompt(profile: dict, prompt: str, group: str = "treatment", funnel: str = "") -> dict:
    prompt = " ".join(prompt.split())
    prompts = profile.setdefault("ai_visibility", {}).setdefault("prompts", [])
    if prompt and prompt.lower() not in {p["prompt"].lower() for p in prompts}:
        prompts.append({"prompt": prompt, "group": group, "funnel": funnel, "added_at": utc_now()})
    return profile


def add_note(profile: dict, text: str, approved_by: str = "inferred") -> dict:
    if approved_by not in ("user", "inferred"):
        raise ValueError("approved_by must be 'user' or 'inferred'")
    profile.setdefault("notes", []).append({"at": utc_now(), "text": text, "approved_by": approved_by})
    return profile


def set_field(profile: dict, dotted_key: str, raw_value: str) -> dict:
    """Set a (possibly nested) field. JSON values are parsed; bare strings kept."""
    try:
        value = json.loads(raw_value)
    except (json.JSONDecodeError, TypeError):
        value = raw_value
    parts = dotted_key.split(".")
    if parts[0] not in DEFAULT_PROFILE or parts[0] in ("slug", "schema_version", "created_at"):
        raise KeyError(f"unknown or read-only field: {parts[0]}")
    default = DEFAULT_PROFILE[parts[0]]
    if len(parts) == 1 and isinstance(default, (dict, list)) and not isinstance(value, type(default)):
        raise ValueError(f"{parts[0]} must be a JSON {type(default).__name__}, got {type(value).__name__}")
    node = profile
    for part in parts[:-1]:
        node = node.setdefault(part, {})
        if not isinstance(node, dict):
            raise KeyError(f"{dotted_key}: {part} is not an object")
    node[parts[-1]] = value
    if dotted_key == "domain":
        profile["domain"] = normalize_domain(str(value))
    return profile


# Second-level labels that sit under a country code (example.co.uk).
_TWO_PART_SUFFIX_SLD = frozenset({"co", "com", "net", "org", "gov", "ac", "edu", "ne", "or", "ltd", "plc"})
# Subdomain-ish labels that are ordinary words: never derive a brand term
# from them ("shop.globex.com" must not turn every "shop" into a mention).
GENERIC_LABELS = frozenset({"www", "app", "apps", "shop", "store", "blog", "get", "try", "go", "my",
                            "web", "mail", "help", "docs", "info", "home", "news", "about", "en"})


def registrable_label(domain: str) -> str:
    """The brand-bearing label of a host: globex for shop.globex.com or globex.co.uk.

    Approximates the public-suffix rule without a dependency: the label left
    of the TLD, or left of a two-part country suffix (co.uk, com.au, ...).
    Returns "" when that label is a generic word.
    """
    labels = [x for x in normalize_domain(domain).split(".") if x]
    if len(labels) < 2:
        label = labels[0] if labels else ""
    elif len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _TWO_PART_SUFFIX_SLD:
        label = labels[-3]
    else:
        label = labels[-2]
    return "" if label in GENERIC_LABELS else label


def all_brand_terms(profile: dict) -> list[str]:
    """Brand terms plus the registrable domain label, deduplicated, lowercase."""
    terms = [t.lower() for t in profile.get("brand_terms", []) if t]
    label = registrable_label(profile.get("domain") or "")
    if label and label not in terms:
        terms.append(label)
    return terms


def competitor_terms(profile: dict) -> list[str]:
    out: list[str] = []
    for c in profile.get("competitors", []):
        for t in [c.get("name", ""), registrable_label(c.get("domain", "")), *c.get("aliases", [])]:
            t = (t or "").lower().strip()
            if t and t not in out:
                out.append(t)
    return out


def list_profiles(data_dir: Optional[str] = None) -> list[dict]:
    d = projects_dir(data_dir)
    out = []
    if d.is_dir():
        for path in sorted(d.glob("*.json")):
            try:
                p = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({"slug": p.get("slug"), "domain": p.get("domain"), "name": p.get("name"),
                        "competitors": len(p.get("competitors", [])), "updated_at": p.get("updated_at")})
    return out


def _print_profile(profile: dict, problems: list[dict]) -> None:
    print(f"{profile['name']} ({profile['domain']})  slug={profile['slug']}")
    print(f"  brand terms : {', '.join(profile['brand_terms']) or '-'}")
    comps = ", ".join(c["domain"] for c in profile["competitors"]) or "-"
    print(f"  competitors : {comps}")
    print(f"  market      : {profile['markets'].get('country')}/{profile['markets'].get('language')}")
    print(f"  GSC property: {profile['gsc_property'] or '- (run client_preflight.py)'}")
    print(f"  GA4 property: {profile['ga4_property'] or '-'}")
    print(f"  money pages : {', '.join(profile['money_pages']) or '-'}")
    print(f"  conversions : {', '.join(profile['conversion_events']) or '-'}")
    print(f"  AI prompts  : {len(profile['ai_visibility'].get('prompts', []))}")
    for p in problems:
        print(f"  [{p['level']}] {p['message']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage claude-seo client/project profiles")
    parser.add_argument("--data-dir", help="Override storage root (see seo_store.py)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="Create a profile")
    p.add_argument("domain")
    p.add_argument("--name", default="")
    p.add_argument("--brand", action="append", default=[], help="Brand term (repeatable)")
    p.add_argument("--competitor", action="append", default=[], help="Competitor domain (repeatable)")
    p.add_argument("--business-type", default="")
    p.add_argument("--gsc-property", default="")
    p.add_argument("--ga4-property", default="")
    p.add_argument("--country", default="US")
    p.add_argument("--language", default="en")
    p.add_argument("--force", action="store_true", help="Overwrite an existing profile")

    p = sub.add_parser("show", help="Show a profile")
    p.add_argument("domain")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("set", help="Set a field (dotted keys, JSON values)")
    p.add_argument("domain")
    p.add_argument("key")
    p.add_argument("value")

    p = sub.add_parser("add-competitor", help="Add a competitor")
    p.add_argument("domain")
    p.add_argument("competitor")
    p.add_argument("--name", default="")
    p.add_argument("--alias", action="append", default=[])

    p = sub.add_parser("add-prompt", help="Add an AI-visibility panel prompt")
    p.add_argument("domain")
    p.add_argument("prompt")
    p.add_argument("--group", default="treatment", help="treatment|control (for holdout measurement)")
    p.add_argument("--funnel", default="", help="TOFU|MOFU|BOFU")

    p = sub.add_parser("note", help="Append a decision/note with provenance")
    p.add_argument("domain")
    p.add_argument("text")
    p.add_argument("--approved-by", default="inferred", choices=["user", "inferred"])

    sub.add_parser("list", help="List profiles")

    p = sub.add_parser("path", help="Print the profile file path")
    p.add_argument("domain")

    args = parser.parse_args()

    if args.cmd == "list":
        rows = list_profiles(args.data_dir)
        print(json.dumps(rows, indent=2))
        return 0
    try:
        if args.cmd == "path":
            print(profile_path(args.domain, args.data_dir))
            return 0
        existing = load_profile(args.domain, args.data_dir)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.cmd == "init":
        if existing and not args.force:
            print(f"Profile already exists: {profile_path(args.domain, args.data_dir)} (use --force)",
                  file=sys.stderr)
            return 1
        try:
            profile = new_profile(
                args.domain, name=args.name, brand_terms=[b.lower() for b in args.brand] or None,
                competitors=args.competitor, business_type=args.business_type,
                gsc_property=args.gsc_property, ga4_property=args.ga4_property,
                markets={"country": args.country.upper(), "language": args.language.lower()},
            )
            path = save_profile(profile, args.data_dir)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        _print_profile(profile, validate_profile(profile))
        print(f"Saved {path}")
        return 0

    profile = existing
    if profile is None:
        print(f"No profile for {args.domain}. Create one: seo_project.py init {args.domain}",
              file=sys.stderr)
        return 1

    if args.cmd == "show":
        problems = validate_profile(profile)
        if args.json:
            print(json.dumps({"profile": profile, "problems": problems}, indent=2))
        else:
            _print_profile(profile, problems)
        return 0

    try:
        if args.cmd == "set":
            set_field(profile, args.key, args.value)
        elif args.cmd == "add-competitor":
            add_competitor(profile, args.competitor, args.name, args.alias)
        elif args.cmd == "add-prompt":
            add_prompt(profile, args.prompt, args.group, args.funnel)
        elif args.cmd == "note":
            add_note(profile, args.text, args.approved_by)
        path = save_profile(profile, args.data_dir)
    except (KeyError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Updated {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
