"""Tests for scripts/ai_visibility.py (AI share of voice).

No network and no real cache: every store lives under tmp_path, and the
Anthropic SDK is replaced by a fake module/client, so the suite runs with
the ``anthropic`` package absent.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import ai_visibility as av  # noqa: E402
import seo_project  # noqa: E402
from seo_metrics import holm_adjust, wilson_interval  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _profile(prompts=()):
    profile = seo_project.new_profile("acme.com", name="Acmé Analytics", brand_terms=["acme"],
                                      competitors=["rivalco.com", "otherly.io"])
    profile["competitors"][0]["aliases"] = ["Rival Co"]
    for text, group in prompts:
        seo_project.add_prompt(profile, text, group=group)
    return profile


@pytest.fixture()
def data_dir(tmp_path):
    profile = _profile([
        ("best analytics tool for startups", "treatment"),
        ("how to measure product engagement", "treatment"),
        ("acme pricing", "treatment"),          # branded: names the client
        ("mixpanel alternatives", "control"),
    ])
    seo_project.save_profile(profile, str(tmp_path))
    return str(tmp_path)


class FakeAPIError(Exception):
    pass


class FakeAPIStatusError(FakeAPIError):
    def __init__(self, message="", status_code=500):
        super().__init__(message)
        self.status_code = status_code


class FakeAuthenticationError(FakeAPIStatusError):
    pass


class FakePermissionDeniedError(FakeAPIStatusError):
    pass


class FakeNotFoundError(FakeAPIStatusError):
    pass


class FakeRateLimitError(FakeAPIStatusError):
    pass


class FakeAPIConnectionError(FakeAPIError):
    pass


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns queued responses."""

    def __init__(self, responses):
        self.queue = list(responses)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        item = self.queue.pop(0) if self.queue else _resp("Default answer without brands.")
        if isinstance(item, Exception):
            raise item
        return item


def _fake_sdk(client=None):
    return SimpleNamespace(
        APIStatusError=FakeAPIStatusError, AuthenticationError=FakeAuthenticationError,
        PermissionDeniedError=FakePermissionDeniedError, NotFoundError=FakeNotFoundError,
        RateLimitError=FakeRateLimitError, APIConnectionError=FakeAPIConnectionError,
        Anthropic=lambda: client)


def _resp(text, citations=(), stop="end_turn", searched=None, stop_details=None,
          model="claude-opus-5-5"):
    content = []
    if searched is not None:
        content.append({"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
                        "input": {"query": "q"}})
        content.append({"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
                        "content": searched})
    content.append({"type": "text", "text": text, "citations": [
        {"type": "web_search_result_location", "url": u, "title": "t", "cited_text": "c",
         "encrypted_index": "xyz"} for u in citations] or None})
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop, "stop_details": stop_details}


# ---------------------------------------------------------------------------
# Brand matching and source classification
# ---------------------------------------------------------------------------

def test_fold_and_word_boundary_matching():
    folded = av.fold("Try ACMÉ, or Acmes Inc., or acme-based tools.")
    assert av.first_mention(folded, ["acme"]) == folded.index("acme")
    assert av.first_mention(av.fold("Acmes only"), ["acme"]) is None   # no partial-word match
    assert av.first_mention(av.fold("Visit acme.com today"), ["acme.com"]) is not None
    assert av.first_mention(av.fold("Résumé tips"), ["resume"]) == 0


def test_entities_and_branded_prompts():
    profile = _profile()
    entities = av.build_entities(profile)
    assert entities[0]["key"] == "brand"
    assert "acme" in entities[0]["terms"] and "acme.com" in entities[0]["terms"]
    assert entities[1]["domain"] == "rivalco.com" and "Rival Co" in entities[1]["terms"]
    assert av.is_branded("Is Acme any good?", profile)
    assert av.is_branded("acmé pricing", profile)
    assert not av.is_branded("best analytics tool", profile)
    assert not av.is_branded("rivalco vs otherly", profile)


def test_short_terms_are_warned():
    profile = _profile()
    profile["brand_terms"] = ["ac"]
    assert any("shorter than 3" in w for w in av.term_warnings(av.build_entities(profile)))


@pytest.mark.parametrize("url,expected", [
    ("https://acme.com/pricing", "own"),
    ("https://blog.acme.com/post", "own"),
    ("https://www.rivalco.com/", "competitor"),
    ("https://www.reddit.com/r/analytics", "social"),
    ("https://en.wikipedia.org/wiki/Analytics", "reference"),
    ("https://www.nist.gov/x", "reference"),
    ("https://www.ox.ac.uk/research", "reference"),
    ("https://notacme.com/", "other"),
    ("not a url", "other"),
])
def test_classify_source(url, expected):
    assert av.classify_source(url, "acme.com", ["rivalco.com", "otherly.io"]) == expected


# ---------------------------------------------------------------------------
# Answer extraction and the Anthropic engine (mocked)
# ---------------------------------------------------------------------------

def test_extract_answer_handles_citations_results_and_search_errors():
    content = [
        {"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": "https://a.example/1", "title": "A", "page_age": None},
            {"type": "web_search_result", "url": "https://a.example/1", "title": "dup"}]},
        {"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error",
                                                       "error_code": "max_uses_exceeded"}},
        {"type": "text", "text": "Acme is ", "citations": None},
        {"type": "text", "text": "popular.", "citations": [
            {"type": "web_search_result_location", "url": "https://acme.com/", "title": "Acme",
             "cited_text": "Acme is popular"},
            {"type": "web_search_result_location", "url": "https://acme.com/", "title": "Acme",
             "cited_text": "Acme is popular"}]},
        {"type": "thinking", "thinking": "", "signature": "sig"},
    ]
    out = av.extract_answer(content)
    assert out["answer"] == "Acme is popular."
    assert [c["url"] for c in out["cited_urls"]] == ["https://acme.com/"]
    assert [s["url"] for s in out["searched_urls"]] == ["https://a.example/1"]
    assert out["search_errors"] == ["max_uses_exceeded"]


def test_engine_request_shape_and_ok_answer():
    client = FakeClient([_resp("Acme and RivalCo both work.", ["https://acme.com/a"],
                               searched=[{"type": "web_search_result", "url": "https://acme.com/a",
                                          "title": "t", "encrypted_content": "BLOB"}])])
    engine = av.AnthropicEngine(client=client, sdk=_fake_sdk(client))
    result = engine.ask("best analytics tool", "claude-opus-5-5", av.Budget(1))
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["max_tokens"] == 16000
    assert call["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    assert call["output_config"] == {"effort": "medium"}
    assert call["messages"] == [{"role": "user", "content": "best analytics tool"}]
    for forbidden in ("system", "thinking", "fallbacks", "betas"):
        assert forbidden not in call
    assert result["status"] == "ok" and result["error"] is None
    assert result["answer"] == "Acme and RivalCo both work."
    assert result["cited_urls"][0]["url"] == "https://acme.com/a"
    assert "BLOB" not in json.dumps(result["raw"]) and "xyz" not in json.dumps(result["raw"])


def test_engine_optional_user_location():
    client = FakeClient([_resp("x")])
    av.AnthropicEngine(client=client, sdk=_fake_sdk(client)).ask("q", "m", av.Budget(1), country="GB")
    assert client.calls[0]["tools"][0]["user_location"] == {"type": "approximate", "country": "GB"}


def test_engine_resumes_pause_turn_without_extra_user_message():
    first = _resp("Part one. ", stop="pause_turn")
    client = FakeClient([first, _resp("Part two mentions Acme.")])
    budget = av.Budget(5)
    budget.take()  # the caller's first request
    result = av.AnthropicEngine(client=client, sdk=_fake_sdk(client)).ask("q", "m", budget)
    assert len(client.calls) == 2 and budget.used == 2
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant"]
    assert second[0] == {"role": "user", "content": "q"}
    assert second[1]["content"] == first["content"]
    assert result["status"] == "ok"
    assert result["answer"] == "Part one. Part two mentions Acme."
    assert len(result["raw"]["responses"]) == 2


def test_engine_caps_continuations_and_marks_incomplete():
    client = FakeClient([_resp("p", stop="pause_turn") for _ in range(10)])
    budget = av.Budget(100)
    budget.take()
    result = av.AnthropicEngine(client=client, sdk=_fake_sdk(client)).ask("q", "m", budget)
    assert len(client.calls) == 1 + av.MAX_CONTINUATIONS
    assert result["status"] == "error" and "incomplete" in result["error"]


def test_engine_continuation_respects_budget():
    client = FakeClient([_resp("p", stop="pause_turn"), _resp("never sent")])
    budget = av.Budget(1)
    budget.take()
    result = av.AnthropicEngine(client=client, sdk=_fake_sdk(client)).ask("q", "m", budget)
    assert len(client.calls) == 1 and result["status"] == "error"


def test_engine_records_refusal_with_category():
    client = FakeClient([_resp("", stop="refusal", stop_details={"type": "refusal", "category": "cyber"})])
    result = av.AnthropicEngine(client=client, sdk=_fake_sdk(client)).ask("q", "m", av.Budget(1))
    assert result["status"] == "refused" and result["error"] == "refusal: cyber"


def test_engine_max_tokens_is_ok_with_warning():
    client = FakeClient([_resp("long", stop="max_tokens")])
    result = av.AnthropicEngine(client=client, sdk=_fake_sdk(client)).ask("q", "m", av.Budget(1))
    assert result["status"] == "ok" and "max_tokens" in result["error"]


@pytest.mark.parametrize("exc,fatal", [
    (FakeRateLimitError("slow down", 429), False),
    (FakeAPIStatusError("boom", 529), False),
    (FakeAPIConnectionError("net"), False),
    (FakeAuthenticationError("bad key", 401), True),
    (FakePermissionDeniedError("nope", 403), True),
    (FakeNotFoundError("no model", 404), True),
])
def test_engine_error_handling(exc, fatal):
    client = FakeClient([exc])
    engine = av.AnthropicEngine(client=client, sdk=_fake_sdk(client))
    if fatal:
        with pytest.raises(av.EngineFatalError):
            engine.ask("q", "m", av.Budget(1))
    else:
        result = engine.ask("q", "m", av.Budget(1))
        assert result["status"] == "error" and result["error"]


def test_client_construction_failure_is_fatal_with_guidance():
    def boom():
        raise RuntimeError("no credentials")
    sdk = _fake_sdk()
    sdk.Anthropic = boom
    with pytest.raises(av.EngineFatalError, match="ant auth login"):
        av.AnthropicEngine(sdk=sdk)


def test_missing_sdk_gives_install_message(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)  # import raises ImportError
    with pytest.raises(av.EngineFatalError, match="pip install anthropic"):
        av._import_anthropic()


# ---------------------------------------------------------------------------
# run command: spend guards and storage
# ---------------------------------------------------------------------------

def _install_fake_engine(monkeypatch, client):
    made = []

    def factory(**_kw):   # accepts search_tool like the real engine
        made.append(1)
        return av.AnthropicEngine(client=client, sdk=_fake_sdk(client))

    monkeypatch.setitem(av.ENGINES["anthropic"], "factory", factory)
    return made


def test_run_refuses_before_any_call_when_plan_exceeds_max_calls(monkeypatch, data_dir, capsys):
    client = FakeClient([])
    made = _install_fake_engine(monkeypatch, client)
    rc = av.main(["run", "--project", "acme.com", "--data-dir", data_dir, "--engine", "anthropic",
                  "--runs", "5", "--max-calls", "19"])
    assert rc == 2 and not made and not client.calls
    assert "needs 20 calls" in capsys.readouterr().err


def test_run_requires_max_calls(data_dir):
    with pytest.raises(SystemExit):
        av.main(["run", "--project", "acme.com", "--data-dir", data_dir, "--engine", "anthropic"])


def test_dry_run_makes_no_calls(monkeypatch, data_dir, capsys):
    client = FakeClient([])
    made = _install_fake_engine(monkeypatch, client)
    rc = av.main(["run", "--project", "acme.com", "--data-dir", data_dir, "--engine", "anthropic",
                  "--runs", "5", "--max-calls", "1", "--dry-run", "--json"])
    assert rc == 0 and not made and not client.calls
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["planned_calls"] == 20


def test_run_stores_rows_interleaved(monkeypatch, data_dir):
    client = FakeClient([_resp(f"Answer {i} mentions Acme.", ["https://acme.com/"]) for i in range(8)])
    _install_fake_engine(monkeypatch, client)
    rc = av.main(["run", "--project", "acme.com", "--data-dir", data_dir, "--engine", "anthropic",
                  "--runs", "2", "--max-calls", "8"])
    assert rc == 0 and len(client.calls) == 8
    conn = av.open_store(data_dir)
    rows = av.load_runs(conn, "acme.com")
    conn.close()
    assert len(rows) == 8
    prompts = [r["prompt"] for r in rows]
    assert prompts[:4] == prompts[4:]   # run 1 over all prompts, then run 2
    branded = {r["prompt"]: r["branded"] for r in rows}
    assert branded["acme pricing"] is True and branded["mixpanel alternatives"] is False
    assert {r["prompt_group"] for r in rows} == {"treatment", "control"}
    assert all(r["surface"] == "api" and r["model"] == "claude-opus-5-5" for r in rows)
    assert rows[0]["cited_urls"][0]["url"] == "https://acme.com/"


def test_run_stops_on_fatal_error_and_on_repeated_errors(monkeypatch, data_dir):
    client = FakeClient([FakeAuthenticationError("bad", 401)])
    _install_fake_engine(monkeypatch, client)
    rc = av.main(["run", "--project", "acme.com", "--data-dir", data_dir, "--engine", "anthropic",
                  "--runs", "1", "--max-calls", "4"])
    assert rc == 1 and len(client.calls) == 1

    client = FakeClient([FakeAPIStatusError("x", 500)] * 10)
    _install_fake_engine(monkeypatch, client)
    rc = av.main(["run", "--project", "acme.com", "--data-dir", data_dir, "--engine", "anthropic",
                  "--runs", "5", "--max-calls", "20", "--json"])
    assert rc == 0 and len(client.calls) == av.MAX_CONSECUTIVE_ERRORS


def test_run_without_sdk_fails_cleanly(monkeypatch, data_dir, capsys):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    rc = av.main(["run", "--project", "acme.com", "--data-dir", data_dir, "--engine", "anthropic",
                  "--runs", "1", "--max-calls", "4"])
    assert rc == 2 and "pip install anthropic" in capsys.readouterr().err


def test_plan_requires_profile_and_rejects_non_native_engine(tmp_path, data_dir):
    with pytest.raises(SystemExit):
        av.main(["plan", "--project", "nobody.com", "--data-dir", str(tmp_path / "empty")])
    assert av.main(["plan", "--project", "acme.com", "--data-dir", data_dir, "--engine", "chatgpt"]) == 2


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) if not isinstance(r, str) else r for r in rows) + "\n")
    return str(path)


def test_ingest_validates_dedupes_and_marks_branding(tmp_path, data_dir):
    f = _write_jsonl(tmp_path / "chatgpt.jsonl", [
        {"prompt": "best analytics tool for startups", "answer": "Acme leads.",
         "sources": [{"url": "https://acme.com/x"}, "https://reddit.com/r/a", "ftp://bad"],
         "run_at": "2026-10-02T10:00:00+02:00"},
        {"prompt": "Is Acmé worth it?", "answer": "Yes.", "citations": [], "run_at": "2026-10-02"},
        {"prompt": "", "answer": "no prompt"},
        "not json",
    ])
    rc = av.main(["ingest", "--project", "acme.com", "--data-dir", data_dir, f,
                  "--engine", "chatgpt", "--json"])
    assert rc == 0
    conn = av.open_store(data_dir)
    rows = av.load_runs(conn, "acme.com")
    conn.close()
    assert len(rows) == 2
    first = [r for r in rows if r["prompt"].startswith("best")][0]
    assert first["surface"] == "ui" and first["engine"] == "chatgpt"
    assert first["run_at"] == "2026-10-02T08:00:00Z"
    assert [c["url"] for c in first["cited_urls"]] == ["https://acme.com/x", "https://reddit.com/r/a"]
    assert first["prompt_group"] == "treatment"          # taken from the profile panel
    assert [r for r in rows if r["prompt"].startswith("Is")][0]["branded"] is True
    # re-ingesting the same file adds nothing
    av.main(["ingest", "--project", "acme.com", "--data-dir", data_dir, f, "--engine", "chatgpt"])
    conn = av.open_store(data_dir)
    assert len(av.load_runs(conn, "acme.com")) == 2
    conn.close()
    # --strict rejects the whole file
    assert av.main(["ingest", "--project", "acme.com", "--data-dir", data_dir, f,
                    "--engine", "perplexity", "--strict", "--json"]) == 2


def test_ingest_keeps_identical_answers_from_different_runs(tmp_path, data_dir):
    rows = [{"prompt": "mixpanel alternatives", "answer": "Acme.", "run_at": f"2026-10-0{i}T00:00:00Z"}
            for i in range(1, 6)]
    f = _write_jsonl(tmp_path / "runs.jsonl", rows + [{"prompt": "mixpanel alternatives", "answer": "Acme."}])
    av.main(["ingest", "--project", "acme.com", "--data-dir", data_dir, f, "--engine", "copilot"])
    av.main(["ingest", "--project", "acme.com", "--data-dir", data_dir, f, "--engine", "copilot"])
    conn = av.open_store(data_dir)
    rows = av.load_runs(conn, "acme.com", engine="copilot")
    conn.close()
    # 5 dated runs kept once each; the undated row is stored on each ingest (cannot be recognised)
    assert len(rows) == 7


def test_ingest_refuses_grounded_gemini_api_answers(tmp_path, data_dir):
    f = _write_jsonl(tmp_path / "g.jsonl", [{"prompt": "p", "answer": "a"}])
    assert av.main(["ingest", "--project", "acme.com", "--data-dir", data_dir, f,
                    "--engine", "gemini", "--surface", "api"]) == 2
    assert av.main(["ingest", "--project", "acme.com", "--data-dir", data_dir, f,
                    "--engine", "gemini", "--surface", "api", "--not-grounded"]) == 0


def test_parse_ingest_row_errors():
    with pytest.raises(ValueError):
        av.parse_ingest_row({"prompt": "p", "answer": "a", "run_at": "yesterday"})
    with pytest.raises(ValueError):
        av.parse_ingest_row({"prompt": "p", "answer": "a", "status": "maybe"})
    with pytest.raises(ValueError):
        av.parse_ingest_row({"prompt": "p", "answer": "a", "citations": "https://x.com"})
    assert av.parse_ingest_row({"prompt": "p", "status": "refused"})["answer"] == ""


# ---------------------------------------------------------------------------
# report: metrics are exact and the headline excludes branded prompts
# ---------------------------------------------------------------------------

def _row(prompt, answer, *, engine="anthropic", surface="api", branded=False, group="treatment",
         funnel="MOFU", cited=(), status="ok", run_at="2026-10-05T00:00:00Z", rid=[0]):
    rid[0] += 1
    return {"id": rid[0], "project": "acme.com", "batch_id": "b", "run_at": run_at, "prompt": prompt,
            "prompt_group": group, "branded": branded, "funnel": funnel, "engine": engine,
            "surface": surface, "model": "m", "locale": "en-US", "status": status, "error": None,
            "answer": answer, "cited_urls": [{"url": u} for u in cited], "searched_urls": []}


def _report_rows():
    rows = []
    # 10 unbranded answers: brand mentioned in 4; RivalCo in 6; Otherly in 2.
    for i in range(10):
        parts = []
        if i < 6:
            parts.append("RivalCo is solid.")
        if i < 4:
            parts.append("Acme is great.")
        if i in (8, 9):
            parts.append("Otherly works.")
        cited = ["https://acme.com/a", "https://www.reddit.com/r/x"] if i < 2 else ["https://rivalco.com/"]
        rows.append(_row(f"prompt {i % 5}", " ".join(parts) or "Nothing relevant.", cited=cited,
                         group="treatment" if i % 5 < 3 else "control", funnel="TOFU" if i % 2 else "BOFU"))
    # branded answers always mention the brand; must not move the headline
    rows += [_row("acme pricing", "Acme costs $10.", branded=True) for _ in range(5)]
    rows.append(_row("prompt 0", "", status="refused"))
    rows.append(_row("prompt 1", "", status="error"))
    # a UI capture: separate engine/surface row, never averaged with the API
    rows += [_row("prompt 0", "Acme.", engine="chatgpt", surface="ui") for _ in range(3)]
    return rows


def test_report_metrics_are_exact():
    rep = av.build_report(_report_rows(), _profile())
    api = next(e for e in rep["engines"] if e["engine"] == "anthropic")
    u = api["unbranded"]
    assert u["n"] == 10 and u["mentions"] == 4 and u["mention_rate"] == 0.4
    assert (u["ci_low"], u["ci_high"]) == wilson_interval(4, 10)
    assert u["thin"] is True
    assert u["sov"] == round(4 / (4 + 6 + 2), 4)
    assert u["citation_rate"] == 0.2 and u["answers_citing_own"] == 2
    assert u["citation_share"] == round(2 / (2 * 2 + 8), 4)
    # Acme appears after RivalCo in every answer that mentions both
    assert u["avg_first_position"] == 2.0
    assert api["branded"]["n"] == 5 and api["branded"]["mention_rate"] == 1.0
    assert api["counts"] == {"total": 17, "ok": 15, "refused": 1, "error": 1}
    assert set(api["by_group"]) == {"treatment", "control"}
    assert set(api["by_funnel"]) == {"TOFU", "BOFU"}
    comp = {c["name"]: c for c in api["competitors"]}
    assert comp["rivalco"]["mentions"] == 6 and comp["rivalco"]["avg_first_position"] == 1.0
    assert api["citations"]["by_class"] == {"own": 2, "competitor": 8, "social": 2, "reference": 0, "other": 0}
    assert api["citations"]["top_domains"][0] == {"domain": "rivalco.com", "class": "competitor", "answers": 8}


def test_headline_is_unbranded_and_never_mixes_surfaces():
    rep = av.build_report(_report_rows(), _profile())
    h = rep["headline"]
    assert (h["engine"], h["surface"], h["n"]) == ("anthropic", "api", 10)
    assert "unbranded" in h["basis"]
    ui = next(e for e in rep["engines"] if e["engine"] == "chatgpt")
    assert ui["surface"] == "ui" and ui["unbranded"]["n"] == 3
    assert ui["unbranded"]["citation_rate"] is None          # no citations captured
    assert av.build_report(_report_rows(), _profile(), engine="chatgpt")["headline"]["engine"] == "chatgpt"


def test_report_cli_emits_kpi_envelope(tmp_path, data_dir):
    conn = av.open_store(data_dir)
    for row in _report_rows():
        av.insert_run(conn, row)
    conn.commit()
    conn.close()
    out = tmp_path / "kpis" / "ai.json"
    rc = av.main(["report", "--project", "acme.com", "--data-dir", data_dir, "--emit-kpis", str(out), "--json"])
    assert rc == 0
    env = json.loads(out.read_text())
    assert env["kpi_envelope"] == 1 and env["project"] == "acme.com" and env["source"] == "ai_visibility.py"
    assert env["date"] == "2026-10-05"
    assert env["metrics"] == {"ai.mention_rate": 0.4, "ai.mention_rate_ci_low": wilson_interval(4, 10)[0],
                              "ai.mention_rate_ci_high": wilson_interval(4, 10)[1],
                              "ai.citation_rate": 0.2, "ai.sov": round(4 / 12, 4),
                              "ai.retrieval_rate": None, "ai.n": 10}
    assert env["meta"]["thin"] is True and env["meta"]["surface"] == "api"
    tracker = pytest.importorskip("performance_tracker")
    validate = getattr(tracker, "validate_envelope", None)
    if validate is None:
        pytest.skip("performance_tracker.validate_envelope not available")
    result = validate(env)
    assert result["ok"], result["errors"]
    assert not result["warnings"], result["warnings"]


# ---------------------------------------------------------------------------
# compare: paired sign test, Holm, verdicts
# ---------------------------------------------------------------------------

def _window_rows(prompt_rates, day, group):
    """prompt -> number of 5 runs mentioning Acme."""
    rows = []
    for prompt, k in prompt_rates.items():
        for i in range(5):
            rows.append(_row(prompt, "Acme helps." if i < k else "Other tools help.", group=group,
                             run_at=f"{day}T00:00:00Z"))
    return rows


def _experiment(t_a, t_b, c_a, c_b):
    a = _window_rows({f"t{i}": v for i, v in enumerate(t_a)}, "2026-09-10", "treatment") + \
        _window_rows({f"c{i}": v for i, v in enumerate(c_a)}, "2026-09-10", "control")
    b = _window_rows({f"t{i}": v for i, v in enumerate(t_b)}, "2026-10-10", "treatment") + \
        _window_rows({f"c{i}": v for i, v in enumerate(c_b)}, "2026-10-10", "control")
    return av.compare_windows(a, b, _profile())


def test_compare_promotes_treatment_gain_over_flat_control():
    res = _experiment([0] * 8, [3] * 8, [2] * 8, [2] * 8)
    e = res["engines"][0]
    t, c = e["groups"]["treatment"], e["groups"]["control"]
    assert (t["n_up"], t["n_down"], t["n_tie"]) == (8, 0, 0)
    assert (t["p_adj"], c["p_adj"]) == tuple(holm_adjust([t["p"], c["p"]]))
    assert e["verdict"] == "Promote" and e["diff_in_change_pp"] == 60.0
    assert res["holm_family_size"] == 2


def test_compare_rollback_and_drift_and_keep_testing():
    assert _experiment([4] * 8, [1] * 8, [2] * 8, [2] * 8)["engines"][0]["verdict"] == "Rollback"
    drift = _experiment([0] * 8, [3] * 8, [0] * 8, [4] * 8)["engines"][0]
    assert drift["verdict"] == "Unproven" and "control" in drift["reason"]
    mixed = _experiment([1, 2, 1, 2, 1, 2, 1, 2], [2, 1, 2, 1, 2, 1, 2, 2], [2] * 8, [2] * 8)
    assert mixed["engines"][0]["verdict"] == "Keep-testing"


def test_compare_unproven_without_control_or_with_too_few_pairs():
    a = _window_rows({f"t{i}": 0 for i in range(8)}, "2026-09-10", "treatment")
    b = _window_rows({f"t{i}": 5 for i in range(8)}, "2026-10-10", "treatment")
    e = av.compare_windows(a, b, _profile())["engines"][0]
    assert e["verdict"] == "Unproven" and "control" in e["reason"]
    small = _experiment([0] * 3, [5] * 3, [2] * 3, [2] * 3)["engines"][0]
    assert small["verdict"] == "Unproven" and "fewer than" in small["reason"]


def test_compare_only_pairs_shared_prompts_and_skips_branded():
    a = _window_rows({"shared": 1, "only_a": 2}, "2026-09-10", "treatment")
    b = _window_rows({"shared": 3, "only_b": 2}, "2026-10-10", "treatment")
    b += [_row("acme pricing", "Acme", branded=True, run_at="2026-10-10T00:00:00Z")]
    e = av.compare_windows(a, b, _profile())["engines"][0]
    assert e["shared_prompts"] == 1 and e["only_in_a"] == 1 and e["only_in_b"] == 1
    assert e["groups"]["treatment"]["pairs"][0]["prompt"] == "shared"


def test_compare_cli_rejects_overlapping_windows(data_dir):
    assert av.main(["compare", "--project", "acme.com", "--data-dir", data_dir,
                    "--a-since", "2026-09-01", "--a-until", "2026-10-05",
                    "--b-since", "2026-10-01", "--b-until", "2026-10-31"]) == 2
