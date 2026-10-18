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
