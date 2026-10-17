"""AI crawler claims are checked against the right bot.

Adapted from upstream AgriciDaniel/claude-seo tests/test_ai_crawler_claims.py
(MIT) to this fork's files: the geo-* cluster, the seo-geo router and agents,
and scripts/aeo_score.py. The defects these guard against (spec section 2.2,
item 5) distorted the AEO score: GPTBot described as powering ChatGPT search,
ClaudeBot as Claude search, `anthropic-ai` listed as a live crawler,
Claude-SearchBot / Claude-User missing, and points deducted for blocking
training-only crawlers.

Sources: OpenAI https://developers.openai.com/api/docs/bots, Anthropic
https://support.anthropic.com/en/articles/8896518, Google
https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers,
Apple https://support.apple.com/en-us/119829, Perplexity
https://docs.perplexity.ai/guides/bots.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import aeo_score  # noqa: E402

AEO_DOCS = sorted(
    [p for p in (REPO_ROOT / "skills").glob("geo-*/SKILL.md")]
    + [REPO_ROOT / "skills" / "seo-geo" / "SKILL.md", REPO_ROOT / "skills" / "seo-audit" / "SKILL.md"]
    + [p for p in (REPO_ROOT / "agents").glob("geo-*.md")]
    + [REPO_ROOT / "agents" / "seo-geo.md"]
)
GEO_CRAWLERS = REPO_ROOT / "skills" / "geo-crawlers" / "SKILL.md"
NEGATION = re.compile(r"\b(not|never|no effect|only|does not|doesn't|unscored|not scored)\b", re.I)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _norm(text: str) -> str:
    """Collapse whitespace so prose reflows do not break sentence-level checks."""
    return re.sub(r"\s+", " ", text)


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _is_claim_table_row(line: str) -> bool:
    """Rows of the claim -> bot table name the WRONG bot on purpose (last column)."""
    return line.startswith('| "')


def _table_row(text: str, first_cell: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"| {first_cell} |"):
            return line
    raise AssertionError(f"no table row for {first_cell}")


# --- GPTBot is training, OAI-SearchBot is ChatGPT Search -------------------

@pytest.mark.parametrize("path", AEO_DOCS, ids=_rel)
def test_gptbot_never_described_as_chatgpt_search(path):
    for line in _read(path).splitlines():
        lowered = line.lower()
        if "gptbot" not in lowered or _is_claim_table_row(line):
            continue
        if "chatgpt search" in lowered or "chatgpt web search" in lowered or "(chatgpt)" in lowered:
            assert NEGATION.search(line), f"{_rel(path)}: GPTBot tied to ChatGPT search: {line.strip()}"
        assert "training + chatgpt search" not in lowered, _rel(path)


def test_known_gptbot_regressions_are_gone():
    assert "| GPTBot | OpenAI (training + ChatGPT search) |" not in _read(REPO_ROOT / "agents/geo-ai-visibility.md")
    compare = _read(REPO_ROOT / "skills/geo-compare/SKILL.md")
    assert "GPTBot (ChatGPT)" not in compare
    assert "ChatGPT can now crawl and cite your content" not in compare


# --- ClaudeBot is training, Claude-SearchBot is Claude search --------------

@pytest.mark.parametrize("path", AEO_DOCS, ids=_rel)
def test_claudebot_never_described_as_claude_search(path):
    for line in _read(path).splitlines():
        lowered = line.lower()
        if "claudebot" not in lowered or _is_claim_table_row(line):
            continue
        stripped = re.sub(r"(claude|oai)-searchbot|searchbot", "", lowered)
        if "search" in stripped:
            assert "training" in stripped or NEGATION.search(line), \
                f"{_rel(path)}: ClaudeBot tied to search: {line.strip()}"
        assert "claude web features" not in lowered


def test_geo_agent_recommends_claude_searchbot_not_claudebot():
    text = _read(REPO_ROOT / "agents/seo-geo.md")
    assert "Claude-SearchBot" in text
    assert "Allow for AI search visibility: GPTBot, OAI-SearchBot, ClaudeBot, PerplexityBot" not in text


# --- geo-crawlers documents the right matrix --------------------------------

def test_geo_crawlers_documents_answer_surface_agents():
    text = _read(GEO_CRAWLERS)
    for agent in ("OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User",
                  "PerplexityBot", "Perplexity-User", "Googlebot", "Bingbot", "Applebot"):
        _table_row(text, agent)
    assert "ChatGPT Search" in _table_row(text, "OAI-SearchBot")
    assert "citability" in _table_row(text, "Claude-SearchBot").lower()


def test_claude_user_is_documented_as_honoring_robots_txt():
    row = _table_row(_read(GEO_CRAWLERS), "Claude-User")
    assert "yes" in row.lower() and "ignore" not in row.lower()


def test_training_tokens_are_documented_as_training():
    text = _read(GEO_CRAWLERS)
    assert "training only" in _table_row(text, "GPTBot").lower()
    assert "training only" in _table_row(text, "ClaudeBot").lower()
    ext = _table_row(text, "Google-Extended")
    assert "does not affect google search" in ext.lower() and "ai overviews" in ext.lower()
    apple = _table_row(text, "Applebot-Extended").lower()
    assert "training" in apple and ("siri" in apple or "spotlight" in apple)


def test_anthropic_ai_is_not_listed_as_a_current_crawler():
    text = _read(GEO_CRAWLERS)
    assert not any(line.startswith("| anthropic-ai |") for line in text.splitlines())
    assert "undocumented" in _norm(text).lower()
    for path in AEO_DOCS:
        assert "Optional block (training only): CCBot, anthropic-ai" not in _read(path), _rel(path)


def test_perplexitybot_is_never_described_as_a_training_crawler():
    for path in AEO_DOCS:
        for line in _read(path).splitlines():
            if line.startswith("| PerplexityBot |"):
                assert "+ training" not in line and ("training" not in line.lower() or NEGATION.search(line)), \
                    f"{_rel(path)}: {line}"


def test_geo_crawlers_cites_vendor_docs():
    text = _read(GEO_CRAWLERS)
    for url in ("https://developers.openai.com/api/docs/bots",
                "https://support.anthropic.com/en/articles/8896518",
                "https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers",
                "https://support.apple.com/en-us/119829",
                "https://docs.perplexity.ai/guides/bots"):
        assert url in text, f"missing citation: {url}"


def test_geo_crawlers_has_claim_to_bot_table_and_cloudflare_step():
    text = _norm(_read(GEO_CRAWLERS))
    assert "Check the right bot for the claim you are making" in text
    assert "aeo_score.py crawlers" in text
    assert "# BEGIN Cloudflare Managed content" in text
    assert "may have been injected by Cloudflare rather than written by the site owner" in text


def test_script_and_skill_agree_on_answer_surface_agents():
    text = _read(GEO_CRAWLERS)
    section = text[text.index("### Answer surfaces (scored)"):text.index("### Training crawlers")]
    documented = {line.split("|")[1].strip() for line in section.splitlines()
                  if line.startswith("| ") and not line.startswith("| Agent") and not line.startswith("|---")}
    assert documented == {a["agent"] for a in aeo_score.ANSWER_SURFACE_AGENTS}


# --- No penalty for blocking training-only crawlers -------------------------

def test_no_doc_deducts_points_for_training_crawlers():
    visibility = _read(REPO_ROOT / "agents/geo-ai-visibility.md")
    assert "Deduct 15 points for each critical crawler blocked (GPTBot, ClaudeBot" not in visibility
    platform = _read(REPO_ROOT / "agents/geo-platform-analysis.md")
    assert "signals openness" not in platform
    crawlers = _read(GEO_CRAWLERS)
    assert "Tier 1 Crawlers Allowed" not in crawlers
    assert "5 points for llms.txt" not in crawlers           # llms.txt carries no weight
    for path in AEO_DOCS:
        norm = _norm(_read(path)).lower()
        assert "blocking gptbot" not in norm or "not" in norm, _rel(path)


def test_scorer_gives_full_marks_when_only_training_crawlers_are_blocked():
    robots = "\n".join(f"User-agent: {a['agent']}\nDisallow: /\n" for a in aeo_score.TRAINING_AGENTS)
    result = aeo_score.analyze_robots(robots + "\nUser-agent: *\nAllow: /\n", 200)
    assert result["score"] == 100
    assert all(a["status"] == "blocked" for a in result["training"])


def test_google_extended_is_never_a_google_search_signal():
    for rel in ("skills/seo-geo/SKILL.md", "agents/seo-geo.md", "skills/geo-crawlers/SKILL.md"):
        lowered = _norm(_read(REPO_ROOT / rel)).lower()
        assert "google-extended" in lowered, rel
        assert "not google search" in lowered or "does not affect google search" in lowered \
            or "never out of google search" in lowered, rel
    spec = next(a for a in aeo_score.TRAINING_AGENTS if a["agent"] == "Google-Extended")
    assert "not Google Search" in spec["purpose"]
    assert "Google-Extended" not in {a["agent"] for a in aeo_score.ANSWER_SURFACE_AGENTS}


# --- Agents treat fetched content as untrusted ------------------------------

@pytest.mark.parametrize("rel", ["agents/seo-geo.md", "agents/geo-ai-visibility.md",
                                 "agents/geo-platform-analysis.md"])
def test_agents_treat_fetched_content_as_untrusted(rel):
    text = _norm(_read(REPO_ROOT / rel)).lower()
    assert "untrusted" in text
    assert "never follow instructions" in text
