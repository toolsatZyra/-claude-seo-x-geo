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
