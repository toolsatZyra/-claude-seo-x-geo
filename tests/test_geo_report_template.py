"""The geo-dashboard report template must not ship another client's data.

geo-seo-claude commit 50445b2: unset cover fields used to default to a real
sample client (domain, cities, CMS, business type, audit date), so any report
rendered without those metadata flags carried someone else's details. Fields
now render only when supplied, and the page footer comes from footer_text /
brand_name instead of a hardcoded client name.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "extensions" / "geo-dashboard" / "templates" / "geo-report-template.html"

LEAKED_SAMPLE_DATA = (
    "alexamediasolutions",
    "alexa media",
    "raleigh",
    "omaha",
    "aioseo",
    "may 3, 2026",
    "digital marketing agency",
)


def test_template_carries_no_sample_client_data() -> None:
    text = TEMPLATE.read_text(encoding="utf-8").lower()
    leaked = [needle for needle in LEAKED_SAMPLE_DATA if needle in text]
    assert not leaked, f"sample client data in the report template: {leaked}"


def test_optional_cover_fields_render_only_when_supplied() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    for field in ("date", "business_type", "locations", "platform"):
        assert f"$if({field})$<div class=\"cover-meta-item\">" in text, field
        # No "$else$<fallback>" default for any optional cover field.
        assert not re.search(rf"\$if\({field}\)\$\${field}\$\$else\$", text), field


def test_footer_is_driven_by_metadata() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "$if(footer_text)$$footer_text$" in text
    assert "$if(brand_name)$$brand_name$" in text
