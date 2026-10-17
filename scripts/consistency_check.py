#!/usr/bin/env python3
"""Repository consistency checker: dead references, orphans, routing, lock integrity.

Complements tests/test_manifest_consistency.py (counts and version triangulation) with
reference-graph checks that no other tool covers:

1. ``references/X`` mentions in SKILL.md and agent files resolve via the fallback chain
   own dir -> shared ``skills/seo/references/`` -> any skill's references dir (cross-skill
   resolutions are reported as info, dead ones as errors).
2. ``research/X.md`` path mentions exist.
3. ``scripts/X.py`` mentions resolve PATH-AWARE: repo-root ``scripts/`` first, then the
   enclosing extension's ``scripts/`` dir for files under ``extensions/<name>/``. A bare
   basename existing somewhere else in the tree does NOT count.
4. Script invocations in instruction files (skills, agents, extensions) use this fork's
   canonical form, ``python3 scripts/<name>.py`` run from the plugin root. The upstream
   managed-runtime launcher (``scripts/claude-seo run <name>.py``) is not shipped here,
   and ``python``/``py -3`` are interpreter-dependent, so both are errors.
5. Routing tables in ``skills/seo/SKILL.md`` and ``docs/COMMANDS.md`` agree with each
   other and with the skill directories on disk (``/seo <cmd>``).
6. ``/geo <cmd>`` mentions resolve to a ``skills/geo-<cmd>/`` directory (fork addition:
   the grafted geo-* cluster has no routing table of its own).
7. ``agents/<name>.md`` path mentions exist in ``agents/`` or in any
   ``extensions/<ext>/agents/`` tree (``seo-newagent`` doc example whitelisted).
8. Subagents named in the ``skills/seo-audit/SKILL.md`` delegation list resolve to an
   agent file; a name that resolves only to a skill (runs inline) is a warning, a name
   that resolves to neither is an error (fork addition).
9. ``skills/seo-flow/references/flow-prompts.lock`` SHA-256 integrity (CRLF folded).
10. Orphan-file candidates (tracked files whose basename is mentioned nowhere else);
    reported as warnings, never errors.

Design and research notes (``docs/superpowers/``, the ``docs/reference/MERGE_SPEC*``
handoff), ``research/``, ``.github/`` and ``CHANGELOG.md`` are historical/example carriers: they may name commands, scripts and
agents that are planned or retired, so the dead-reference checks skip them.

Ported from AgriciDaniel/claude-seo (MIT) ``scripts/consistency_check.py`` (upstream
v2.2.3 through v2.4.x). Fork adaptations: check 4 inverted to this fork's invocation
style, checks 6 and 8 added, ``--root`` and ``--include-untracked`` added, the read cache
keyed by root so the checks can run against fixture trees.

Usage:
    python3 scripts/consistency_check.py [--json] [--strict]
    python3 scripts/consistency_check.py --include-untracked --json   # pre-commit view
    python3 scripts/consistency_check.py --root /path/to/checkout --json

Exit codes: 0 = no errors (warnings allowed unless --strict), 1 = errors found.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ORPHAN_SCRIPT_WHITELIST = {
    "portability_check.py", "agent_ux_check.py", "gbp_deprecation_lint.py",
    "release_sign.py", "verify_release.py", "consistency_check.py",
}
GENERIC_BASENAMES = {"README.md", "SKILL.md", "__init__.py", "LICENSE", "LICENSE.txt",
                     "plugin.json", "marketplace.json", "hooks.json"}
DOC_EXAMPLE_AGENTS = {"seo-newagent"}
LOCK_PATH = "skills/seo-flow/references/flow-prompts.lock"
AUDIT_SKILL = "skills/seo-audit/SKILL.md"
# Hub commands handled by the orchestrator itself (scripts, not a skill dir).
RUNTIME_UTILITY_COMMANDS: set[str] = {"growth", "preflight", "project"}
# `/seo <command>` -> skill directory, for commands whose name differs from
# the skill that serves them. Targets are verified to exist, so an alias can
# never outlive the skill it points at.
COMMAND_ALIASES: dict[str, str] = {
    "rank": "seo-track",
    "ai-visibility": "geo-share-of-voice",
}
SELF_DOC = {"scripts/consistency_check.py", "tests/test_consistency_check.py"}
# Carriers that may legitimately mention planned, retired or example paths.
HISTORICAL_PREFIXES = ("research/", ".github/", "docs/superpowers/", "docs/reference/MERGE_SPEC")
HISTORICAL_FILES = {"CHANGELOG.md"}
TEXT_SUFFIXES = (".md", ".json", ".yaml", ".yml", ".toml", ".py", ".sh", ".ps1",
                 ".cff", ".txt", ".html")

_CACHE: dict[tuple[str, str], str] = {}


def clear_cache() -> None:
    """Forget cached file contents (tests point REPO at fixture trees)."""
    _CACHE.clear()


def _is_historical(rel: str) -> bool:
    return rel.startswith(HISTORICAL_PREFIXES) or rel in HISTORICAL_FILES or rel in SELF_DOC


def _walk_files(root: str) -> list[str]:
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".venv", "node_modules"}]
        for name in names:
            out.append(os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/"))
    return sorted(out)


def tracked_files(include_untracked: bool = False) -> list[str]:
    """Files git tracks under REPO (plus untracked, unignored ones on request).

    Falls back to a filesystem walk when REPO is not a git work tree, which is
    how the fixture tests run.
    """
    cmd = ["git", "-C", REPO, "ls-files"]
    if include_untracked:
        cmd += ["--cached", "--others", "--exclude-standard"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return _walk_files(REPO)
    files = [line for line in proc.stdout.splitlines() if line.strip()]
    # A file deleted in the work tree but still in the index is not a live file.
    return sorted({f for f in files if os.path.exists(os.path.join(REPO, f))})


def read(rel: str) -> str:
    key = (REPO, rel)
    if key not in _CACHE:
        try:
            with open(os.path.join(REPO, rel), encoding="utf-8", errors="replace") as fh:
                _CACHE[key] = fh.read()
        except OSError:
            _CACHE[key] = ""
    return _CACHE[key]


def _exists(rel: str) -> bool:
    return os.path.exists(os.path.join(REPO, rel))


def extension_root(rel: str) -> str | None:
    m = re.match(r"(extensions/[^/]+)/", rel)
    return m.group(1) if m else None


def check_references(files, md):
    ref_pat = re.compile(r'references/([A-Za-z0-9_\-./]+\.(?:md|html|json|txt|ya?ml))')
    errors, infos = [], []
    carriers = [f for f in md if (f.startswith(("skills/", "extensions/")) and f.endswith("SKILL.md"))
                or f.startswith("agents/")]
    for f in carriers:
        base = os.path.dirname(f)
        for m in sorted(set(ref_pat.findall(read(f)))):
            candidates = [os.path.join(base, "references", m),
                          os.path.join("skills/seo/references", m)]
            if any(_exists(c) for c in candidates):
                continue
            hits = (glob.glob(os.path.join(REPO, "skills", "*", "references", m))
                    + glob.glob(os.path.join(REPO, "extensions", "*", "skills", "*", "references", m)))
            if hits:
                infos.append(f"{f}: references/{m} resolves cross-skill to "
                             f"{os.path.relpath(hits[0], REPO)}")
            else:
                errors.append(f"{f}: dead reference references/{m}")
    return errors, infos


def check_research_refs(files, texts):
    pat = re.compile(r'research/([A-Za-z0-9_\-]+\.md)')
    errors = []
    for f in texts:
        if _is_historical(f):
            continue
        for m in sorted(set(pat.findall(read(f)))):
            if not _exists(os.path.join("research", m)):
                errors.append(f"{f}: dead research ref research/{m}")
    return errors


def check_script_refs(files, texts):
    """Path-aware: scripts/X.py must exist at repo scripts/ or the enclosing extension's.

    The lookbehind skips path-qualified mentions such as
    ``extensions/banana/scripts/edit.py`` (checked via their own full path elsewhere).
    """
    pat = re.compile(r'(?<![\w/])scripts/([A-Za-z0-9_]+\.py)\b')
    errors = []
    for f in texts:
        if _is_historical(f):
            continue
        ext_root = extension_root(f)
        for m in sorted(set(pat.findall(read(f)))):
            candidates = [f"scripts/{m}"]
            if ext_root:
                candidates.insert(0, f"{ext_root}/scripts/{m}")
            if not any(c in files or _exists(c) for c in candidates):
                errors.append(f"{f}: dead script ref scripts/{m} "
                              f"(checked: {', '.join(candidates)})")
    orphans = []
    all_text = "\n".join(read(f) for f in texts)
    for s in sorted(os.path.basename(f) for f in files
                    if f.startswith("scripts/") and f.endswith(".py")):
        if s in ORPHAN_SCRIPT_WHITELIST:
            continue
        others = all_text.count(s) - read(f"scripts/{s}").count(s)
        if others <= 0:
            orphans.append(f"scripts/{s}: referenced nowhere outside itself")
    return errors, orphans


def check_skill_dir_script_refs(files, texts):
    """Validate scripts invoked through Claude's portable skill-root variable.

    Extension installers place their scripts beside the installed skill. In the
    source tree those scripts live at ``extensions/<name>/scripts``. Core skills
    must carry scripts inside their own skill directory before using this form.
    """
    pat = re.compile(r'\$\{CLAUDE_SKILL_DIR\}/scripts/([A-Za-z0-9_]+\.py)\b')
    errors = []
    for f in texts:
        for script in sorted(set(pat.findall(read(f)))):
            ext_root = extension_root(f)
            if ext_root:
                candidate = f"{ext_root}/scripts/{script}"
            elif f.startswith("skills/"):
                skill_root = "/".join(f.split("/")[:2])
                candidate = f"{skill_root}/scripts/{script}"
            else:
                errors.append(f"{f}: CLAUDE_SKILL_DIR script used outside a skill layout")
                continue
            if candidate not in files and not _exists(candidate):
                errors.append(
                    f"{f}: dead skill-root script {script} (checked: {candidate})"
                )
    return errors


def check_invocation_style(texts):
    """Instruction files must invoke bundled scripts as ``python3 scripts/<x>.py``.

    Upstream enforces the opposite (its managed launcher); this fork does not ship
    ``scripts/claude-seo``, so a launcher invocation can never run here.
    """
    errors = []
    carriers = [
        f for f in texts
        if f.startswith(("skills/", "agents/", "extensions/")) and f.endswith(".md")
    ]
    launcher = re.compile(r"(?:scripts/claude-seo[\"']?\s+run|\bclaude-seo[\"']?\s+run)\b[^\n`]*")
    interpreter = re.compile(
        r"(?<![\w./-])(?:python|py\s+-3)\s+(?:-[A-Za-z]+\s+)*[^\s`]*scripts/[A-Za-z0-9_./-]+\.py"
    )
    for f in carriers:
        content = read(f)
        for match in launcher.finditer(content):
            errors.append(f"{f}: launcher invocation not supported in this fork "
                          f"(use python3 scripts/<name>.py): {match.group(0).strip()}")
        for match in interpreter.finditer(content):
            errors.append(f"{f}: interpreter-dependent invocation (use python3): "
                          f"{match.group(0)}")
    return errors


def check_routing(files):
    cmd_pat = re.compile(r'`/seo(?:\s+([a-z][a-z0-9-]*))?')
    tables = {src: {m for m in cmd_pat.findall(read(src)) if m}
              for src in ("skills/seo/SKILL.md", "docs/COMMANDS.md")}
    skill_tokens = {d.split("/")[1][4:] for d in files
                    if d.startswith("skills/seo-") and d.endswith("SKILL.md")}
    ext_tokens = {p.split("/")[3][4:] for p in files
                  if re.match(r'extensions/[^/]+/skills/seo-[^/]+/SKILL\.md$', p)}
    known = skill_tokens | ext_tokens
    skill_dirs = {d.split("/")[1] for d in files
                  if d.startswith("skills/") and d.endswith("/SKILL.md")}
    a, b = tables["skills/seo/SKILL.md"], tables["docs/COMMANDS.md"]
    errors = []
    for cmd, target in sorted(COMMAND_ALIASES.items()):
        if target in skill_dirs:
            known = known | {cmd}
        elif cmd in (a | b):
            errors.append(f"routing: alias `/seo {cmd}` -> {target}, but skills/{target}/SKILL.md is missing")
    for c in sorted(a - b):
        errors.append(f"routing: `/seo {c}` in orchestrator but not docs/COMMANDS.md")
    for c in sorted(b - a):
        errors.append(f"routing: `/seo {c}` in docs/COMMANDS.md but not orchestrator")
    for c in sorted((a | b) - known - RUNTIME_UTILITY_COMMANDS):
        errors.append(f"routing: `/seo {c}` has no matching skill directory")
    return errors


def check_geo_commands(files, texts):
    """``/geo <cmd>`` mentions must name an existing ``skills/geo-<cmd>/`` skill."""
    pat = re.compile(r'`/geo\s+([a-z][a-z0-9-]*)')
    geo_skills = {f.split("/")[1][4:] for f in files
                  if re.match(r'skills/geo-[^/]+/SKILL\.md$', f)}
    geo_skills |= {f.split("/")[3][4:] for f in files
                   if re.match(r'extensions/[^/]+/skills/geo-[^/]+/SKILL\.md$', f)}
    errors = []
    for f in texts:
        if _is_historical(f) or not f.endswith(".md"):
            continue
        for cmd in sorted(set(pat.findall(read(f)))):
            if cmd not in geo_skills:
                errors.append(f"{f}: dead command `/geo {cmd}` (no skills/geo-{cmd}/)")
    return errors


def check_agent_refs(files, texts):
    """``agents/<name>.md`` mentions must resolve to a real agent file.

    Path-aware: an agent resolves against the repo-root ``agents/`` tree, and
    additionally against any extension's own ``extensions/<ext>/agents/`` tree,
    since extension installers copy those into ``~/.claude/agents/``.
    """
    agents = {os.path.basename(f)[:-3] for f in files
              if f.startswith("agents/") and f.endswith(".md")}
    ext_agents = {os.path.basename(f)[:-3] for f in files
                  if re.match(r'extensions/[^/]+/agents/[a-z0-9-]+\.md$', f)}
    known = agents | ext_agents
    pat = re.compile(r'agents/([a-z0-9-]+)\.md')
    errors = []
    for f in texts:
        if f.startswith("agents/") or _is_historical(f):
            continue
        for m in sorted(set(pat.findall(read(f)))):
            if m not in known and m not in DOC_EXAMPLE_AGENTS:
                errors.append(f"{f}: dead agent ref agents/{m}.md")
    return errors


def audit_delegates(text: str) -> list[str]:
    """Subagent names from the seo-audit delegation list (``   - `name` -- ...``)."""
    return sorted(set(re.findall(r"^\s*-\s+`((?:seo|geo)-[a-z0-9-]+)`\s+--", text, re.MULTILINE)))


def check_audit_delegation(files):
    errors, warnings = [], []
    if AUDIT_SKILL not in files and not _exists(AUDIT_SKILL):
        return errors, warnings
    agents = {os.path.basename(f)[:-3] for f in files
              if (f.startswith("agents/") or re.match(r"extensions/[^/]+/agents/", f))
              and f.endswith(".md")}
    skills = {f.split("/")[1] for f in files
              if re.match(r"skills/[^/]+/SKILL\.md$", f)}
    for name in audit_delegates(read(AUDIT_SKILL)):
        if name in agents:
            continue
        if name in skills:
            warnings.append(f"{AUDIT_SKILL}: audit delegates to `{name}` but no "
                            f"agents/{name}.md exists; it can only run inline")
        else:
            errors.append(f"{AUDIT_SKILL}: audit delegates to `{name}`, which is "
                          "neither an agent nor a skill")
    return errors, warnings


def _normalise_newlines(data: bytes) -> bytes:
    """Hash lock inputs as LF text so a CRLF checkout matches the baseline."""
    return data.replace(b"\r\n", b"\n")


def check_flow_lock(files):
    errors = []
    locked = {}
    for line in read(LOCK_PATH).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 2:
            locked[parts[1]] = parts[0]
    for rel, want in locked.items():
        full = os.path.join(REPO, rel)
        if not os.path.exists(full):
            errors.append(f"flow lock: missing {rel}")
            continue
        with open(full, "rb") as fh:
            got = hashlib.sha256(_normalise_newlines(fh.read())).hexdigest()
        if got != want:
            errors.append(f"flow lock: hash mismatch {rel}")
    extra = {f for f in files
             if f.startswith("skills/seo-flow/references/prompts/") and f.endswith(".md")} - set(locked)
    for rel in sorted(extra):
        errors.append(f"flow lock: unlocked prompt file {rel}")
    return errors


def check_orphan_files(files, texts):
    warnings = []
    prefixes = ("skills/", "docs/", "research/", "data/", "schema/")
    corpus = {f: read(f) for f in texts}
    for f in files:
        if not f.startswith(prefixes):
            continue
        base = os.path.basename(f)
        if base in GENERIC_BASENAMES or f.startswith("skills/seo-flow/references/prompts/"):
            continue
        if not any(base in c for other, c in corpus.items() if other != f):
            warnings.append(f"orphan candidate: {f}")
    return warnings


def run(files: list[str], strict: bool = False) -> dict:
    """Run every check over ``files`` (paths relative to REPO)."""
    fileset = set(files)
    md = [f for f in files if f.endswith(".md")]
    texts = [f for f in files if f.endswith(TEXT_SUFFIXES)]

    ref_errors, ref_infos = check_references(fileset, md)
    script_errors, script_orphans = check_script_refs(fileset, texts)
    audit_errors, audit_warnings = check_audit_delegation(fileset)
    errors = (ref_errors + check_research_refs(fileset, texts) + script_errors
              + check_skill_dir_script_refs(fileset, texts)
              + check_invocation_style(texts)
              + check_routing(fileset) + check_geo_commands(fileset, texts)
              + check_agent_refs(fileset, texts) + audit_errors
              + check_flow_lock(fileset))
    warnings = script_orphans + audit_warnings + check_orphan_files(fileset, texts)
    return {"errors": errors, "warnings": warnings, "info": ref_infos,
            "files_checked": len(files),
            "status": "FAIL" if errors or (strict and warnings) else "PASS"}


def main() -> int:
    global REPO
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    ap.add_argument("--include-untracked", action="store_true",
                    help="also scan untracked, unignored files (pre-commit view)")
    ap.add_argument("--root", help="checkout to scan (default: this repository)")
    args = ap.parse_args()

    if args.root:
        REPO = os.path.abspath(args.root)
        clear_cache()
    result = run(tracked_files(args.include_untracked), strict=args.strict)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for e in result["errors"]:
            print(f"ERROR: {e}")
        for w in result["warnings"]:
            print(f"WARN:  {w}")
        print(f"{result['status']}: {len(result['errors'])} errors, "
              f"{len(result['warnings'])} warnings, {len(result['info'])} cross-skill infos, "
              f"{result['files_checked']} files")
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
