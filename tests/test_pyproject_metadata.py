"""Packaging metadata and lint-config guards."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_has_authors_and_keywords() -> None:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'authors = [' in text
    assert 'name = "Daniel Agrici"' in text
    assert 'email = "agricidaniel@gmail.com"' in text
    for keyword in ("seo", "claude-code", "schema-markup", "e-e-a-t", "geo"):
        assert f'"{keyword}"' in text


def test_pyproject_has_minimal_ruff_config_only() -> None:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.ruff]" in text
    assert 'target-version = "py311"' in text
    assert "line-length = 100" in text
    assert "[tool.ruff.lint]" in text
    assert 'select = ["E", "F", "W", "I"]' in text
    assert 'ignore = ["E501"]' in text


def _floor(text: str, package: str) -> tuple[int, ...]:
    match = re.search(rf"^{re.escape(package)}>=([0-9.]+),<", text, re.MULTILINE | re.IGNORECASE)
    assert match, f"{package} needs a bounded '>=floor,<ceiling' requirement"
    return tuple(int(part) for part in match.group(1).split("."))


def test_requirements_keep_security_and_compatibility_floors() -> None:
    """Floors may rise (Dependabot bumps) but never fall below these minimums.

    Security floors (advisory fixed in that release, PyPI vulnerability feed
    checked 2026-10-17): requests 2.34.2 (CVE-2026-25645), weasyprint 70.0
    (PYSEC-2026-3940), Pillow 12.3.0, urllib3 2.8.0, lxml_html_clean 0.4.5,
    flask 3.1.3 (CVE-2026-27205). playwright 1.62.0 and google-auth 2.56.2
    mirror upstream v2.2.6.
    """
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    minimums = {
        "lxml": (6, 1, 1),
        "lxml_html_clean": (0, 4, 5),
        "requests": (2, 34, 2),
        "urllib3": (2, 8, 0),
        "Pillow": (12, 3, 0),
        "playwright": (1, 62, 0),
        "weasyprint": (70, 0),
        "google-auth": (2, 56, 2),
        "google-auth-httplib2": (0, 4, 0),
        "flask": (3, 1, 3),
    }
    for package, minimum in minimums.items():
        assert _floor(text, package) >= minimum, f"{package} floor is below {minimum}"


def test_weasyprint_ceiling_admits_the_fixed_release() -> None:
    text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    match = re.search(r"^weasyprint>=([0-9.]+),<([0-9.]+)", text, re.MULTILINE)
    assert match
    floor = tuple(int(p) for p in match.group(1).split("."))
    ceiling = tuple(int(p) for p in match.group(2).split("."))
    assert floor < ceiling


def test_geo_dashboard_installers_use_the_flask_floor() -> None:
    for rel in ("extensions/geo-dashboard/install.sh", "extensions/geo-dashboard/install.ps1"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "flask>=3.1.3" in text, rel
