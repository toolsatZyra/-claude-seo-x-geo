#!/usr/bin/env python3
"""Remove one MCP server entry from a Claude Code JSON config file, safely.

Used by the extension uninstallers (for ``~/.claude.json``) and by the
installers and uninstallers to clean up after older releases.

Why the legacy cleanup exists
=============================
Before the upstream v2.3.0 fix (#204, ported in ZYRA v3.1), the dataforseo,
firecrawl, ahrefs and banana installers wrote ``mcpServers.<name>``, including
the API credential, into ``~/.claude/settings.json``. Claude Code does not
read MCP servers from that file, so the server never loaded, but the secret
stayed on disk. The installers now write ``~/.claude.json`` (the file
``claude mcp add`` writes); this helper removes the stale copy.

Safety contract
===============
- Only ``mcpServers.<name>`` is removed. Nothing else in the file changes
  (an emptied ``mcpServers`` object is dropped).
- A file that does not parse, or whose root or ``mcpServers`` is not a JSON
  object, is never rewritten: the helper reports it and exits 0, so an
  uninstall can never destroy a user's configuration.
- The write is atomic (temp file in the same directory, then ``os.replace``)
  and keeps the file's permission bits; a symlinked config is updated at its
  target, not replaced by a regular file.
- No secret is read from argv or printed.

Usage::

    python3 mcp_config_cleanup.py <server-name> [--file PATH] [--json]

``--file`` defaults to the legacy ``~/.claude/settings.json``. Exit status is
0 whether or not anything was removed; 2 for a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def legacy_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def remove_server(path: str | os.PathLike, name: str) -> dict:
    """Remove ``mcpServers[name]`` from the JSON file at ``path``.

    Returns ``{"status": ..., "file": ..., "server": ...}`` where status is one
    of ``removed``, ``absent`` (file or entry missing), or ``skipped``
    (unreadable / unparseable / unexpected shape: the file was left alone).
    """
    if not _NAME_RE.match(name or ""):
        raise ValueError(f"invalid MCP server name: {name!r}")
    target = Path(path)
    result = {"status": "absent", "file": str(target), "server": name}
    if not target.is_file():
        return result

    real = Path(os.path.realpath(target))
    try:
        raw = real.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        result["status"] = "skipped"
        result["reason"] = f"could not parse ({type(exc).__name__}); file left untouched"
        return result
    if not isinstance(data, dict):
        result["status"] = "skipped"
        result["reason"] = "root is not a JSON object; file left untouched"
        return result
    servers = data.get("mcpServers")
    if servers is None:
        return result
    if not isinstance(servers, dict):
        result["status"] = "skipped"
        result["reason"] = "mcpServers is not a JSON object; file left untouched"
        return result
    if name not in servers:
        return result

    del servers[name]
    if not servers:
        del data["mcpServers"]

    try:
        mode = real.stat().st_mode & 0o777
        fd, tmp = tempfile.mkstemp(dir=str(real.parent), prefix=f".{real.name}.", suffix=".tmp")
    except OSError as exc:
        result["status"] = "skipped"
        result["reason"] = f"could not write ({type(exc).__name__}); file left untouched"
        return result
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(exc, OSError):
            result["status"] = "skipped"
            result["reason"] = f"could not write ({type(exc).__name__}); file left untouched"
            return result
        raise
    result["status"] = "removed"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Remove one MCP server entry from a Claude Code JSON config file."
    )
    parser.add_argument("server", help="MCP server name, e.g. dataforseo")
    parser.add_argument(
        "--file",
        default=None,
        help="Config file to clean (default: the legacy ~/.claude/settings.json)",
    )
    parser.add_argument("--json", action="store_true", help="Emit a JSON result")
    args = parser.parse_args(argv)

    path = Path(args.file).expanduser() if args.file else legacy_settings_path()
    try:
        result = remove_server(path, args.server)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    elif result["status"] == "removed":
        print(f"  Removed mcpServers.{args.server} from {path}")
    elif result["status"] == "skipped":
        print(
            f"  Note: {path} was not changed ({result['reason']}). "
            f"Remove any mcpServers.{args.server} entry by hand.",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
