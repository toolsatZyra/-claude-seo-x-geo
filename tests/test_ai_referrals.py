"""
Tests for scripts/ai_referrals.py — the versioned AI-source classifier, GA4
row normalization (UI CSV, API JSON, row lists), the AI-vs-organic summary,
KPI envelope output and the GA4 request shape (via a fake client).

Offline only: no GA4 calls, no real credentials, storage under tmp_path.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import ai_referrals as ar  # noqa: E402
import performance_tracker as pt  # noqa: E402

SCRIPT = str(REPO_ROOT / "scripts" / "ai_referrals.py")


@pytest.mark.parametrize("source,expected", [
    ("chatgpt.com", "ChatGPT"),
    ("chat.openai.com", "ChatGPT"),
    ("https://chatgpt.com/c/abc", "ChatGPT"),
    ("www.perplexity.ai", "Perplexity"),
    ("perplexity.ai", "Perplexity"),
    ("gemini.google.com", "Gemini"),
    ("bard.google.com", "Gemini"),
    ("copilot.microsoft.com", "Microsoft Copilot"),
    ("copilot.cloud.microsoft", "Microsoft Copilot"),
    ("edgeservices.bing.com", "Microsoft Copilot"),
    ("claude.ai", "Claude"),
    ("you.com", "You.com"),
    ("phind.com", "Phind"),
    ("meta.ai", "Meta AI"),
    ("chat.deepseek.com", "DeepSeek"),
    ("grok.com", "Grok"),
    ("chat.mistral.ai", "Mistral Le Chat"),
    ("CHATGPT.COM", "ChatGPT"),
    ("google", None),
    ("bing.com", None),
    ("openai.com", None),            # docs/blog referrals are not assistant answers
    ("notchatgpt.com", None),
    ("chatgpt.com.evil.net", None),
    ("(direct)", None),
    ("", None),
])
def test_classify_source(source, expected):
    assert ar.classify_source(source) == expected


def test_ga4_regex_matches_exactly_the_table():
    rx = re.compile(ar.ai_source_regex(), re.IGNORECASE)
    for _name, hosts in ar.AI_SOURCES:
        for h in hosts:
            assert rx.fullmatch(h) and rx.fullmatch("www." + h)
    for other in ("google", "notchatgpt.com", "chatgpt.com.evil.net", "openai.com"):
        assert not rx.fullmatch(other)
    assert ar.AI_SOURCES_VERSION == "2026-10-17"


UI_CSV = """# ----------------------------------------
# Traffic acquisition: Session source / medium
# ----------------------------------------
Session source / medium,Session default channel group,Landing page,Sessions,Key events,Session key event rate,keyEvents:generate_lead
google / organic,Organic Search,/,"1,000",50,4.5%,20
bing / organic,Organic Search,/blog,200,4,2%,1
chatgpt.com / referral,Referral,/pricing,60,6,10%,4
www.perplexity.ai / referral,Referral,/blog/guide,40,0,0%,0
chatgpt.com / organic,Organic Search,/pricing,10,1,10%,1
(direct) / (none),Direct,/,500,10,2%,5
gptzero-clone.app / referral,Referral,/,7,0,0%,0
Grand total,,,,,,
"""


def test_load_rows_ui_csv(tmp_path):
    p = tmp_path / "ga4.csv"
    p.write_text(UI_CSV)
    rows = ar.load_rows(str(p))
    assert len(rows) == 7                                    # comment + total lines dropped
    first = rows[0]
    assert (first["source"], first["medium"], first["sessions"]) == ("google", "organic", 1000.0)
    assert first["key_event_rate"] == 0.045 and first["events"] == {"generate_lead": 20.0}


def test_load_rows_api_json_and_row_list(tmp_path):
    api = {"dimensionHeaders": [{"name": "sessionSource"}, {"name": "sessionMedium"},
                                {"name": "sessionDefaultChannelGroup"}],
           "metricHeaders": [{"name": "sessions"}, {"name": "keyEvents"}],
           "rows": [{"dimensionValues": [{"value": "claude.ai"}, {"value": "referral"},
                                         {"value": "Referral"}],
                     "metricValues": [{"value": "12"}, {"value": "3"}]}]}
    p = tmp_path / "api.json"
    p.write_text(json.dumps(api))
    rows = ar.load_rows(str(p))
    assert rows[0]["source"] == "claude.ai" and rows[0]["key_events"] == 3.0
    assert rows[0]["key_event_rate"] is None
    q = tmp_path / "rows.json"
    q.write_text(json.dumps([{"source": "chatgpt.com", "medium": "referral", "sessions": 5,
                              "key_events": 1}]))
    assert ar.load_rows(str(q))[0]["sessions"] == 5.0


def test_summarize_ai_vs_organic(tmp_path):
    p = tmp_path / "ga4.csv"
    p.write_text(UI_CSV)
    s = ar.summarize(ar.load_rows(str(p)), conversion_events=["generate_lead"])
    assert s["totals"]["sessions"] == 1817
    ai = s["ai"]
    # chatgpt.com / organic counts as AI, never also as organic.
    assert ai["sessions"] == 110 and s["organic"]["sessions"] == 1200
    assert ai["share_of_total"] == round(110 / 1817, 4)
    assert [a["assistant"] for a in ai["by_assistant"]] == ["ChatGPT", "Perplexity"]
    assert ai["by_assistant"][0]["sessions"] == 70
    assert ai["cvr_basis"] == "sessions_with_key_event"
    assert ai["cvr"] == round((6 + 0 + 1) / 110, 4)         # rate x sessions, summed
    assert s["organic"]["cvr"] == round((45 + 4) / 1200, 4)
    assert [p["landing_page"] for p in ai["top_landing_pages"]] == ["/pricing", "/blog/guide"]
    assert ai["top_landing_pages"][0]["assistants"] == ["ChatGPT"]
    assert s["conversion_events"]["generate_lead"] == {"ai": 5.0, "organic": 21.0, "total": 31.0}
    assert s["possible_unclassified_ai_sources"] == [{"source": "gptzero-clone.app", "sessions": 7.0}]
    assert any("undercounted" in lim for lim in s["limitations"])


def test_summarize_without_rates_uses_events_basis():
    rows = [ar.normalize_row({"sessionSource": "chatgpt.com", "sessions": 10, "keyEvents": 15}),
            ar.normalize_row({"sessionSource": "google", "sessionMedium": "organic",
                              "sessions": 100, "keyEvents": 5})]
    s = ar.summarize(rows)
    assert s["ai"]["cvr_basis"] == "key_events_per_session"
    assert s["ai"]["cvr"] == 1.5                             # can exceed 1 on this basis
    assert s["organic"]["sessions"] == 100                   # medium fallback without channel
    env = pt.build_envelope("example.com", "ai_referrals.py", ar.kpis_from_summary(s))
    assert env["metrics"]["ga4.ai_cvr"] == 1.5


def test_empty_data_yields_null_rates():
    s = ar.summarize([])
    k = ar.kpis_from_summary(s)
    assert k["ga4.ai_sessions"] == 0 and k["ga4.ai_cvr"] is None
    assert pt.validate_envelope({"kpi_envelope": 1, "project": "example.com",
                                 "date": "2026-10-17", "source": "ai_referrals.py",
                                 "metrics": k})["skipped_null"] == ["ga4.ai_cvr", "ga4.organic_cvr"]


def test_landing_rows_override_traffic_rows():
    traffic = [ar.normalize_row({"sessionSource": "chatgpt.com", "sessions": 10, "keyEvents": 0})]
    landing = [ar.normalize_row({"sessionSource": "chatgpt.com", "landingPage": "/a", "sessions": 6}),
               ar.normalize_row({"sessionSource": "chatgpt.com", "landingPage": "/b", "sessions": 4}),
               ar.normalize_row({"sessionSource": "google", "landingPage": "/c", "sessions": 99})]
    s = ar.summarize(traffic, landing_rows=landing)
    assert [p["landing_page"] for p in s["ai"]["top_landing_pages"]] == ["/a", "/b"]


# ---------------------------------------------------------------------------
# GA4 request shape (fake client; requires the GA4 client library types)
# ---------------------------------------------------------------------------

def _resp(dims, mets, rows):
    return SimpleNamespace(
        dimension_headers=[SimpleNamespace(name=d) for d in dims],
        metric_headers=[SimpleNamespace(name=m) for m in mets],
        rows=[SimpleNamespace(dimension_values=[SimpleNamespace(value=v) for v in dv],
                              metric_values=[SimpleNamespace(value=v) for v in mv])
              for dv, mv in rows],
        row_count=len(rows))


class FakeClient:
    def __init__(self, reject_event_metrics=False):
        self.requests = []
        self.reject = reject_event_metrics

    def run_report(self, request):
        self.requests.append(request)
        metrics = [m.name for m in request.metrics]
        dims = [d.name for d in request.dimensions]
        if self.reject and any(":" in m for m in metrics):
            raise ValueError("INVALID_ARGUMENT: Did you mean keyEvents?")
        if "landingPage" in dims:
            return _resp(dims, metrics, [(["chatgpt.com", "/pricing"], ["9", "1"])])
        values = {"sessions": "9", "keyEvents": "1", "sessionKeyEventRate": "0.111"}
        mv = [values.get(m, "1") for m in metrics]
        return _resp(dims, metrics, [(["chatgpt.com", "referral", "Referral"], mv)])


def test_fetch_requests_per_event_metrics_and_ai_filter():
    pytest.importorskip("google.analytics.data_v1beta")
    client = FakeClient()
    rows, landing, notes = ar.fetch_ga4_rows("123", "2026-09-19", "2026-10-16",
                                             ["generate_lead", "bad name!"], client=client)
    traffic_req, landing_req = client.requests
    assert traffic_req.property == "properties/123"
    assert [m.name for m in traffic_req.metrics] == ["sessions", "keyEvents", "sessionKeyEventRate",
                                                     "keyEvents:generate_lead"]
    assert [d.name for d in traffic_req.dimensions] == ["sessionSource", "sessionMedium",
                                                        "sessionDefaultChannelGroup"]
    flt = landing_req.dimension_filter.filter
    assert flt.field_name == "sessionSource" and flt.string_filter.value == ar.ai_source_regex()
    assert rows[0]["events"] == {"generate_lead": 1.0}
    assert landing[0]["landing_page"] == "/pricing"
    assert any("bad name!" in n for n in notes)


def test_fetch_falls_back_when_event_metrics_rejected():
    pytest.importorskip("google.analytics.data_v1beta")
    client = FakeClient(reject_event_metrics=True)
    rows, _landing, notes = ar.fetch_ga4_rows("properties/123", "2026-09-19", "2026-10-16",
                                              ["generate_lead"], client=client)
    assert rows and rows[0]["events"] == {}
    assert any("rejected the per-event metrics" in n for n in notes)


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

def test_cli_input_json_and_emit_kpis(tmp_path):
    p = tmp_path / "ga4.csv"
    p.write_text(UI_CSV)
    kpis = tmp_path / "kpis.json"
    r = subprocess.run([sys.executable, SCRIPT, "--project", "www.example.com", "--input", str(p),
                        "--as-of", "2026-10-17", "--emit-kpis", str(kpis), "--json",
                        "--data-dir", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["project"] == "example.com" and out["ai"]["sessions"] == 110
    assert set(out) >= {"data_sources", "limitations", "kpis", "classification"}
    env = json.loads(kpis.read_text())
    assert pt.validate_envelope(env)["ok"]
    assert env["date"] == "2026-10-17" and env["metrics"]["ga4.organic_sessions"] == 1200

    r = subprocess.run([sys.executable, SCRIPT, "--project", "example.com", "--input", str(p),
                        "--data-dir", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0 and "AI assistants:" in r.stdout and "heuristic" in r.stdout


def test_cli_print_regex_and_missing_property(tmp_path):
    r = subprocess.run([sys.executable, SCRIPT, "--print-regex"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == ar.ai_source_regex()
    r = subprocess.run([sys.executable, SCRIPT, "--project", "example.com", "--data-dir",
                        str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 1 and "no GA4 property" in r.stderr
