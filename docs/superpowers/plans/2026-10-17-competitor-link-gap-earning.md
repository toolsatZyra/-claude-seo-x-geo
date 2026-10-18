# Competitor Link Gap and Link Earning: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `seo-links` skill that studies competitor backlinks and runs a white-hat link-earning pipeline:
- deterministic gap and prospect scoring;
- outreach drafts that a person approves and sends;
- a tracker;
- won-link verification;
- `links.*` KPIs.

**Architecture:**
- **Shared store.** `link_store.py` holds the SQLite schema for the `links` store. `link_sources.py` writes dated referring-domain snapshots into it from DataForSEO (REST), Moz, or CSV exports.
- **Scoring.** `link_gap.py` reads one source's latest snapshots, then segments, excludes, classifies and scores the referring domains (pure, no network).
- **Pipeline.** `link_outreach.py` runs the prospect pipeline on top of the gap results.
- **Wiring.** A new skill, `skills/seo-links/`, orchestrates the scripts. `backlinks_auth.py` gets fixed DataForSEO detection.

**Tech Stack:**
- Python 3.10+ (CI) / 3.12 (skill venv), standard library `sqlite3`, `csv`, `argparse`;
- `requests` (already a dependency);
- pytest;
- the existing hub modules: `seo_store`, `seo_project`, `seo_kpi`, `seo_metrics`, `keyword_research`, `competitor_gap`, `dataforseo_costs`, `moz_api`, `verify_backlinks`, `backlinks_auth`.

**Spec:** `docs/superpowers/specs/2026-10-17-competitor-link-gap-earning-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

**Policy**
- No paid links, link exchanges or reciprocal links, anywhere. Nothing is ever sent automatically. No personal email harvesting.
- Client data lives only in `$CLAUDE_SEO_DATA_DIR` (default `~/.cache/claude-seo`), never in the repo.
- Credentials are never printed, logged or written by these scripts. `~/.claude/settings.json` is never read for credentials.

**Scoring**
- Deterministic: scores are computed from stored snapshots, and one gap run uses one source.
- Prospect score: `round_half_up(30*O + 20*A + 20*T + 10*M + 10*Q + 10*V)`.
- Exclusions: spam score ≥ 60 is excluded.
- Buckets: high-value means score ≥ 70; a quick win means low effort and score ≥ 50.

**Pipeline**
- Cooldown is 90 days.
- One follow-up, at least 7 days after first contact.
- Draft body at most 150 words; subject at most 90 characters.
- `links.win_rate` is null below 5 contacted.

**DataForSEO**
- Hard `--max-cost`, default `$1.00`.
- Insufficient funds is fatal (stop, keep the snapshots already taken).
- Actual cost goes to the existing ledger, at `backlinks_backlinks` = `$0.02` per call.

**Code**
- Every script has a module docstring, an argparse CLI, JSON output with `--json`, and tests.
- `SKILL.md` stays under 500 lines; each reference file under 200 lines.
- Python 3.10-compatible syntax (CI runs 3.10). Never nest same-type quotes inside f-strings.

**Commands**
- Run tests with `~/.claude/skills/seo/.venv/bin/python -m pytest …` from the repo root (the worktree). Abbreviate it as `PY=~/.claude/skills/seo/.venv/bin/python`.
- The known flake `tests/test_sync_flow.py` (GitHub rate limit) is not a regression.

**Commits**
- Messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Push to `origin claude/aeo-seo-geo-consolidation-272910` only. Never push to `main`; the user opens one PR at the end.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `scripts/backlinks_auth.py` | modify | DataForSEO detection from `~/.claude.json`; stale-config flag; REST credential resolver |
| `scripts/dataforseo_costs.py` | modify | Public `unit_cost()` and `record_spend()` helpers (ledger write reused by `cmd_log`) |
| `scripts/seo_project.py` | modify | Optional `topics` profile field plus validation |
| `scripts/seo_kpi.py` | modify | Reserve the `links.*` metrics |
| `scripts/link_store.py` | create | Schema plus snapshot read/write for the `links` store |
| `scripts/link_sources.py` | create | DataForSEO, Moz and CSV adapters; cost-capped fetch runner; CLI |
| `scripts/link_gap.py` | create | Segmentation, exclusion, classification, scoring, plan buckets, gap KPIs; CLI |
| `scripts/link_outreach.py` | create | Tracker state machine, briefs, draft lint, approvals, verification, export, KPIs; CLI |
| `skills/seo-links/SKILL.md` | create | `/seo links` routing and workflow |
| `skills/seo-links/references/link-earning-playbook.md` | create | Type → tactic → asset → effort |
| `skills/seo-links/references/outreach-rules.md` | create | Draft rules, banned asks, privacy, cadence |
| `skills/seo-links/references/prospect-scoring.md` | create | The formula, with worked examples |
| `skills/seo/SKILL.md`, `skills/seo-competitors/SKILL.md`, `skills/seo-backlinks/SKILL.md`, `docs/COMMANDS.md`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md` | modify | Routing, counts (39 → 40 skills; 35 → 36 core), docs |
| `tests/test_backlinks_auth_dataforseo.py`, `tests/test_link_core_additions.py`, `tests/test_link_store.py`, `tests/test_link_sources.py`, `tests/test_link_gap.py`, `tests/test_link_outreach.py`, `tests/test_links_integration.py` | create | Tests |

---

### Task 1: DataForSEO detection fix and credential resolver

**Files:**
- Modify: `scripts/backlinks_auth.py`: the `SERVICE_AUTH`/`SERVICE_NAMES` dicts (lines 44-57), `check_credentials` (line 104), `has_dataforseo_mcp` (line 203), `detect_tier` (line 227).
- Test: `tests/test_backlinks_auth_dataforseo.py`

**Interfaces:**
- Produces:
  - `backlinks_auth.CLAUDE_JSON_PATH: str`
  - `backlinks_auth.LEGACY_SETTINGS_PATHS: tuple[str, ...]`
  - `backlinks_auth.dataforseo_credentials(claude_json_path: str | None = None) -> tuple[str, str, str] | None`, returning `(username, password, source)` where source is `"env"` or `"claude_json"`
  - `backlinks_auth.dataforseo_status(claude_json_path=None, legacy_paths=None) -> dict` with keys `mcp_configured: bool`, `stale_config: bool`, `rest_credentials: bool`, `rest_credentials_source: str | None`, `fix: str | None`
  - `check_credentials("dataforseo")` is supported.

- [ ] **Step 1: Write the failing test**

Create `tests/test_backlinks_auth_dataforseo.py`:

```python
"""
DataForSEO detection reads the files Claude Code actually loads.

Before this fix, backlinks_auth reported "Tier 3, Premium (DataForSEO MCP)"
whenever ~/.claude/settings.json had mcpServers.dataforseo. Claude Code never
loads MCP servers from that file, so the server never ran. Detection now reads
~/.claude.json (user and project scopes), flags the settings.json copy as
stale, and resolves REST credentials (env first) without printing them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import backlinks_auth as ba  # noqa: E402

SECRET = "s3cr3t-pw-value"
ENTRY = {"command": "npx", "args": ["-y", "dataforseo-mcp-server"],
         "env": {"DATAFORSEO_USERNAME": "user@example.com", "DATAFORSEO_PASSWORD": SECRET}}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    claude_json = tmp_path / "claude.json"
    legacy = tmp_path / "settings.json"
    monkeypatch.setattr(ba, "CLAUDE_JSON_PATH", str(claude_json))
    monkeypatch.setattr(ba, "LEGACY_SETTINGS_PATHS", (str(legacy),))
    monkeypatch.setattr(ba, "load_config", lambda: {})
    monkeypatch.delenv("DATAFORSEO_USERNAME", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    return claude_json, legacy


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_settings_json_only_is_stale_not_configured(paths):
    _, legacy = paths
    _write(legacy, {"mcpServers": {"dataforseo": ENTRY}})
    status = ba.dataforseo_status()
    assert status["mcp_configured"] is False
    assert status["stale_config"] is True
    assert status["rest_credentials"] is False
    assert "install.sh" in status["fix"]
    assert ba.detect_tier()["tier"] == 0


def test_user_scope_entry_configures_mcp_and_rest(paths):
    claude_json, _ = paths
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY}})
    status = ba.dataforseo_status()
    assert status["mcp_configured"] and status["rest_credentials"]
    assert status["rest_credentials_source"] == "claude_json"
    assert status["fix"] is None
    assert ba.dataforseo_credentials() == ("user@example.com", SECRET, "claude_json")
    assert ba.detect_tier()["tier"] == 3


def test_project_scope_entry_counts(paths):
    claude_json, _ = paths
    _write(claude_json, {"projects": {"/work/site": {"mcpServers": {"dataforseo": ENTRY}}}})
    assert ba.dataforseo_status()["mcp_configured"] is True


def test_env_credentials_win(paths, monkeypatch):
    claude_json, _ = paths
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY}})
    monkeypatch.setenv("DATAFORSEO_USERNAME", "env-user")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "env-pass")
    assert ba.dataforseo_credentials() == ("env-user", "env-pass", "env")


def test_both_locations_flag_leftover_copy(paths):
    claude_json, legacy = paths
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY}})
    _write(legacy, {"mcpServers": {"dataforseo": ENTRY}})
    status = ba.dataforseo_status()
    assert status["mcp_configured"] and status["stale_config"]
    assert "mcp_config_cleanup.py dataforseo" in status["fix"]


def test_no_secret_in_status_or_check(paths):
    claude_json, _ = paths
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY}})
    assert SECRET not in json.dumps(ba.dataforseo_status())
    check = ba.check_credentials("dataforseo")
    assert check["available"] is True
    assert SECRET not in json.dumps(check)


def test_unreadable_claude_json_is_not_configured(paths):
    claude_json, _ = paths
    claude_json.write_text("{not json", encoding="utf-8")
    assert ba.dataforseo_status()["mcp_configured"] is False
    assert ba.dataforseo_credentials() is None
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `$PY -m pytest tests/test_backlinks_auth_dataforseo.py -q`
Expected: FAIL with `AttributeError: module 'backlinks_auth' has no attribute 'dataforseo_status'` (or `CLAUDE_JSON_PATH`).

- [ ] **Step 3: Implement it**

In `scripts/backlinks_auth.py`, replace the two dicts at lines 44-57 with:

```python
SERVICE_AUTH = {
    "moz": "api_key",
    "bing": "api_key",
    "commoncrawl": "none",
    "verify": "none",
    "dataforseo": "mcp_or_env",
}

# Human-readable service names
SERVICE_NAMES = {
    "moz": "Moz Link Explorer API",
    "bing": "Bing Webmaster Tools API",
    "commoncrawl": "Common Crawl Web Graph",
    "verify": "Backlink Verification Crawler",
    "dataforseo": "DataForSEO API (MCP server or REST credentials)",
}

# Where Claude Code loads MCP servers from (user scope and per-project scopes).
CLAUDE_JSON_PATH = os.path.expanduser("~/.claude.json")
# Older installers wrote MCP servers here; Claude Code never loads them from it.
LEGACY_SETTINGS_PATHS = (
    os.path.expanduser("~/.claude/settings.json"),
    os.path.expanduser("~/.claude/settings.local.json"),
)
```

In `check_credentials`, add this branch immediately before the final `else:` (the `Unknown service` branch):

```python
    elif service == "dataforseo":
        status = dataforseo_status()
        result["available"] = status["mcp_configured"] or status["rest_credentials"]
        for key in ("mcp_configured", "stale_config", "rest_credentials", "rest_credentials_source"):
            result[key] = status[key]
        if status["fix"]:
            result["error"] = status["fix"]
        elif not result["available"]:
            result["error"] = "DataForSEO is not configured. Run extensions/dataforseo/install.sh"
```

Replace the whole `has_dataforseo_mcp` function (line 203 to the line before `def detect_tier`) with:

```python
def _read_json_file(path: str) -> Optional[dict]:
    """Parse a JSON object from ``path``; None when missing, unreadable or not an object."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _dataforseo_entries(claude_json_path: Optional[str] = None) -> list:
    """Every mcpServers.dataforseo entry Claude Code loads: user scope, then project scopes."""
    data = _read_json_file(claude_json_path or CLAUDE_JSON_PATH) or {}
    entries = []
    user = (data.get("mcpServers") or {}).get("dataforseo")
    if isinstance(user, dict):
        entries.append(user)
    for cfg in (data.get("projects") or {}).values():
        if isinstance(cfg, dict):
            entry = (cfg.get("mcpServers") or {}).get("dataforseo")
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def dataforseo_credentials(claude_json_path: Optional[str] = None) -> Optional[tuple]:
    """(username, password, source) for DataForSEO REST calls, or None.

    Order: the DATAFORSEO_USERNAME / DATAFORSEO_PASSWORD environment variables,
    then the env block of the dataforseo MCP entry in ~/.claude.json. The legacy
    ~/.claude/settings.json copy is never read. Callers must never print these.
    """
    user = os.environ.get("DATAFORSEO_USERNAME", "").strip()
    password = os.environ.get("DATAFORSEO_PASSWORD", "").strip()
    if user and password:
        return user, password, "env"
    for entry in _dataforseo_entries(claude_json_path):
        env = entry.get("env") or {}
        user = str(env.get("DATAFORSEO_USERNAME", "")).strip()
        password = str(env.get("DATAFORSEO_PASSWORD", "")).strip()
        if user and password:
            return user, password, "claude_json"
    return None


def dataforseo_status(claude_json_path: Optional[str] = None,
                      legacy_paths: Optional[tuple] = None) -> dict:
    """Where DataForSEO is configured, without revealing any credential."""
    mcp = bool(_dataforseo_entries(claude_json_path))
    stale = False
    for path in legacy_paths if legacy_paths is not None else LEGACY_SETTINGS_PATHS:
        data = _read_json_file(path) or {}
        if "dataforseo" in (data.get("mcpServers") or {}):
            stale = True
    creds = dataforseo_credentials(claude_json_path)
    fix = None
    if stale and not mcp:
        fix = ("DataForSEO is only in ~/.claude/settings.json, which Claude Code does not load. "
               "Re-run extensions/dataforseo/install.sh (it writes ~/.claude.json and removes the stale copy).")
    elif stale:
        fix = ("A stale DataForSEO copy remains in ~/.claude/settings.json. Remove it with: "
               "python3 extensions/mcp_config_cleanup.py dataforseo")
    return {"mcp_configured": mcp, "stale_config": stale, "rest_credentials": creds is not None,
            "rest_credentials_source": creds[2] if creds else None, "fix": fix}


def has_dataforseo_mcp() -> bool:
    """True only when ~/.claude.json configures the dataforseo MCP server."""
    return dataforseo_status()["mcp_configured"]
```

In `detect_tier`, replace the line `    if has_dataforseo_mcp():` with:

```python
    dfs = dataforseo_status()
    if dfs["mcp_configured"] or dfs["rest_credentials"]:
```

In the same tier-3 return dict, change `"description": "Premium (DataForSEO MCP + Common Crawl + Verify)",` to `"description": "Premium (DataForSEO + Common Crawl + Verify)",`. In `main()`, change the `--check` help text to `"Check credentials. Optionally specify: moz, bing, commoncrawl, verify, dataforseo"`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/test_backlinks_auth_dataforseo.py tests/test_moz_api.py tests/test_dataforseo_tool_names.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/backlinks_auth.py tests/test_backlinks_auth_dataforseo.py
git commit -m "Detect DataForSEO where Claude Code loads it, not in settings.json

backlinks_auth reported Tier 3 whenever ~/.claude/settings.json held a
dataforseo MCP entry, but Claude Code never loads MCP servers from that
file. It now reads ~/.claude.json (user and project scopes), flags the
settings.json copy as stale with the fix command, and resolves REST
credentials (env first) for scripts without ever printing them.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Shared core additions (profile topics, links KPIs, cost helpers)

**Files:**
- Modify: `scripts/seo_project.py`: `DEFAULT_PROFILE` (line 50) and `validate_profile` (line 152)
- Modify: `scripts/seo_kpi.py`: `RESERVED_METRICS` (line 54)
- Modify: `scripts/dataforseo_costs.py`: add the helpers after `_today_spend` (line 267) and refactor `cmd_log` (line 393)
- Test: `tests/test_link_core_additions.py`

**Interfaces:**
- Produces:
  - profile key `topics: list[str]` (default `[]`);
  - KPI names `links.referring_domains`, `links.gap_domains`, `links.prospects`, `links.contacted`, `links.won`, `links.won_verified` (count) and `links.win_rate` (fraction);
  - `dataforseo_costs.unit_cost(endpoint: str) -> float | None`;
  - `dataforseo_costs.record_spend(endpoint: str, cost: float, note: str = "") -> dict`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_link_core_additions.py`:

```python
"""Shared-core additions used by the seo-links scripts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import dataforseo_costs  # noqa: E402
import seo_kpi  # noqa: E402
import seo_project  # noqa: E402


def test_profile_topics_default_and_validation():
    profile = seo_project.new_profile("acme.in", "Acme", ["acme"], ["rival.com"])
    assert profile["topics"] == []
    profile["topics"] = ["training video", "compliance training"]
    assert not [p for p in seo_project.validate_profile(profile) if p["level"] == "error"]
    profile["topics"] = ["ok", ""]
    errors = [p["message"] for p in seo_project.validate_profile(profile) if p["level"] == "error"]
    assert any("topics" in m for m in errors)
    profile["topics"] = "training video"
    errors = [p["message"] for p in seo_project.validate_profile(profile) if p["level"] == "error"]
    assert any("topics" in m for m in errors)


def test_links_metrics_are_reserved_and_validated():
    for name in ("links.referring_domains", "links.gap_domains", "links.prospects",
                 "links.contacted", "links.won", "links.won_verified"):
        assert seo_kpi.RESERVED_METRICS[name] == "count"
    assert seo_kpi.RESERVED_METRICS["links.win_rate"] == "fraction"
    ok = seo_kpi.build_envelope("acme.in", "link_outreach.py",
                                {"links.won": 2, "links.win_rate": 0.4, "links.contacted": 5})
    assert ok["metrics"]["links.won"] == 2
    with pytest.raises(seo_kpi.EnvelopeError):
        seo_kpi.build_envelope("acme.in", "x", {"links.win_rate": 40})
    with pytest.raises(seo_kpi.EnvelopeError):
        seo_kpi.build_envelope("acme.in", "x", {"links.won": -1})


def test_cost_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(dataforseo_costs, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(dataforseo_costs, "LEDGER_FILE", tmp_path / "dataforseo-ledger.json")
    monkeypatch.setattr(dataforseo_costs, "LOCK_FILE", tmp_path / "dataforseo-ledger.lock")
    assert dataforseo_costs.unit_cost("backlinks_backlinks") == 0.02
    assert dataforseo_costs.unit_cost("no_such_endpoint") is None
    entry = dataforseo_costs.record_spend("backlinks_backlinks", 0.0215, note="link_sources rival.com")
    assert entry["cost"] == 0.0215 and entry["note"] == "link_sources rival.com"
    ledger = json.loads((tmp_path / "dataforseo-ledger.json").read_text())
    assert ledger["entries"][-1]["endpoint"] == "backlinks_backlinks"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `$PY -m pytest tests/test_link_core_additions.py -q`
Expected: FAIL (`KeyError: 'topics'`, `KeyError: 'links.referring_domains'`, and `AttributeError: ... 'unit_cost'`).

- [ ] **Step 3: Implement it**

`scripts/seo_project.py`: in `DEFAULT_PROFILE`, add this line directly after the `"competitors": [],` line:

```python
    "topics": [],                 # service/topic terms for link relevance (seo-links), e.g. "training video"
```

In `validate_profile`, add this immediately before `    return out`:

```python
    topics = profile.get("topics")
    if isinstance(topics, list) and any(not isinstance(t, str) or not t.strip() for t in topics):
        out.append({"level": "error", "message": "topics must be a list of non-empty strings"})
```

(A non-list `topics` is already rejected by the existing generic type loop over `DEFAULT_PROFILE`.)

`scripts/seo_kpi.py`: in `RESERVED_METRICS`, add this line directly after the `"seo.health": "score",` line:

```python
    "links.referring_domains": "count", "links.gap_domains": "count", "links.prospects": "count",
    "links.contacted": "count", "links.won": "count", "links.won_verified": "count",
    "links.win_rate": "fraction",
```

`scripts/dataforseo_costs.py`: add these two functions directly after `_today_spend`:

```python
def unit_cost(endpoint):
    """Budgeted USD cost per call for a known endpoint, or None when unknown."""
    return COST_TABLE.get(endpoint)


def record_spend(endpoint, cost, note=""):
    """Append one completed call's actual cost to the shared ledger; returns the entry."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "endpoint": endpoint,
        "cost": float(cost),
    }
    if note:
        entry["note"] = note
    # Read and write inside one lock, so a concurrent log cannot overwrite this
    # entry with a ledger it read before this one was appended.
    with _locked_ledger(write=True) as ledger:
        ledger["entries"].append(entry)
    return entry
```

Replace the body of `cmd_log` with:

```python
def cmd_log(args):
    """Log a completed API call cost."""
    entry = record_spend(args.endpoint, args.cost, args.note or "")
    result = {
        "status": "logged",
        "entry": entry,
        "today_total_usd": round(_today_spend(_ledger_snapshot()), 4),
    }
    json.dump(result, sys.stdout, indent=2)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/test_link_core_additions.py tests/test_dataforseo_costs.py tests/test_seo_core.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/seo_project.py scripts/seo_kpi.py scripts/dataforseo_costs.py tests/test_link_core_additions.py
git commit -m "Add profile topics, links.* KPIs and public DataForSEO cost helpers

Groundwork for the seo-links skill: an optional profile topics list (link
relevance terms), reserved links.* KPI metrics, and unit_cost/record_spend
so scripts can budget and log DataForSEO calls through the shared ledger.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The `links` store

**Files:**
- Create: `scripts/link_store.py`
- Modify: `docs/superpowers/specs/2026-10-17-competitor-link-gap-earning-design.md`, applying the amendments in Step 6
- Test: `tests/test_link_store.py`

**Interfaces:**
- Consumes: `seo_store.connect`, `seo_store.db_path`, `seo_store.normalize_domain`, `seo_store.utc_now`.
- Produces:
  - `link_store.STORE = "links"`
  - `link_store.RECORD_FIELDS: tuple[str, ...]`
  - `link_store.open_store(data_dir: str | None = None) -> sqlite3.Connection`
  - `link_store.save_snapshot(conn, project, target, source, records, row_cap_hit=False, cost_usd=None, error=None, collected_at=None) -> int`
  - `link_store.latest_snapshots(conn, project, source) -> dict[str, sqlite3.Row]`, keyed by target
  - `link_store.snapshot_records(conn, snapshot_id) -> list[dict]`
  - A `prospects` table with the columns listed in Step 3 (PRIMARY KEY `(project, domain)`) and an `events` table.

A normalized record is a dict with keys `domain, authority, authority_scale, spam_score, dofollow, attributes, first_seen, last_seen, sample_url, sample_anchor, sample_title, tld`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_link_store.py`:

```python
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
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `$PY -m pytest tests/test_link_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'link_store'`.

- [ ] **Step 3: Implement it**

Create `scripts/link_store.py`:

```python
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
              for table in ("snapshots", "referring_domains", "prospects", "events")}
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
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/test_link_store.py -q && $PY scripts/link_store.py --help`
Expected: 4 passed; the help text prints.

- [ ] **Step 5: Amend the spec to match the decomposition**

In `docs/superpowers/specs/2026-10-17-competitor-link-gap-earning-design.md`, make four edits.

1. In §3 Components, add this row directly after the `scripts/link_sources.py` row:

```
| `scripts/link_store.py` | Shared `links` store schema plus snapshot read and write, used by all three scripts | `seo_store` |
```

2. In §5.2, replace the `prospects(...)` bullet with:

```
- `prospects(project, domain, status, source, segment, type, matched_rule, score, effort, bucket, tactic, evidence_json, brief_json, brief_hash, draft_subject, draft_body, reviewed_by, reviewed_at, contacted_at, followup_at, outcome_at, link_url, verified_at, verified_status, link_rel, cooldown_until, notes, created_at, updated_at)`, with UNIQUE(project, domain)
```

3. In §5.1, append this bullet after the CSV import bullet:

```
- **CSV source names.** CSV snapshots are stored with source `csv-<format>` (for example `csv-ahrefs`), so the single-source rule in §5.3 applies to them too.
```

4. In §6.1 item 4, replace the token list with `` `sponsored`, `advertorial`, `guest-post-pricing`, `buy-backlinks`, `link-insertion`, `paid-post` ``. Then append this sentence to the end of that bullet:

```
`write-for-us` is not a paid signal; §7.1 uses such pages as contact paths.
```

In §7.2's banned-asks list, insert `` `sponsorship`, `` directly after `` `sponsored`, ``.

- [ ] **Step 6: Commit**

```bash
git add scripts/link_store.py tests/test_link_store.py
git add -f docs/superpowers/specs/2026-10-17-competitor-link-gap-earning-design.md
git commit -m "Add the links store shared by the seo-links scripts

One schema for referring-domain snapshots, the prospect pipeline and its
event log, under the seo_store root (0700/0600). Failed fetches are stored
as snapshots with an error, so a coverage gap is a recorded fact. The spec
gains the module, the csv-<format> source names, and the paid-signal fix.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: `link_sources.py` (adapters and the cost-capped fetch)

**Files:**
- Create: `scripts/link_sources.py`
- Test: `tests/test_link_sources.py`

**Interfaces:**
- Consumes:
  - `backlinks_auth.dataforseo_credentials`, `dataforseo_status`, `get_moz_api_key` (Task 1);
  - `dataforseo_costs.unit_cost`, `record_spend` (Task 2);
  - `link_store.open_store`, `save_snapshot` (Task 3);
  - `seo_project.load_profile`, `seo_store.normalize_domain`;
  - `moz_api.get_linking_domains(url, api_key, limit=50) -> {"status", "data": {"referring_domains": [{"domain", "domain_authority", "spam_score", ...}]}, "error"}`.
- Produces:
  - `link_sources.normalize_dataforseo_item(item) -> dict | None`
  - `link_sources.normalize_moz_item(item) -> dict | None`
  - `link_sources.import_csv(path, fmt) -> list[dict]`, where fmt is one of `ahrefs | semrush | gsc | generic`; raises `CsvFormatError`
  - `link_sources.fetch_dataforseo(target, limit, credentials, post=None) -> {"records", "cost", "row_cap_hit", "total_count"}`; raises `InsufficientFunds` or `SourceError`
  - `link_sources.fetch_moz(target, limit, api_key, get=None) -> same shape`
  - `link_sources.resolve_targets(project, targets, data_dir) -> list[str]`, client first
  - `link_sources.run_fetch(conn, project, targets, source, limit, max_cost, fetcher, unit_cost=0.0, spend=None) -> dict`
  - `link_sources.main(argv=None) -> int`
  - Source names: `dataforseo`, `moz`, `csv-<format>`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_link_sources.py`:

```python
"""link_sources: adapters, CSV import, cost cap, insufficient funds. No network."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import link_sources as ls  # noqa: E402
import link_store  # noqa: E402

ITEM_PUB = {"type": "backlink", "domain_from": "www.trainingmag.com",
            "url_from": "https://www.trainingmag.com/2025/03/best-video-studios/",
            "domain_from_rank": 612, "rank": 120, "backlink_spam_score": 3, "dofollow": True,
            "attributes": None, "anchor": "Rival Studio",
            "page_from_title": "Best corporate training video studios",
            "first_seen": "2025-03-04 10:00:00 +00:00", "last_seen": "2026-10-01 08:00:00 +00:00",
            "tld_from": "com"}
ITEM_DIR = {"type": "backlink", "domain_from": "clutch.co",
            "url_from": "https://clutch.co/video-production/india", "domain_from_rank": 700,
            "backlink_spam_score": 0, "dofollow": False, "attributes": ["nofollow"],
            "anchor": "rival.com", "first_seen": "2024-01-01 00:00:00 +00:00",
            "last_seen": "2026-09-30 00:00:00 +00:00", "tld_from": "co"}


def dfs_body(items, total=None, cost=0.0215):
    return {"status_code": 20000, "status_message": "Ok.", "cost": cost, "tasks": [{
        "status_code": 20000, "status_message": "Ok.", "cost": cost,
        "result": [{"target": "rival.com", "total_count": total if total is not None else len(items),
                    "items_count": len(items), "items": items}]}]}


def test_normalize_dataforseo_item():
    rec = ls.normalize_dataforseo_item(ITEM_PUB)
    assert rec["domain"] == "trainingmag.com" and rec["authority"] == 61.2
    assert rec["authority_scale"] == "dataforseo_domain_rank/10"
    assert rec["spam_score"] == 3.0 and rec["dofollow"] is True and rec["attributes"] == []
    assert rec["first_seen"] == "2025-03-04" and rec["last_seen"] == "2026-10-01"
    assert rec["sample_title"] == "Best corporate training video studios" and rec["tld"] == "com"
    nofollow = ls.normalize_dataforseo_item(ITEM_DIR)
    assert nofollow["dofollow"] is False and nofollow["attributes"] == ["nofollow"]
    no_rank = ls.normalize_dataforseo_item({**ITEM_PUB, "domain_from_rank": None})
    assert no_rank["authority"] is None  # backlink-level rank is never domain authority
    assert ls.normalize_dataforseo_item({"domain_from": ""}) is None


def test_fetch_dataforseo_payload_cost_and_cap():
    seen = {}

    def post(url, payload, credentials):
        seen.update(url=url, payload=payload, credentials=credentials)
        return 200, dfs_body([ITEM_PUB, ITEM_DIR], total=3)

    got = ls.fetch_dataforseo("rival.com", 1000, ("u", "p", "env"), post=post)
    assert seen["url"].endswith("/v3/backlinks/backlinks/live")
    task = seen["payload"][0]
    assert task["target"] == "rival.com" and task["mode"] == "one_per_domain" and task["limit"] == 1000
    assert [r["domain"] for r in got["records"]] == ["trainingmag.com", "clutch.co"]
    assert got["cost"] == 0.0215 and got["row_cap_hit"] is True and got["total_count"] == 3


@pytest.mark.parametrize("http_status, body", [
    (402, {"status_code": 40200, "status_message": "Payment Required."}),
    (200, {"status_code": 20000, "tasks": [{"status_code": 40200,
                                             "status_message": "Insufficient funds."}]}),
])
def test_insufficient_funds_is_fatal(http_status, body):
    with pytest.raises(ls.InsufficientFunds):
        ls.fetch_dataforseo("rival.com", 10, ("u", "p", "env"), post=lambda *a: (http_status, body))


def test_task_error_is_per_target():
    body = {"status_code": 20000, "tasks": [{"status_code": 40501, "status_message": "Invalid Field"}]}
    with pytest.raises(ls.SourceError) as exc:
        ls.fetch_dataforseo("rival.com", 10, ("u", "p", "env"), post=lambda *a: (200, body))
    assert not isinstance(exc.value, ls.InsufficientFunds)


def _ok(records=None, cost=0.02):
    return {"records": records or [{"domain": "a.org"}], "cost": cost, "row_cap_hit": False,
            "total_count": 1}


def test_run_fetch_records_errors_and_continues(tmp_path):
    conn = link_store.open_store(str(tmp_path))
    calls = []

    def fetcher(target, limit):
        calls.append(target)
        if target == "b.com":
            raise ls.SourceError("HTTP 500")
        return _ok()

    out = ls.run_fetch(conn, "acme.io", ["acme.io", "b.com", "c.com"], "moz", 50, 1.0, fetcher)
    assert calls == ["acme.io", "b.com", "c.com"]
    assert out["coverage"] == "2 of 3" and out["errors"] == 1 and out["stopped"] is None
    errored = conn.execute("SELECT error FROM snapshots WHERE target = 'b.com'").fetchone()
    assert errored["error"] == "HTTP 500"


def test_run_fetch_stops_on_insufficient_funds(tmp_path):
    conn = link_store.open_store(str(tmp_path))

    def fetcher(target, limit):
        if target == "b.com":
            raise ls.InsufficientFunds("Payment Required.")
        return _ok()

    out = ls.run_fetch(conn, "acme.io", ["acme.io", "b.com", "c.com"], "dataforseo", 10, 1.0,
                       fetcher, unit_cost=0.02)
    assert out["stopped"] == "insufficient_funds" and out["coverage"] == "1 of 3"
    assert [r["target"] for r in out["targets"]] == ["acme.io", "b.com"]


def test_run_fetch_respects_max_cost_and_logs_spend(tmp_path):
    conn = link_store.open_store(str(tmp_path))
    spent = []
    calls = []

    def fetcher(target, limit):
        calls.append(target)
        return _ok(cost=0.02 if target == "acme.io" else None)

    out = ls.run_fetch(conn, "acme.io", ["acme.io", "b.com", "c.com"], "dataforseo", 10, 0.04,
                       fetcher, unit_cost=0.02,
                       spend=lambda amount, target, estimated: spent.append((amount, target, estimated)))
    assert calls == ["acme.io", "b.com"]
    assert out["stopped"] == "max_cost_reached" and out["spent_usd"] == 0.04
    assert spent == [(0.02, "acme.io", False), (0.02, "b.com", True)]


def test_moz_adapter():
    rec = ls.normalize_moz_item({"domain": "Example.org", "domain_authority": 41, "spam_score": -1})
    assert rec["authority"] == 41.0 and rec["authority_scale"] == "moz_da" and rec["spam_score"] is None
    items = [{"domain": f"d{i}.org", "domain_authority": 10, "spam_score": 1} for i in range(50)]
    got = ls.fetch_moz("rival.com", 80, "key", get=lambda url, key, limit: {
        "status": "success", "data": {"referring_domains": items}})
    assert len(got["records"]) == 50 and got["row_cap_hit"] is True and got["cost"] is None
    with pytest.raises(ls.SourceError):
        ls.fetch_moz("rival.com", 50, "key", get=lambda url, key, limit: {
            "status": "error", "error": "rate limited"})


@pytest.mark.parametrize("fmt, header, row, expect", [
    ("ahrefs", "Domain,Domain rating,First seen", "news.example.com,72,2025-01-02",
     {"authority": 72.0, "authority_scale": "ahrefs_dr", "first_seen": "2025-01-02"}),
    ("semrush", "Domain,Domain Ascore,Last seen", "blog.example.net,35,2026-09-01",
     {"authority": 35.0, "authority_scale": "semrush_as", "last_seen": "2026-09-01"}),
    ("gsc", "Site,Linking pages", "partner.example.in,12", {"authority": None}),
    ("generic", "domain,authority,dofollow,sample_url,anchor,title",
     "res.example.org,40,true,https://res.example.org/resources/x,Acme,Useful tools",
     {"authority": 40.0, "dofollow": True, "sample_title": "Useful tools"}),
])
def test_import_csv_formats(tmp_path, fmt, header, row, expect):
    path = tmp_path / "export.csv"
    path.write_text(f"{header}\n{row}\n", encoding="utf-8")
    [rec] = ls.import_csv(str(path), fmt)
    for key, value in expect.items():
        assert rec[key] == value


def test_import_csv_missing_domain_column_lists_expected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Referring page,DR\nhttps://x.org/a,10\n", encoding="utf-8")
    with pytest.raises(ls.CsvFormatError) as exc:
        ls.import_csv(str(path), "ahrefs")
    assert "domain" in str(exc.value).lower() and "Referring page" in str(exc.value)


def _cli(tmp_path, *args):
    env = {"CLAUDE_SEO_DATA_DIR": str(tmp_path / "data"), "HOME": str(tmp_path),
           "PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(SCRIPTS / "link_sources.py"), *args],
                          capture_output=True, text=True, env=env)


def test_cli_dry_run_and_budget_refusal(tmp_path):
    proc = _cli(tmp_path, "fetch", "--project", "acme.io", "--targets", "acme.io", "r1.com", "r2.com",
                "--source", "dataforseo", "--dry-run", "--json")
    assert proc.returncode == 0, proc.stderr
    plan = json.loads(proc.stdout)
    assert plan["calls"] == 3 and plan["estimated_cost_usd"] == 0.06
    refused = _cli(tmp_path, "fetch", "--project", "acme.io", "--targets", "acme.io", "r1.com",
                   "--source", "dataforseo", "--max-cost", "0.01", "--json")
    assert refused.returncode == 2 and "max-cost" in refused.stderr


def test_cli_without_credentials_refuses(tmp_path):
    proc = _cli(tmp_path, "fetch", "--project", "acme.io", "--targets", "acme.io",
                "--source", "dataforseo", "--json")
    assert proc.returncode == 2 and "/seo links setup" in proc.stderr


def test_cli_import(tmp_path):
    csv_path = tmp_path / "r.csv"
    csv_path.write_text("domain,authority\nx.org,20\ny.org,30\n", encoding="utf-8")
    proc = _cli(tmp_path, "import", "--project", "acme.io", "--target", "rival.com",
                "--format", "generic", str(csv_path), "--json")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["source"] == "csv-generic" and out["rows"] == 2
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `$PY -m pytest tests/test_link_sources.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'link_sources'`.

- [ ] **Step 3: Implement it**

Create `scripts/link_sources.py`:

```python
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
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/test_link_sources.py -q && $PY scripts/link_sources.py --help`
Expected: all pass; the help prints.

- [ ] **Step 5: Commit**

```bash
git add scripts/link_sources.py tests/test_link_sources.py
git commit -m "Add link_sources: DataForSEO, Moz and CSV referring-domain snapshots

DataForSEO uses backlinks/backlinks/live (one_per_domain) for evidence per
referring domain, estimates cost first, refuses runs over --max-cost, stops
on insufficient funds and logs the actual cost to the shared ledger. Moz
and CSV exports (Ahrefs, Semrush, Search Console, generic) produce the same
normalized record. Per-target failures are stored as facts.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `link_gap.py` (segment, exclude, classify, score)

**Files:**
- Create: `scripts/link_gap.py`
- Test: `tests/test_link_gap.py`

**Interfaces:**
- Consumes:
  - `link_store.open_store`, `latest_snapshots`, `snapshot_records` (Task 3);
  - `seo_project.load_profile`, `all_brand_terms`; `seo_store.host_matches`, `normalize_domain`;
  - `keyword_research.fold_token(token) -> str`;
  - `competitor_gap.slug_tokens(url) -> list[str]` (folded tokens) and `competitor_gap.crawl_domain(domain) -> {"urls": [...]}`;
  - `seo_metrics.STOPWORDS`;
  - `seo_kpi.write_envelope`, `EnvelopeError`.
- Produces:
  - `link_gap.classify(sig) -> (type, matched_rule)`
  - `link_gap.exclusion_reason(sig, client, competitors) -> str | None`
  - `link_gap.segment_domains(client_records, competitor_records) -> dict`
  - `link_gap.topic_matches(terms, texts) -> int`
  - `link_gap.market_fit(tld, country) -> float`
  - `link_gap.score_prospect(k, authority, topic_fit, market, quality, type_) -> (int, dict)`
  - `link_gap.plan_bucket(score, effort) -> str`
  - `link_gap.resolve_topics(profile, sitemap_urls) -> (list, str)`
  - `link_gap.fold_words(text) -> list[str]`
  - `link_gap.analyze_project(project, source, data_dir=None, use_sitemap=True, crawl=None) -> dict`, raising `GapError`
  - `link_gap.main(argv=None) -> int`
  - The analysis dict has keys `project, source, collected, coverage, topics, topics_source, segments, buckets, warnings, domains, prospects, excluded, kpis`.
  - Each prospect dict has keys `domain, segment, competitors, k, type, matched_rule, score, components, effort, bucket, tactic, authority, evidence`.
  - Each evidence item has keys `competitor, authority, spam_score, dofollow, attributes, sample_url, sample_anchor, sample_title, tld`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_link_gap.py`:

```python
"""link_gap: segmentation, exclusions, classification, scoring. No network."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import link_gap as lg  # noqa: E402
import link_store  # noqa: E402
import seo_kpi  # noqa: E402
import seo_project  # noqa: E402


def sig(domain, url=None, title=None, anchor=None, authority=None, spam=None, attrs=(), tld=None):
    texts = [t for t in (title, url, anchor) if t]
    return {"domain": domain, "sample_url": url, "sample_title": title, "sample_anchor": anchor,
            "authority": authority, "spam_score": spam, "attributes": list(attrs),
            "tld": tld or domain.rsplit(".", 1)[-1], "texts": texts, "quality": 0.5}


@pytest.mark.parametrize("s, expected", [
    (sig("clutch.co", "https://clutch.co/video-production/india"), "directory"),
    (sig("x.com.au", "https://x.com.au/top-video-production-companies"), "directory"),
    (sig("iitb.ac.in", "https://iitb.ac.in/news/x"), "association"),
    (sig("hr-society.org", "https://hr-society.org/members"), "association"),
    (sig("reddit.com", "https://reddit.com/r/elearning/comments/1"), "community"),
    (sig("ld-show.com", "https://ld-show.com/podcast/episode-12"), "event"),
    (sig("hrweekly.in", "https://hrweekly.in/resources/compliance-training-tools"), "resource"),
    (sig("lms.io", "https://lms.io/integrations/video"), "partner"),
    (sig("trainingmag.com", "https://trainingmag.com/2025/03/best-studios/", authority=80), "publication"),
    (sig("economictimes.com", "https://economictimes.com/tech/x"), "publication"),
    (sig("blog.vendor.io", "https://blog.vendor.io/post"), "blog"),
    (sig("random.net", "https://random.net/about"), "unclassified"),
])
def test_classification_rules(s, expected):
    kind, rule = lg.classify(s)
    assert kind == expected and rule.startswith("rule")


@pytest.mark.parametrize("s, reason", [
    (sig("acme.in"), "own_property"),
    (sig("shop.acme.in"), "own_property"),
    (sig("rival.com"), "competitor_property"),
    (sig("linkedin.com"), "social_ugc"),
    (sig("spam.biz", spam=60), "spam"),
    (sig("pr.net", "https://pr.net/sponsored-post/x"), "paid_or_scheme"),
    (sig("pr2.net", attrs=["sponsored"]), "paid_or_scheme"),
    (sig("good.org", "https://good.org/write-for-us"), None),
])
def test_exclusions(s, reason):
    assert lg.exclusion_reason(s, "acme.in", ["rival.com", "other.in"]) == reason


def test_segments():
    client = [{"domain": "a.org"}, {"domain": "b.org"}]
    comps = {"rival.com": [{"domain": "b.org"}, {"domain": "c.org"}, {"domain": "d.org"}],
             "other.in": [{"domain": "c.org"}, {"domain": "e.org"}]}
    merged = lg.segment_domains(client, comps)
    seg = {d: e["segment"] for d, e in merged.items()}
    assert seg == {"a.org": "moat", "b.org": "shared", "c.org": "gap", "d.org": "single",
                   "e.org": "single"}
    assert merged["c.org"]["competitors"] == ["other.in", "rival.com"] and merged["c.org"]["k"] == 2


def test_topic_matching_folds_plurals_and_never_spans_texts():
    terms = ["training video", "compliance training"]
    assert lg.topic_matches(terms, ["Best training videos for compliance training"]) == 2
    assert lg.topic_matches(terms, ["https://x.com/corporate-training-video-guide"]) == 1
    assert lg.topic_matches(terms, ["about training", "video tips"]) == 0


def test_market_fit():
    assert lg.market_fit("in", "IN") == 1.0
    assert lg.market_fit("com", "IN") == 0.5
    assert lg.market_fit("de", "IN") == 0.2
    assert lg.market_fit("uk", "GB") == 1.0


def test_score_golden_and_neutral_priors():
    score, comps = lg.score_prospect(2, 80.0, 2 / 3, 0.5, 1.0, "publication")
    assert score == 74 and comps["overlap"] == pytest.approx(0.6667, abs=1e-4)
    neutral, _ = lg.score_prospect(1, None, 0.5, 0.5, 0.5, "unclassified")
    assert neutral == 45


def test_round_half_up_not_bankers():
    # 10 + 10.5 + 10 + 5 + 5 + 6 = 46.5 -> 47 (Python round() would give 46)
    score, _ = lg.score_prospect(1, 52.5, 0.5, 0.5, 0.5, "blog")
    assert score == 47


@pytest.mark.parametrize("score, effort, bucket", [
    (75, "high", "high_value"), (70, "medium", "high_value"), (55, "low", "quick_win"),
    (50, "low", "quick_win"), (55, "medium", "backlog"), (49, "low", "backlog")])
def test_plan_buckets(score, effort, bucket):
    assert lg.plan_bucket(score, effort) == bucket


def test_resolve_topics():
    profile = {"domain": "acme.in", "brand_terms": ["acme"], "topics": ["Training Video"]}
    assert lg.resolve_topics(profile, None) == (["training video"], "profile")
    profile["topics"] = []
    urls = ["https://acme.in/solutions/compliance-training-video",
            "https://acme.in/solutions/safety-training-video", "https://acme.in/acme-story"]
    terms, origin = lg.resolve_topics(profile, urls)
    assert origin == "sitemap" and terms[:2] == ["training", "video"] and "acme" not in terms
    assert lg.resolve_topics(profile, []) == ([], "none")


def _store(tmp_path):
    data_dir = str(tmp_path)
    profile = seo_project.new_profile("acme.in", "Acme", ["acme"], ["rival.com", "other.in", "third.io"],
                                      topics=["training video", "compliance training"],
                                      markets={"country": "IN", "language": "en"})
    seo_project.save_profile(profile, data_dir)
    conn = link_store.open_store(data_dir)
    link_store.save_snapshot(conn, "acme.in", "acme.in", "csv-generic", [{"domain": "partner.in"}])
    pub = {"domain": "trainingmag.com", "authority": 80.0, "dofollow": True,
           "sample_url": "https://trainingmag.com/2025/03/best-training-video-studios/",
           "sample_title": "Best training video studios for compliance training", "tld": "com"}
    clutch = {"domain": "clutch.co", "authority": 70.0, "dofollow": True,
              "sample_url": "https://clutch.co/video-production/india", "tld": "co"}
    link_store.save_snapshot(conn, "acme.in", "rival.com", "csv-generic",
                             [pub, clutch, {"domain": "spamfarm.biz", "spam_score": 80.0},
                              {"domain": "partner.in"}])
    link_store.save_snapshot(conn, "acme.in", "other.in", "csv-generic",
                             [pub, {"domain": "hrweekly.in", "authority": 40.0, "dofollow": True,
                                    "sample_url": "https://hrweekly.in/resources/compliance-training-tools",
                                    "sample_title": "Compliance training tools", "tld": "in"},
                              {"domain": "linkedin.com"}])
    link_store.save_snapshot(conn, "acme.in", "third.io", "csv-generic",
                             [clutch, {"domain": "blogger.net",
                                       "sample_url": "https://blogger.net/blog/my-favourite-studios/"}])
    return data_dir


def test_analyze_project_end_to_end(tmp_path):
    data_dir = _store(tmp_path)
    out = lg.analyze_project("acme.in", "csv-generic", data_dir, use_sitemap=False)
    assert out["segments"] == {"gap": 2, "single": 4, "shared": 1, "moat": 0}
    ranked = [(p["domain"], p["score"], p["bucket"]) for p in out["prospects"]]
    assert ranked == [("trainingmag.com", 74, "high_value"), ("clutch.co", 55, "quick_win"),
                      ("hrweekly.in", 53, "backlog"), ("blogger.net", 36, "backlog")]
    assert {(e["domain"], e["reason"]) for e in out["excluded"]} == {
        ("spamfarm.biz", "spam"), ("linkedin.com", "social_ugc")}
    assert out["kpis"] == {"links.referring_domains": 1, "links.gap_domains": 2}
    assert out["topics_source"] == "profile" and not out["warnings"]


def test_coverage_gap_is_reported_not_filled(tmp_path):
    data_dir = _store(tmp_path)
    conn = link_store.open_store(data_dir)
    link_store.save_snapshot(conn, "acme.in", "acme.in", "moz", [])
    link_store.save_snapshot(conn, "acme.in", "rival.com", "moz", [{"domain": "x.org"}])
    out = lg.analyze_project("acme.in", "moz", data_dir, use_sitemap=False)
    assert out["coverage"]["missing"] == ["other.in", "third.io"]
    assert any("fewer than 2 competitors" in w for w in out["warnings"])


def test_missing_client_snapshot_is_an_error(tmp_path):
    data_dir = _store(tmp_path)
    with pytest.raises(lg.GapError):
        lg.analyze_project("acme.in", "dataforseo", data_dir, use_sitemap=False)


def test_cli_prospects_and_kpis(tmp_path):
    data_dir = _store(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = lg.main(["prospects", "--project", "acme.in", "--source", "csv-generic", "--no-sitemap",
                      "--top", "2", "--data-dir", data_dir, "--json"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert [p["domain"] for p in out["prospects"]] == ["trainingmag.com", "clutch.co"]
    kpi_path = tmp_path / "kpis-links-gap.json"
    with redirect_stdout(io.StringIO()):
        rc = lg.main(["kpis", "--project", "acme.in", "--source", "csv-generic", "--no-sitemap",
                      "--emit-kpis", str(kpi_path), "--data-dir", data_dir, "--json"])
    assert rc == 0
    env = json.loads(kpi_path.read_text())
    assert seo_kpi.validate_envelope(env)["ok"]
    assert env["metrics"] == {"links.referring_domains": 1, "links.gap_domains": 2}
    assert env["source"] == "link_gap.py (csv-generic)"
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `$PY -m pytest tests/test_link_gap.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'link_gap'`.

- [ ] **Step 3: Implement it**

Create `scripts/link_gap.py`:

```python
#!/usr/bin/env python3
"""
Competitor link gap and prospect scoring for the seo-links skill.

Reads the latest referring-domain snapshot per target from ONE source (see
link_sources.py), segments every referring domain, removes non-prospects, then
classifies and scores the rest. Deterministic: no network, except the optional
read of the client's sitemap used to derive topic terms when the profile has none.

Segments (competitors = profile competitors that have a snapshot from the source):
    gap     links to >= 2 competitors and not to the client
    single  links to exactly 1 competitor and not to the client
    shared  links to the client and at least 1 competitor
    moat    links to the client only

Prospect score (0-100), see skills/seo-links/references/prospect-scoring.md:
    round_half_up(30*overlap + 20*authority + 20*topic + 10*market + 10*quality + 10*type)

Usage:
    python link_gap.py gap --project acme.io --source dataforseo --json
    python link_gap.py prospects --project acme.io --source dataforseo --top 50 --json
    python link_gap.py prospects --project acme.io --source csv-ahrefs --no-sitemap --csv prospects.csv
    python link_gap.py kpis --project acme.io --source dataforseo --emit-kpis kpis-links-gap.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from competitor_gap import crawl_domain, slug_tokens  # noqa: E402
from keyword_research import fold_token  # noqa: E402
from link_store import latest_snapshots, open_store, snapshot_records  # noqa: E402
from seo_kpi import EnvelopeError, write_envelope  # noqa: E402
from seo_metrics import STOPWORDS  # noqa: E402
from seo_project import all_brand_terms, load_profile  # noqa: E402
from seo_store import host_matches, normalize_domain  # noqa: E402

SPAM_THRESHOLD = 60.0
GENERIC_TLDS = frozenset({"com", "org", "net", "io", "co", "ai"})
COUNTRY_TLD_OVERRIDES = {"GB": "uk"}
SOCIAL_UGC_HOSTS = ("linkedin.com", "facebook.com", "x.com", "twitter.com", "instagram.com",
                    "youtube.com", "pinterest.com", "tiktok.com", "medium.com", "threads.net", "t.co")
COMMUNITY_HOSTS = ("reddit.com", "quora.com", "stackexchange.com", "stackoverflow.com")
DIRECTORY_HOSTS = ("clutch.co", "goodfirms.co", "designrush.com", "g2.com", "capterra.com",
                   "sortlist.com", "themanifest.com", "upcity.com", "trustpilot.com", "crunchbase.com",
                   "indiamart.com", "justdial.com", "sulekha.com", "tradeindia.com")
PAID_TOKENS = ("sponsored", "advertorial", "guest-post-pricing", "buy-backlinks", "link-insertion",
               "paid-post")
DIRECTORY_TOKENS = frozenset({"directory", "listing", "listings", "companies", "vendors", "agencies"})
ASSOCIATION_TOKENS = frozenset({"association", "society", "council", "chamber", "institute"})
COMMUNITY_TOKENS = frozenset({"forum", "forums", "community"})
EVENT_TOKENS = frozenset({"podcast", "podcasts", "episode", "episodes", "conference", "summit",
                          "webinar", "webinars", "expo", "awards", "event", "events"})
RESOURCE_TOKENS = frozenset({"resources", "resource", "links", "tools", "useful", "recommended"})
PARTNER_TOKENS = frozenset({"partners", "partner", "integrations", "integration", "marketplace",
                            "customers", "clients"})
PUBLICATION_LABEL_PARTS = ("news", "magazine", "journal", "times", "media")
EVIDENCE_FIELDS = ("authority", "spam_score", "dofollow", "attributes", "sample_url",
                   "sample_anchor", "sample_title", "tld")

WEIGHTS = {"overlap": 30, "authority": 20, "topic": 20, "market": 10, "quality": 10, "type": 10}
TYPE_VALUE = {"publication": 1.0, "association": 1.0, "resource": 0.8, "partner": 0.8, "event": 0.7,
              "directory": 0.6, "blog": 0.6, "unclassified": 0.5, "community": 0.3}
EFFORT = {"directory": "low", "partner": "low", "resource": "medium", "event": "medium",
          "association": "medium", "community": "medium", "unclassified": "medium",
          "publication": "high", "blog": "high"}
TACTIC = {
    "directory": "Create or complete a genuine profile; ask real clients for reviews",
    "partner": "Ask a vendor or partner you genuinely work with for a listing",
    "resource": "Offer your most relevant, genuinely useful page for their resource list",
    "event": "Pitch a speaker, panel or podcast guest slot",
    "association": "Join, or get listed as a member",
    "community": "Participate and answer questions; never drop links",
    "publication": "Pitch expert commentary or an original data point",
    "blog": "Offer an expert contribution or a correction; never paid",
    "unclassified": "Review the site manually before any outreach",
}
SEGMENTS = ("gap", "single", "shared", "moat")
BUCKETS = ("high_value", "quick_win", "backlog")


class GapError(ValueError):
    """The analysis cannot run (no profile, no competitors, or no client snapshot)."""


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def fold_words(text: str) -> list:
    """Lowercase alphanumeric words with naive plural folding (keyword_research.fold_token)."""
    return [fold_token(w) for w in _words(text)]


def _host_in(domain: str, hosts) -> bool:
    return any(domain == h or domain.endswith("." + h) for h in hosts)


def classify(sig: dict) -> tuple:
    """(type, matched_rule) for one prospect; first matching rule wins. Always INFERRED."""
    dom = sig["domain"]
    url = (sig.get("sample_url") or "").lower()
    path = urlparse(url).path if url else ""
    path_words = set(_words(path))
    text_words = path_words | set(_words(sig.get("sample_title") or ""))
    dom_words = set(_words(dom))
    if (_host_in(dom, DIRECTORY_HOSTS) or DIRECTORY_TOKENS & (text_words | dom_words)
            or re.search(r"top-[a-z0-9-]*-(?:companies|agencies)", path)):
        return "directory", "rule1:directory-or-review"
    if (re.search(r"\.(?:edu|gov|mil)$|\.(?:ac|gov|edu)\.[a-z]{2}$", dom)
            or ASSOCIATION_TOKENS & (text_words | dom_words)):
        return "association", "rule2:association-edu-gov"
    if _host_in(dom, COMMUNITY_HOSTS) or COMMUNITY_TOKENS & (text_words | dom_words):
        return "community", "rule3:community"
    if EVENT_TOKENS & (text_words | dom_words):
        return "event", "rule4:event-or-podcast"
    if RESOURCE_TOKENS & path_words:
        return "resource", "rule5:resource-page"
    if PARTNER_TOKENS & path_words:
        return "partner", "rule6:partner-or-integration"
    article = re.search(r"/(?:news|article|articles)/|/(?:19|20)\d{2}/\d{1,2}/", path)
    label = dom.rsplit(".", 1)[0]
    if ((sig.get("authority") or 0) >= 60 and article) or any(p in label for p in PUBLICATION_LABEL_PARTS):
        return "publication", "rule7:publication"
    if dom.startswith("blog.") or "/blog/" in path:
        return "blog", "rule8:blog"
    return "unclassified", "rule9:no-rule-matched"


def exclusion_reason(sig: dict, client: str, competitors: list) -> Optional[str]:
    """Why a referring domain is not a prospect, or None."""
    dom = sig["domain"]
    if host_matches(dom, client):
        return "own_property"
    if any(host_matches(dom, c) for c in competitors):
        return "competitor_property"
    if _host_in(dom, SOCIAL_UGC_HOSTS):
        return "social_ugc"
    spam = sig.get("spam_score")
    if isinstance(spam, (int, float)) and spam >= SPAM_THRESHOLD:
        return "spam"
    blob = " ".join(sig.get("texts") or []).lower()
    if "sponsored" in (sig.get("attributes") or []) or any(t in blob for t in PAID_TOKENS):
        return "paid_or_scheme"
    return None


def segment_domains(client_records: list, competitor_records: dict) -> dict:
    """Merge per-target records into {domain: {domain, competitors, evidence, k, segment}}."""
    client = {r["domain"] for r in client_records}
    merged: dict = {}
    for comp in sorted(competitor_records):
        for rec in competitor_records[comp]:
            entry = merged.setdefault(rec["domain"], {"domain": rec["domain"], "competitors": [],
                                                      "evidence": []})
            entry["competitors"].append(comp)
            entry["evidence"].append({"competitor": comp, **{f: rec.get(f) for f in EVIDENCE_FIELDS}})
    for rec in client_records:
        merged.setdefault(rec["domain"], {"domain": rec["domain"], "competitors": [], "evidence": []})
    for dom, entry in merged.items():
        k = len(entry["competitors"])
        in_client = dom in client
        entry["k"] = k
        entry["segment"] = ("shared" if in_client and k else "moat" if in_client
                            else "gap" if k >= 2 else "single")
    return merged


def merged_signals(entry: dict) -> dict:
    """One signal dict per referring domain from all its competitor evidence."""
    ev = entry["evidence"]
    auths = [e["authority"] for e in ev if isinstance(e.get("authority"), (int, float))]
    spams = [e["spam_score"] for e in ev if isinstance(e.get("spam_score"), (int, float))]
    dofollow = [e["dofollow"] for e in ev if isinstance(e.get("dofollow"), bool)]
    first = next((e for e in ev if e.get("sample_url")), ev[0] if ev else {})
    tld = next((e["tld"] for e in ev if e.get("tld")), entry["domain"].rsplit(".", 1)[-1])
    return {"domain": entry["domain"], "authority": max(auths) if auths else None,
            "spam_score": max(spams) if spams else None,
            "quality": (1.0 if any(dofollow) else 0.0) if dofollow else 0.5,
            "attributes": sorted({a for e in ev for a in (e.get("attributes") or [])}),
            "sample_url": first.get("sample_url"), "sample_title": first.get("sample_title"),
            "sample_anchor": first.get("sample_anchor"), "tld": tld,
            "texts": [t for e in ev for t in (e.get("sample_title"), e.get("sample_url"),
                                              e.get("sample_anchor")) if t]}


def topic_matches(terms: list, texts: list) -> int:
    """How many distinct topic terms appear as whole phrases in the texts (plural-folded)."""
    words: list = []
    for text in texts:
        words += fold_words(text) + [""]  # "" separates texts, so a phrase never spans two
    count = 0
    for term in terms:
        tw = fold_words(term)
        if tw and any(words[i:i + len(tw)] == tw for i in range(len(words) - len(tw) + 1)):
            count += 1
    return count


def market_fit(tld: str, country: str) -> float:
    """1.0 same-country ccTLD, 0.5 generic TLD, 0.2 any other ccTLD."""
    code = (country or "").upper()
    cc = COUNTRY_TLD_OVERRIDES.get(code, code.lower())
    tld = (tld or "").lower()
    if cc and tld == cc:
        return 1.0
    if tld in GENERIC_TLDS:
        return 0.5
    return 0.2


def _round_half_up(value: float) -> int:
    return int(Decimal(repr(round(value, 9))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def score_prospect(k: int, authority, topic_fit: float, market: float, quality: float,
                   type_: str) -> tuple:
    """(score 0-100, components 0-1) per references/prospect-scoring.md."""
    comps = {"overlap": min(k, 3) / 3,
             "authority": 0.5 if authority is None else max(0.0, min(float(authority), 100.0)) / 100,
             "topic": topic_fit, "market": market, "quality": quality, "type": TYPE_VALUE[type_]}
    total = sum(WEIGHTS[name] * value for name, value in comps.items())
    return _round_half_up(total), {name: round(value, 4) for name, value in comps.items()}


def plan_bucket(score: int, effort: str) -> str:
    """high_value (score >= 70), then quick_win (low effort, score >= 50), else backlog."""
    if score >= 70:
        return "high_value"
    if effort == "low" and score >= 50:
        return "quick_win"
    return "backlog"


def resolve_topics(profile: dict, sitemap_urls: Optional[list]) -> tuple:
    """(terms, origin): profile topics; else the 10 commonest sitemap slug tokens; else none."""
    terms = [t.strip().lower() for t in (profile.get("topics") or [])
             if isinstance(t, str) and t.strip()]
    if terms:
        return terms, "profile"
    if not sitemap_urls:
        return [], "none"
    brand = {fold_token(w) for t in all_brand_terms(profile) for w in _words(t)}
    counts: Counter = Counter()
    for url in sitemap_urls:
        for tok in set(slug_tokens(url)):
            if tok in brand or tok in STOPWORDS or tok.isdigit() or len(tok) < 3:
                continue
            counts[tok] += 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    return [tok for tok, _ in top], "sitemap"


def load_targets(conn, project: str, source: str, client: str, competitors: list) -> dict:
    latest = latest_snapshots(conn, project, source)
    data = {"client": None, "competitors": {}, "missing": [], "collected": {}, "row_cap_hit": []}
    if client in latest:
        data["client"] = snapshot_records(conn, latest[client]["id"])
        data["collected"][client] = latest[client]["collected_at"]
    for comp in competitors:
        if comp in latest:
            data["competitors"][comp] = snapshot_records(conn, latest[comp]["id"])
            data["collected"][comp] = latest[comp]["collected_at"]
        else:
            data["missing"].append(comp)
    wanted = {client, *competitors}
    data["row_cap_hit"] = sorted(t for t, row in latest.items() if row["row_cap_hit"] and t in wanted)
    return data


def analyze(client: str, profile: dict, competitors: list, data: dict, topics: list,
            topics_source: str, source: str) -> dict:
    warnings = []
    if data["missing"]:
        warnings.append(f"no {source} snapshot for: {', '.join(data['missing'])} "
                        "(coverage gap; never filled from another source)")
    if len(data["competitors"]) < 2:
        warnings.append("fewer than 2 competitors with data: the gap segment needs at least 2, "
                        "so only 'single' prospects are possible")
    if data["row_cap_hit"]:
        warnings.append(f"row cap hit for: {', '.join(data['row_cap_hit'])}; "
                        "lower-authority referring domains are missing")
    if not topics:
        warnings.append("no topic terms: topic fit is neutral (0.5) for every prospect; "
                        "set them with seo_project.py set <domain> topics '[...]'")
    country = (profile.get("markets") or {}).get("country", "")
    merged = segment_domains(data["client"] or [], data["competitors"])
    counts = Counter(e["segment"] for e in merged.values())
    prospects, excluded = [], []
    for dom in sorted(merged):
        entry = merged[dom]
        if entry["segment"] not in ("gap", "single"):
            continue
        sig = merged_signals(entry)
        reason = exclusion_reason(sig, client, competitors)
        if reason:
            excluded.append({"domain": dom, "reason": reason, "segment": entry["segment"],
                             "competitors": entry["competitors"]})
            continue
        type_, rule = classify(sig)
        if not sig["texts"] or not topics:
            topic_fit = 0.5
        else:
            topic_fit = min(topic_matches(topics, sig["texts"]), 3) / 3
        score, comps = score_prospect(entry["k"], sig["authority"], topic_fit,
                                      market_fit(sig["tld"], country), sig["quality"], type_)
        effort = EFFORT[type_]
        prospects.append({"domain": dom, "segment": entry["segment"],
                          "competitors": entry["competitors"], "k": entry["k"], "type": type_,
                          "matched_rule": rule, "score": score, "components": comps,
                          "effort": effort, "bucket": plan_bucket(score, effort),
                          "tactic": TACTIC[type_], "authority": sig["authority"],
                          "evidence": entry["evidence"]})
    prospects.sort(key=lambda p: (-p["score"], -p["k"], p["domain"]))
    buckets = Counter(p["bucket"] for p in prospects)
    return {"project": client, "source": source, "collected": data["collected"],
            "coverage": {"client": data["client"] is not None,
                         "competitors_with_data": sorted(data["competitors"]),
                         "missing": data["missing"], "row_cap_hit": data["row_cap_hit"]},
            "topics": topics, "topics_source": topics_source,
            "segments": {s: counts.get(s, 0) for s in SEGMENTS},
            "buckets": {b: buckets.get(b, 0) for b in BUCKETS},
            "warnings": warnings,
            "domains": [{"domain": d, "segment": merged[d]["segment"],
                         "competitors": merged[d]["competitors"]} for d in sorted(merged)],
            "prospects": prospects, "excluded": excluded,
            "kpis": {"links.referring_domains": len(data["client"] or []),
                     "links.gap_domains": counts.get("gap", 0)}}


def analyze_project(project: str, source: str, data_dir: Optional[str] = None,
                    use_sitemap: bool = True, crawl: Optional[Callable] = None) -> dict:
    """Load profile and snapshots for one source, then analyze. Raises GapError."""
    client = normalize_domain(project)
    profile = load_profile(client, data_dir)
    if not profile:
        raise GapError(f"no profile for {client}: run seo_project.py init {client} --competitor <domain>")
    competitors = [normalize_domain(c["domain"]) for c in profile.get("competitors") or []
                   if c.get("domain")]
    if not competitors:
        raise GapError("the profile lists no competitors: add 3-7 with seo_project.py add-competitor")
    conn = open_store(data_dir)
    data = load_targets(conn, client, source, client, competitors)
    if data["client"] is None:
        raise GapError(f"no {source} snapshot for the client {client}: run link_sources.py "
                       "fetch (or import) for the client first")
    sitemap_urls = None
    if use_sitemap and not profile.get("topics"):
        sitemap_urls = (crawl or crawl_domain)(client).get("urls") or []
    topics, topics_source = resolve_topics(profile, sitemap_urls)
    return analyze(client, profile, competitors, data, topics, topics_source, source)


CSV_COLUMNS = ("domain", "score", "bucket", "effort", "type", "matched_rule", "segment", "k",
               "competitors", "tactic", "sample_url", "sample_anchor", "sample_title")


def _write_csv(path: str, prospects: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for p in prospects:
            first = next((e for e in p["evidence"] if e.get("sample_url")), p["evidence"][0])
            writer.writerow({"domain": p["domain"], "score": p["score"], "bucket": p["bucket"],
                             "effort": p["effort"], "type": p["type"],
                             "matched_rule": p["matched_rule"], "segment": p["segment"], "k": p["k"],
                             "competitors": ";".join(p["competitors"]), "tactic": p["tactic"],
                             "sample_url": first.get("sample_url") or "",
                             "sample_anchor": first.get("sample_anchor") or "",
                             "sample_title": first.get("sample_title") or ""})


def _print(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    for key in ("project", "source", "topics_source", "segments", "buckets", "coverage"):
        if key in result:
            print(f"{key}: {result[key]}")
    for warning in result.get("warnings", []):
        print(f"WARNING: {warning}")
    for p in result.get("prospects", []):
        print(f"  {p['score']:3d}  {p['bucket']:10s} {p['effort']:6s} {p['type']:12s} "
              f"{p['domain']}  <- {', '.join(p['competitors'])}")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True, help="Client domain (profile slug)")
    common.add_argument("--source", required=True,
                        help="Snapshot source: dataforseo | moz | csv-ahrefs | csv-semrush | csv-gsc | csv-generic")
    common.add_argument("--no-sitemap", action="store_true",
                        help="Do not read the client sitemap to derive topic terms")
    common.add_argument("--data-dir", help="Storage root (default $CLAUDE_SEO_DATA_DIR or ~/.cache/claude-seo)")
    common.add_argument("--json", action="store_true", help="Output JSON")
    parser = argparse.ArgumentParser(description="Competitor link gap and prospect scoring (seo-links)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gap", parents=[common], help="Segment referring domains: gap/single/shared/moat")
    p = sub.add_parser("prospects", parents=[common], help="Classify, score and rank prospects")
    p.add_argument("--top", type=int, default=50, help="How many prospects to print (default 50)")
    p.add_argument("--csv", help="Also write the ranked prospects to this CSV file")
    k = sub.add_parser("kpis", parents=[common], help="Write links.referring_domains and links.gap_domains")
    k.add_argument("--emit-kpis", required=True, help="Path for the KPI envelope (performance_tracker.py ingest)")
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = analyze_project(args.project, args.source, args.data_dir,
                                 use_sitemap=not args.no_sitemap)
    except GapError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "gap":
        _print({k: result[k] for k in ("project", "source", "collected", "coverage", "segments",
                                       "warnings", "domains")}, args.json)
        return 0
    if args.cmd == "prospects":
        if args.csv:
            _write_csv(args.csv, result["prospects"])
        shown = {k: result[k] for k in ("project", "source", "collected", "coverage", "topics",
                                        "topics_source", "segments", "buckets", "warnings",
                                        "excluded")}
        shown["total_prospects"] = len(result["prospects"])
        shown["prospects"] = result["prospects"][:args.top]
        _print(shown, args.json)
        return 0
    try:
        env = write_envelope(args.emit_kpis, result["project"], f"link_gap.py ({args.source})",
                             result["kpis"], meta={"data_source": args.source,
                                                   "collected": result["collected"]})
    except EnvelopeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    _print(env, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/test_link_gap.py -q && $PY scripts/link_gap.py --help`
Expected: all pass. If a golden score is off by one, recompute it by hand from the formula before changing either side. Never change a test value to match a code result without checking the arithmetic.

- [ ] **Step 5: Commit**

```bash
git add scripts/link_gap.py tests/test_link_gap.py
git commit -m "Add link_gap: deterministic competitor link gap and prospect scoring

Segments referring domains (gap/single/shared/moat) from one source's latest
snapshots, excludes own, competitor, social, spam (>= 60) and paid signals,
classifies prospects by first-matching rule and scores them with the fixed
30/20/20/10/10/10 formula (round half up). Coverage gaps and row caps are
reported, never filled from another source. Emits links.* gap KPIs.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `link_outreach.py` (tracker, briefs, lint, verification, KPIs)

**Files:**
- Create: `scripts/link_outreach.py`
- Test: `tests/test_link_outreach.py`

**Interfaces:**
- Consumes:
  - `link_store.open_store` (Task 3);
  - `link_gap.analyze_project`, `GapError`, `fold_words` (Task 5);
  - `seo_project.load_profile`; `seo_store.host_matches`, `normalize_domain`, `utc_now`;
  - `seo_kpi.write_envelope`, `EnvelopeError`;
  - `verify_backlinks.verify_single_backlink(source_url, target_url, head_only=False, timeout=30) -> {"status": "verified"|"link_removed"|"lost"|"moved"|"unverifiable_js"|"exists"|"error", "rel_attributes": [...]}`;
  - `competitor_gap.crawl_domain`.
- Produces:
  - `link_outreach.TransitionError`
  - `add_prospects(conn, project, prospects, source, today=None, now=None) -> {"added", "skipped"}`
  - `build_brief(profile, row, pages) -> dict` (with `brief_hash`)
  - `store_brief(conn, project, domain, brief) -> None`
  - `lint_draft(subject, body, brief) -> list[dict]`
  - `save_draft(conn, project, domain, subject, body, brief_hash, today=None, now=None) -> dict`
  - `approve(conn, project, domain, reviewed_by, now=None) -> dict`
  - `mark(conn, project, domain, status, link_url=None, note=None, today=None, now=None) -> dict`
  - `verify(conn, project, domain=None, verifier=None, now=None) -> list`
  - `outreach_kpis(conn, project) -> dict`
  - `export_rows(conn, project, include_all=False) -> list`
  - `main(argv=None) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_link_outreach.py`:

```python
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
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `$PY -m pytest tests/test_link_outreach.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'link_outreach'`.

- [ ] **Step 3: Implement it**

Create `scripts/link_outreach.py`:

```python
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
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `$PY -m pytest tests/test_link_outreach.py tests/test_link_gap.py -q && $PY scripts/link_outreach.py --help`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/link_outreach.py tests/test_link_outreach.py
git commit -m "Add link_outreach: approval-gated link-earning tracker

Tracks prospects from link_gap through new, drafted, approved, contacted and
won/lost/no_reply, with a named reviewer required before contact, one
follow-up after 7 days, a 90-day cooldown and permanent do-not-contact.
Briefs limit claims and URLs; a deterministic lint rejects payment,
sponsorship, link-swap and dofollow asks. Nothing is sent. Won links are
verified on the linking page, and links.* KPIs are emitted.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The `seo-links` skill, references and hub wiring

**Files:**
- Create: `skills/seo-links/SKILL.md`, `skills/seo-links/references/link-earning-playbook.md`, `skills/seo-links/references/outreach-rules.md`, `skills/seo-links/references/prospect-scoring.md`
- Modify: `skills/seo/SKILL.md` (Research table near line 40; numbered list near line 400; lines 22 and 364 counts), `skills/seo-competitors/SKILL.md` (Step 4 near line 116), `skills/seo-track/SKILL.md` (report order near line 190; cadence table near line 213), `skills/seo-backlinks/SKILL.md` (description line 3; §6 lines 135-147; output heading line 205), `docs/COMMANDS.md` (new section before `### /seo content-engine`; summary table near line 731), `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/ARCHITECTURE.md`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `CHANGELOG.md`
- Test: the existing gates (`tests/test_manifest_consistency.py`, `scripts/consistency_check.py`, `scripts/portability_check.py`)

**Interfaces:**
- Consumes: every script CLI from Tasks 1-6, exactly as documented in their docstrings.
- Produces: the `/seo links <setup|gap|prospects|draft|track> <domain>` command, which routes to `skills/seo-links`.

- [ ] **Step 1: Run the gates and confirm the count test will catch the new skill**

Run: `mkdir -p skills/seo-links/references && $PY -m pytest tests/test_manifest_consistency.py -q`
Expected: PASS, because the directory has no `SKILL.md` yet. After Step 2 creates `SKILL.md`, `test_plugin_json_skill_count_matches_disk` must FAIL (40 on disk, 39 claimed) until Step 4 updates the counts.

- [ ] **Step 2: Create `skills/seo-links/SKILL.md`**

```markdown
---
name: seo-links
description: >
  Competitor backlink study and white-hat link earning. Finds the sites that
  link to two or more competitors but not to you, classifies and scores them
  for relevance, drafts outreach that a named person approves and sends, tracks
  the pipeline, verifies won links and reports links.* KPIs. Sources: DataForSEO,
  Moz, or a CSV export (Ahrefs, Semrush, Search Console). Use when user says
  "link building", "link gap", "competitor backlinks", "who links to my
  competitors", "link prospects", "link outreach", "earn links", "link
  intersect", or "digital PR".
user-invocable: true
argument-hint: "[setup|gap|prospects|draft|track] [domain]"
license: MIT
metadata:
  author: ZYRA
  version: "3.1.0"
  category: seo
---

# Link Gap and Link Earning

This skill answers three questions:
- **Who links to our competitors and not to us,** and which of those sites are worth earning?
- **What should we offer each one,** and what exactly do we say?
- **Did it work?** Won links are verified on the page, then tracked as KPIs.

**Hard rules.** These come from `references/outreach-rules.md` and are not negotiable:
- No paid links, link exchanges, reciprocal links or "dofollow" asks.
- Nothing is ever sent by this skill. A named person approves every draft and sends it from their own email.
- Claim only what the client profile allows. Never invent clients, results or numbers.
- No personal email harvesting: contact paths are public pages only.

## Data source (one per run)

| Source | When | Cost |
|---|---|---|
| `dataforseo` | Default when `/seo links setup` shows REST credentials | About $0.02 per target (guard estimate), hard cap with `--max-cost` |
| `moz` | Free fallback or cross-check | Free tier: 2,500 rows a month, 50 per target |
| `csv-ahrefs`, `csv-semrush`, `csv-gsc`, `csv-generic` | You already have exports | Free |

A gap run uses **one** source for every domain. Never mix sources in one run: authority scales differ and row limits differ.

## Commands

Scripts live in `scripts/` and print JSON with `--json`.

### `/seo links setup`

1. `python3 scripts/backlinks_auth.py --check dataforseo --json`
   - `stale_config: true` means the credentials are in `~/.claude/settings.json`, which Claude Code never loads. Show the `fix` text and offer to run it.
   - `rest_credentials: true` means scripts can call DataForSEO now.
2. `python3 scripts/link_sources.py status --json`: Moz and CSV availability.
3. Confirm the profile: `python3 scripts/seo_project.py show <domain> --json`.
   - It needs 3-7 competitors and `markets.country`.
   - It needs `topics` (service terms). Set them with `python3 scripts/seo_project.py set <domain> topics '["term one", "term two"]'`.

### `/seo links gap <domain>`

1. **Estimate first:** `python3 scripts/link_sources.py fetch --project <domain> --source dataforseo --dry-run --json`. Show the estimated cost and **ask for approval** before any paid call.
2. **Fetch:** `python3 scripts/link_sources.py fetch --project <domain> --source dataforseo --max-cost <approved> --json`.
   - Exit code 3 means the run stopped early (insufficient funds or the cap). Report the coverage and do not retry automatically.
   - For CSV exports, run `link_sources.py import --project <domain> --target <domain-in-export> --format ahrefs <file>` once per domain instead.
3. **Segment:** `python3 scripts/link_gap.py gap --project <domain> --source <source> --json`.
4. **Report:**
   - the segment counts (gap, single, shared, moat);
   - coverage, with any warning (a missing competitor, a row cap, no topics);
   - the 10 largest gap domains.

### `/seo links prospects <domain>`

`python3 scripts/link_gap.py prospects --project <domain> --source <source> --top 30 --json`, optionally with `--csv prospects.csv`.

Present the results as three groups:
- **High-value** (score ≥ 70);
- **Quick wins** (low effort, score ≥ 50);
- **Backlog**.

For each prospect, show its score, type, the rule that matched, the competitors it links to, and one evidence line (sample URL plus anchor). Then list the excluded domains with their reasons. Types come from rules, so they are INFERRED; say so. The formula is in `references/prospect-scoring.md`.

### `/seo links draft <domain> --top N`

1. Run `python3 scripts/link_outreach.py add --project <domain> --source <source> --top N --json`.
2. For each added prospect, get its brief: `python3 scripts/link_outreach.py brief --project <domain> --domain <prospect> --json`.
3. Write the draft **from the brief only**, following `references/link-earning-playbook.md` for the tactic and `references/outreach-rules.md` for tone:
   - a subject of at most 90 characters;
   - a body of at most 150 words;
   - one ask;
   - links only to `asset_url` or `client_home`.
4. Save it: write the body to a temp file, then run `python3 scripts/link_outreach.py save-draft --project <domain> --domain <prospect> --brief-hash <hash> --subject "<subject>" --body-file <file> --json`.
   - A lint failure (exit 1) lists the offending spans.
   - Rewrite and save again. **Never** work around the lint.
5. Show every draft to the user and ask who approves it.

### `/seo links track <domain>`

| Action | Command |
|---|---|
| Approve (the user names the reviewer) | `link_outreach.py approve --project <domain> --domain <prospect> --reviewed-by "<Name>"` |
| Export approved drafts for the user's own email tool | `link_outreach.py export --project <domain> --out outreach.csv` |
| After the user says it was sent | `link_outreach.py mark --project <domain> --domain <prospect> --status contacted` |
| Outcome | `mark --status won --link-url <page on their site>`, or `lost`, `no_reply`, `skipped`, `do_not_contact` |
| Verify won links | `link_outreach.py verify --project <domain> --json` |
| Board | `link_outreach.py board --project <domain> --json` |
| KPIs for `/seo track` | `link_gap.py kpis --project <domain> --source <source> --emit-kpis kpis-links-gap.json` and `link_outreach.py kpis --project <domain> --emit-kpis kpis-links.json`, then `performance_tracker.py ingest kpis-links-gap.json kpis-links.json` |

Notes on the pipeline:
- **Follow-ups:** one only, at least 7 days after first contact. It needs its own draft and approval.
- **Cooldown:** `lost` and `no_reply` start a 90-day cooldown before the domain can be re-added.
- **Win rate:** `links.win_rate` stays null until 5 prospects have been contacted.

## Error handling

| Situation | Action |
|---|---|
| `link_sources.py` exit 2: no credentials | Run `/seo links setup`. Never switch source silently. |
| Exit 3: stopped (funds or cap) | Report the coverage. Ask before spending more. |
| `link_gap.py` error: no client snapshot | Fetch or import the client domain first, from the same source. |
| Warning: a competitor is missing from the source | Report the coverage gap. Do not fill it from another source. |
| `save-draft` exit 1 | Show the lint problems, rewrite, save again. |
| `mark` or `approve` exit 2 | The pipeline rule refused it. Explain the rule; do not force it. |

## Related skills

- `seo-backlinks`: the client's own profile, toxic links and disavow.
- `seo-competitors`: the full competitor hub. Its link-gap step routes here.
- `seo-track`: KPI history, including `links.*`.
- `geo-brand-mentions`: unlinked brand mentions. Import them with `--format generic` to reclaim them as links.
```

- [ ] **Step 3: Create the three references**

`skills/seo-links/references/prospect-scoring.md`:

```markdown
# Prospect scoring

The scoring is deterministic: the same snapshot always gives the same scores.
It is implemented in `scripts/link_gap.py`.

## Formula

score = round_half_up(30·O + 20·A + 20·T + 10·M + 10·Q + 10·V)

| Signal | Definition | Unknown value |
|---|---|---|
| O, competitor overlap | min(k, 3) / 3, where k is the number of competitors the domain links to | (never unknown) |
| A, authority | DataForSEO domain rank / 1000, or Moz DA / 100 (CSV: DR or AS / 100) | 0.5 |
| T, topic fit | min(m, 3) / 3, where m is the number of distinct profile `topics` found as whole phrases (plural-folded) in the sample title, URL or anchor | 0.5 when there is no text or no topics |
| M, market fit | 1.0 for a same-country ccTLD; 0.5 for com, org, net, io, co, ai; 0.2 for any other ccTLD | (never unknown) |
| Q, link quality | 1.0 if any sampled link is dofollow; 0.0 if all are nofollow or UGC | 0.5 |
| V, type value | publication or association 1.0; resource or partner 0.8; event or podcast 0.7; directory or blog 0.6; unclassified 0.5; community 0.3 | (never unknown) |

**Comparability.** Scores compare within one run, which uses one source. Authority from different sources is not comparable.

## Excluded before scoring

The order is fixed, and each exclusion is reported with its reason:
1. own property;
2. competitor property;
3. social or user-generated platform;
4. spam score ≥ 60;
5. paid or link-scheme signal: a `sponsored` attribute, or `sponsored`, `advertorial`, `guest-post-pricing`, `buy-backlinks`, `link-insertion` or `paid-post` in the sample URL or title.

## Effort and buckets

Effort is never part of the score:
- **Low:** directory or review, partner or integration.
- **Medium:** resource, event, association, community, unclassified.
- **High:** publication, blog.

Buckets are checked in this order, so each prospect lands in exactly one:
1. high-value: score ≥ 70;
2. quick win: low effort and score ≥ 50;
3. backlog: everything else.

Ties are ordered by score, then k (descending), then domain (A→Z).

## Worked examples

**1. A gap publication.**
- Inputs: k = 2, rank 800, two topic phrases in the title, `.com` for an Indian client, dofollow, publication.
- Sum: 30·0.667 + 20·0.8 + 20·0.667 + 10·0.5 + 10·1 + 10·1 = 20 + 16 + 13.33 + 5 + 10 + 10 = 74.33.
- Result: **74**, high-value.

**2. A directory.**
- Inputs: k = 2, rank 700, no topic match, `.co`, dofollow, directory.
- Sum: 20 + 14 + 0 + 5 + 10 + 6 = 55.
- Result: **55**, a quick win (low effort).

**3. A blog with no data.**
- Inputs: k = 1, authority unknown, no topic match, `.net`, link type unknown.
- Sum: 10 + 10 + 0 + 5 + 5 + 6 = 36.
- Result: **36**, backlog.

**4. Rounding.**
- Inputs: k = 1, authority 52.5, neutral topic, `.com`, unknown link type, blog.
- Sum: 10 + 10.5 + 10 + 5 + 5 + 6 = 46.5.
- Result: **47**. It is rounded half up, never to even.

## Classification rules (first match wins; every type is INFERRED)

| # | Type | Rule |
|---|---|---|
| 1 | directory | A known listing host (Clutch, GoodFirms, DesignRush, G2, Capterra, Sortlist, The Manifest, UpCity, Trustpilot, Crunchbase, IndiaMART, Justdial, Sulekha, TradeIndia), or the tokens directory, listing, companies, vendors, agencies, or a `top-…-companies` path |
| 2 | association | `.edu`, `.gov`, `.mil`, `.ac.xx`, `.gov.xx`, or the tokens association, society, council, chamber, institute |
| 3 | community | reddit, quora, stackexchange, stackoverflow, or the tokens forum, community |
| 4 | event | podcast, episode, conference, summit, webinar, expo, awards, event |
| 5 | resource | path tokens resources, links, tools, useful, recommended |
| 6 | partner | path tokens partners, integrations, marketplace, customers, clients |
| 7 | publication | authority ≥ 60 and an article path (`/news/`, `/article/`, `/YYYY/MM/`), or news, magazine, journal, times or media in the domain name |
| 8 | blog | a `blog.` subdomain or a `/blog/` path |
| 9 | unclassified | anything else |
```

`skills/seo-links/references/link-earning-playbook.md`:

```markdown
# Link-earning playbook

Every tactic below is white-hat. Each one earns a link because the target
site's readers benefit. None of them involves payment, swaps or link schemes.

| Prospect type | Tactic | What to offer (`asset_url`) | Effort |
|---|---|---|---|
| directory or review | Create or complete a genuine profile; ask real clients for reviews | Homepage or services hub | Low |
| partner or integration | Ask a vendor or partner you genuinely work with for a listing (LMS, tools, agencies) | The page that shows the integration or partnership | Low |
| resource page | Offer your most relevant, genuinely useful page for their list | A guide, template, checklist or calculator | Medium |
| event or podcast | Pitch a speaker, panel or guest slot with a specific angle | Speaker page or a relevant case study | Medium |
| association | Join, or get listed as a member; contribute to member resources | About page | Medium |
| community | Answer questions where you have expertise; links only when asked for | (none: participation, not outreach) | Medium |
| publication | Expert commentary on a trend, or an original data point; use source requests (Qwoted, Featured) | Data page, study or expert bio | High |
| blog (editorial) | Offer an expert contribution or point out an error or outdated fact; never paid | The page that answers the gap | High |
| unclassified | Look at the site manually first; most should be skipped | (none) | Medium |

## Choosing what to work on

1. **High-value prospects first.** Spend a personalized pitch on each one.
2. **Quick wins in batches.** Directories and partner pages need accurate, genuine profiles, not outreach copy.
3. **Leave the backlog alone** unless a prospect fits a campaign you are already running.

## Assets that earn links for B2B services

- **Original data:** a survey of your clients' buyers, or anonymized production benchmarks. Publish the method.
- **Practical tools:** a cost estimator, a brief template, a checklist.
- **Expert explainers** for questions that buyers search for. These match the topics in the profile.
- **Real case studies**, with client approval.
  - Never present third-party or placeholder work as your own.
  - If proof is thin, pitch expertise (commentary, data), not portfolio.

## Reclaiming unlinked mentions

If `geo-brand-mentions` or a search turns up pages that name the client without linking:

1. Import them: `link_sources.py import --format generic`, with the columns `domain`, `sample_url` and `title`.
2. Handle them as prospects with the tactic "Ask to add a link where you are already mentioned". This is low effort and has the highest acceptance rate.

## Measuring

- **Weekly:** `link_outreach.py verify`, then the KPIs, then `performance_tracker.py ingest`.
- **Monthly:** re-fetch the gap from the same source and compare `links.referring_domains`.
```

`skills/seo-links/references/outreach-rules.md`:

```markdown
# Outreach rules

`scripts/link_outreach.py` enforces the rules marked **(enforced)**. The rest are judgment rules for whoever writes the draft.

## Never

- **(enforced)** Offer or mention payment, sponsorship, link exchanges, swapped or reciprocal links, guest-post fees, or "dofollow". The lint rejects: pay, payment, paid, sponsor, sponsored, sponsorship, link exchange, swap links, reciprocal, guest post fee, dofollow, do-follow.
- **(enforced)** Link to anything except the brief's `asset_url`, `client_home`, `contact_path` or the prospect's own evidence pages.
- **(enforced)** Send without a named approver, or contact a domain marked `do_not_contact`.
- Claim a client, result, award or number that is not in the brief's `allowed_claims`. If proof is thin, offer expertise, not portfolio.
- Pretend to be a reader, a fan or a mutual connection.
- Scrape or guess personal email addresses. Use the site's public contact page, or the address a person published for this purpose.

## Format

- **(enforced)** Subject of at most 90 characters; body of at most 150 words; neither empty.
- One ask, stated plainly in the last two sentences.
- The first line says why this page fits *their* readers, quoting the evidence (the page title or URL that links to a competitor).
- Plain text. No attachments. A signature with the sender's real name and role.

## Cadence

- **(enforced)** One follow-up at most, at least 7 days after first contact, with its own approval.
- **(enforced)** `lost` and `no_reply` start a 90-day cooldown before the domain can be re-added.
- Stop immediately on any opt-out, and mark `do_not_contact`.

## Compliance

- Follow the anti-spam law of the sender's and the recipient's country: identify the sender, give a working reply address, and honor opt-outs.
- Keep a record. The `events` table logs every status change with its actor and time.
```

- [ ] **Step 4: Wire the hub, the docs and the counts**

1. **`skills/seo/SKILL.md`, routing.** In the **Research** table, add this row directly after the `/seo competitors <domain>` row:

```markdown
| `/seo links <setup\|gap\|prospects\|draft\|track> <domain>` | Competitor link gap, scored prospects, approval-gated outreach drafts, tracker, won-link verification (`seo-links`) |
```

2. **`skills/seo/SKILL.md`, skill list.** In the numbered skill list, add this item after item 37 (`geo-share-of-voice`):

```markdown
38. **seo-links** -- Competitor link gap and white-hat link earning: deterministic prospect scoring, human-approved drafts, pipeline tracker, won-link verification, links.* KPIs
```

   If the list already ends above 37, renumber so the numbering stays sequential.

3. **`skills/seo/SKILL.md`, counts.** In both count sentences (near lines 22 and 364), replace `38 sub-skills (35 core` with `39 sub-skills (36 core`.

4. **`skills/seo-competitors/SKILL.md`.** Replace the two lines under `## Step 4: Backlink gap` that begin "Route to `seo-backlinks`…" with:

```markdown
Route to `seo-links`: `/seo links gap <domain>` (it runs `scripts/link_sources.py`
and `scripts/link_gap.py` on one source for the client and every profile
competitor). Report the gap segment (domains linking to 2+ competitors but not
to us) with its coverage, then `/seo links prospects` for the ranked list.
```

5. **`skills/seo-backlinks/SKILL.md`, description.** In the description on line 3, replace `competitor gap analysis.` with `competitor link gap (routed to seo-links).`, and replace `link gap, link building, disavow` with `disavow`.

6. **`skills/seo-backlinks/SKILL.md`, §6.** Replace the whole body of `### 6. Competitor Gap Analysis` (everything up to `### 7.`) with:

```markdown
Handled by `seo-links`, which is deterministic and source-consistent:
`/seo links gap <domain>` then `/seo links prospects <domain>` (DataForSEO,
Moz or CSV exports; one source per run). Do not compare referring domains here
by hand.
```

7. **`skills/seo-backlinks/SKILL.md`, report heading.** Replace the line `### Link Building Opportunities (top 10)` with `### Link Building Opportunities (top 10 from /seo links prospects)`.

8. **`docs/COMMANDS.md`, command section.** Insert this section immediately before the line `### /seo content-engine [plan|brief|draft|check|export|measure] <domain|item|file>` (keep the `---` separator):

```markdown
### `/seo links setup|gap|prospects|draft|track <domain>`

Competitor link gap and white-hat link earning (`seo-links`):
- **Gap:** referring domains of the client and its 3-7 profile competitors, from
  one source (DataForSEO, Moz or a CSV export), segmented as gap / single /
  shared / moat.
- **Prospects:** exclusions (own, competitor, social, spam ≥ 60, paid signals),
  a rule-based type and a deterministic 0-100 score; high-value, quick-win and
  backlog buckets.
- **Drafts:** written from a brief and linted against payment, sponsorship,
  link-swap and dofollow asks. A named person approves; nothing is ever sent.
- **Track:** contacted → won/lost/no-reply, one follow-up, a 90-day cooldown,
  won links verified on the page, `links.*` KPIs for `/seo track`.

Runs `scripts/link_sources.py`, `scripts/link_gap.py` and
`scripts/link_outreach.py`.

---
```

9. **`docs/COMMANDS.md`, summary table.** Add this row after the `/seo competitors <domain>` row:

```markdown
| `/seo links <domain>` | Competitor link gap, scored prospects, approved outreach, tracker |
```

10. **Commands tables in the root docs.**
    - `CLAUDE.md`: add `` | `/seo links <setup\|gap\|prospects\|draft\|track> <domain>` | Competitor link gap, scored prospects, approval-gated outreach, tracker | `` after the `/seo competitors <domain>` row.
    - `AGENTS.md`: add `` | `/seo links <domain>` | Competitor link gap, prospects, approved outreach, tracker | `` after its `/seo competitors` row.
    - `README.md`: add `` | `/seo links <domain>` | Competitor link gap, deterministic prospect scoring, human-approved outreach drafts, pipeline tracker, won-link verification | `` after its `/seo competitors` row.

11. **Architecture tree and script list in `CLAUDE.md`.**
    - In the skills tree, add `    seo-links/                   # Competitor link gap + link earning (prospects, approved drafts, tracker)` after the `seo-track/` line.
    - In the scripts list, add these lines after `ai_visibility.py …`:

```
    link_store.py                # links store: referring-domain snapshots, prospects, events
    link_sources.py              # DataForSEO / Moz / CSV referring domains, cost-capped
    link_gap.py                  # Competitor link gap, prospect classification and scoring
    link_outreach.py             # Approval-gated outreach tracker, draft lint, verification, KPIs
```

11b. **`skills/seo-track/SKILL.md`.**
    - In the report-order list, insert this item after item 3 ("AI visibility …") and renumber the old item 4 to 5:

```markdown
4. Links: `links.referring_domains` and `links.gap_domains` (from `link_gap.py kpis`,
   per data source; never compare DataForSEO counts with Moz counts) and the
   outreach pipeline `links.contacted`, `links.won`, `links.won_verified`,
   `links.win_rate` (from `link_outreach.py kpis`; win rate stays null below 5
   contacted).
```

    - In the `## 6. Cadence` table, append this to the end of the Monthly cell: `` , `link_outreach.py verify` + `kpis` and `link_gap.py kpis` + `ingest` ``.

12. **Counts.** Run this from the repo root:

```bash
$PY - <<'EOF'
from pathlib import Path
edits = {
    "README.md": [("39 sub-skills", "40 sub-skills")],
    "CLAUDE.md": [("39 sub-skills (35 core", "40 sub-skills (36 core"), ("39 sub-skills", "40 sub-skills")],
    "AGENTS.md": [("39 sub-skills (35 core", "40 sub-skills (36 core"), ("39 sub-skills", "40 sub-skills")],
    "docs/ARCHITECTURE.md": [("39 sub-skills (35 core", "40 sub-skills (36 core")],
    ".claude-plugin/plugin.json": [("39 sub-skills (35 core", "40 sub-skills (36 core")],
    ".claude-plugin/marketplace.json": [("39 sub-skills (35 core", "40 sub-skills (36 core"), ("39 sub-skills", "40 sub-skills")],
}
for rel, pairs in edits.items():
    p = Path(rel); s = p.read_text(encoding="utf-8")
    for old, new in pairs:
        s = s.replace(old, new)
    p.write_text(s, encoding="utf-8")
print("counts updated")
EOF
grep -rn "39 sub-skills\|35 core" README.md CLAUDE.md AGENTS.md docs/ARCHITECTURE.md .claude-plugin/ skills/seo/SKILL.md
```

Expected: `counts updated`, and the grep prints nothing.

13. **`CHANGELOG.md`.** Under `## Unreleased`, add an `### Added` heading above `### Fixed`:

```markdown
### Added

- **`/seo links`: competitor link gap and white-hat link earning** (new
  `seo-links` skill and `link_store.py`, `link_sources.py`, `link_gap.py`,
  `link_outreach.py`).
  - **Sources:** referring domains for the client and its profile competitors
    come from DataForSEO (cost estimated first, hard `--max-cost`, stops on
    insufficient funds, actual cost logged), Moz, or CSV exports. One source is
    used per run.
  - **Gap and scoring:** a deterministic gap segments the domains, excludes
    spam and paid signals, classifies prospects by rule, and scores them with a
    fixed formula into high-value, quick-win and backlog buckets.
  - **Outreach:** drafts are written from briefs and linted against payment,
    sponsorship, link-swap and dofollow asks. A named person approves; nothing
    is ever sent.
  - **Tracking:** a pipeline tracker with one follow-up, a 90-day cooldown and
    do-not-contact; won links are verified on the page; `links.*` KPIs.
- **Profile `topics` field** (service terms used for link relevance).
- **`dataforseo_costs.unit_cost` / `record_spend`** for scripts that budget
  paid calls.
```

    In the same `Unreleased` section, under `### Fixed`, add:

```markdown
- **DataForSEO detection.** `backlinks_auth.py` reported "Tier 3, Premium"
  whenever `~/.claude/settings.json` had a dataforseo MCP entry, but Claude Code
  never loads MCP servers from that file. It now reads `~/.claude.json` (user
  and project scopes), flags the stale copy with the fix command, and resolves
  REST credentials without printing them.
```

- [ ] **Step 5: Run the gates**

Run:
```bash
$PY -m pytest tests/test_manifest_consistency.py -q
$PY scripts/consistency_check.py
$PY scripts/portability_check.py
wc -l skills/seo-links/SKILL.md skills/seo-links/references/*.md
```

Expected:
- manifest tests PASS;
- `consistency_check` reports `PASS: 0 errors`;
- `portability_check` reports 0 errors;
- `SKILL.md` is under 500 lines and every reference is under 200 lines.

If `consistency_check` reports a routing error for `/seo links`, make sure the command appears both in `skills/seo/SKILL.md` and in `docs/COMMANDS.md`, in backticks.

- [ ] **Step 6: Commit**

```bash
git add skills/seo-links skills/seo/SKILL.md skills/seo-competitors/SKILL.md skills/seo-backlinks/SKILL.md skills/seo-track/SKILL.md \
  docs/COMMANDS.md README.md CLAUDE.md AGENTS.md docs/ARCHITECTURE.md .claude-plugin/plugin.json \
  .claude-plugin/marketplace.json CHANGELOG.md
git commit -m "Add the seo-links skill and route link-gap work to it

/seo links setup|gap|prospects|draft|track with a playbook, outreach rules
and the scoring reference. seo-competitors step 4 and seo-backlinks section
6 now route competitor link gaps here; skill counts go to 40 (36 core).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: End-to-end integration test

**Files:**
- Create: `tests/test_links_integration.py`

**Interfaces:**
- Consumes: the CLIs of `seo_project.py`, `link_sources.py`, `link_gap.py`, `link_outreach.py` and `performance_tracker.py`, run as subprocesses.

- [ ] **Step 1: Write the test**

Create `tests/test_links_integration.py`:

```python
"""
End-to-end contract test for /seo links, run as real CLI subprocesses.

profile -> CSV imports (client + 3 competitors) -> gap -> prospects -> gap KPIs
-> outreach add -> brief -> save-draft (lint) -> approve -> contacted -> won
-> outreach KPIs -> performance_tracker ingest/report.

No network: CSV fixtures, --no-sitemap, and HOME pointed at a temp dir so no
real credential file can be read.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
DOMAIN = "acme.in"
SRC = "csv-generic"


def run(tmp: Path, script: str, *args: str, expect: int = 0) -> subprocess.CompletedProcess:
    proc = subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True,
                          env={"CLAUDE_SEO_DATA_DIR": str(tmp / "data"), "HOME": str(tmp),
                               "PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"})
    assert proc.returncode == expect, f"{script} {args}: rc={proc.returncode}\n{proc.stderr}\n{proc.stdout}"
    return proc


def write_csv(path: Path, rows: list) -> Path:
    header = "domain,authority,dofollow,sample_url,anchor,title,spam_score"
    lines = [header] + [",".join(str(r.get(k, "")) for k in
                                 ("domain", "authority", "dofollow", "sample_url", "anchor", "title",
                                  "spam_score")) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_links_loop_contracts(tmp_path: Path) -> None:
    run(tmp_path, "seo_project.py", "init", DOMAIN, "--name", "Acme", "--brand", "acme",
        "--competitor", "rival.com", "--competitor", "other.in", "--competitor", "third.io",
        "--country", "IN")
    run(tmp_path, "seo_project.py", "set", DOMAIN, "topics", '["training video", "compliance training"]')

    pub = {"domain": "trainingmag.com", "authority": 80, "dofollow": "true",
           "sample_url": "https://trainingmag.com/2025/03/best-training-video-studios/",
           "anchor": "Rival", "title": "Best training video studios for compliance training"}
    clutch = {"domain": "clutch.co", "authority": 70, "dofollow": "true",
              "sample_url": "https://clutch.co/video-production/india", "anchor": "Rival"}
    files = {
        DOMAIN: write_csv(tmp_path / "client.csv", [{"domain": "partner.in"}]),
        "rival.com": write_csv(tmp_path / "rival.csv", [pub, clutch, {"domain": "spamfarm.biz", "spam_score": 80},
                                                         {"domain": "partner.in"}]),
        "other.in": write_csv(tmp_path / "other.csv", [pub, {
            "domain": "hrweekly.in", "authority": 40, "dofollow": "true",
            "sample_url": "https://hrweekly.in/resources/compliance-training-tools",
            "title": "Compliance training tools"}, {"domain": "linkedin.com"}]),
        "third.io": write_csv(tmp_path / "third.csv", [clutch, {
            "domain": "blogger.net", "sample_url": "https://blogger.net/blog/my-favourite-studios/"}]),
    }
    for target, path in files.items():
        run(tmp_path, "link_sources.py", "import", "--project", DOMAIN, "--target", target,
            "--format", "generic", str(path), "--json")

    gap = json.loads(run(tmp_path, "link_gap.py", "gap", "--project", DOMAIN, "--source", SRC,
                         "--no-sitemap", "--json").stdout)
    assert gap["segments"] == {"gap": 2, "single": 4, "shared": 1, "moat": 0}

    pros = json.loads(run(tmp_path, "link_gap.py", "prospects", "--project", DOMAIN, "--source", SRC,
                          "--no-sitemap", "--json").stdout)
    assert [(p["domain"], p["score"], p["bucket"]) for p in pros["prospects"]] == [
        ("trainingmag.com", 74, "high_value"), ("clutch.co", 55, "quick_win"),
        ("hrweekly.in", 53, "backlog"), ("blogger.net", 36, "backlog")]

    gap_kpis = tmp_path / "kpis-links-gap.json"
    run(tmp_path, "link_gap.py", "kpis", "--project", DOMAIN, "--source", SRC, "--no-sitemap",
        "--emit-kpis", str(gap_kpis), "--json")

    added = json.loads(run(tmp_path, "link_outreach.py", "add", "--project", DOMAIN, "--source", SRC,
                           "--no-sitemap", "--json").stdout)
    assert added["added"] == ["trainingmag.com", "clutch.co"]

    brief = json.loads(run(tmp_path, "link_outreach.py", "brief", "--project", DOMAIN,
                           "--domain", "trainingmag.com", "--json").stdout)
    assert brief["asset_url"] == "https://acme.in/"
    bad = tmp_path / "bad.txt"
    bad.write_text("Happy to pay for a dofollow link.", encoding="utf-8")
    lint = json.loads(run(tmp_path, "link_outreach.py", "save-draft", "--project", DOMAIN,
                          "--domain", "trainingmag.com", "--brief-hash", brief["brief_hash"],
                          "--subject", "Hi", "--body-file", str(bad), "--json", expect=1).stdout)
    assert {p["term"] for p in lint["problems"]} >= {"pay", "dofollow"}
    good = tmp_path / "good.txt"
    good.write_text("Your list of training video studios helps compliance teams. Acme makes "
                    "compliance training videos: https://acme.in/ Worth a look for your next update?",
                    encoding="utf-8")
    run(tmp_path, "link_outreach.py", "save-draft", "--project", DOMAIN, "--domain", "trainingmag.com",
        "--brief-hash", brief["brief_hash"], "--subject", "For your training video studios list",
        "--body-file", str(good), "--json")
    run(tmp_path, "link_outreach.py", "mark", "--project", DOMAIN, "--domain", "trainingmag.com",
        "--status", "contacted", expect=2)  # not approved yet
    run(tmp_path, "link_outreach.py", "approve", "--project", DOMAIN, "--domain", "trainingmag.com",
        "--reviewed-by", "Riya", "--json")
    run(tmp_path, "link_outreach.py", "mark", "--project", DOMAIN, "--domain", "trainingmag.com",
        "--status", "contacted", "--json")
    run(tmp_path, "link_outreach.py", "mark", "--project", DOMAIN, "--domain", "trainingmag.com",
        "--status", "won", "--link-url", "https://trainingmag.com/2025/03/best-training-video-studios/",
        "--json")

    out_kpis = tmp_path / "kpis-links.json"
    run(tmp_path, "link_outreach.py", "kpis", "--project", DOMAIN, "--emit-kpis", str(out_kpis), "--json")
    env = json.loads(out_kpis.read_text())
    assert env["metrics"]["links.won"] == 1 and env["metrics"]["links.win_rate"] is None

    run(tmp_path, "performance_tracker.py", "ingest", str(gap_kpis), str(out_kpis))
    rep = json.loads(run(tmp_path, "performance_tracker.py", "report", "--project", DOMAIN,
                         "--json").stdout)
    latest = {r["metric"]: r["latest"] for r in rep["metrics"]}
    assert latest["links.won"]["value"] == 1
    assert latest["links.gap_domains"]["source"] == "link_gap.py (csv-generic)"
    assert "links.win_rate" not in latest  # null is "not measured", never a fake zero
```

- [ ] **Step 2: Run it**

Run: `$PY -m pytest tests/test_links_integration.py -q`
Expected: PASS. If `seo_project.py set` rejects a JSON list value, read `cmd_set` in `scripts/seo_project.py` and pass the value in the format it parses. Do not weaken the assertion.

- [ ] **Step 3: Run the full suite**

Run: `$PY -m pytest tests -q -p no:cacheprovider`
Expected: everything passes except the known `tests/test_sync_flow.py` network flake.

- [ ] **Step 4: Commit and push**

```bash
git add tests/test_links_integration.py
git commit -m "Test the /seo links loop end to end through the CLIs

Profile, CSV imports, gap, prospects, gap KPIs, outreach add, brief, lint
rejection, approval gate, contacted, won, outreach KPIs and
performance_tracker ingest and report, with no network and no real
credential file.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push origin claude/aeo-seo-geo-consolidation-272910
```

---

### Task 9: Machine setup and live smoke test (needs user approvals)

This task changes the user's own config files and spends money, so every step marked **ASK** waits for an explicit yes in chat.

**Files:** none in the repo. The task touches `~/.claude.json` and `~/.claude/settings.json` (with backups), and Moz settings in `~/.config/claude-seo/backlinks-api.json`.

- [ ] **Step 1: Install the updated scripts into the skill** (mirrors `install.sh`)

```bash
cp scripts/link_store.py scripts/link_sources.py scripts/link_gap.py scripts/link_outreach.py \
   scripts/backlinks_auth.py scripts/dataforseo_costs.py scripts/seo_project.py scripts/seo_kpi.py \
   scripts/citability_scorer.py scripts/brand_scanner.py scripts/llmstxt_generator.py \
   ~/.claude/skills/seo/scripts/
mkdir -p ~/.claude/skills/seo-links && cp -R skills/seo-links/. ~/.claude/skills/seo-links/
for s in seo seo-competitors seo-backlinks; do cp skills/$s/SKILL.md ~/.claude/skills/$s/SKILL.md; done
```

- [ ] **Step 2 (ASK first): Move the DataForSEO entry**

The user approved this config change during design; confirm once more. Then run:

```bash
TS=$(date +%Y%m%d-%H%M%S); B=~/.cache/claude-seo/backups; mkdir -p "$B"
cp -p ~/.claude/settings.json "$B/settings.json.$TS"; [ -f ~/.claude.json ] && cp -p ~/.claude.json "$B/claude.json.$TS"
python3 - <<'EOF'
import json, os, tempfile
src = os.path.expanduser("~/.claude/settings.json"); dst = os.path.expanduser("~/.claude.json")
entry = json.load(open(src))["mcpServers"]["dataforseo"]
data = json.load(open(dst)) if os.path.exists(dst) else {}
servers = data.setdefault("mcpServers", {})
if "dataforseo" in servers:
    print("~/.claude.json already has dataforseo; leaving it unchanged")
else:
    servers["dataforseo"] = entry
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dst)); os.close(fd)
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    os.chmod(tmp, 0o600); os.replace(tmp, dst)
    print("moved dataforseo entry into ~/.claude.json (values not printed)")
EOF
python3 extensions/mcp_config_cleanup.py dataforseo --json
~/.claude/skills/seo/.venv/bin/python ~/.claude/skills/seo/scripts/backlinks_auth.py --check dataforseo --json
```

Expected: `mcp_configured: true`, `stale_config: false`, `rest_credentials: true`, `rest_credentials_source: "claude_json"`. No credential value appears anywhere in the output.

- [ ] **Step 3: Moz key (the user runs this; the key never enters the chat)**

Give the user this command to run in their own terminal:

```bash
read -rs "MOZKEY?Paste Moz API key (hidden): " && MOZKEY="$MOZKEY" python3 -c 'import json,os;p=os.path.expanduser("~/.config/claude-seo/backlinks-api.json");d=json.load(open(p));d["moz_api_key"]=os.environ["MOZKEY"].strip();json.dump(d,open(p,"w"),indent=2);os.chmod(p,0o600);print("saved")' && unset MOZKEY
```

Then check it: `~/.claude/skills/seo/.venv/bin/python ~/.claude/skills/seo/scripts/backlinks_auth.py --check moz --json`. Expected: `"available": true`.

- [ ] **Step 4 (ASK first): Live DataForSEO smoke on Zyra**

Run the dry run and show the estimate to the user:

```bash
cd ~/.claude/skills/seo && .venv/bin/python scripts/link_sources.py fetch --project thezyra.studio --source dataforseo --dry-run --json
```

Expected: 3 calls, about $0.06. After the user says yes:

```bash
cd ~/.claude/skills/seo && .venv/bin/python scripts/link_sources.py fetch --project thezyra.studio --source dataforseo --max-cost 0.25 --json
```

Expected: exit 0 or 1, coverage "3 of 3" (or the errors listed), and `spent_usd` ≤ 0.25. If the API rejects `order_by` `domain_from_rank,desc` with a field error, change `fetch_dataforseo` to `["rank,desc"]`, add a test asserting the new payload, re-run Task 4's tests, and commit.

- [ ] **Step 5: Validate the field mapping against the live snapshot**

```bash
~/.claude/skills/seo/.venv/bin/python - <<'EOF'
import sys, os; sys.path.insert(0, os.path.expanduser("~/.claude/skills/seo/scripts"))
import link_store
c = link_store.open_store()
for t, row in link_store.latest_snapshots(c, "thezyra.studio", "dataforseo").items():
    recs = link_store.snapshot_records(c, row["id"])
    n = len(recs) or 1
    fill = {f: round(sum(r[f] is not None for r in recs) / n, 2) for f in ("authority", "sample_url", "sample_anchor", "sample_title", "dofollow", "spam_score")}
    print(t, row["row_count"], "cap" if row["row_cap_hit"] else "", fill)
EOF
```

Expected: `sample_url` at 1.0 and `authority` at or near 1.0 for targets with rows. If `authority` or `sample_title` is 0.0, the response uses a different field name. Read one item from a fresh `--limit 5` fetch, fix `normalize_dataforseo_item`, add the real field to `tests/test_link_sources.py`'s `ITEM_PUB`, and re-run.

- [ ] **Step 6: Review the live gap**

Run `link_gap.py prospects --project thezyra.studio --source dataforseo --top 20` and show the user:
- the buckets;
- the top 10 prospects;
- the exclusions;
- the warnings (coverage, topics).

Suggest setting the profile `topics` if the run reports `topics_source: sitemap` or `none`.

- [ ] **Step 7: Final gates, then commit and push any fixes from Steps 4-5**

```bash
$PY -m pytest tests -q -p no:cacheprovider
$PY scripts/consistency_check.py
git status --short
git push origin claude/aeo-seo-geo-consolidation-272910
```

Then give the user the compare link: `https://github.com/toolsatZyra/-claude-seo-x-geo/compare/main...claude/aeo-seo-geo-consolidation-272910`.
