# GSC-MCP extension setup

Optional. OAuth-free alternative to `seo-google`'s native Google Search
Console integration (`scripts/gsc_query.py`, `scripts/gsc_inspect.py`),
which remains this plugin's primary, test-covered GSC path.

Requires: Node.js, the Claude Code CLI, and a Google Search Console MCP
server package (you supply the package name/path during install — this
extension does not bundle a specific MCP server implementation).

## Install (macOS/Linux)

```bash
bash extensions/gsc-mcp/install.sh
```

## Install (Windows)

```powershell
extensions\gsc-mcp\install.ps1
```

## Uninstall

```bash
bash extensions/gsc-mcp/uninstall.sh
```

No core skill depends on this extension — `seo-google` continues to work
via native OAuth whether or not this extension is installed.
