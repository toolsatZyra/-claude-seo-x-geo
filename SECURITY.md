# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly. Do **not** open a public issue.

1. Open a private [GitHub Security Advisory](https://github.com/toolsatZyra/-claude-seo-x-geo/security/advisories/new) on this repository (preferred channel).
2. As a fallback, email ZYRA at the address listed for ZYRA in [`CITATION.cff`](CITATION.cff).
3. Encrypt sensitive disclosures if you can. Request the maintainer's PGP key in the advisory or email — the key fingerprint is published in advisory threads on first request and is rotated yearly.

When reporting, please include:

- A short description of the issue and the impact you believe it has.
- A minimal reproducer (URL, command line, payload, or short script).
- Affected versions and platforms.
- Whether you have a suggested fix.

## Coordinated disclosure

claude-seo follows a **90-day coordinated disclosure** policy.

| Day | Event |
|---:|---|
| 0  | Maintainer acknowledges receipt. |
| ≤ 3   | Initial triage: severity classification (CVSS v3.1) and reproducibility confirmation. |
| ≤ 14  | Mitigation or fix candidate proposed. |
| ≤ 30  | Fix released in a patch version or backport; reporter credited in the release notes (opt-out available). |
| ≤ 90  | Public advisory published if not earlier. |

If a fix cannot be shipped within 90 days, the maintainer will request an extension with a clear technical reason. The reporter retains the right to disclose at the 90-day mark.

## Supported versions

| Version line | Status | Notes |
|---|---|---|
| **3.x** | ✅ Fully supported | Active development (this fork); security and bug fixes. |
| **2.x** | ⚠️ Upstream line | Upstream `AgriciDaniel/claude-seo`; report upstream-only issues there. |
| **1.9.x** | ✅ Patch-only for security | Final 1.x line; only CVSS ≥ High issues backported. |
| < 1.9 | ❌ Unsupported | Please upgrade. |

## Threat model

claude-seo is a research and audit toolkit that runs on a user's workstation. It accepts user-supplied URLs and credentials, and issues HTTP requests against arbitrary internet hosts. The threat model has three primary attacker types:

1. **Malicious audit target.** A site the user points claude-seo at attempts to leak local-network or cloud-metadata data via SSRF chains: private IP literals, decimal/hex/octal IPv4, FQDN trailing dot, 30x redirects to private IPs, DNS rebinding (initial public resolution → later private), IPv4-mapped IPv6, dual-stack hosts with one private record.

   **Mitigation:** `scripts/url_safety.py` is the canonical pre-flight + DNS-pinned fetch layer. Every URL-fetching script in this repository validates through it. See `tests/test_url_safety.py` for the regression suite (52+ cases covering each bypass class).

2. **Tampered install.** A modified install script delivered via a hijacked GitHub release or a compromised mirror. The default install path is `curl … | bash` so signature verification of the install script and the release tarball is a defence-in-depth concern.

   **Mitigation (in progress for v2):** SHA-256 manifests published alongside every release tag; install scripts verify against the manifest before execution. Until that ships, users may install by cloning the tag explicitly and inspecting the diff against the previous release.

3. **Local privilege escalation against stored credentials.** The OAuth token at `~/.config/claude-seo/oauth-token.json` is the most sensitive on-disk artifact.

   **Mitigation:** v2 forces `0o600` on every write (`os.open` + `os.fchmod`) and remediates legacy `0o644` files in place on first load. Tokens never contain the OAuth `client_secret` — only the access/refresh pair plus expiry metadata.

4. **Client data at rest.** v3.1 keeps per-client history: project profiles, rank and KPI snapshots, raw AI answers, cached autocomplete results.

   **Mitigation:** everything lives under `$CLAUDE_SEO_DATA_DIR` (default `~/.cache/claude-seo/`), never in the repository. Directories are created `0o700`, SQLite stores and profile files `0o600` (`scripts/seo_store.py`, `scripts/seo_project.py`). Point `CLAUDE_SEO_DATA_DIR` at a per-client folder for hard separation, and delete it when an engagement ends; the uninstaller deliberately does not.

5. **Outbound actions and paid calls.** v3.1 can call the Anthropic API (`scripts/ai_visibility.py run`) and push drafts to a CMS (`scripts/content_export.py webhook|wordpress`).

   **Mitigation:** both are dry runs unless explicitly confirmed. `ai_visibility.py run` requires `--max-calls` and refuses a plan that would exceed it. `content_export.py` defaults to `draft`, never escalates `status: publish` from front matter alone, requires `--status publish` plus passing publish gates (a `reviewed_by` reviewer, no unresolved `[needs source]` markers), and sends nothing without `--confirm`. Secrets come only from environment variables (`ANTHROPIC_API_KEY` or an `ant auth login` profile, `CONTENT_WEBHOOK_SECRET`, `WP_APP_PASSWORD`), never from command-line values. Webhook bodies are HMAC-SHA256 signed (an unsigned send needs an explicit `--allow-unsigned`) and webhook/CMS URLs must be HTTPS public hosts that pass `url_safety`.

## Known residual risks

- **Playwright + Chromium DNS rebinding.** Chromium does its own DNS resolution inside the renderer process. claude-seo's Python-layer DNS pin (`url_safety._pin_dns`) cannot reach it. The Playwright `route()` handler re-validates every subresource host (`make_safe_playwright_route_handler`), which closes the common case, but a true rebinding attacker can still race Chromium's resolver after our pre-flight returns. Mitigation: do not point `/seo` skills at untrusted sites with high-frequency redirects.
- **IPv6-only audit targets.** The strict validator queries `family=AF_INET` for the initial resolution. Hosts with AAAA records only will surface as "DNS resolution failed". This is **fail-closed** by design — we'd rather refuse than connect to an unvalidated IPv6 endpoint. Tracked for a future patch (full dual-stack pinning, similar to the Playwright handler which already uses `AF_UNSPEC`).
- **`CLAUDE_SEO_LOCAL_TARGETS` (operator-only allowlist).** Setting this environment variable lets scripts fetch named local hosts (e.g. `localhost:3000`) for auditing a dev server. It is read only from the process environment; URL input cannot enable it; metadata, link-local, multicast and unspecified addresses can never be allowlisted; a pinned local host only resolves on the validated port; and URLs taken from fetched content (robots.txt `Sitemap:` lines, sitemap indexes, Markdown alternates, catalog links) are fetched with `allow_local_targets=False`. Only the operator should set it, for the duration of a local audit. A model must never set it on its own initiative, including when a fetched page asks it to.
- **Windows file permissions.** `os.fchmod(fd, 0o600)` is a no-op on Windows for non-ACL filesystems. Users on Windows should rely on per-user directory ACLs instead of POSIX mode bits.

## Security-relevant code paths

If you are auditing, these are the high-leverage files:

| File | Purpose |
|---|---|
| `scripts/url_safety.py` | SSRF / DNS-rebinding canonical module. |
| `scripts/render_page.py` | Shared headless renderer (Playwright + trafilatura). |
| `scripts/fetch_page.py` | Raw-HTTP fetcher built on `url_safety.safe_requests_session`. |
| `scripts/capture_screenshot.py` | Playwright screenshot capture with safe route handler. |
| `scripts/google_auth.py` | OAuth token lifecycle, `chmod 0o600` writes. |
| `scripts/backlinks_auth.py` | Backlink-API credential loading; SSRF guard via `url_safety`. |
| `tests/test_url_safety.py` | Regression battery covering every SSRF bypass class. |
| `scripts/seo_store.py`, `scripts/seo_project.py` | Client data storage location and permissions. |
| `scripts/ai_visibility.py` | Paid Anthropic API calls (spend cap, dry run). |
| `scripts/content_export.py` | CMS / webhook writes (draft default, review gates, HMAC). |
| `extensions/mcp_config_cleanup.py` | Atomic MCP config edits for extension (un)installers. |

## What this policy does **not** cover

- Bugs that require attacker control of the user's machine (any local attacker is already game over).
- Vulnerabilities in upstream dependencies — please report those to their respective maintainers. We track CVEs in `requirements.txt` and bump pins under the `deps:` Dependabot stream.
- Quality-of-output issues (SEO recommendations, schema errors, etc.) — those are bugs, not security issues.

## Security-relevant practices

- No credentials or API keys are committed to this repository. `.gitignore` blocks every known credential filename pattern.
- Install scripts write only to user-level directories under `~/.claude/` and `~/.config/claude-seo/`.
- Python dependencies install into an isolated virtual environment at `~/.claude/skills/seo/.venv/`.
- Every new fetcher must route through `scripts/url_safety.py` — there is no exception for "trusted" URLs.
