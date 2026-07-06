"""Tests for the aeo.llmstxt_mode gate on scripts/llmstxt_generator.py.
Asserts the generator refuses to run when mode == 'off', per the reconciled
llms.txt policy in skills/seo-geo/SKILL.md."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import llmstxt_generator  # noqa: E402


def test_generate_llmstxt_refuses_when_mode_is_off():
    with pytest.raises(llmstxt_generator.LlmsTxtGenerationDisabledError):
        llmstxt_generator.generate_llmstxt("https://example.com", mode="off")


def test_generate_llmstxt_default_mode_is_generate():
    """Default mode must be 'generate', not 'off' — validated by inspecting
    the function's own default parameter rather than a network call."""
    import inspect
    sig = inspect.signature(llmstxt_generator.generate_llmstxt)
    assert sig.parameters["mode"].default == "generate"


def test_validate_llmstxt_is_never_gated_by_mode():
    """validate_llmstxt has no mode parameter at all — auditing presence
    must always be allowed regardless of aeo.llmstxt_mode."""
    import inspect
    sig = inspect.signature(llmstxt_generator.validate_llmstxt)
    assert "mode" not in sig.parameters
