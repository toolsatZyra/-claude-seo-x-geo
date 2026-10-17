#!/usr/bin/env python3
"""
Client Preflight — onboarding access check for a prospective or new client.

Answers one question before an engagement starts: which parts of this plugin
will actually return data for this client, and what exactly do we still need
them to grant us?

Google APIs (Search Console, GA4) are the highest-value inputs in the whole
plugin, and they are the only ones that cannot be obtained by crawling. They
require the client to add our Google account to their properties. That request
belongs in onboarding, not halfway through an audit call — this script exists
so an operator can send it on day one.

Usage:
    python client_preflight.py example.com
    python client_preflight.py https://www.example.com --json
    python client_preflight.py example.com --request-email

Exit codes:
    0  GO       -- Google access confirmed, full-depth audit possible
    1  PARTIAL  -- crawl-only audit possible, Google access missing
    2  BLOCKED  -- site itself is unreachable
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

UA = "Mozilla/5.0 (compatible; ZyraSEO-Preflight/1.0)"
TIMEOUT = 20

# AI crawler access is evaluated by aeo_score.py (RFC 9309 group matching,
# current vendor facts, Cloudflare managed-robots detection) so the preflight
# and the AEO score can never disagree about which bots a site blocks. Only
# answer-surface agents (OAI-SearchBot, Claude-SearchBot, PerplexityBot,
# Googlebot, Bingbot, ...) decide whether the client can appear in AI answers;
# training crawlers (GPTBot, ClaudeBot, Google-Extended, CCBot) are reported as
# a licensing choice, not a visibility problem.
MAX_BODY_BYTES = 512_000


def _get(url: str, method: str = "GET"):
    """Fetch a public URL through url_safety, returning (status, final_url, body).

    Never raises: SSRF refusals, timeouts and transport errors return
    (None, url, ""). The body is capped at MAX_BODY_BYTES.
    """
    import requests
    from url_safety import URLSafetyError, decode_body, safe_requests_get, safe_requests_head

    try:
        if method == "HEAD":
            resp = safe_requests_head(url, timeout=TIMEOUT, headers={"User-Agent": UA},
                                      allow_redirects=True)
            return resp.status_code, resp.url, ""
        resp = safe_requests_get(url, timeout=TIMEOUT, headers={"User-Agent": UA},
                                 allow_redirects=True, stream=True)
    except (URLSafetyError, requests.RequestException, ValueError):
        return None, url, ""
    try:
        raw = resp.raw.read(MAX_BODY_BYTES, decode_content=True) if resp.raw else b""
        body = decode_body(raw or b"", resp.headers.get("Content-Type", ""))
        return resp.status_code, resp.url, body
    except Exception:  # noqa: BLE001 - a broken body still tells us the status
        return resp.status_code, resp.url, ""
    finally:
        resp.close()


def normalize(domain: str) -> str:
    """Reduce user input to a bare host without a leading ``www.``.

    The documented usage passes ``https://www.example.com``; keeping the
    ``www.`` would probe ``www.www.example.com`` and look for the GSC property
    ``sc-domain:www.example.com`` instead of ``sc-domain:example.com``.
    """
    d = domain.strip()
    if "://" in d:
        d = urllib.parse.urlsplit(d).netloc
    d = d.split("/")[0].split("@")[-1].split(":")[0].strip(".").lower()
    return d[4:] if d.startswith("www.") else d


def check_reachable(host: str) -> dict:
    """Find the canonical live URL, following redirects across www/https."""
    for candidate in (f"https://www.{host}", f"https://{host}", f"http://{host}"):
        status, final, _ = _get(candidate)
        if status and status < 400:
            return {"ok": True, "tried": candidate, "final_url": final, "status": status}
    return {"ok": False, "tried": f"https://{host}", "final_url": None, "status": None}


def check_robots(base: str, analysis: dict | None = None) -> dict:
    """Resolve AI crawler access via aeo_score.check_crawlers (one evaluator).

    ``analysis`` lets tests inject an aeo_score.analyze_robots() result.
    """
    if analysis is None:
        from aeo_score import check_crawlers
        analysis = check_crawlers(base)
    result = {
        "present": analysis["robots_status"] == "ok",
        "status": analysis.get("http_status"),
        "robots_status": analysis["robots_status"],  # ok | missing | unavailable
        "sitemaps": analysis.get("sitemaps", []),
        "crawler_access_score": analysis.get("score"),  # AEO crawler_access component
        "cloudflare_managed": analysis.get("cloudflare_managed", False),
        "ai_crawlers": {},
        "blanket_disallow": False,
        "notes": analysis.get("notes", []),
    }
    for scored, entries in ((True, analysis.get("answer_surface", [])),
                            (False, analysis.get("training", []))):
        for a in entries:
            result["ai_crawlers"][a["agent"]] = {
                "purpose": a["purpose"],
                "status": "allowed" if a["status"] == "allowed" else "BLOCKED",
                "matched": a.get("matched_group") or "no rule (allowed by default)",
                "answer_surface": scored,
                "cloudflare_injected": a.get("cloudflare_injected", False),
            }
    googlebot = result["ai_crawlers"].get("Googlebot")
    result["blanket_disallow"] = bool(googlebot and googlebot["status"] == "BLOCKED"
                                      and googlebot["matched"] == "*")
    return result


def check_asset(base: str, path: str) -> dict:
    root = f"{urllib.parse.urlsplit(base).scheme}://{urllib.parse.urlsplit(base).netloc}"
    status, _, body = _get(f"{root}{path}")
    return {"present": status == 200, "status": status, "bytes": len(body)}


def check_gsc(host: str) -> dict:
    """
    Report which Search Console property forms we can actually read.

    A property can exist in several forms (domain property, https+www URL
    prefix, bare https). Access is granted per form, so knowing which one we
    hold is the difference between a working audit and a permission error
    mid-engagement.
    """
    out = {"available": False, "accessible": [], "candidates": [], "error": None}
    candidates = [
        f"sc-domain:{host}",
        f"https://www.{host}/",
        f"https://{host}/",
    ]
    out["candidates"] = candidates
    try:
        from googleapiclient.discovery import build  # noqa: WPS433
        from google_auth import get_oauth_credentials
    except ImportError as exc:
        out["error"] = f"Google client libraries unavailable: {exc}"
        return out

    try:
        creds = get_oauth_credentials(["https://www.googleapis.com/auth/webmasters"])
        if not creds:
            out["error"] = "No Google credentials configured for this operator."
            return out
        service = build("searchconsole", "v1", credentials=creds)
        entries = service.sites().list().execute().get("siteEntry", [])
    except Exception as exc:  # noqa: BLE001 - surface any auth/API failure verbatim
        out["error"] = str(exc)
        return out

    owned = {e.get("siteUrl"): e.get("permissionLevel") for e in entries}
    for cand in candidates:
        if cand in owned:
            out["accessible"].append({"property": cand, "permission": owned[cand]})
    out["available"] = bool(out["accessible"])
    out["all_properties_on_account"] = len(owned)
    return out


def check_crux(host: str, origin: str | None = None) -> dict:
    """Does the client have enough real traffic for CrUX field data?"""
    out = {"has_field_data": False, "error": None}
    try:
        from google_auth import get_api_key, google_api_key_headers, redact_google_api_key
    except ImportError as exc:
        out["error"] = str(exc)
        return out
    key = get_api_key()
    if not key:
        out["error"] = "No Google API key configured."
        return out
    # CrUX keys data by origin; use the canonical one the reachability check
    # landed on (apex or www, https) rather than assuming www.
    payload = json.dumps({"origin": origin or f"https://{host}"}).encode()
    # The key travels in the X-Goog-Api-Key header, never the URL, so it cannot
    # end up in proxy logs, shell history or an error message.
    req = urllib.request.Request(
        "https://chromeuxreport.googleapis.com/v1/records:queryRecord",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 **google_api_key_headers(key)},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            json.load(resp)
            out["has_field_data"] = True
    except urllib.error.HTTPError as exc:
        # 404 is the documented "origin has insufficient traffic" response.
        out["has_field_data"] = False
        out["error"] = "Insufficient real-user traffic for field data" if exc.code == 404 else f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        out["error"] = redact_google_api_key(exc)
    return out


def build_request_email(host: str, gsc: dict, operator_hint: str) -> str:
    """Copy-pasteable access request — the actual output of onboarding."""
    return f"""Subject: Access needed to start your SEO/AEO audit — {host}

Hi,

To run the full audit we need read access to two Google properties you already
own. This takes about three minutes and nothing changes on your site.

1) Google Search Console — https://search.google.com/search-console
   Settings -> Users and permissions -> Add user
   Email: {operator_hint}
   Permission: Full (or Restricted — Restricted is enough for reporting)

2) Google Analytics 4 — https://analytics.google.com
   Admin -> Property access management -> +
   Email: {operator_hint}
   Role: Viewer

Without these we can still audit everything visible from the outside, but we
cannot see which queries you actually rank for, which pages Google has indexed,
or your real-user Core Web Vitals — which is where most of the value is.

Thanks,
Zyra
"""


def run(host: str) -> dict:
    reach = check_reachable(host)
    report = {"domain": host, "reachable": reach}
    if not reach["ok"]:
        report["verdict"] = "BLOCKED"
        report["summary"] = "Site did not respond on https or http. Confirm the domain."
        return report

    base = reach["final_url"]
    report["robots"] = check_robots(base)
    report["sitemap"] = check_asset(base, "/sitemap.xml")
    report["llms_txt"] = check_asset(base, "/llms.txt")
    report["gsc"] = check_gsc(host)
    final = urllib.parse.urlsplit(reach["final_url"])
    report["crux"] = check_crux(host, origin=f"{final.scheme}://{final.netloc}")

    if report["gsc"]["available"]:
        report["verdict"] = "GO"
        report["summary"] = "Google access confirmed. Full-depth audit available."
    else:
        report["verdict"] = "PARTIAL"
        report["summary"] = (
            "Crawl-only audit available. Request Search Console and GA4 access "
            "before quoting on ranking or traffic work."
        )
    return report


def render(report: dict, operator_hint: str, email_follows: bool = False) -> None:
    host = report["domain"]
    print(f"=== Client Preflight: {host} ===\n")

    reach = report["reachable"]
    if not reach["ok"]:
        print(f"  [BLOCKED] Site unreachable (tried {reach['tried']})")
        print(f"\nVerdict: {report['verdict']} — {report['summary']}")
        return
    print(f"  [OK] Reachable -> {reach['final_url']}")

    robots = report["robots"]
    robots_state = robots.get("robots_status") or ("ok" if robots["present"] else "missing")
    label = {"ok": ("OK", "found"),
             "missing": ("--", "absent — all crawlers allowed"),
             "unavailable": ("!!", "unreachable (5xx/timeout)")}.get(robots_state, ("--", robots_state))
    print(f"  [{label[0]}] robots.txt ({label[1]})")
    if robots.get("robots_status") == "unavailable":
        print("       [!] robots.txt unreachable (5xx/timeout): AI crawler access NOT MEASURED;"
              " compliant crawlers treat this as a full disallow")
    answer_blocked = [n for n, v in robots["ai_crawlers"].items()
                      if v["answer_surface"] and v["status"] == "BLOCKED"]
    training_blocked = [n for n, v in robots["ai_crawlers"].items()
                        if not v["answer_surface"] and v["status"] == "BLOCKED"]
    if answer_blocked:
        print(f"       [!] AI answer crawlers BLOCKED: {', '.join(answer_blocked)}"
              " (these decide whether the client can appear in AI answers)")
    elif robots.get("robots_status") != "unavailable":
        print("       All AI answer-surface crawlers allowed")
    if training_blocked:
        print(f"       [i] Training-only crawlers blocked: {', '.join(training_blocked)}"
              " (licensing choice; no effect on AI answer visibility)")
    if robots.get("cloudflare_managed"):
        print("       [i] Cloudflare managed robots.txt detected: some blocks may be injected"
              " at the edge, not written by the site owner")

    sm, lt = report["sitemap"], report["llms_txt"]
    print(f"  [{'OK' if sm['present'] else '--'}] sitemap.xml"
          f"{'' if sm['present'] else ' (not at /sitemap.xml)'}")
    print(f"  [{'OK' if lt['present'] else '--'}] llms.txt"
          f"{'' if lt['present'] else ' (absent — optional, low confidence signal)'}")

    gsc = report["gsc"]
    if gsc["available"]:
        for entry in gsc["accessible"]:
            print(f"  [OK] Search Console: {entry['property']} ({entry['permission']})")
    else:
        print("  [MISSING] Search Console — no matching property on our account")
        if gsc.get("error"):
            print(f"       {gsc['error']}")
        print(f"       Tried: {', '.join(gsc['candidates'])}")

    crux = report["crux"]
    if crux["has_field_data"]:
        print("  [OK] CrUX field data available (real-user Core Web Vitals)")
    else:
        print(f"  [--] CrUX field data unavailable — {crux.get('error') or 'unknown'}")
        print("       Lab data via PageSpeed still works; field data needs traffic.")

    print(f"\nVerdict: {report['verdict']} — {report['summary']}")
    if report["verdict"] == "PARTIAL" and not email_follows:
        print("\nRun with --request-email to print the access request to send.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Client onboarding preflight: what will actually return data?"
    )
    parser.add_argument("domain", help="Client domain (example.com or a full URL)")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--request-email",
        action="store_true",
        help="Print a copy-pasteable Google access request for the client",
    )
    parser.add_argument(
        "--operator-email",
        default=os.environ.get("ZYRA_SEO_OPERATOR_EMAIL", "hello@growthzyra.com"),
        help="The Google account the client must grant access to",
    )
    args = parser.parse_args()

    host = normalize(args.domain)
    if not host or "." not in host:
        print(f"Error: '{args.domain}' is not a valid domain.", file=sys.stderr)
        return 2

    report = run(host)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        render(report, args.operator_email, email_follows=args.request_email)

    if args.request_email:
        print("\n" + "-" * 68)
        print(build_request_email(host, report.get("gsc", {}), args.operator_email))

    return {"GO": 0, "PARTIAL": 1, "BLOCKED": 2}[report["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
