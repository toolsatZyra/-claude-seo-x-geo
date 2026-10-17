"""extensions/mcp_config_cleanup.py and the uninstallers that use it.

Upstream v2.3.0 (#204) moved MCP server registration from
~/.claude/settings.json (a file Claude Code never reads MCP servers from) to
~/.claude.json. Older releases of this fork left the credential-bearing entry
in settings.json; the installers and uninstallers now remove that stale copy,
and the uninstallers rewrite ~/.claude.json atomically instead of truncating
it in place. Every test runs against a temporary HOME, never the real one.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "extensions" / "mcp_config_cleanup.py"
sys.path.insert(0, str(HELPER.parent))

import mcp_config_cleanup as cleanup  # noqa: E402

SERVERS = {
    "dataforseo": "dataforseo",
    "firecrawl": "firecrawl-mcp",
    "ahrefs": "ahrefs",
    "banana": "nanobanana-mcp",
}


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def test_removes_only_the_named_server(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.json"
    _write(cfg, {"theme": "dark", "env": {"A": "1"},
                 "mcpServers": {"dataforseo": {"env": {"DATAFORSEO_PASSWORD": "pw"}},
                                "mine": {"command": "x"}}})
    result = cleanup.remove_server(cfg, "dataforseo")
    assert result["status"] == "removed"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data == {"theme": "dark", "env": {"A": "1"}, "mcpServers": {"mine": {"command": "x"}}}
    assert "pw" not in cfg.read_text(encoding="utf-8")


def test_drops_an_emptied_mcp_servers_object(tmp_path: Path) -> None:
    cfg = tmp_path / "settings.json"
    _write(cfg, {"theme": "dark", "mcpServers": {"ahrefs": {}}})
    assert cleanup.remove_server(cfg, "ahrefs")["status"] == "removed"
    assert json.loads(cfg.read_text(encoding="utf-8")) == {"theme": "dark"}


@pytest.mark.parametrize(
    "content",
    ['{"mcpServers": {"dataforseo": {}}, oops', "[]", '"text"', '{"mcpServers": []}', "\xff\xfe"],
)
def test_never_rewrites_an_unparseable_or_unexpected_file(tmp_path: Path, content: str) -> None:
    cfg = tmp_path / "settings.json"
    cfg.write_bytes(content.encode("utf-8", errors="surrogateescape")
                    if content != "\xff\xfe" else b"\xff\xfe{")
    before = cfg.read_bytes()
    result = cleanup.remove_server(cfg, "dataforseo")
    assert result["status"] == "skipped"
    assert cfg.read_bytes() == before


def test_missing_file_or_entry_is_a_no_op(tmp_path: Path) -> None:
    assert cleanup.remove_server(tmp_path / "nope.json", "x")["status"] == "absent"
    cfg = tmp_path / "settings.json"
    _write(cfg, {"mcpServers": {"other": {}}})
    before = cfg.read_bytes()
    assert cleanup.remove_server(cfg, "dataforseo")["status"] == "absent"
    assert cfg.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits and symlinks")
def test_preserves_mode_and_updates_a_symlink_target(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "claude.json"
    _write(real, {"mcpServers": {"dataforseo": {}, "keep": {}}})
    os.chmod(real, 0o640)
    link = tmp_path / ".claude.json"
    link.symlink_to(real)
    assert cleanup.remove_server(link, "dataforseo")["status"] == "removed"
    assert link.is_symlink()
    assert stat.S_IMODE(real.stat().st_mode) == 0o640
    assert json.loads(real.read_text(encoding="utf-8")) == {"mcpServers": {"keep": {}}}
    assert not list(real.parent.glob(".claude.json.*.tmp"))


@pytest.mark.parametrize("bad", ["", "../x", "a b", "-rf", "x" * 80])
def test_rejects_unsafe_server_names(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        cleanup.remove_server(tmp_path / "settings.json", bad)


def test_cli_defaults_to_the_legacy_settings_file(tmp_path: Path) -> None:
    legacy = tmp_path / ".claude" / "settings.json"
    _write(legacy, {"mcpServers": {"firecrawl-mcp": {"env": {"FIRECRAWL_API_KEY": "k"}}}})
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    out = subprocess.run([sys.executable, str(HELPER), "firecrawl-mcp", "--json"],
                         env=env, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)["status"] == "removed"
    assert json.loads(legacy.read_text(encoding="utf-8")) == {}


def _run_uninstaller(tmp_path: Path, ext: str) -> subprocess.CompletedProcess:
    """Run a copy of the real uninstaller with HOME pointed at tmp_path."""
    tree = tmp_path / "repo" / "extensions"
    (tree / ext).mkdir(parents=True)
    shutil.copy2(ROOT / "extensions" / ext / "uninstall.sh", tree / ext / "uninstall.sh")
    shutil.copy2(HELPER, tree / "mcp_config_cleanup.py")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(home)}
    return subprocess.run(["bash", str(tree / ext / "uninstall.sh")],
                          env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("python3") is None,
                    reason="needs bash and python3")
@pytest.mark.parametrize("ext", sorted(SERVERS))
def test_uninstaller_removes_the_live_and_the_stale_entry(tmp_path: Path, ext: str) -> None:
    name = SERVERS[ext]
    home = tmp_path / "home"
    live = home / ".claude.json"
    legacy = home / ".claude" / "settings.json"
    _write(live, {"projects": {"/x": {"allowedTools": []}},
                  "mcpServers": {name: {"env": {"K": "secret"}}, "keep": {"command": "y"}}})
    _write(legacy, {"theme": "dark", "mcpServers": {name: {"env": {"K": "secret"}}}})
    result = _run_uninstaller(tmp_path, ext)
    assert result.returncode == 0, result.stderr
    assert json.loads(live.read_text(encoding="utf-8")) == {
        "projects": {"/x": {"allowedTools": []}}, "mcpServers": {"keep": {"command": "y"}}}
    assert json.loads(legacy.read_text(encoding="utf-8")) == {"theme": "dark"}


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("python3") is None,
                    reason="needs bash and python3")
@pytest.mark.parametrize("ext", sorted(SERVERS))
def test_uninstaller_leaves_a_malformed_claude_json_alone(tmp_path: Path, ext: str) -> None:
    home = tmp_path / "home"
    live = home / ".claude.json"
    original = '{"mcpServers": {"' + SERVERS[ext] + '": {}}, broken'
    _write(live, original)
    result = _run_uninstaller(tmp_path, ext)
    assert result.returncode == 0, result.stderr
    assert live.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("ext", sorted(SERVERS))
def test_installers_clean_the_stale_settings_entry(ext: str) -> None:
    text = (ROOT / "extensions" / ext / "install.sh").read_text(encoding="utf-8")
    assert "mcp_config_cleanup.py" in text
    assert f'python3 "${{LEGACY_CLEANUP}}" {SERVERS[ext]} || true' in text
    # The live entry goes to ~/.claude.json, never to settings.json.
    assert '"${HOME}/.claude.json"' in text
    assert 'SETTINGS_FILE="${HOME}/.claude/settings.json"' not in text


def test_gsc_mcp_registers_at_user_scope() -> None:
    sh = (ROOT / "extensions" / "gsc-mcp" / "install.sh").read_text(encoding="utf-8")
    ps1 = (ROOT / "extensions" / "gsc-mcp" / "install.ps1").read_text(encoding="utf-8")
    assert "claude mcp add --scope user gsc-mcp" in sh
    assert "claude mcp add --scope user gsc-mcp" in ps1

