"""Full audit report generation from non-Google audit data."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import google_report  # noqa: E402


def test_full_audit_html_includes_summary_categories_and_roadmap(tmp_path: Path) -> None:
    data = {
        "summary": {
            "health_score": 82,
            "business_type": "SaaS",
            "top_findings": [
                {"title": "Canonical mismatch", "severity": "Critical"},
                "Thin service pages",
            ],
            "quick_wins": ["Add missing meta descriptions"],
        },
        "categories": [
            {
                "name": "Technical SEO",
                "score": 74,
                "what_works": ["HTTPS is enabled", "Robots.txt is reachable"],
                "findings": [
                    {
                        "title": "Canonical mismatch",
                        "severity": "Critical",
                        "description": "Homepage canonical points to a staging URL.",
                        "recommendation": "Set canonical to the production HTTPS URL.",
                    }
                ],
            },
            {
                "name": "Content Quality",
                "score": 68,
                "what_works": ["Clear product positioning"],
                "findings": [
                    {
                        "title": "Thin comparison pages",
                        "severity": "High",
                        "description": "Several pages have fewer than 300 words.",
                    }
                ],
            },
        ],
        "action_plan": {
            "phases": [
                {
                    "name": "Phase 1: Indexing Fixes",
                    "timeframe": "Week 1",
                    "items": ["Fix canonical mismatch", "Resubmit sitemap"],
                },
                {
                    "name": "Phase 2: Content Expansion",
                    "timeframe": "Weeks 2-3",
                    "items": ["Expand comparison page copy"],
                },
            ]
        },
    }

    result = google_report.generate_report(
        "full",
        data,
        "example.com",
        tmp_path,
        output_format="html",
    )

    assert result["error"] is None
    html_path = Path(result["files"][0])
    html = html_path.read_text(encoding="utf-8")
    assert "Executive Summary" in html
    assert "SaaS" in html
    assert "Technical SEO" in html
    assert "What Works" in html
    assert "Canonical mismatch" in html
    assert "Action Plan" in html
    assert "Phase 1: Indexing Fixes" in html
    assert "Content Quality" in html


def test_full_audit_renders_aeo_section_distinct_from_seo_categories(tmp_path: Path) -> None:
    """AEO must render as its own section — never folded into the SEO
    categories table or the SEO Health Score, per the AEO stance in CLAUDE.md."""
    data = {
        "summary": {"health_score": 68, "business_type": "AI content studio"},
        "categories": [
            {"name": "Technical SEO", "score": 70, "what_works": [], "findings": []},
        ],
        "aeo": {
            "ai_visibility_score": {
                "composite": 43,
                "label": "Fair",
                "components": {
                    "citability": {"score": 29.7, "weight": "39%"},
                    "brand_mentions": {"score": 11, "weight": "33%"},
                    "ai_crawler_access": {"score": 100, "weight": "28%"},
                },
            },
            "citability_scores": [
                {"url": "https://example.com/faq", "score": 0, "grade": "N/A",
                 "note": "Answers exist only in JSON-LD, invisible in the rendered DOM."},
            ],
            "ai_crawler_access": {
                "summary": "robots.txt allows all crawlers.",
                "tier_1_critical": ["GPTBot — Allowed"],
            },
            "llms_txt_status": "Absent (404).",
            "brand_visibility": {
                "score": 11,
                "findings": [{"platform": "LinkedIn", "status": "Confirmed", "note": "Active company page."}],
            },
            "per_platform_readiness": {
                "average": 21,
                "scores": [{"platform": "Perplexity", "score": 15, "status": "Critical", "top_fix": "Add prose content."}],
            },
        },
        "action_plan": {"phases": []},
    }

    result = google_report.generate_report(
        "full",
        data,
        "example.com",
        tmp_path,
        output_format="html",
    )

    assert result["error"] is None
    html = Path(result["files"][0]).read_text(encoding="utf-8")

    assert "AEO Score" in html
    assert "AI Visibility Score" in html
    assert "never averaged" in html
    assert "43" in html
    assert "Deterministic Citability Scores" in html
    assert "example.com/faq" in html
    assert "JSON-LD" in html
    assert "GPTBot" in html
    assert "Absent (404)" in html
    assert "LinkedIn" in html
    assert "Perplexity" in html

    # AEO must be its own section, rendered after the SEO categories section,
    # not merged into the same <div class="section"> as the SEO Health Score.
    # Search for the actual section headings (not the TOC, which lists both
    # titles up front and would make a plain substring search order-blind).
    categories_idx = html.index("2. Audit Categories")
    aeo_heading_idx = html.rindex("AEO Score")  # last occurrence = the real section heading, not the TOC entry
    assert aeo_heading_idx > categories_idx
    # The SEO Health Score (68) and AEO composite (43) are distinct figures
    # appearing separately — never combined into one blended score string.
    assert "68" in html and "43" in html
    assert "68/43" not in html and "43/68" not in html
