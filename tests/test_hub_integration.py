"""
End-to-end integration test for the v3.1 growth loop.

Each workstream tests its own module; this test checks the CONTRACTS between
them by running every script as a real CLI subprocess against one shared,
temporary data directory, in the order the hub's Growth Loop uses them:

    seo_project init  ->  keyword_research score  ->  rank_tracker add/ingest/report
    ->  aeo_score compute  ->  ai_visibility ingest/report  ->  content_decay analyze
    ->  performance_tracker ingest/record/report/export  (what geo-compare reads)

No network: every data source is a fixture file. Dates are pinned with
--as-of / --date so the result is deterministic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
DOMAIN = "acme.io"
AS_OF = "2026-10-17"


def run(data_dir: Path, script: str, *args: str, expect: int = 0) -> subprocess.CompletedProcess:
    proc = subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True,
                          env={"CLAUDE_SEO_DATA_DIR": str(data_dir), "PATH": "/usr/bin:/bin",
                               "PYTHONIOENCODING": "utf-8"})
    assert proc.returncode == expect, f"{script} {args}: rc={proc.returncode}\n{proc.stderr}\n{proc.stdout}"
    return proc


def days(start: date, n: int) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def gsc_rows(query: str, page: str, start: date, n: int, pos: float, imps: int, clicks: int) -> list[dict]:
    """gsc_query.py-shaped rows; ctr is a PERCENT there, like the real script."""
    return [{"keys": [d, query, page], "clicks": clicks, "impressions": imps,
             "ctr": round(100 * clicks / imps, 2), "position": pos} for d in days(start, n)]


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def test_growth_loop_contracts(tmp_path: Path, data_dir: Path) -> None:
    # 1. Client profile ------------------------------------------------------
    run(data_dir, "seo_project.py", "init", DOMAIN, "--name", "Acme", "--brand", "acme",
        "--competitor", "rival.com", "--competitor", "other.io", "--competitor", "third.net",
        "--gsc-property", f"sc-domain:{DOMAIN}")
    run(data_dir, "seo_project.py", "set", DOMAIN, "money_pages", '["/pricing"]')
    for prompt, group in (("best crm for startups", "treatment"),
                          ("crm with email automation", "treatment"),
                          ("what is a crm", "control")):
        run(data_dir, "seo_project.py", "add-prompt", DOMAIN, prompt, "--group", group)
    profile = json.loads(run(data_dir, "seo_project.py", "show", DOMAIN, "--json").stdout)["profile"]
    assert profile["competitors"][0]["domain"] == "rival.com"
    assert len(profile["ai_visibility"]["prompts"]) == 3

    # 2. Keyword research: merge an Ahrefs-style CSV with a planner-style JSON
    csv = tmp_path / "ahrefs.csv"
    csv.write_text("Keyword,Volume,KD,Position,URL\n"
                   "crm pricing,2400,35,8,https://acme.io/pricing\n"
                   "what is a crm,9900,60,,\n"
                   "acme login,800,5,1,https://acme.io/login\n"
                   "rival alternatives,700,20,,\n", encoding="utf-8")
    kw = json.loads(run(data_dir, "keyword_research.py", "score", "--input", str(csv),
                        "--project", DOMAIN, "--json").stdout)
    by_kw = {k["keyword"]: k for k in kw["keywords"]}
    assert by_kw["crm pricing"]["funnel"] == "BOFU"
    assert by_kw["acme login"]["intent"] == "navigational"          # brand from the profile
    assert by_kw["rival alternatives"]["funnel"] == "BOFU"          # competitor from the profile
    # a measured BOFU keyword in striking distance outranks thin or TOFU ones
    assert by_kw["crm pricing"]["opportunity_score"] > by_kw["what is a crm"]["opportunity_score"]

    # 3. Rank tracking from GSC history -> KPI envelope ----------------------
    run(data_dir, "rank_tracker.py", "add", "crm pricing", "what is a crm",
        "--tag", "bofu", "--project", DOMAIN)
    rows = (gsc_rows("crm pricing", "https://acme.io/pricing", date(2026, 10, 1), 7, 9.0, 200, 4)
            + gsc_rows("crm pricing", "https://acme.io/pricing", date(2026, 10, 8), 7, 4.0, 200, 14))
    gsc_file = tmp_path / "gsc.json"
    gsc_file.write_text(json.dumps({"rows": rows}))
    run(data_dir, "rank_tracker.py", "ingest-gsc", "--input", str(gsc_file), "--project", DOMAIN)
    rank_env = tmp_path / "kpi-rank.json"
    rank = json.loads(run(data_dir, "rank_tracker.py", "report", "--as-of", AS_OF, "--project", DOMAIN,
                          "--emit-kpis", str(rank_env), "--json").stdout)
    assert rank["movers"]["gainers"][0]["keyword"] == "crm pricing"

    # 4. One AEO score -------------------------------------------------------
    aeo_env = tmp_path / "kpi-aeo.json"
    aeo = json.loads(run(data_dir, "aeo_score.py", "compute", "--citability", "62", "--crawler-access", "89",
                         "--schema", "55", "--project", DOMAIN, "--date", AS_OF,
                         "--emit-kpis", str(aeo_env), "--json").stdout)
    # the printed expression must reproduce the score (scoring-rubric Rule 4)
    assert eval(aeo["expression"], {"__builtins__": {"round": round}}) == aeo["score"]  # noqa: S307
    assert aeo["completeness"] < 1.0

    # 5. AI share of voice from captured answers ------------------------------
    answers = tmp_path / "chatgpt.jsonl"
    lines = []
    for i in range(6):
        lines.append({"prompt": "best crm for startups", "run_at": f"2026-10-1{i}T10:00:00Z",
                      "answer": "Top picks: Acme and Rival." if i % 2 == 0 else "Rival is popular.",
                      "citations": ["https://acme.io/pricing"] if i % 2 == 0 else ["https://rival.com/"]})
    answers.write_text("\n".join(json.dumps(r) for r in lines) + "\n")
    run(data_dir, "ai_visibility.py", "ingest", "--project", DOMAIN, str(answers), "--engine", "chatgpt")
    ai_env = tmp_path / "kpi-ai.json"
    ai = json.loads(run(data_dir, "ai_visibility.py", "report", "--project", DOMAIN,
                        "--emit-kpis", str(ai_env), "--json").stdout)
    assert ai["headline"]["mention_rate"] == pytest.approx(0.5)
    assert ai["headline"]["thin"] is True                           # n < 20 is never presented as solid

    # 6. Content decay with the money page sorted first -----------------------
    windows = tmp_path / "windows.json"
    windows.write_text(json.dumps({
        "current": [{"page": "https://acme.io/pricing", "clicks": 40, "impressions": 4000, "position": 6.0},
                    {"page": "https://acme.io/blog/a", "clicks": 30, "impressions": 3000, "position": 7.0}],
        "yoy": [{"page": "https://acme.io/pricing", "clicks": 200, "impressions": 4200, "position": 5.0},
                {"page": "https://acme.io/blog/a", "clicks": 150, "impressions": 3100, "position": 6.5}],
        "previous": [], "query_page": []}))
    decay = json.loads(run(data_dir, "content_decay.py", "analyze", "--input", str(windows),
                           "--project", DOMAIN, "--as-of", AS_OF, "--json").stdout)
    assert decay["pages"][0]["page"].endswith("/pricing")

    # 7. KPI history: ingest every envelope, add CRM leads, compare, export ---
    for env in (rank_env, aeo_env, ai_env):
        run(data_dir, "performance_tracker.py", "ingest", str(env))
    run(data_dir, "performance_tracker.py", "record", "--project", DOMAIN, "--metric", "leads.organic",
        "--value", "12", "--date", "2026-09-17")
    run(data_dir, "performance_tracker.py", "record", "--project", DOMAIN, "--metric", "leads.organic",
        "--value", "6", "--date", AS_OF)
    # a 50% lead drop must trip the gate (exit 3), the CI/cron contract
    run(data_dir, "performance_tracker.py", "report", "--project", DOMAIN, "--compare", "30d",
        "--fail-on-drop", "20", "--watch", "leads.organic", expect=3)
    # Envelopes carry their own measurement dates (the AI envelope is dated by
    # its last captured answer), so consumers read each metric's latest value
    # via `report`, and the export keeps every dated snapshot for geo-compare.
    rep = json.loads(run(data_dir, "performance_tracker.py", "report", "--project", DOMAIN,
                         "--json").stdout)
    latest = {r["metric"]: r["latest"] for r in rep["metrics"]}
    assert latest["aeo.score"]["value"] == aeo["score"]
    assert latest["ai.mention_rate"]["source"] == "ai_visibility.py"
    assert latest["ai.mention_rate"]["date"] == "2026-10-15"
    assert latest["rank.tracked"]["value"] == 2
    # readiness and outcome stay separate metrics: nothing blended them
    assert {"aeo.score", "ai.sov"} <= set(latest) and "seo.health" not in latest

    export = json.loads(run(data_dir, "performance_tracker.py", "export", "--project", DOMAIN,
                            "--json").stdout)
    dates = [s["date"] for s in export["snapshots"]]
    assert dates == sorted(dates)
    exported = {m for s in export["snapshots"] for m in s["metrics"]}
    assert {"aeo.score", "ai.mention_rate", "rank.visibility", "leads.organic"} <= exported


def test_bad_producer_value_is_rejected_at_the_source(tmp_path: Path, data_dir: Path) -> None:
    """A percent passed where a 0-100 score is fine, but >100 must fail before writing."""
    env = tmp_path / "bad.json"
    run(data_dir, "aeo_score.py", "compute", "--citability", "140", "--project", DOMAIN,
        "--emit-kpis", str(env), expect=2)
    assert not env.exists()
