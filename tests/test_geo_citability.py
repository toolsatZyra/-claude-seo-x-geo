"""
Tests for scripts/citability_scorer.py.

Mirrors tests/test_url_safety.py's pattern: prove the grafted scorer cannot
be used to fetch private/loopback/link-local hosts, and that the scoring
function returns a bounded 0-100 score.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import citability_scorer  # noqa: E402


def test_score_passage_bounded_zero_to_hundred():
    text = (
        "Citability is a measure of how likely an AI model is to quote a "
        "passage verbatim in a generated answer. According to research from "
        "Princeton, front-loaded, self-contained passages with statistics "
        "score highest. Studies show citations lift AI visibility by "
        "roughly 40 percent, and statistics alone add about 37 percent. "
        "Keyword stuffing, by contrast, reduces citability by roughly 10 "
        "percent, so AI-specific keyword rewriting is not recommended."
    )
    result = citability_scorer.score_passage(text, heading="What is citability?")
    assert 0 <= result["total_score"] <= 100
    assert result["grade"] in {"A", "B", "C", "D", "F"}


def test_score_passage_empty_text_does_not_crash():
    result = citability_scorer.score_passage("", heading=None)
    assert result["total_score"] == 0
    assert result["grade"] == "F"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://2130706433/",
        "https://metadata.google.internal./",
        "http://0.0.0.0/",
    ],
)
def test_analyze_page_citability_rejects_unsafe_urls(url):
    """Every private/loopback/metadata/obfuscated target must be refused
    with an error key, never raise, and never attempt a real connection."""
    result = citability_scorer.analyze_page_citability(url)
    assert "error" in result
    assert "total_blocks_analyzed" not in result


def test_analyze_page_citability_handles_unreachable_public_host():
    """A syntactically valid public URL that can't be reached must return
    a structured error, not raise."""
    result = citability_scorer.analyze_page_citability(
        "https://this-domain-should-not-resolve-aeo-merge-test.invalid/"
    )
    assert "error" in result
