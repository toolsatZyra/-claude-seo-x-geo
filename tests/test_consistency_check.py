"""Fixture-based tests for scripts/consistency_check.py.

Every test builds a miniature plugin tree under ``tmp_path`` and points the
checker at it, so these tests pin the checker's behaviour without depending on
the state of this repository. The repo-level gate (zero errors on the real
tree) is deliberately NOT asserted here while parallel workstreams are still
landing; see the module docstring of scripts/consistency_check.py.

Ported in spirit from AgriciDaniel/claude-seo (MIT) tests/test_consistency_check.py
(upstream asserted the repo-wide gate directly; its CRLF lock and extension-agent
cases are kept here as fixture tests).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "consistency_check.py"
sys.path.insert(0, str(REPO / "scripts"))

import consistency_check as cc  # noqa: E402


def _write(root: Path, rel: str, text: str = "", *, binary: bytes | None = None) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary is not None:
        path.write_bytes(binary)
    else:
        path.write_text(text, encoding="utf-8")


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    """A clean miniature plugin tree; tests add defects to it."""
    root = tmp_path / "plugin"
    files = {
        "skills/seo/SKILL.md": "Commands: `/seo audit <url>` and `/seo page <url>`.\n"
                               "See references/shared-guide.md.\n",
        "skills/seo/references/shared-guide.md": "Shared guide.\n",
        "skills/seo-audit/SKILL.md": (
            "# Audit\n\n4. **Delegate to subagents**:\n"
            "   - `seo-technical` -- crawlability\n"
            "   - `seo-content` -- quality\n"
            "Run `python3 scripts/fetch_page.py <url>`.\n"
        ),
        "skills/seo-page/SKILL.md": "Run `python3 scripts/fetch_page.py <url>`; "
                                    "load references/page-notes.md.\n",
        "skills/seo-page/references/page-notes.md": "Notes.\n",
        "skills/geo-prospect/SKILL.md": "Use `/geo prospect list` to see the pipeline.\n",
        "docs/COMMANDS.md": "| `/seo audit` | full |\n| `/seo page` | one |\n",
        "agents/seo-technical.md": "Run `python3 scripts/fetch_page.py`. shared-guide.md\n",
        "agents/seo-content.md": "Content agent. page-notes.md\n",
        "scripts/fetch_page.py": "# fetch_page.py helper\n",
        "extensions/banana/skills/seo-image-gen/SKILL.md":
            "Run `python3 scripts/generate.py` from the extension.\n",
        "extensions/banana/scripts/generate.py": "# generate.py\n",
        "extensions/banana/install.sh": "cp agents/seo-image-gen.md ~/.claude/agents/\n",
        "extensions/banana/agents/seo-image-gen.md": "Image agent.\n",
    }
    for rel, text in files.items():
        _write(root, rel, text)
    monkeypatch.setattr(cc, "REPO", str(root))
    cc.clear_cache()
    yield root
    cc.clear_cache()


def _files(root: Path) -> list[str]:
    return cc._walk_files(str(root))


def _run(root: Path) -> dict:
    cc.clear_cache()
    return cc.run(_files(root))


# ---------------------------------------------------------------------------
# Clean tree and end-to-end CLI
# ---------------------------------------------------------------------------


def test_clean_fixture_tree_passes(tree):
    result = _run(tree)
    assert result["errors"] == [], result["errors"]
    assert result["status"] == "PASS"
    assert result["files_checked"] == len(_files(tree))


def test_cli_root_option_scans_a_non_git_tree_and_exits_by_status(tree):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    ok = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tree), "--json"],
                        capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["status"] == "PASS"

    _write(tree, "agents/seo-schema.md", "Run `python3 scripts/missing_tool.py`.\n")
    bad = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tree), "--json"],
                         capture_output=True, text=True, env=env)
    assert bad.returncode == 1
    payload = json.loads(bad.stdout)
    assert payload["status"] == "FAIL"
    assert any("missing_tool.py" in e for e in payload["errors"])


def test_strict_mode_fails_on_warnings_only(tree):
    _write(tree, "skills/seo-page/references/unused-orphan.md", "nobody links here\n")
    cc.clear_cache()
    lenient = cc.run(_files(tree))
    cc.clear_cache()
    strict = cc.run(_files(tree), strict=True)
    assert lenient["errors"] == [] and lenient["status"] == "PASS"
    assert any("unused-orphan.md" in w for w in strict["warnings"])
    assert strict["status"] == "FAIL"


# ---------------------------------------------------------------------------
# references/, scripts/, agents/ resolution
# ---------------------------------------------------------------------------


def test_dead_reference_is_an_error_and_cross_skill_hit_is_info(tree):
    _write(tree, "skills/seo-content/SKILL.md",
           "Load references/page-notes.md and references/nowhere.md.\n")
    result = _run(tree)
    assert "skills/seo-content/SKILL.md: dead reference references/nowhere.md" in result["errors"]
    assert any("references/page-notes.md resolves cross-skill" in i for i in result["info"])


def test_script_refs_are_path_aware(tree):
    # A core skill naming an extension-only script is dead even though a file
    # with that basename exists under extensions/banana/scripts/.
    _write(tree, "skills/seo-image-gen/SKILL.md", "Run `python3 scripts/generate.py`.\n")
    # A path-qualified mention is not a bare scripts/ reference.
    _write(tree, "skills/seo-schema/SKILL.md",
           "See extensions/banana/scripts/generate.py for the fallback.\n")
    errors = _run(tree)["errors"]
    assert any(e.startswith("skills/seo-image-gen/SKILL.md: dead script ref scripts/generate.py")
               for e in errors)
    assert not any(e.startswith("skills/seo-schema/SKILL.md") for e in errors)
    # The extension's own skill resolves against its own scripts/ dir.
    assert not any(e.startswith("extensions/banana/skills/") for e in errors)


def test_historical_carriers_are_exempt_from_dead_ref_checks(tree):
    text = ("Planned: `python3 scripts/not_built_yet.py`, agents/seo-future.md, "
            "and `/geo someday`.\n")
    for rel in ("docs/superpowers/plans/plan.md", "CHANGELOG.md", "research/notes.md",
                "docs/reference/MERGE_SPEC_x.md"):
        _write(tree, rel, text)
    errors = _run(tree)["errors"]
    assert errors == [], errors


def test_agent_refs_resolve_inside_an_extension_tree(tree):
    files = ["agents/seo-technical.md", "extensions/banana/agents/seo-image-gen.md"]
    assert cc.check_agent_refs(files, ["extensions/banana/install.sh"]) == []


def test_agent_refs_still_catch_a_genuinely_missing_agent(tree):
    _write(tree, "docs/COMMANDS.md",
           "| `/seo audit` | full |\n| `/seo page` | one |\nsee agents/seo-nonexistent.md\n")
    errors = _run(tree)["errors"]
    assert "docs/COMMANDS.md: dead agent ref agents/seo-nonexistent.md" in errors


# ---------------------------------------------------------------------------
# Invocation style (fork-specific inversion of upstream's launcher rule)
# ---------------------------------------------------------------------------


def test_launcher_and_interpreter_dependent_invocations_are_errors(tree):
    _write(tree, "agents/seo-schema.md",
           '"${CLAUDE_PLUGIN_ROOT}/scripts/claude-seo" run fetch_page.py <URL> --json\n'
           "python scripts/fetch_page.py <URL>\n"
           "py -3 scripts/fetch_page.py <URL>\n")
    errors = _run(tree)["errors"]
    joined = "\n".join(errors)
    assert "launcher invocation not supported" in joined
    assert joined.count("interpreter-dependent invocation") == 2


def test_python3_relative_invocation_is_the_accepted_form(tree):
    _write(tree, "agents/seo-schema.md",
           "python3 scripts/fetch_page.py <URL>\npython3 -m pytest tests/\n")
    assert _run(tree)["errors"] == []


# ---------------------------------------------------------------------------
# Routing: /seo tables and /geo commands
# ---------------------------------------------------------------------------


def test_routing_tables_must_agree_with_each_other_and_with_skill_dirs(tree):
    _write(tree, "skills/seo/SKILL.md",
           "`/seo audit` `/seo page` `/seo keywords` references/shared-guide.md\n")
    errors = _run(tree)["errors"]
    assert "routing: `/seo keywords` in orchestrator but not docs/COMMANDS.md" in errors
    assert "routing: `/seo keywords` has no matching skill directory" in errors


def test_extension_skill_satisfies_routing(tree):
    _write(tree, "skills/seo/SKILL.md",
           "`/seo audit` `/seo page` `/seo image-gen` references/shared-guide.md\n")
    _write(tree, "docs/COMMANDS.md", "`/seo audit` `/seo page` `/seo image-gen`\n")
    assert _run(tree)["errors"] == []


def test_dead_geo_command_is_flagged_and_prose_slashes_are_ignored(tree):
    _write(tree, "skills/geo-proposal/SKILL.md",
           "If not, suggest running `/geo quick <domain>` first. Then `/geo prospect list`.\n"
           "Find one specific to the client's industry/geo and cite it.\n")
    errors = _run(tree)["errors"]
    assert errors == ["skills/geo-proposal/SKILL.md: dead command `/geo quick` "
                      "(no skills/geo-quick/)"]


# ---------------------------------------------------------------------------
# Audit delegation (fork addition)
# ---------------------------------------------------------------------------


def test_audit_delegate_without_agent_warns_or_errors(tree):
    _write(tree, "skills/seo-audit/SKILL.md",
           "   - `seo-technical` -- crawl\n"
           "   - `seo-images` -- alt text\n"
           "   - `seo-ghost` -- nothing\n")
    _write(tree, "skills/seo-images/SKILL.md", "Image skill.\n")
    result = _run(tree)
    assert any("`seo-images` but no agents/seo-images.md" in w for w in result["warnings"])
    assert any("`seo-ghost`, which is neither an agent nor a skill" in e
               for e in result["errors"])
    assert not any("seo-technical" in m for m in result["errors"] + result["warnings"])


def test_audit_delegates_parser_reads_only_list_items():
    text = ("Spawn `seo-geo` later.\n"
            "   - `seo-technical` -- robots.txt\n"
            "   - `geo-ai-visibility` -- AEO\n")
    assert cc.audit_delegates(text) == ["geo-ai-visibility", "seo-technical"]


# ---------------------------------------------------------------------------
# FLOW lock integrity
# ---------------------------------------------------------------------------


def _lock_fixture(root: Path) -> list[str]:
    rels = ["skills/seo-flow/references/prompts/find/one.md",
            "skills/seo-flow/references/flow-framework.md"]
    lines = ["# lock"]
    for i, rel in enumerate(rels):
        data = f"prompt {i}\nline two\n".encode()
        _write(root, rel, binary=data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {rel}")
    _write(root, cc.LOCK_PATH, "\n".join(lines) + "\n")
    return rels


def test_flow_lock_accepts_crlf_checkout(tree):
    rels = _lock_fixture(tree)
    for rel in rels:
        path = tree / rel
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    cc.clear_cache()
    assert cc.check_flow_lock(set(_files(tree))) == []


def test_flow_lock_detects_tampering_missing_and_unlocked_files(tree):
    rels = _lock_fixture(tree)
    with open(tree / rels[0], "ab") as fh:
        fh.write(b"tampered\r\n")
    (tree / rels[1]).unlink()
    _write(tree, "skills/seo-flow/references/prompts/win/new.md", "unlocked\n")
    cc.clear_cache()
    errors = cc.check_flow_lock(set(_files(tree)))
    assert errors == [
        f"flow lock: hash mismatch {rels[0]}",
        f"flow lock: missing {rels[1]}",
        "flow lock: unlocked prompt file skills/seo-flow/references/prompts/win/new.md",
    ]


# ---------------------------------------------------------------------------
# Orphans
# ---------------------------------------------------------------------------


def test_orphan_scripts_and_files_are_warnings_not_errors(tree):
    _write(tree, "scripts/lonely_tool.py", "# lonely_tool.py\n")
    _write(tree, "data/forgotten.json", "{}")
    result = _run(tree)
    assert result["errors"] == []
    assert "scripts/lonely_tool.py: referenced nowhere outside itself" in result["warnings"]
    assert "orphan candidate: data/forgotten.json" in result["warnings"]


def test_read_cache_is_scoped_to_the_scanned_root(tmp_path, monkeypatch):
    first, second = tmp_path / "a", tmp_path / "b"
    _write(first, "x.md", "first")
    _write(second, "x.md", "second")
    monkeypatch.setattr(cc, "REPO", str(first))
    assert cc.read("x.md") == "first"
    monkeypatch.setattr(cc, "REPO", str(second))
    assert cc.read("x.md") == "second"
    cc.clear_cache()


def test_command_alias_resolves_only_when_target_skill_exists(tmp_path):
    """`/seo rank` is served by seo-track; the alias must not mask a missing target."""
    files_ok = ["skills/seo/SKILL.md", "docs/COMMANDS.md", "skills/seo-track/SKILL.md"]
    files_missing = ["skills/seo/SKILL.md", "docs/COMMANDS.md"]
    doc = "`/seo rank example.com`\n"
    original = cc.read
    try:
        cc.read = lambda _p: doc  # both routing tables mention /seo rank
        assert cc.check_routing(files_ok) == []
        errs = cc.check_routing(files_missing)
        assert any("alias `/seo rank` -> seo-track" in e for e in errs)
    finally:
        cc.read = original


def test_runtime_utility_commands_are_not_routing_errors():
    original = cc.read
    try:
        cc.read = lambda _p: "`/seo growth x` `/seo project init x` `/seo preflight x`\n"
        assert cc.check_routing(["skills/seo/SKILL.md", "docs/COMMANDS.md"]) == []
    finally:
        cc.read = original


def test_repository_has_no_consistency_errors():
    """Repo-wide gate: no dead script/agent/reference paths, no unroutable
    commands, no `/geo <cmd>` pointing at a removed skill.

    --include-untracked so the gate also holds in a working tree before the
    new files are committed; in CI (clean checkout) it is identical.
    """
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / "consistency_check.py"), "--json",
         "--include-untracked"],
        capture_output=True, text=True, cwd=repo,
    )
    result = json.loads(proc.stdout)
    assert result["errors"] == [], "\n".join(result["errors"])
    assert result["status"] == "PASS" and proc.returncode == 0
