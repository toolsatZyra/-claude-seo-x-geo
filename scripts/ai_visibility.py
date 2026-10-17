#!/usr/bin/env python3
"""
AI share of voice: does a prompt panel's AI answers mention and cite the client?

This is the AEO OUTCOME metric. It is measured, not inferred from readiness
signals, and it is never blended into the AEO Readiness Score (aeo_score.py)
or the SEO Health Score.

Method (after the public geo-score / Elmo / Limelit trackers and the
SparkToro-Gumshoe consistency study):
  * Raw answers are stored, so every metric can be recomputed later.
  * Each prompt runs k times per engine (k >= 5 recommended): answers are
    non-deterministic, and mention frequency is steadier than list position.
  * mention rate  = answers mentioning the brand / valid answers (Wilson 95% CI)
  * share of voice = answers mentioning the brand / sum over tracked brands of
                     answers mentioning that brand (presence-based, per answer)
  * citation rate = answers citing an owned URL / valid answers
  * citation share = owned cited URLs / all cited URLs
  * average first-mention position among tracked brands (low weight)
  * n < 20 is flagged "thin"; branded prompts (that name the client) are
    excluded from the headline figure; API answers and consumer-UI answers
    are never averaged together (separate engine/surface rows).
  * Period-to-period change only through ``compare``: a paired sign test over
    prompts present in both windows, Holm-adjusted across engines x groups,
    with treatment-vs-control difference-in-change and a verdict
    (Promote / Keep-testing / Rollback / Unproven).

Engines. ``anthropic`` is the only native engine: the Messages API with the
server-side web search tool, through the official ``anthropic`` SDK (imported
lazily; install it into ~/.claude/skills/seo/.venv). Consumer surfaces
(ChatGPT app, AI Overviews / AI Mode, Copilot, Perplexity) come in through
``ingest`` from licensed providers (DataForSEO ``ai_optimization_chat_gpt_scraper``
/ ``ai_opt_llm_ment_search`` via the seo-dataforseo extension) or manual
capture. Gemini API answers grounded with Google Search are excluded: those
terms forbid caching and analysing grounded results.

Spend safety: ``run`` requires ``--max-calls`` (API requests, including
pause_turn continuations), refuses before the first call if the plan needs
more, supports ``--dry-run``, and stops after 3 consecutive errors. Token
cost depends on answer length and web-search usage, so no dollar figure is
printed.

Storage: SQLite store ``ai-visibility`` under the claude-seo data root
(seo_store.py; --data-dir or $CLAUDE_SEO_DATA_DIR). Encrypted/opaque blobs
(encrypted_content, encrypted_index, signature) are stripped from stored raw
responses; nothing needed to recompute metrics is dropped.

Usage:
    python ai_visibility.py plan --project example.com [--engine anthropic] [--runs 5] [--group treatment]
    python ai_visibility.py run --project example.com --engine anthropic --runs 5 --max-calls 150 [--dry-run]
    python ai_visibility.py ingest --project example.com chatgpt.jsonl --engine chatgpt --surface ui
    python ai_visibility.py report --project example.com [--since 2026-10-01] [--until 2026-10-31] \
        [--engine anthropic] [--emit-kpis kpis-ai.json] [--json]
    python ai_visibility.py compare --project example.com --a-since 2026-09-01 --a-until 2026-09-30 \
        --b-since 2026-10-01 --b-until 2026-10-31 [--engine anthropic] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata
import uuid
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from seo_kpi import EnvelopeError, write_envelope  # noqa: E402
from seo_metrics import classify_intent, holm_adjust, sign_test_p, wilson_interval  # noqa: E402
from seo_project import all_brand_terms, competitor_terms, load_profile, registrable_label  # noqa: E402
from seo_store import connect, host_matches, normalize_domain, today, utc_now  # noqa: E402

SOURCE = "ai_visibility.py"
STORE = "ai-visibility"
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY,
    project       TEXT NOT NULL,
    batch_id      TEXT NOT NULL,
    run_at        TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    prompt_group  TEXT,
    branded       INTEGER NOT NULL DEFAULT 0,
    funnel        TEXT,
    engine        TEXT NOT NULL,
    surface       TEXT NOT NULL CHECK (surface IN ('api', 'ui')),
    model         TEXT,
    locale        TEXT,
    status        TEXT NOT NULL CHECK (status IN ('ok', 'refused', 'error')),
    error         TEXT,
    answer        TEXT,
    cited_urls    TEXT NOT NULL DEFAULT '[]',
    searched_urls TEXT NOT NULL DEFAULT '[]',
    raw           TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_project_engine ON runs (project, engine, surface, run_at);
"""

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
WEB_SEARCH_MAX_USES = 5
MAX_CONTINUATIONS = 3          # pause_turn continuations per prompt run
MAX_CONSECUTIVE_ERRORS = 3     # circuit breaker for a batch
RECOMMENDED_RUNS = 5           # k >= 5 runs per prompt per engine
THIN_N = 20                    # fewer valid answers than this -> "thin"
MIN_PAIRED_PROMPTS = 6         # smallest n for which a two-sided sign test can reach p < 0.05
ALPHA = 0.05
_ENGINE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,40}$")

SOCIAL_DOMAINS = (
    "reddit.com", "youtube.com", "youtu.be", "x.com", "twitter.com", "facebook.com",
    "instagram.com", "linkedin.com", "tiktok.com", "quora.com", "medium.com",
    "pinterest.com", "threads.net", "news.ycombinator.com", "stackoverflow.com",
    "stackexchange.com", "substack.com",
)
REFERENCE_DOMAINS = ("wikipedia.org", "wikidata.org", "wikimedia.org", "britannica.com")
_REFERENCE_SUFFIX_RE = re.compile(r"(\.(gov|edu|mil|int)$)|(\.(gov|edu|ac)\.[a-z]{2}$)")

DECISION_RULE = (
    "Unproven: no control group, fewer than {m} paired prompts in treatment or control, or "
    "treatment improved significantly but control improved as much or more (engine-wide drift). "
    "Promote: treatment n_up > n_down with Holm-adjusted sign-test p < {a}, difference-in-change "
    "(treatment minus control mean change) > 0, and control not significantly improved. "
    "Rollback: treatment n_down > n_up with adjusted p < {a} and difference-in-change < 0. "
    "Keep-testing: anything else (valid design, effect not yet significant)."
).format(m=MIN_PAIRED_PROMPTS, a=ALPHA)

LIMITATIONS = [
    "AI answers are non-deterministic; rates are estimates with the stated Wilson 95% intervals",
    "API answers differ from consumer apps (no personalization, memory, location or app-side "
    "retrieval); api and ui surfaces are reported separately and never averaged",
    "vendors change models and retrieval silently; compare only windows measured the same way",
    "a mention or citation is not a visit: pair with ai_referrals.py (GA4) for traffic",
    "brand matching is lexical (word boundaries, case- and accent-folded); ambiguous or very "
    "short brand terms over-match, and unlisted spellings under-match",
]


# ---------------------------------------------------------------------------
# Deterministic brand matching
# ---------------------------------------------------------------------------

_MARK_SIGNS = str.maketrans({"\u2122": " ", "\u2120": " ", "\u00ae": " ", "\u00a9": " "})


def fold(text: str) -> str:
    """Case- and diacritic-fold text: NFKD, drop combining marks, casefold.

    Trademark/registered/copyright signs become spaces first: NFKD would turn
    "Acme\u2122" into "AcmeTM", hiding a real mention from a word-boundary match.
    """
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(_MARK_SIGNS))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


@lru_cache(maxsize=4096)
def _term_regex(term: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(fold(term)) + r"(?!\w)")


def first_mention(folded_text: str, terms: Iterable[str]) -> Optional[int]:
    """Index of the earliest whole-word occurrence of any term, or None."""
    best: Optional[int] = None
    for term in terms:
        if not term or not term.strip():
            continue
        m = _term_regex(term.strip()).search(folded_text)
        if m and (best is None or m.start() < best):
            best = m.start()
    return best


def build_entities(profile: dict) -> list[dict]:
    """Tracked brands: the client first (key 'brand'), then each competitor."""
    domain = normalize_domain(profile.get("domain", ""))
    brand_terms = list(dict.fromkeys(
        [*all_brand_terms(profile), (profile.get("name") or "").strip(), domain]))
    entities = [{"key": "brand", "name": profile.get("name") or domain, "domain": domain,
                 "terms": [t for t in brand_terms if t]}]
    for comp in profile.get("competitors", []):
        cdom = normalize_domain(comp.get("domain", ""))
        terms = [comp.get("name", ""), registrable_label(cdom) if cdom else "", cdom, *comp.get("aliases", [])]
        entities.append({"key": f"competitor:{cdom}", "name": comp.get("name") or cdom, "domain": cdom,
                         "terms": [t for t in dict.fromkeys(t.strip() for t in terms) if t]})
    return entities


def term_warnings(entities: list[dict]) -> list[str]:
    out = []
    for e in entities:
        for t in e["terms"]:
            if len(fold(t)) < 3:
                out.append(f"term {t!r} for {e['name']} is shorter than 3 characters and will over-match")
    return out


def is_branded(prompt: str, profile: dict) -> bool:
    """True when the prompt names the client (those prompts leave the headline)."""
    return first_mention(fold(prompt), build_entities(profile)[0]["terms"]) is not None


# ---------------------------------------------------------------------------
# Cited-source classification
# ---------------------------------------------------------------------------

def url_host(url: str) -> str:
    return normalize_domain(url or "")


def classify_source(url: str, own_domain: str, competitor_domains: Iterable[str]) -> str:
    """own | competitor | social | reference | other."""
    host = url_host(url)
    if not host:
        return "other"
    if own_domain and host_matches(host, own_domain):
        return "own"
    if any(d and host_matches(host, d) for d in competitor_domains):
        return "competitor"
    if any(host_matches(host, d) for d in SOCIAL_DOMAINS):
        return "social"
    if any(host_matches(host, d) for d in REFERENCE_DOMAINS) or _REFERENCE_SUFFIX_RE.search(host):
        return "reference"
    return "other"


# ---------------------------------------------------------------------------
# Prompt panel
# ---------------------------------------------------------------------------

def _prompt_record(prompt: str, profile: dict, group: str = "", funnel: str = "") -> dict:
    prompt = " ".join((prompt or "").split())
    if not funnel:
        funnel = classify_intent(prompt, all_brand_terms(profile), competitor_terms(profile))["funnel"]
    return {"prompt": prompt, "group": group or "unassigned", "funnel": funnel.upper(),
            "branded": is_branded(prompt, profile)}


def load_prompts_file(path: str) -> list[dict]:
    """Text (one prompt per line, '#' comments), JSON list, or JSONL objects."""
    text = Path(path).read_text(encoding="utf-8")
    items: list[dict] = []
    if path.endswith(".jsonl"):
        for line in text.splitlines():
            if line.strip():
                obj = json.loads(line)
                items.append(obj if isinstance(obj, dict) else {"prompt": str(obj)})
    elif path.endswith(".json"):
        data = json.loads(text)
        for obj in data if isinstance(data, list) else []:
            items.append(obj if isinstance(obj, dict) else {"prompt": str(obj)})
    else:
        items = [{"prompt": line.strip()} for line in text.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
    return items


def load_panel(profile: dict, prompts_file: Optional[str] = None, group: Optional[str] = None) -> list[dict]:
    """The prompt panel: profile ai_visibility.prompts or a prompts file."""
    raw = load_prompts_file(prompts_file) if prompts_file else \
        (profile.get("ai_visibility") or {}).get("prompts", [])
    panel, seen = [], set()
    for item in raw:
        rec = _prompt_record(item.get("prompt", ""), profile, item.get("group", ""), item.get("funnel", ""))
        if not rec["prompt"] or rec["prompt"].lower() in seen:
            continue
        if group and rec["group"] != group:
            continue
        seen.add(rec["prompt"].lower())
        panel.append(rec)
    return panel


# ---------------------------------------------------------------------------
# Anthropic engine (native)
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute or key access, so SDK objects and plain dicts both work."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


_OPAQUE_KEYS = frozenset({"encrypted_content", "encrypted_index", "signature"})


def _strip_opaque(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_opaque(v) for k, v in obj.items() if k not in _OPAQUE_KEYS}
    if isinstance(obj, list):
        return [_strip_opaque(v) for v in obj]
    return obj


def _to_raw(response: Any) -> Any:
    if isinstance(response, dict):
        data = response
    elif hasattr(response, "to_dict"):
        data = response.to_dict()
    else:
        data = {"repr": repr(response)}
    return _strip_opaque(data)


def extract_answer(content: Iterable[Any]) -> dict:
    """Answer text, cited URLs and searched URLs from Messages API content blocks.

    * answer text = concatenated ``text`` blocks
    * cited URLs  = ``citations`` of type ``web_search_result_location`` on text blocks
    * searched    = ``web_search_tool_result`` blocks whose content is a LIST of
                    ``web_search_result`` items; an object there is an error
                    (e.g. ``error_code``), recorded rather than raised
    """
    texts: list[str] = []
    cited: list[dict] = []
    searched: list[dict] = []
    search_errors: list[str] = []
    seen_cited: set = set()
    seen_searched: set = set()
    for block in content or []:
        btype = _get(block, "type")
        if btype == "text":
            texts.append(_get(block, "text") or "")
            for cit in _get(block, "citations") or []:
                if _get(cit, "type") != "web_search_result_location":
                    continue
                url = _get(cit, "url")
                key = (url, _get(cit, "cited_text"))
                if url and key not in seen_cited:
                    seen_cited.add(key)
                    cited.append({"url": url, "title": _get(cit, "title"),
                                  "cited_text": _get(cit, "cited_text")})
        elif btype == "web_search_tool_result":
            payload = _get(block, "content")
            if isinstance(payload, (list, tuple)):
                for item in payload:
                    url = _get(item, "url")
                    if _get(item, "type") == "web_search_result" and url and url not in seen_searched:
                        seen_searched.add(url)
                        searched.append({"url": url, "title": _get(item, "title"),
                                         "page_age": _get(item, "page_age")})
            elif payload is not None:
                search_errors.append(str(_get(payload, "error_code") or _get(payload, "type") or "unknown"))
    return {"answer": "".join(texts), "cited_urls": cited, "searched_urls": searched,
            "search_errors": search_errors}


class Budget:
    """API-request budget for one batch (--max-calls)."""

    def __init__(self, max_calls: int):
        self.max_calls = max_calls
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.max_calls:
            return False
        self.used += 1
        return True


class EngineFatalError(RuntimeError):
    """An error that would repeat for every call (credentials, unknown model)."""


def _import_anthropic():
    try:
        import anthropic  # noqa: PLC0415  (optional dependency, imported lazily)
    except ImportError as exc:
        raise EngineFatalError(
            "the 'anthropic' SDK is not installed. Install it into the plugin venv: "
            "~/.claude/skills/seo/.venv/bin/pip install anthropic") from exc
    return anthropic


class AnthropicEngine:
    """Messages API + server-side web search, as close to a consumer ask as the API allows.

    No system prompt (consumer-like behaviour) and no assistant prefill. Thinking
    is left at the model default (adaptive on this model) and depth is set with
    effort. The server-side ``fallbacks`` parameter is deliberately NOT enabled:
    a fallback model answering a refused prompt would put a different model's
    answer under this model's name and contaminate per-model measurement. A
    refusal is stored as a refusal instead.
    """

    name = "anthropic"
    surface = "api"
    default_model = DEFAULT_MODEL

    def __init__(self, client: Any = None, sdk: Any = None):
        self.sdk = sdk or _import_anthropic()
        # Credentials resolve from ANTHROPIC_API_KEY or an `ant auth login`
        # profile; a key is never accepted on the command line.
        try:
            # max_retries=0: the --max-calls budget counts every HTTP request;
            # SDK auto-retries would otherwise send up to 3 per counted call.
            self.client = client or self.sdk.Anthropic(max_retries=0)
        except Exception as exc:  # the SDK raises its own error type when no credentials resolve
            raise EngineFatalError(
                f"could not create the Anthropic client ({exc.__class__.__name__}). Set "
                "ANTHROPIC_API_KEY or run `ant auth login`; never pass a key on the command line.") from exc

    def request_kwargs(self, model: str, messages: list, country: Optional[str] = None) -> dict:
        tool: dict = {"type": "web_search_20260209", "name": "web_search", "max_uses": WEB_SEARCH_MAX_USES}
        if country:
            tool["user_location"] = {"type": "approximate", "country": country}
        return {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "tools": [tool],
            "output_config": {"effort": "medium"},
            "messages": messages,
        }

    def ask(self, prompt: str, model: str, budget: Budget, country: Optional[str] = None) -> dict:
        """One prompt run (plus pause_turn continuations). Never raises except EngineFatalError.

        The caller has already taken one unit of ``budget`` for the first request.
        """
        sdk = self.sdk
        messages: list = [{"role": "user", "content": prompt}]
        assistant_content: list = []
        raws: list = []
        continuations = 0
        stop_reason = None
        stop_details = None
        try:
            while True:
                response = self.client.messages.create(**self.request_kwargs(model, messages, country))
                raws.append(_to_raw(response))
                assistant_content.extend(list(_get(response, "content") or []))
                stop_reason = _get(response, "stop_reason")
                stop_details = _get(response, "stop_details")
                served_model = _get(response, "model") or model
                if stop_reason != "pause_turn":
                    break
                if continuations >= MAX_CONTINUATIONS or not budget.take():
                    break
                continuations += 1
                # Resume the paused server-side turn: same user message plus the
                # assistant content so far, no extra user message.
                messages = [{"role": "user", "content": prompt},
                            {"role": "assistant", "content": list(assistant_content)}]
        except sdk.AuthenticationError as exc:
            raise EngineFatalError(f"authentication failed: {exc.__class__.__name__}") from exc
        except sdk.PermissionDeniedError as exc:
            raise EngineFatalError(f"permission denied: {exc.__class__.__name__}") from exc
        except sdk.NotFoundError as exc:
            raise EngineFatalError(f"model or endpoint not found ({model!r})") from exc
        except sdk.RateLimitError:
            return self._result("error", "rate limited (after SDK retries)", model, raws, assistant_content)
        except sdk.APIStatusError as exc:
            return self._result("error", f"API error HTTP {getattr(exc, 'status_code', '?')}",
                                model, raws, assistant_content)
        except sdk.APIConnectionError as exc:
            return self._result("error", f"connection error: {exc.__class__.__name__}",
                                model, raws, assistant_content)

        if stop_reason == "refusal":
            category = _get(stop_details, "category") if stop_details is not None else None
            return self._result("refused", f"refusal: {category or 'uncategorized'}",
                                served_model, raws, assistant_content)
        if stop_reason == "pause_turn":
            return self._result("error", f"incomplete: still paused after {continuations} continuation(s)",
                                served_model, raws, assistant_content)
        note = "warning: stop_reason=max_tokens (answer truncated)" if stop_reason == "max_tokens" else None
        return self._result("ok", note, served_model, raws, assistant_content)

    @staticmethod
    def _result(status: str, error: Optional[str], model: str, raws: list, content: list) -> dict:
        extracted = extract_answer(content)
        if extracted["search_errors"]:
            msg = "web_search error: " + ", ".join(extracted["search_errors"])
            error = f"{error}; {msg}" if error else msg
        return {"status": status, "error": error, "model": model,
                "answer": extracted["answer"], "cited_urls": extracted["cited_urls"],
                "searched_urls": extracted["searched_urls"], "raw": {"responses": raws}}


# Native engine registry. A new engine implements the AnthropicEngine
# interface (name, surface, default_model, ask(prompt, model, budget, country)).
ENGINES: dict[str, dict] = {
    "anthropic": {"factory": AnthropicEngine, "surface": "api", "default_model": DEFAULT_MODEL,
                  "description": "Claude Messages API + web_search_20260209 (official anthropic SDK)"},
}


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def open_store(data_dir: Optional[str] = None):
    return connect(STORE, SCHEMA, data_dir)


def insert_run(conn, row: dict) -> int:
    cur = conn.execute(
        "INSERT INTO runs (project, batch_id, run_at, prompt, prompt_group, branded, funnel, engine,"
        " surface, model, locale, status, error, answer, cited_urls, searched_urls, raw)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["project"], row["batch_id"], row["run_at"], row["prompt"], row.get("prompt_group"),
         1 if row.get("branded") else 0, row.get("funnel"), row["engine"], row["surface"],
         row.get("model"), row.get("locale"), row["status"], row.get("error"), row.get("answer"),
         json.dumps(row.get("cited_urls") or []), json.dumps(row.get("searched_urls") or []),
         json.dumps(row.get("raw")) if row.get("raw") is not None else None))
    return cur.lastrowid


def load_runs(conn, project: str, since: Optional[str] = None, until: Optional[str] = None,
              engine: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM runs WHERE project = ?"
    params: list = [project]
    if since:
        sql += " AND substr(run_at, 1, 10) >= ?"
        params.append(since)
    if until:
        sql += " AND substr(run_at, 1, 10) <= ?"
        params.append(until)
    if engine:
        sql += " AND engine = ?"
        params.append(engine)
    sql += " ORDER BY run_at, id"
    rows = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["cited_urls"] = json.loads(d.get("cited_urls") or "[]")
        d["searched_urls"] = json.loads(d.get("searched_urls") or "[]")
        d["branded"] = bool(d["branded"])
        rows.append(d)
    return rows


# ---------------------------------------------------------------------------
# Metrics (pure)
# ---------------------------------------------------------------------------

def analyze_answer(answer: str, cited_urls: list, entities: list[dict]) -> dict:
    """Per-answer facts: which tracked brands appear, where, and what is cited."""
    folded = fold(answer or "")
    positions = {}
    for e in entities:
        idx = first_mention(folded, e["terms"])
        if idx is not None:
            positions[e["key"]] = idx
    order = sorted(positions, key=lambda k: positions[k])
    brand_rank = order.index("brand") + 1 if "brand" in positions else None

    own = entities[0]["domain"]
    comp_domains = [e["domain"] for e in entities[1:]]
    urls = []
    for c in cited_urls or []:
        u = c.get("url") if isinstance(c, dict) else c
        if u and u not in urls:
            urls.append(u)
    classes = [classify_source(u, own, comp_domains) for u in urls]
    return {
        "mentioned": set(positions),
        "order": order,                      # tracked brands by first mention
        "brand_mentioned": "brand" in positions,
        "brand_rank": brand_rank,
        "urls": urls,
        "classes": classes,
        "owned_citations": classes.count("own"),
        "total_citations": len(urls),
        "domains": sorted({url_host(u) for u in urls if url_host(u)}),
    }


def _rate(k: int, n: int) -> Optional[float]:
    return round(k / n, 4) if n else None


def summarize(analyses: list[dict], entities: list[dict]) -> dict:
    """Mention / SoV / citation metrics over valid answers."""
    n = len(analyses)
    mentions = sum(1 for a in analyses if a["brand_mentioned"])
    lo, hi = wilson_interval(mentions, n)
    counts = {e["key"]: sum(1 for a in analyses if e["key"] in a["mentioned"]) for e in entities}
    total_mentions = sum(counts.values())
    with_cites = sum(1 for a in analyses if a["total_citations"] > 0)
    owned = sum(a["owned_citations"] for a in analyses)
    total_cit = sum(a["total_citations"] for a in analyses)
    citing_own = sum(1 for a in analyses if a["owned_citations"] > 0)
    ranks = [a["brand_rank"] for a in analyses if a["brand_rank"] is not None]
    captured = with_cites > 0
    return {
        "n": n,
        "mentions": mentions,
        "mention_rate": _rate(mentions, n),
        "ci_low": lo if n else None,
        "ci_high": hi if n else None,
        "thin": n < THIN_N,
        "sov": round(counts["brand"] / total_mentions, 4) if total_mentions else None,
        "citation_rate": _rate(citing_own, n) if captured else None,
        "answers_citing_own": citing_own,
        "answers_with_citations": with_cites,
        "citation_share": round(owned / total_cit, 4) if total_cit else None,
        "owned_citations": owned,
        "total_citations": total_cit,
        "citations_captured": captured,
        "avg_first_position": round(statistics.mean(ranks), 2) if ranks else None,
        "n_positioned": len(ranks),
    }


def _competitor_table(analyses: list[dict], entities: list[dict]) -> list[dict]:
    n = len(analyses)
    counts = {e["key"]: sum(1 for a in analyses if e["key"] in a["mentioned"]) for e in entities}
    total = sum(counts.values())
    rows = []
    for e in entities:
        k = counts[e["key"]]
        lo, hi = wilson_interval(k, n)
        # rank of this brand among tracked brands, in answers that mention it
        positions = [a["order"].index(e["key"]) + 1 for a in analyses if e["key"] in a["mentioned"]]
        rows.append({"name": e["name"], "domain": e["domain"], "is_client": e["key"] == "brand",
                     "mentions": k, "mention_rate": _rate(k, n),
                     "ci_low": lo if n else None, "ci_high": hi if n else None,
                     "sov": round(k / total, 4) if total else None,
                     "avg_first_position": round(statistics.mean(positions), 2) if positions else None})
    return rows


def _citation_sources(analyses: list[dict]) -> dict:
    by_class = {"own": 0, "competitor": 0, "social": 0, "reference": 0, "other": 0}
    domains: dict[str, dict] = {}
    for a in analyses:
        for url, cls in zip(a["urls"], a["classes"]):
            by_class[cls] += 1
        for url, cls in zip(a["urls"], a["classes"]):
            host = url_host(url)
            if host:
                d = domains.setdefault(host, {"domain": host, "class": cls, "answers": set()})
                d["answers"].add(a["_id"])
    top = sorted(({"domain": d["domain"], "class": d["class"], "answers": len(d["answers"])}
                  for d in domains.values()), key=lambda d: (-d["answers"], d["domain"]))[:15]
    return {"by_class": by_class, "top_domains": top}


def _analyze_rows(rows: list[dict], entities: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        a = analyze_answer(row.get("answer") or "", row.get("cited_urls") or [], entities)
        a["_id"] = row.get("id")
        a["_row"] = row
        out.append(a)
    return out


def _breakdown(analyses: list[dict], entities: list[dict], key: str) -> dict:
    groups: dict[str, list] = {}
    for a in analyses:
        groups.setdefault(a["_row"].get(key) or "unassigned", []).append(a)
    return {g: summarize(items, entities) for g, items in sorted(groups.items())}


def build_report(rows: list[dict], profile: dict, since: Optional[str] = None,
                 until: Optional[str] = None, engine: Optional[str] = None) -> dict:
    """Full report over stored rows (pure: no I/O)."""
    entities = build_entities(profile)
    by_key: dict[tuple, list] = {}
    for row in rows:
        by_key.setdefault((row["engine"], row["surface"]), []).append(row)

    engines_out = []
    for (eng, surface), items in sorted(by_key.items()):
        valid = [r for r in items if r["status"] == "ok"]
        analyses = _analyze_rows(valid, entities)
        unbranded = [a for a in analyses if not a["_row"]["branded"]]
        branded = [a for a in analyses if a["_row"]["branded"]]
        per_prompt: dict[str, dict] = {}
        for r in items:
            p = per_prompt.setdefault(r["prompt"], {"prompt": r["prompt"], "branded": r["branded"],
                                                    "group": r.get("prompt_group"), "funnel": r.get("funnel"),
                                                    "n": 0, "mentions": 0, "refused": 0, "errors": 0})
            if r["status"] == "refused":
                p["refused"] += 1
            elif r["status"] == "error":
                p["errors"] += 1
        for a in analyses:
            p = per_prompt[a["_row"]["prompt"]]
            p["n"] += 1
            p["mentions"] += 1 if a["brand_mentioned"] else 0
        for p in per_prompt.values():
            p["mention_rate"] = _rate(p["mentions"], p["n"])
        engines_out.append({
            "engine": eng,
            "surface": surface,
            "models": sorted({r.get("model") or "unknown" for r in items}),
            "counts": {"total": len(items), "ok": len(valid),
                       "refused": sum(1 for r in items if r["status"] == "refused"),
                       "error": sum(1 for r in items if r["status"] == "error")},
            "unbranded": summarize(unbranded, entities),
            "branded": summarize(branded, entities),
            "by_group": _breakdown(unbranded, entities, "prompt_group"),
            "by_funnel": _breakdown(unbranded, entities, "funnel"),
            "competitors": _competitor_table(unbranded, entities),
            "citations": _citation_sources(unbranded),
            "per_prompt": sorted(per_prompt.values(), key=lambda p: (p["branded"], p["prompt"])),
            "last_run_date": max(r["run_at"][:10] for r in items),
        })

    candidates = [e for e in engines_out if (engine is None or e["engine"] == engine)
                  and e["unbranded"]["n"] > 0]
    headline = None
    if candidates:
        best = sorted(candidates, key=lambda e: (-e["unbranded"]["n"], e["engine"], e["surface"]))[0]
        u = best["unbranded"]
        headline = {"engine": best["engine"], "surface": best["surface"], "models": best["models"],
                    "basis": "unbranded prompts only (prompts naming the client are excluded)",
                    **{k: u[k] for k in ("n", "mentions", "mention_rate", "ci_low", "ci_high", "thin",
                                         "sov", "citation_rate", "citation_share", "avg_first_position")},
                    "last_run_date": best["last_run_date"]}
    return {
        "project": normalize_domain(profile.get("domain", "")),
        "generated_at": utc_now(),
        "window": {"since": since, "until": until},
        "tracked_brands": [{"name": e["name"], "domain": e["domain"], "terms": e["terms"]} for e in entities],
        "headline": headline,
        "engines": engines_out,
        "warnings": term_warnings(entities) + ([] if headline else
                                               ["no valid unbranded answers in the window; no headline"]),
        "data_sources": sorted({f"{e['engine']} ({e['surface']}; models: {', '.join(e['models'])})"
                                for e in engines_out}),
        "limitations": LIMITATIONS,
    }


def compare_windows(rows_a: list[dict], rows_b: list[dict], profile: dict,
                    include_branded: bool = False) -> dict:
    """Paired comparison of per-prompt mention rates between two windows (pure)."""
    entities = build_entities(profile)

    def per_prompt(rows):
        out: dict[tuple, dict] = {}
        for a in _analyze_rows([r for r in rows if r["status"] == "ok"], entities):
            r = a["_row"]
            if r["branded"] and not include_branded:
                continue
            p = out.setdefault((r["engine"], r["surface"]), {}).setdefault(
                r["prompt"], {"n": 0, "mentions": 0, "group": r.get("prompt_group") or "unassigned"})
            p["n"] += 1
            p["mentions"] += 1 if a["brand_mentioned"] else 0
            p["group"] = r.get("prompt_group") or "unassigned"
        return out

    pa, pb = per_prompt(rows_a), per_prompt(rows_b)
    engines = []
    family: list[tuple[int, str]] = []   # (engine index, group) entries in the Holm family
    pvals: list[float] = []
    for key in sorted(set(pa) & set(pb)):
        a_prompts, b_prompts = pa[key], pb[key]
        shared = sorted(set(a_prompts) & set(b_prompts))
        groups: dict[str, dict] = {}
        for prompt in shared:
            ra = a_prompts[prompt]["mentions"] / a_prompts[prompt]["n"]
            rb = b_prompts[prompt]["mentions"] / b_prompts[prompt]["n"]
            g = groups.setdefault(b_prompts[prompt]["group"], {"pairs": []})
            g["pairs"].append({"prompt": prompt, "rate_a": round(ra, 4), "rate_b": round(rb, 4),
                               "n_a": a_prompts[prompt]["n"], "n_b": b_prompts[prompt]["n"],
                               "direction": "up" if rb > ra else "down" if rb < ra else "tie"})
        for gname, g in groups.items():
            pairs = g["pairs"]
            n_up = sum(1 for p in pairs if p["direction"] == "up")
            n_down = sum(1 for p in pairs if p["direction"] == "down")
            g.update({"n_pairs": len(pairs), "n_up": n_up, "n_down": n_down,
                      "n_tie": len(pairs) - n_up - n_down, "p": sign_test_p(n_up, n_down), "p_adj": None,
                      "mean_change_pp": round(100 * statistics.mean(p["rate_b"] - p["rate_a"] for p in pairs), 2),
                      "min_runs_per_prompt": min(min(p["n_a"], p["n_b"]) for p in pairs)})
            if gname in ("treatment", "control"):
                family.append((len(engines), gname))
                pvals.append(g["p"])
        engines.append({"engine": key[0], "surface": key[1], "shared_prompts": len(shared),
                        "only_in_a": len(set(a_prompts) - set(b_prompts)),
                        "only_in_b": len(set(b_prompts) - set(a_prompts)), "groups": groups})

    for (idx, gname), padj in zip(family, holm_adjust(pvals) if pvals else []):
        engines[idx]["groups"][gname]["p_adj"] = padj

    for e in engines:
        e.update(_verdict(e["groups"]))
        low_runs = [g for g, d in e["groups"].items() if d["min_runs_per_prompt"] < RECOMMENDED_RUNS]
        e["warnings"] = ([f"group(s) {', '.join(low_runs)} have prompts with fewer than "
                          f"{RECOMMENDED_RUNS} runs in a window; per-prompt rates are coarse"]
                         if low_runs else [])
    return {"engines": engines, "holm_family_size": len(pvals), "decision_rule": DECISION_RULE,
            "basis": "unbranded prompts only" if not include_branded else "all prompts",
            "limitations": LIMITATIONS}


def _verdict(groups: dict) -> dict:
    t, c = groups.get("treatment"), groups.get("control")
    if not t or not c:
        return {"verdict": "Unproven", "diff_in_change_pp": None,
                "reason": "no treatment/control split in the shared prompts; the change cannot be "
                          "separated from engine-wide drift"}
    did = round(t["mean_change_pp"] - c["mean_change_pp"], 2)
    if t["n_pairs"] < MIN_PAIRED_PROMPTS or c["n_pairs"] < MIN_PAIRED_PROMPTS:
        return {"verdict": "Unproven", "diff_in_change_pp": did,
                "reason": f"fewer than {MIN_PAIRED_PROMPTS} paired prompts in treatment "
                          f"({t['n_pairs']}) or control ({c['n_pairs']})"}
    t_sig = t["p_adj"] is not None and t["p_adj"] < ALPHA
    c_up_sig = c["p_adj"] is not None and c["p_adj"] < ALPHA and c["n_up"] > c["n_down"]
    if t_sig and t["n_up"] > t["n_down"]:
        if did > 0 and not c_up_sig:
            return {"verdict": "Promote", "diff_in_change_pp": did,
                    "reason": f"treatment improved (p_adj={t['p_adj']}) and beat control by {did} pp"}
        return {"verdict": "Unproven", "diff_in_change_pp": did,
                "reason": "treatment improved but control improved as much or more; likely engine drift"}
    if t_sig and t["n_down"] > t["n_up"] and did < 0:
        return {"verdict": "Rollback", "diff_in_change_pp": did,
                "reason": f"treatment declined (p_adj={t['p_adj']}) and trailed control by {abs(did)} pp"}
    return {"verdict": "Keep-testing", "diff_in_change_pp": did,
            "reason": "no significant treatment change after Holm adjustment"}


# ---------------------------------------------------------------------------
# Ingest validation (pure)
# ---------------------------------------------------------------------------

def _normalize_run_at(value: Any) -> str:
    if value in (None, ""):
        return utc_now()
    text = str(value).strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text).isoformat() + "T00:00:00Z"
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"run_at {text!r} is not ISO 8601") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ingest_row(obj: Any) -> dict:
    """Validate one JSONL row; returns a normalized dict or raises ValueError."""
    if not isinstance(obj, dict):
        raise ValueError("row is not a JSON object")
    prompt = obj.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("missing 'prompt'")
    status = obj.get("status", "ok")
    if status not in ("ok", "refused", "error"):
        raise ValueError(f"status must be ok|refused|error, got {status!r}")
    answer = obj.get("answer", obj.get("text"))
    if answer is None and status == "ok":
        raise ValueError("missing 'answer'")
    if answer is not None and not isinstance(answer, str):
        raise ValueError("'answer' must be a string")
    raw_cites = obj.get("citations", obj.get("cited_urls", obj.get("sources", [])))
    if raw_cites is None:
        raw_cites = []
    if not isinstance(raw_cites, list):
        raise ValueError("'citations' must be a list of URLs or {url} objects")
    cites, dropped = [], 0
    for c in raw_cites:
        url = c.get("url") if isinstance(c, dict) else c
        if isinstance(url, str) and urlparse(url).scheme in ("http", "https") and urlparse(url).hostname:
            cites.append({"url": url, "title": c.get("title") if isinstance(c, dict) else None})
        else:
            dropped += 1
    return {"prompt": " ".join(prompt.split()), "answer": answer or "", "status": status,
            "cited_urls": cites, "dropped_citations": dropped,
            "run_at": _normalize_run_at(obj.get("run_at")),
            "run_at_provided": obj.get("run_at") not in (None, ""),
            "model": _opt_str(obj, "model"), "locale": _opt_str(obj, "locale"),
            "group": _opt_str(obj, "group"), "funnel": _opt_str(obj, "funnel"),
            "error": _opt_str(obj, "error")}


def _opt_str(obj: dict, key: str) -> Optional[str]:
    """Optional string field of an ingest row; anything else makes the row invalid."""
    value = obj.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{key}' must be a string (got {type(value).__name__})")
    return value.strip()


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def write_kpi_envelope(path: str, project: str, metrics: dict, meta: dict, day: Optional[str] = None) -> dict:
    """Validate and write a KPI envelope (contract: scripts/seo_kpi.py).

    Raises seo_kpi.EnvelopeError when a value breaks the contract (e.g. a
    percent where a 0-1 fraction belongs), so it fails here, not at ingest.
    """
    return write_envelope(path, project, SOURCE, metrics, day=day, meta=meta)


def _pct(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{100 * v:.1f}%"


def _line(m: dict) -> str:
    ci = f"[{_pct(m['ci_low'])}, {_pct(m['ci_high'])}]" if m["n"] else ""
    return (f"n={m['n']}{' THIN' if m['thin'] else ''} mention {_pct(m['mention_rate'])} {ci} "
            f"SoV {_pct(m['sov'])} cite-rate {_pct(m['citation_rate'])} "
            f"cite-share {_pct(m['citation_share'])} avg-pos {m['avg_first_position'] or 'n/a'}")


def _print_report(rep: dict) -> None:
    w = rep["window"]
    print(f"AI visibility: {rep['project']}  window {w['since'] or 'start'}..{w['until'] or 'now'}")
    h = rep["headline"]
    if h:
        print(f"Headline [{h['basis']}]\n  {h['engine']}/{h['surface']}  mention {_pct(h['mention_rate'])} "
              f"(95% CI {_pct(h['ci_low'])}-{_pct(h['ci_high'])}), n={h['n']}"
              f"{' THIN (n<20)' if h['thin'] else ''}, SoV {_pct(h['sov'])}, "
              f"citation rate {_pct(h['citation_rate'])}")
    for e in rep["engines"]:
        c = e["counts"]
        print(f"\n{e['engine']}/{e['surface']}  models: {', '.join(e['models'])}  "
              f"ok {c['ok']} / refused {c['refused']} / error {c['error']}")
        print(f"  unbranded  {_line(e['unbranded'])}")
        print(f"  branded    {_line(e['branded'])}")
        for g, m in e["by_group"].items():
            print(f"  group {g:<10} {_line(m)}")
        for f, m in e["by_funnel"].items():
            print(f"  funnel {f:<9} {_line(m)}")
        for comp in e["competitors"]:
            print(f"  brand {comp['name'][:24]:<24} mention {_pct(comp['mention_rate'])} SoV {_pct(comp['sov'])}")
        src = e["citations"]["by_class"]
        print("  cited sources: " + ", ".join(f"{k} {v}" for k, v in src.items()))
    for warn in rep["warnings"]:
        print(f"Warning: {warn}")


def _profile_or_exit(project: str, data_dir: Optional[str]) -> dict:
    profile = load_profile(project, data_dir)
    if profile is None:
        print(f"Error: no project profile for {project}. Create one first: "
              f"seo_project.py init {project} --brand <term> --competitor <domain>", file=sys.stderr)
        raise SystemExit(2)
    return profile


def _day(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def _locale(profile: dict) -> str:
    m = profile.get("markets") or {}
    return f"{(m.get('language') or 'en').lower()}-{(m.get('country') or 'US').upper()}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def make_plan(profile: dict, panel: list[dict], engine: str, runs: int, model: str) -> dict:
    planned = len(panel) * runs
    unbranded = sum(1 for p in panel if not p["branded"])
    groups = sorted({p["group"] for p in panel})
    warnings = term_warnings(build_entities(profile))
    if runs < RECOMMENDED_RUNS:
        warnings.append(f"--runs {runs} < {RECOMMENDED_RUNS}: single answers are noisy; use k >= 5")
    if unbranded * runs < THIN_N:
        warnings.append(f"only {unbranded * runs} unbranded answers per batch: the headline will be "
                        f"flagged thin (n < {THIN_N}); add prompts (20-50 recommended)")
    if "control" not in groups:
        warnings.append("no control group: compare will return Unproven for any change")
    return {
        "project": normalize_domain(profile["domain"]),
        "engine": engine, "surface": ENGINES[engine]["surface"], "model": model, "runs": runs,
        "prompts": panel, "n_prompts": len(panel), "n_unbranded": unbranded,
        "n_branded": len(panel) - unbranded, "groups": groups,
        "planned_calls": planned,
        "worst_case_requests": planned * (1 + MAX_CONTINUATIONS),
        "suggested_max_calls": planned,
        "request": {"max_tokens": MAX_TOKENS, "tools": [f"web_search_20260209 (max_uses {WEB_SEARCH_MAX_USES})"],
                    "effort": "medium", "system_prompt": None, "fallbacks": "disabled (per-model measurement)"},
        "cost_note": "Token cost depends on answer length and web-search usage, so no dollar estimate is "
                     "given. Each run is at least one API request; a paused search turn adds up to "
                     f"{MAX_CONTINUATIONS} continuation requests, all counted against --max-calls.",
        "tos_notes": [
            "Gemini API grounding with Google Search is excluded (its terms forbid caching/analysing results)",
            "consumer surfaces (ChatGPT app, AI Overviews/AI Mode, Copilot, Perplexity) only via licensed "
            "providers (DataForSEO through seo-dataforseo) or manual capture, then `ingest`",
        ],
        "warnings": warnings,
        "confirm": (f"ai_visibility.py run --project {normalize_domain(profile['domain'])} --engine {engine} "
                    f"--runs {runs} --max-calls {planned}"),
    }


def _print_plan(plan: dict) -> None:
    print(f"Plan: {plan['project']}  engine {plan['engine']} ({plan['surface']})  model {plan['model']}")
    print(f"  prompts {plan['n_prompts']} ({plan['n_unbranded']} unbranded, {plan['n_branded']} branded)"
          f"  groups {', '.join(plan['groups'])}  runs/prompt {plan['runs']}")
    print(f"  API calls: {plan['planned_calls']} (worst case with pause_turn continuations: "
          f"{plan['worst_case_requests']})")
    print(f"  {plan['cost_note']}")
    for w in plan["warnings"]:
        print(f"  Warning: {w}")
    print(f"Confirm the call count with the operator, then run:\n  {plan['confirm']}")


def cmd_plan(args) -> int:
    profile = _profile_or_exit(args.project, args.data_dir)
    if args.engine not in ENGINES:
        print(f"Error: engine {args.engine!r} has no native runner (native: {', '.join(ENGINES)}). "
              "Capture its answers through DataForSEO or manually and use `ingest`.", file=sys.stderr)
        return 2
    panel = load_panel(profile, args.prompts_file, args.group)
    if not panel:
        print("Error: empty prompt panel. Add prompts: seo_project.py add-prompt <domain> \"<prompt>\" "
              "--group treatment|control", file=sys.stderr)
        return 2
    plan = make_plan(profile, panel, args.engine, args.runs, args.model or ENGINES[args.engine]["default_model"])
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        _print_plan(plan)
    return 0


def cmd_run(args) -> int:
    profile = _profile_or_exit(args.project, args.data_dir)
    if args.engine not in ENGINES:
        print(f"Error: engine {args.engine!r} has no native runner; use `ingest`.", file=sys.stderr)
        return 2
    if args.max_calls < 1:
        print("Error: --max-calls must be >= 1", file=sys.stderr)
        return 2
    panel = load_panel(profile, args.prompts_file, args.group)
    if not panel:
        print("Error: empty prompt panel", file=sys.stderr)
        return 2
    model = args.model or ENGINES[args.engine]["default_model"]
    plan = make_plan(profile, panel, args.engine, args.runs, model)
    if args.dry_run:
        if args.json:
            print(json.dumps({"dry_run": True, **plan}, indent=2))
        else:
            print("DRY RUN: no API calls made.")
            _print_plan(plan)
        return 0
    if plan["planned_calls"] > args.max_calls:
        print(f"Error: the plan needs {plan['planned_calls']} calls ({len(panel)} prompts x {args.runs} runs) "
              f"but --max-calls is {args.max_calls}. Nothing was sent. Reduce --runs/--group or raise "
              "--max-calls after the operator confirms.", file=sys.stderr)
        return 2
    country = None
    if args.country:
        country = args.country.upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            print("Error: --country must be a 2-letter ISO 3166-1 code", file=sys.stderr)
            return 2

    try:
        engine = ENGINES[args.engine]["factory"]()
    except EngineFatalError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    conn = open_store(args.data_dir)
    project = normalize_domain(profile["domain"])
    batch_id = f"{today()}-{uuid.uuid4().hex[:8]}"
    budget = Budget(args.max_calls)
    counts = {"ok": 0, "refused": 0, "error": 0}
    consecutive_errors = 0
    stopped = None
    for _run in range(args.runs):           # interleave: an early stop leaves even coverage
        for item in panel:
            if not budget.take():
                stopped = f"--max-calls budget ({args.max_calls}) exhausted"
                break
            try:
                result = engine.ask(item["prompt"], model, budget, country)
            except EngineFatalError as exc:
                stopped = f"fatal engine error: {exc}"
                break
            insert_run(conn, {
                "project": project, "batch_id": batch_id, "run_at": utc_now(), "prompt": item["prompt"],
                "prompt_group": item["group"], "branded": item["branded"], "funnel": item["funnel"],
                "engine": engine.name, "surface": engine.surface, "model": result["model"],
                "locale": _locale(profile), "status": result["status"], "error": result["error"],
                "answer": result["answer"], "cited_urls": result["cited_urls"],
                "searched_urls": result["searched_urls"], "raw": result["raw"]})
            conn.commit()
            counts[result["status"]] += 1
            consecutive_errors = consecutive_errors + 1 if result["status"] == "error" else 0
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                stopped = f"{MAX_CONSECUTIVE_ERRORS} consecutive errors (last: {result['error']})"
                break
        if stopped:
            break
    conn.close()
    summary = {"batch_id": batch_id, "project": project, "engine": args.engine, "model": model,
               "requests_used": budget.used, "max_calls": args.max_calls, "results": counts,
               "stopped_early": stopped,
               "next": f"ai_visibility.py report --project {project} --since {today()} --emit-kpis kpis-ai.json"}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Batch {batch_id}: ok {counts['ok']}, refused {counts['refused']}, error {counts['error']}; "
              f"{budget.used}/{args.max_calls} requests used")
        if stopped:
            print(f"Stopped early: {stopped}")
    return 1 if stopped and stopped.startswith("fatal") else 0


def cmd_ingest(args) -> int:
    profile = _profile_or_exit(args.project, args.data_dir)
    engine = args.engine.strip().lower()
    if not _ENGINE_NAME_RE.match(engine):
        print("Error: --engine must be a short lowercase name, e.g. chatgpt, google-aio, perplexity",
              file=sys.stderr)
        return 2
    if "gemini" in engine and args.surface == "api" and not args.not_grounded:
        print("Error: Gemini API answers grounded with Google Search may not be stored or analysed under "
              "Google's grounding terms. If these answers were produced WITHOUT grounding, re-run with "
              "--not-grounded.", file=sys.stderr)
        return 2
    panel_meta = {p["prompt"].lower(): p for p in load_panel(profile)}
    project = normalize_domain(profile["domain"])
    batch_id = f"ingest-{today()}-{uuid.uuid4().hex[:8]}"
    valid, problems = [], []
    with open(args.file, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                row = parse_ingest_row(json.loads(line))
            except (json.JSONDecodeError, ValueError) as exc:
                problems.append({"line": lineno, "error": str(exc)})
                continue
            valid.append(row)
    if problems and args.strict:
        print(json.dumps({"ingested": 0, "problems": problems}, indent=2))
        return 2

    conn = open_store(args.data_dir)
    inserted = duplicates = dropped = undated = 0
    for row in valid:
        meta = panel_meta.get(row["prompt"].lower())
        rec = _prompt_record(row["prompt"], profile, row["group"] or (meta or {}).get("group", ""),
                             row["funnel"] or (meta or {}).get("funnel", ""))
        # A duplicate is the same answer to the same prompt at the same capture
        # time (a re-ingested file). Identical answers from different runs are
        # legitimate and kept. Rows without run_at get the ingest time and so
        # cannot be recognised on a later re-ingest; they are counted below.
        if not row["run_at_provided"]:
            undated += 1
        elif not args.allow_duplicates and conn.execute(
                "SELECT 1 FROM runs WHERE project=? AND engine=? AND surface=? AND prompt=? AND run_at=?"
                " AND COALESCE(answer, '')=?",
                (project, engine, args.surface, rec["prompt"], row["run_at"], row["answer"])).fetchone():
            duplicates += 1
            continue
        dropped += row["dropped_citations"]
        insert_run(conn, {
            "project": project, "batch_id": batch_id, "run_at": row["run_at"], "prompt": rec["prompt"],
            "prompt_group": rec["group"], "branded": rec["branded"], "funnel": rec["funnel"],
            "engine": engine, "surface": args.surface, "model": row["model"] or args.model,
            "locale": row["locale"] or _locale(profile), "status": row["status"], "error": row["error"],
            "answer": row["answer"], "cited_urls": row["cited_urls"], "searched_urls": [],
            "raw": {"source_file": os.path.basename(args.file)}})
        inserted += 1
    conn.commit()
    conn.close()
    out = {"batch_id": batch_id, "engine": engine, "surface": args.surface, "ingested": inserted,
           "skipped_duplicates": duplicates, "invalid_rows": problems, "dropped_citations": dropped,
           "rows_without_run_at": undated}
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"Ingested {inserted} rows as {engine}/{args.surface} (batch {batch_id}); "
              f"{duplicates} duplicates skipped, {len(problems)} invalid rows, {dropped} unusable citations")
        if undated:
            print(f"  {undated} rows had no run_at and were dated now; they cannot be de-duplicated "
                  "if this file is ingested again")
        for p in problems[:10]:
            print(f"  line {p['line']}: {p['error']}")
    return 2 if problems and not valid else 0   # exit 2 only when no row in the file was usable


def cmd_report(args) -> int:
    profile = _profile_or_exit(args.project, args.data_dir)
    conn = open_store(args.data_dir)
    rows = load_runs(conn, normalize_domain(profile["domain"]), args.since, args.until, args.engine)
    conn.close()
    if not rows:
        print("No stored runs match. Run `plan` + `run`, or `ingest` captured answers first.", file=sys.stderr)
        return 1
    rep = build_report(rows, profile, args.since, args.until, args.engine)
    if args.emit_kpis:
        h = rep["headline"]
        if h is None:
            print("Error: no headline (no valid unbranded answers); KPI envelope not written", file=sys.stderr)
            return 1
        try:
            write_kpi_envelope(args.emit_kpis, rep["project"], {
                "ai.mention_rate": h["mention_rate"], "ai.mention_rate_ci_low": h["ci_low"],
                "ai.mention_rate_ci_high": h["ci_high"], "ai.citation_rate": h["citation_rate"],
                "ai.sov": h["sov"], "ai.n": h["n"]},
                day=args.date or h["last_run_date"], meta={
                    "engine": h["engine"], "surface": h["surface"], "models": h["models"],
                    "basis": h["basis"], "thin": h["thin"], "window": rep["window"],
                    "citation_share": h["citation_share"], "avg_first_position": h["avg_first_position"]})
        except EnvelopeError as exc:
            print(f"Error: KPI envelope rejected, nothing written: {exc}", file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        _print_report(rep)
    return 0


def cmd_compare(args) -> int:
    if not args.a_until < args.b_since:
        print("Error: window A must end before window B starts", file=sys.stderr)
        return 2
    profile = _profile_or_exit(args.project, args.data_dir)
    project = normalize_domain(profile["domain"])
    conn = open_store(args.data_dir)
    rows_a = load_runs(conn, project, args.a_since, args.a_until, args.engine)
    rows_b = load_runs(conn, project, args.b_since, args.b_until, args.engine)
    conn.close()
    res = compare_windows(rows_a, rows_b, profile, args.include_branded)
    res.update({"project": project, "windows": {"a": [args.a_since, args.a_until], "b": [args.b_since, args.b_until]}})
    if not res["engines"]:
        res["note"] = "no engine/surface has valid answers in both windows"
    if args.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"Compare {project}: A {args.a_since}..{args.a_until} vs B {args.b_since}..{args.b_until} "
          f"({res['basis']}; Holm family {res['holm_family_size']})")
    for e in res["engines"]:
        print(f"\n{e['engine']}/{e['surface']}: {e['shared_prompts']} shared prompts -> "
              f"{e['verdict']} ({e['reason']})")
        for g, d in sorted(e["groups"].items()):
            print(f"  {g:<10} pairs {d['n_pairs']} up {d['n_up']} down {d['n_down']} tie {d['n_tie']} "
                  f"mean {d['mean_change_pp']:+.1f} pp  p={d['p']} p_adj={d['p_adj']}")
        for w in e["warnings"]:
            print(f"  Warning: {w}")
    if not res["engines"]:
        print(res["note"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI share of voice: prompt panel x engines x runs")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True, help="Client domain (seo_project.py profile)")
    common.add_argument("--data-dir", help="Storage root (default $CLAUDE_SEO_DATA_DIR or ~/.cache/claude-seo)")
    common.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", parents=[common], help="Show the prompt panel and call count (no network)")
    p.add_argument("--engine", default="anthropic")
    p.add_argument("--runs", type=int, default=RECOMMENDED_RUNS)
    p.add_argument("--group", help="Only prompts in this group")
    p.add_argument("--model")
    p.add_argument("--prompts-file", help="Text / JSON / JSONL prompts instead of the profile panel")

    p = sub.add_parser("run", parents=[common], help="Ask the panel through a native engine (paid API)")
    p.add_argument("--engine", required=True, choices=sorted(ENGINES))
    p.add_argument("--runs", type=int, default=RECOMMENDED_RUNS)
    p.add_argument("--max-calls", type=int, required=True, help="Hard cap on API requests (required)")
    p.add_argument("--model", help=f"Model id (default {DEFAULT_MODEL})")
    p.add_argument("--group")
    p.add_argument("--prompts-file")
    p.add_argument("--country", help="Optional 2-letter country for web_search user_location")
    p.add_argument("--dry-run", action="store_true", help="Print the plan; make no calls")

    p = sub.add_parser("ingest", parents=[common], help="Store captured answers from another engine/surface")
    p.add_argument("file", help="JSONL: {prompt, answer, citations|cited_urls|sources, run_at?, model?, locale?}")
    p.add_argument("--engine", required=True, help="Short name, e.g. chatgpt, google-aio, perplexity, copilot")
    p.add_argument("--surface", choices=["api", "ui"], default="ui", help="ui (consumer app, default) or api")
    p.add_argument("--model", help="Model label when rows carry none")
    p.add_argument("--strict", action="store_true", help="Reject the whole file if any row is invalid")
    p.add_argument("--allow-duplicates", action="store_true")
    p.add_argument("--not-grounded", action="store_true",
                   help="Assert Gemini API answers were produced without Google Search grounding")

    p = sub.add_parser("report", parents=[common], help="Mention rate, SoV, citations per engine/surface")
    p.add_argument("--since", type=_day)
    p.add_argument("--until", type=_day)
    p.add_argument("--engine")
    p.add_argument("--date", type=_day, help="KPI envelope date (default: latest run date in the headline)")
    p.add_argument("--emit-kpis", help="Write ai.* KPI envelope for performance_tracker.py ingest")

    p = sub.add_parser("compare", parents=[common], help="Paired window comparison with verdicts")
    p.add_argument("--a-since", type=_day, required=True)
    p.add_argument("--a-until", type=_day, required=True)
    p.add_argument("--b-since", type=_day, required=True)
    p.add_argument("--b-until", type=_day, required=True)
    p.add_argument("--engine")
    p.add_argument("--include-branded", action="store_true")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "runs", 1) is not None and getattr(args, "runs", 1) < 1:
        print("Error: --runs must be >= 1", file=sys.stderr)
        return 2
    handlers = {"plan": cmd_plan, "run": cmd_run, "ingest": cmd_ingest,
                "report": cmd_report, "compare": cmd_compare}
    try:
        return handlers[args.cmd](args)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
