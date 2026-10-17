"""Banana script and reference paths must match how this fork installs them.

Adapted from AgriciDaniel/claude-seo (MIT) tests/test_banana_install_layout.py
(v2.2.6+). Upstream routes every Banana script through its managed launcher
(``"${CLAUDE_PLUGIN_ROOT}/scripts/claude-seo" run --extension banana ...``),
which this fork does not ship. Here the standalone extension invokes its
scripts as ``python3 "${CLAUDE_SKILL_DIR}/scripts/<name>.py"``, because
``extensions/banana/install.sh`` copies ``scripts/`` and ``references/`` beside
the installed SKILL.md. The core mirror (``skills/seo-image-gen``) ships no
Banana scripts, so it must never point at one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE_DIR = ROOT / "skills" / "seo-image-gen"
CORE_SKILL = CORE_DIR / "SKILL.md"
EXTENSION = ROOT / "extensions" / "banana"
EXTENSION_SKILL = EXTENSION / "skills" / "seo-image-gen" / "SKILL.md"

_LAUNCHER = re.compile(r"CLAUDE_PLUGIN_ROOT|claude-seo[\"']?\s+run\b")
_SKILL_DIR_SCRIPT = re.compile(r'python3 "\$\{CLAUDE_SKILL_DIR\}/scripts/([A-Za-z0-9_]+\.py)"')


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _core_texts() -> dict[Path, str]:
    paths = [CORE_SKILL, *sorted((CORE_DIR / "references").glob("*.md"))]
    return {p: _text(p) for p in paths}


def _extension_texts() -> dict[Path, str]:
    paths = [EXTENSION_SKILL, *sorted((EXTENSION / "references").glob("*.md"))]
    return {p: _text(p) for p in paths}


def test_core_image_skill_does_not_assume_banana_scripts_are_local():
    for path, text in _core_texts().items():
        assert "${CLAUDE_SKILL_DIR}/scripts/" not in text, path
        assert "extensions/banana/scripts/" not in text, path
        assert "~/.claude/skills/seo-image-gen/scripts/" not in text, path
        assert not re.search(r"(?<![\w/])scripts/[a-z_]+\.py", text), path


def test_no_banana_doc_uses_the_upstream_launcher():
    for path, text in {**_core_texts(), **_extension_texts()}.items():
        assert not _LAUNCHER.search(text), f"{path.relative_to(ROOT)} uses the upstream launcher"


def test_standalone_extension_invokes_every_script_from_the_installed_skill_dir():
    combined = "\n".join(_extension_texts().values())
    referenced = set(_SKILL_DIR_SCRIPT.findall(combined))
    assert referenced == {
        "batch.py",
        "cost_tracker.py",
        "generate.py",
        "presets.py",
        "setup_mcp.py",
    }
    for script in referenced:
        assert (EXTENSION / "scripts" / script).is_file(), script
    # No cwd-relative or hard-coded-home invocations left over from v2.2.0.
    assert not re.search(r"python3 scripts/", combined)
    assert "~/.claude/skills/seo-image-gen/scripts/" not in combined


def test_standalone_installer_copies_scripts_and_references_beside_skill_file():
    installer = _text(EXTENSION / "install.sh")
    assert 'mkdir -p "${SKILL_DIR}/scripts" "${SKILL_DIR}/references"' in installer
    assert 'cp "${SOURCE_DIR}/scripts/"*.py "${SKILL_DIR}/scripts/"' in installer
    assert 'cp "${SOURCE_DIR}/references/"*.md "${SKILL_DIR}/references/"' in installer


@pytest.mark.parametrize(
    "skill,ref_dir",
    [(CORE_SKILL, CORE_DIR / "references"),
     (EXTENSION_SKILL, EXTENSION / "references")],
    ids=["core", "extension"],
)
def test_every_reference_file_is_linked_from_its_skill(skill: Path, ref_dir: Path):
    text = _text(skill)
    missing = [p.name for p in sorted(ref_dir.glob("*.md")) if p.name not in text]
    assert not missing, f"{skill.relative_to(ROOT)} does not link {missing}"


def test_extension_skill_references_exist_in_both_layouts():
    """The top-level installer copies the extension SKILL.md over the core mirror's
    directory, so every reference it names must exist in both reference trees."""
    names = set(re.findall(r"references/([a-z0-9-]+\.md)", _text(EXTENSION_SKILL)))
    assert {"prompt-templates.md", "prompt-adaptation-safety.md"} <= names
    for name in names:
        assert (EXTENSION / "references" / name).is_file(), name
        assert (CORE_DIR / "references" / name).is_file(), name


def test_prompt_engineering_split_targets_exist():
    """The split moved templates and safety rephrasing out of prompt-engineering.md."""
    for ref_dir in (CORE_DIR / "references", EXTENSION / "references"):
        pe = _text(ref_dir / "prompt-engineering.md")
        for anchor in ("prompt-templates.md#proven-prompt-templates",
                       "prompt-adaptation-safety.md#safety-filter-rephrase-strategies",
                       "prompt-adaptation-safety.md#prompt-adaptation-rules",
                       "prompt-adaptation-safety.md#common-prompt-mistakes"):
            assert anchor in pe, (ref_dir, anchor)
            target, heading = anchor.split("#")
            headings = {
                re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
                for h in re.findall(r"^#+ (.+)$", _text(ref_dir / target), re.M)
            }
            assert heading in headings, (ref_dir / target, heading)
        assert "## Safety Filter Rephrase Strategies" not in pe
        assert "## Proven Prompt Templates" not in pe
