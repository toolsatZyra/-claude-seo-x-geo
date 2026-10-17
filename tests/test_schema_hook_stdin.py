"""Stdin hook-event contract for hooks/validate-schema.py.

Claude Code delivers a PostToolUse event as JSON on stdin; the argv template
(``${tool_input.file_path}``) is only substituted by some harnesses. The hook
must find the file through either channel, report diagnostics on the channel
Claude actually reads (stderr + exit 2 for critical errors, additionalContext
JSON + exit 0 for warnings), and never crash on a malformed event.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "validate-schema.py"


def _page(tmp_path: Path, payload: dict) -> Path:
    html = tmp_path / "page.html"
    html.write_text(
        '<html><head><script type="application/ld+json">'
        + json.dumps(payload)
        + "</script></head></html>",
        encoding="utf-8",
    )
    return html


def _run(argv: list[str], stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK), *argv],
        input=stdin,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )


def test_file_path_from_stdin_event_is_validated(tmp_path: Path) -> None:
    html = _page(tmp_path, {"@context": "https://schema.org", "@type": "ClaimReview"})
    event = {"hook_event_name": "PostToolUse", "tool_input": {"file_path": str(html)}}
    # The literal, unsubstituted template is what a harness that does not
    # expand ${...} passes; it is not a file, so stdin must win.
    result = _run(["${tool_input.file_path}"], json.dumps(event))
    assert result.returncode == 2
    assert "ClaimReview" in result.stderr
    assert result.stdout == ""


def test_warnings_reach_claude_as_additional_context(tmp_path: Path) -> None:
    html = _page(tmp_path, {"@context": "https://schema.org", "name": "No type"})
    event = {"tool_input": {"file_path": str(html)}}
    result = _run([], json.dumps(event))
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "PostToolUse"
    assert "Missing @type" in output["additionalContext"]


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "not json",
        "[]",
        '["tool_input"]',
        '{"tool_input": "a-string"}',
        '{"tool_input": {"file_path": 42}}',
        '{"tool_input": {"file_path": "/definitely/not/a/file.html"}}',
        "null",
    ],
)
def test_malformed_events_exit_cleanly(stdin: str) -> None:
    result = _run([], stdin)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
