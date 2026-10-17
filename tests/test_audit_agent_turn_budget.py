"""Audit subagent turn-budget, early-write and model regressions.

Ported from AgriciDaniel/claude-seo (MIT) tests/test_audit_agent_turn_budget.py
(upstream v2.3.0, issues #177 and #272) and the v2.3.1 Opus assignment (#268).

Reporters found that seo-audit subagents hit their ``maxTurns`` cap on large
sites before ever writing a findings file, so a turn-budget stop threw away all
completed work. The fix has two parts for every subagent
``skills/seo-audit/SKILL.md`` can spawn:

1. ``maxTurns`` raised well above the old defaults (seo-technical was 20,
   seo-content was 15; both need real headroom for a 500-page crawl).
2. An explicit instruction to write a partial findings file after the first
   analysis pass and overwrite it with the complete findings at the end, so a
   maxTurns stop mid-audit still leaves usable output on disk.

Fork adaptations:

* Discovery reads only the delegation list items in seo-audit
  (```   - `seo-x` -- ...```), not every backticked name in the file, because
  this fork's audit skill also names skills (``seo-images``) and AEO fan-out
  targets in prose. A delegate with no agent file must at least resolve to a
  skill (it runs inline).
* The known set is checked as a required SUBSET rather than locked exactly,
  because parallel workstreams are adding delegates (``seo-agentic``) and
  re-wiring AEO (``geo-*``). Lock it exactly once integration settles.
* Agents still owned by other workstreams at port time (``seo-geo`` and
  ``geo-*``: W5; ``seo-agentic``: W1) are checked with a non-strict xfail, so
  they show up as XFAIL until hardened and XPASS afterwards, without breaking
  the suite in between. The integrator should empty ``PENDING_OTHER_OWNERS``
  once those workstreams land.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AUDIT_SKILL = ROOT / "skills" / "seo-audit" / "SKILL.md"
AGENTS_DIR = ROOT / "agents"
EXTENSION_AGENTS_GLOB = "extensions/*/agents"

EARLY_WRITE_SENTENCE = (
    "write a partial findings\nfile after the first analysis pass and overwrite it with the complete findings\n"
    "before finishing, so a turn-budget stop never loses completed work"
)

MIN_MAX_TURNS = 30
NAMED_HIGH_BUDGET_AGENTS = {"seo-technical": 40, "seo-content": 40}
CORE_AUDIT_AGENTS = {
    "seo-technical", "seo-content", "seo-schema", "seo-sitemap", "seo-performance",
    "seo-visual", "seo-geo", "seo-local", "seo-maps", "seo-google", "seo-backlinks",
    "seo-cluster", "seo-sxo", "seo-drift", "seo-ecommerce",
}
# Upstream v2.3.1 (#268): the judgment-heavy agents run on Opus.
OPUS_AGENTS = {"seo-content", "seo-geo", "seo-sxo", "seo-cluster", "seo-drift"}
# Emptied at v3.1 integration: every agent is now held to the same rules.
PENDING_OTHER_OWNERS: dict[str, str] = {}
ALLOWED_MODELS = {"sonnet", "opus", "haiku", "inherit"}


def _discover_audit_delegates() -> set[str]:
    text = AUDIT_SKILL.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*-\s+`((?:seo|geo)-[a-z0-9-]+)`\s+--", text, re.MULTILINE))


def _agent_path(name: str) -> Path | None:
    """Resolve an audit subagent to its file, core tree first, then extensions."""
    core = AGENTS_DIR / f"{name}.md"
    if core.is_file():
        return core
    matches = sorted(ROOT.glob(f"{EXTENSION_AGENTS_GLOB}/{name}.md"))
    return matches[0] if matches else None


def _audit_agents() -> list[str]:
    return sorted(n for n in _discover_audit_delegates() if _agent_path(n) is not None)


def _frontmatter_value(text: str, key: str) -> str | None:
    match = re.search(rf"^{key}:\s*(\S+)", text.split("---", 2)[1], re.MULTILINE)
    return match.group(1) if match else None


def _max_turns(text: str) -> int | None:
    value = _frontmatter_value(text, "maxTurns")
    return int(value) if value and value.isdigit() else None


def _params(names):
    out = []
    for name in sorted(names):
        marks = []
        if name in PENDING_OTHER_OWNERS:
            marks.append(pytest.mark.xfail(
                strict=False,
                reason=f"{name} is owned by {PENDING_OTHER_OWNERS[name]} until integration",
            ))
        out.append(pytest.param(name, marks=marks, id=name))
    return out


def test_audit_skill_still_names_the_core_subagent_set():
    delegates = _discover_audit_delegates()
    missing = CORE_AUDIT_AGENTS - delegates
    assert not missing, f"seo-audit no longer delegates to: {sorted(missing)}"


def test_every_audit_delegate_resolves_to_an_agent_or_an_inline_skill():
    unresolved = [
        name for name in sorted(_discover_audit_delegates())
        if _agent_path(name) is None and not (ROOT / "skills" / name / "SKILL.md").is_file()
    ]
    assert not unresolved, f"audit delegates with neither an agent nor a skill: {unresolved}"


@pytest.mark.parametrize("name", _params(_audit_agents()))
def test_audit_agent_has_a_turn_budget_at_least_30(name):
    turns = _max_turns(_agent_path(name).read_text(encoding="utf-8"))
    assert turns is not None and turns >= MIN_MAX_TURNS, f"{name} maxTurns={turns}"


@pytest.mark.parametrize("name", _params(_audit_agents()))
def test_audit_agent_has_the_early_write_instruction(name):
    assert EARLY_WRITE_SENTENCE in _agent_path(name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name,minimum", sorted(NAMED_HIGH_BUDGET_AGENTS.items()))
def test_named_reporters_agents_have_at_least_40_turns(name, minimum):
    turns = _max_turns((AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8"))
    assert turns is not None and turns >= minimum, f"{name} maxTurns={turns} < {minimum}"


@pytest.mark.parametrize("name", _params(OPUS_AGENTS))
def test_judgment_heavy_agents_run_on_opus(name):
    text = (AGENTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    assert _frontmatter_value(text, "model") == "opus"


def test_dataforseo_agent_has_the_early_write_instruction():
    text = (AGENTS_DIR / "seo-dataforseo.md").read_text(encoding="utf-8")
    assert EARLY_WRITE_SENTENCE in text
    assert "output_dir/findings/dataforseo.md" in text


def test_dataforseo_extension_mirror_body_matches_core_agent():
    core = (AGENTS_DIR / "seo-dataforseo.md").read_text(encoding="utf-8")
    mirror = (ROOT / "extensions" / "dataforseo" / "agents" / "seo-dataforseo.md").read_text(
        encoding="utf-8")
    assert core.split("---", 2)[2] == mirror.split("---", 2)[2]


def test_agent_models_use_portable_aliases():
    bad = []
    for path in sorted(AGENTS_DIR.glob("*.md")):
        model = _frontmatter_value(path.read_text(encoding="utf-8"), "model")
        if model is not None and model not in ALLOWED_MODELS:
            bad.append((path.name, model))
    assert not bad, f"agent model must be one of {sorted(ALLOWED_MODELS)}: {bad}"
