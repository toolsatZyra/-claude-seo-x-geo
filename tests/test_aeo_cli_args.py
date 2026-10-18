"""
CLI argument handling for the AEO scripts that used to read sys.argv by hand.

Before v3.1.1, `citability_scorer.py --help` fetched a page named "--help",
`brand_scanner.py --help` scanned a brand called "--help", and
`llmstxt_generator.py --help` fetched ":///llms.txt". They now use argparse,
keeping the positional interface every skill already calls.

No network: --help exits before any fetch, and the analysis functions are
replaced with recorders for the positional-mapping checks.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = REPO_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import brand_scanner  # noqa: E402
import citability_scorer  # noqa: E402
import llmstxt_generator  # noqa: E402


@pytest.mark.parametrize("script", ["citability_scorer.py", "brand_scanner.py", "llmstxt_generator.py"])
def test_help_prints_usage_and_does_no_work(script):
    p = subprocess.run([sys.executable, str(_SCRIPTS / script), "--help"],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0
    assert p.stdout.startswith("usage:")
    assert "{" not in p.stdout.splitlines()[0]  # no JSON result was emitted


@pytest.mark.parametrize("script", ["citability_scorer.py", "brand_scanner.py", "llmstxt_generator.py"])
def test_missing_arguments_fail_with_usage(script):
    p = subprocess.run([sys.executable, str(_SCRIPTS / script)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 2
    assert "usage:" in p.stderr


def test_citability_positional_url(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(citability_scorer, "analyze_page_citability",
                        lambda url: seen.setdefault("url", url) and {"url": url})
    citability_scorer.main(["https://example.com/page"])
    assert seen["url"] == "https://example.com/page"
    assert json.loads(capsys.readouterr().out)["url"] == "https://example.com/page"


@pytest.mark.parametrize("argv, expected", [
    (["Acme Corp", "acme.com"], ("Acme Corp", "acme.com")),
    (["Acme Corp"], ("Acme Corp", None)),
])
def test_brand_scanner_positional_brand_and_optional_domain(monkeypatch, capsys, argv, expected):
    seen = []
    monkeypatch.setattr(brand_scanner, "generate_brand_report", lambda b, d: seen.append((b, d)) or {})
    brand_scanner.main(argv)
    assert seen == [expected]


def test_llmstxt_defaults_to_validate(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(llmstxt_generator, "validate_llmstxt", lambda url: seen.append(url) or {"ok": 1})
    llmstxt_generator.main(["https://example.com"])
    assert seen == ["https://example.com"]


def test_llmstxt_generate_passes_policy_mode(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(llmstxt_generator, "generate_llmstxt",
                        lambda url, mode: seen.append((url, mode)) or {"ok": 1})
    llmstxt_generator.main(["https://example.com", "generate", "audit"])
    assert seen == [("https://example.com", "audit")]


def test_llmstxt_rejects_unknown_mode():
    with pytest.raises(SystemExit) as exc:
        llmstxt_generator.main(["https://example.com", "publish"])
    assert exc.value.code == 2
