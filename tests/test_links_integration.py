"""
End-to-end contract test for /seo links, run as real CLI subprocesses.

profile -> CSV imports (client + 3 competitors) -> gap -> prospects -> gap KPIs
-> outreach add -> brief -> save-draft (lint) -> approve -> contacted -> won
-> verify (mocked checker, in-process) -> outreach KPIs -> performance_tracker ingest/report.

No network: CSV fixtures, --no-sitemap, and HOME pointed at a temp dir so no
real credential file can be read. verify runs in-process with a fake checker because
the real one fetches the linking page.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import link_outreach  # noqa: E402
import link_store  # noqa: E402

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
    # gap domains are listed on their own, and every exclusion is counted by reason
    assert [p["domain"] for p in pros["gap_prospects"]] == ["trainingmag.com", "clutch.co"]
    assert pros["total_gap_prospects"] == 2 and pros["excluded_counts"] == {"social_ugc": 1, "spam": 1}

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

    # verify: the real checker fetches the linking page, so a fake one stands in for it
    conn = link_store.open_store(str(tmp_path / "data"))
    seen = []

    def fake_checker(source_url, target_url):
        seen.append((source_url, target_url))
        return {"status": "verified", "rel_attributes": ["nofollow"]}

    [checked] = link_outreach.verify(conn, DOMAIN, verifier=fake_checker)
    assert seen == [("https://trainingmag.com/2025/03/best-training-video-studios/", "https://acme.in/")]
    assert checked["verified_status"] == "live" and checked["link_rel"] == "nofollow"
    board = json.loads(run(tmp_path, "link_outreach.py", "board", "--project", DOMAIN, "--json").stdout)
    won = next(p for p in board["prospects"] if p["domain"] == "trainingmag.com")
    assert won["status"] == "won" and won["verified_status"] == "live" and won["link_rel"] == "nofollow"

    out_kpis = tmp_path / "kpis-links.json"
    run(tmp_path, "link_outreach.py", "kpis", "--project", DOMAIN, "--emit-kpis", str(out_kpis), "--json")
    env = json.loads(out_kpis.read_text())
    assert env["metrics"]["links.won"] == 1 and env["metrics"]["links.win_rate"] is None
    assert env["metrics"]["links.won_verified"] == 1  # counted only after the page was checked

    run(tmp_path, "performance_tracker.py", "ingest", str(gap_kpis), str(out_kpis))
    rep = json.loads(run(tmp_path, "performance_tracker.py", "report", "--project", DOMAIN,
                         "--json").stdout)
    latest = {r["metric"]: r["latest"] for r in rep["metrics"]}
    assert latest["links.won"]["value"] == 1
    assert latest["links.gap_domains"]["source"] == "link_gap.py (csv-generic)"
    assert "links.win_rate" not in latest  # null is "not measured", never a fake zero
