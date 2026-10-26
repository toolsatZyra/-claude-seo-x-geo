"""The Ahrefs extension is retired (2026-10-26).

It never worked: the installer wrote the key as AHREFS_API_TOKEN while the
archived 0.0.11 local package reads API_KEY. Ahrefs archived that package on
2026-02-24, and its hosted replacement needs a paid plan. The installers now
only explain the retirement, and the uninstaller cleans up the old setup
without touching a hosted Ahrefs connector a user added on their own.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extensions" / "ahrefs"
OLD_PACKAGE = "@ahrefs/" + "mcp@0.0.11"  # built from parts so this file never matches itself
HISTORY = ("CHANGELOG.md", "docs/MIGRATION-v1-to-v2.md", "docs/superpowers/",
           "extensions/ahrefs/docs/AHREFS-SETUP.md")


def _run(script: str, home: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(["bash", str(EXT / script)], env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)


def test_installer_only_explains_the_retirement(tmp_path: Path) -> None:
    (tmp_path / ".claude" / "skills" / "seo").mkdir(parents=True)
    result = _run("install.sh", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "retired" in result.stdout.lower()
    assert not (tmp_path / ".claude.json").exists()
    assert not (tmp_path / ".claude" / "skills" / "seo-ahrefs").exists()


def test_windows_installer_writes_nothing() -> None:
    text = (EXT / "install.ps1").read_text(encoding="utf-8")
    assert "retired" in text.lower()
    for writer in ("Move-Item", "WriteAllText", "Copy-Item", "Set-Content", "ConvertTo-Json", "npx"):
        assert writer not in text, f"install.ps1 still contains {writer}"


def test_no_seo_ahrefs_skill_ships() -> None:
    assert not (EXT / "skills").exists()


def _home_with(tmp_path: Path, server: dict) -> Path:
    (tmp_path / ".claude" / "skills" / "seo-ahrefs").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "seo-ahrefs" / "SKILL.md").write_text("old", encoding="utf-8")
    (tmp_path / ".claude.json").write_text(json.dumps({"theme": "dark", "mcpServers": {"ahrefs": server}}),
                                           encoding="utf-8")
    return tmp_path


def test_uninstaller_removes_the_old_local_entry_and_skill(tmp_path: Path) -> None:
    legacy = {"command": "npx", "args": ["--yes", "--package=" + OLD_PACKAGE, "mcp"],
              "env": {"AHREFS_API_TOKEN": "x"}}
    home = _home_with(tmp_path, legacy)
    result = _run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr
    config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert "ahrefs" not in config.get("mcpServers", {})
    assert config["theme"] == "dark"
    assert not (home / ".claude" / "skills" / "seo-ahrefs").exists()


def test_uninstaller_keeps_a_hosted_ahrefs_connector(tmp_path: Path) -> None:
    hosted = {"type": "http", "url": "https://api.ahrefs.com/mcp/mcp"}
    home = _home_with(tmp_path, hosted)
    result = _run("uninstall.sh", home)
    assert result.returncode == 0, result.stderr
    config = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert config["mcpServers"]["ahrefs"] == hosted
    assert "kept" in result.stdout.lower()


@pytest.mark.parametrize("suffix", [".md", ".py", ".sh", ".ps1", ".json", ".yml", ".yaml", ".toml"])
def test_old_package_is_mentioned_only_in_history(suffix: str) -> None:
    hits = []
    for path in ROOT.rglob(f"*{suffix}"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith((".git/", ".venv/", "node_modules/")) or rel.startswith(HISTORY):
            continue
        if OLD_PACKAGE in path.read_text(encoding="utf-8", errors="ignore"):
            hits.append(rel)
    assert hits == [], f"live references to the archived package: {hits}"


def test_marketplace_lists_seven_extensions_without_ahrefs() -> None:
    data = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    texts = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "description" and isinstance(value, str) and "optional MCP extensions" in value:
                    texts.append(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    assert texts, "no extension sentence found in marketplace.json"
    for text in texts:
        assert "7 optional MCP extensions" in text
        sentence = text.split("optional MCP extensions", 1)[1].split(")", 1)[0]
        assert "Ahrefs" not in sentence
