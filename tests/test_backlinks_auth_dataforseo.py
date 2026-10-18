"""
DataForSEO detection reads the files Claude Code actually loads.

Before this fix, backlinks_auth reported "Tier 3, Premium (DataForSEO MCP)"
whenever ~/.claude/settings.json had mcpServers.dataforseo. Claude Code never
loads MCP servers from that file, so the server never ran. Detection now reads
~/.claude.json (user and project scopes), flags the settings.json copy as
stale, and resolves REST credentials (env first) without printing them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import backlinks_auth as ba  # noqa: E402

SECRET = "s3cr3t-pw-value"
ENTRY = {"command": "npx", "args": ["-y", "dataforseo-mcp-server"],
         "env": {"DATAFORSEO_USERNAME": "user@example.com", "DATAFORSEO_PASSWORD": SECRET}}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    claude_json = tmp_path / "claude.json"
    legacy = tmp_path / "settings.json"
    monkeypatch.setattr(ba, "CLAUDE_JSON_PATH", str(claude_json))
    monkeypatch.setattr(ba, "LEGACY_SETTINGS_PATHS", (str(legacy),))
    monkeypatch.setattr(ba, "load_config", lambda: {})
    monkeypatch.delenv("DATAFORSEO_USERNAME", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    return claude_json, legacy


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_settings_json_only_is_stale_not_configured(paths):
    _, legacy = paths
    _write(legacy, {"mcpServers": {"dataforseo": ENTRY}})
    status = ba.dataforseo_status()
    assert status["mcp_configured"] is False
    assert status["stale_config"] is True
    assert status["rest_credentials"] is False
    assert "install.sh" in status["fix"]
    assert ba.detect_tier()["tier"] == 0


def test_user_scope_entry_configures_mcp_and_rest(paths):
    claude_json, _ = paths
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY}})
    status = ba.dataforseo_status()
    assert status["mcp_configured"] and status["rest_credentials"]
    assert status["rest_credentials_source"] == "claude_json"
    assert status["fix"] is None
    assert ba.dataforseo_credentials() == ("user@example.com", SECRET, "claude_json")
    assert ba.detect_tier()["tier"] == 3


def test_project_scope_entry_counts(paths):
    claude_json, _ = paths
    _write(claude_json, {"projects": {"/work/site": {"mcpServers": {"dataforseo": ENTRY}}}})
    assert ba.dataforseo_status()["mcp_configured"] is True


def test_env_credentials_win(paths, monkeypatch):
    claude_json, _ = paths
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY}})
    monkeypatch.setenv("DATAFORSEO_USERNAME", "env-user")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "env-pass")
    assert ba.dataforseo_credentials() == ("env-user", "env-pass", "env")


def test_both_locations_flag_leftover_copy(paths):
    claude_json, legacy = paths
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY}})
    _write(legacy, {"mcpServers": {"dataforseo": ENTRY}})
    status = ba.dataforseo_status()
    assert status["mcp_configured"] and status["stale_config"]
    assert "mcp_config_cleanup.py dataforseo" in status["fix"]


def test_no_secret_in_status_or_check(paths):
    claude_json, _ = paths
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY}})
    assert SECRET not in json.dumps(ba.dataforseo_status())
    check = ba.check_credentials("dataforseo")
    assert check["available"] is True
    assert SECRET not in json.dumps(check)


def test_unreadable_claude_json_is_not_configured(paths):
    claude_json, _ = paths
    claude_json.write_text("{not json", encoding="utf-8")
    assert ba.dataforseo_status()["mcp_configured"] is False
    assert ba.dataforseo_credentials() is None


# ---- odd config shapes never crash the detector ----

ODD_SHAPES = [
    {"mcpServers": "x"}, {"mcpServers": ["dataforseo"]}, {"mcpServers": 5},
    {"mcpServers": {"dataforseo": "x"}}, {"mcpServers": {"dataforseo": ["a"]}},
    {"projects": "x"}, {"projects": ["a"]}, {"projects": {"/p": "x"}}, {"projects": {"/p": None}},
    {"projects": {"/p": {"mcpServers": "x"}}}, {"projects": {"/p": {"mcpServers": ["dataforseo"]}}},
    {"projects": {"/p": {"mcpServers": {"dataforseo": 3}}}}, [], "just a string", None,
]


@pytest.mark.parametrize("shape", ODD_SHAPES)
def test_odd_claude_json_shapes_do_not_crash(paths, shape):
    claude_json, legacy = paths
    _write(claude_json, shape)
    status = ba.dataforseo_status()
    assert status["mcp_configured"] is False and status["rest_credentials"] is False
    assert ba.dataforseo_credentials() is None
    assert ba.check_credentials("dataforseo")["available"] is False
    assert ba.detect_tier()["tier"] == 0


@pytest.mark.parametrize("env", ["x", ["a"], 5, None,
                                 {"DATAFORSEO_USERNAME": 5, "DATAFORSEO_PASSWORD": None}])
def test_a_server_entry_with_a_malformed_env_is_configured_but_has_no_credentials(paths, env):
    claude_json, _ = paths
    _write(claude_json, {"mcpServers": {"dataforseo": {"command": "npx", "env": env}}})
    status = ba.dataforseo_status()
    assert status["mcp_configured"] is True and status["rest_credentials"] is False
    assert ba.dataforseo_credentials() is None
    assert ba.detect_tier()["tier"] == 3


@pytest.mark.parametrize("shape", [{"mcpServers": "dataforseo"}, {"mcpServers": ["dataforseo"]},
                                   {"mcpServers": None}, {"mcpServers": 7}])
def test_odd_settings_json_shapes_are_not_a_stale_copy(paths, shape):
    _, legacy = paths
    _write(legacy, shape)
    assert ba.dataforseo_status()["stale_config"] is False  # only a dict with the key counts


# ---- project-scoped credentials are used only for the project you are in ----

def test_a_foreign_projects_credentials_are_ignored(paths, tmp_path):
    claude_json, _ = paths
    _write(claude_json, {"projects": {str(tmp_path / "other-client"): {"mcpServers": {"dataforseo": ENTRY}}}})
    here = tmp_path / "this-client"
    here.mkdir()
    assert ba.dataforseo_credentials(cwd=str(here)) is None
    status = ba.dataforseo_status()
    assert status["mcp_configured"] is True  # the MCP server exists, for that other project
    assert status["rest_credentials"] is False


def test_the_matching_project_scope_is_used(paths, tmp_path):
    claude_json, _ = paths
    project = tmp_path / "client"
    (project / "sub" / "dir").mkdir(parents=True)
    _write(claude_json, {"projects": {str(project): {"mcpServers": {"dataforseo": ENTRY}}}})
    for cwd in (project, project / "sub" / "dir"):
        assert ba.dataforseo_credentials(cwd=str(cwd)) == ("user@example.com", SECRET, "claude_json")


def test_a_sibling_directory_with_the_same_prefix_does_not_match(paths, tmp_path):
    claude_json, _ = paths
    (tmp_path / "site").mkdir()
    (tmp_path / "site-two").mkdir()
    _write(claude_json, {"projects": {str(tmp_path / "site"): {"mcpServers": {"dataforseo": ENTRY}}}})
    assert ba.dataforseo_credentials(cwd=str(tmp_path / "site-two")) is None


def test_user_scope_wins_over_a_matching_project_scope(paths, tmp_path):
    claude_json, _ = paths
    other = {"command": "npx", "env": {"DATAFORSEO_USERNAME": "proj@example.com",
                                       "DATAFORSEO_PASSWORD": "proj-pass"}}
    _write(claude_json, {"mcpServers": {"dataforseo": ENTRY},
                         "projects": {str(tmp_path): {"mcpServers": {"dataforseo": other}}}})
    assert ba.dataforseo_credentials(cwd=str(tmp_path))[0] == "user@example.com"


def test_the_deepest_matching_project_scope_wins(paths, tmp_path):
    claude_json, _ = paths
    inner = tmp_path / "mono" / "app"
    inner.mkdir(parents=True)
    deep = {"env": {"DATAFORSEO_USERNAME": "app@example.com", "DATAFORSEO_PASSWORD": "app-pass"}}
    _write(claude_json, {"projects": {str(tmp_path / "mono"): {"mcpServers": {"dataforseo": ENTRY}},
                                      str(inner): {"mcpServers": {"dataforseo": deep}}}})
    assert ba.dataforseo_credentials(cwd=str(inner))[0] == "app@example.com"


def test_default_cwd_is_the_process_directory(paths, tmp_path, monkeypatch):
    claude_json, _ = paths
    _write(claude_json, {"projects": {str(tmp_path): {"mcpServers": {"dataforseo": ENTRY}}}})
    monkeypatch.chdir(tmp_path)
    assert ba.dataforseo_credentials() is not None
    elsewhere = tmp_path.parent
    monkeypatch.chdir(elsewhere)
    assert ba.dataforseo_credentials() is None
