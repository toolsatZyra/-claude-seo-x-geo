# DataForSEO Extension Uninstaller for Claude SEO (Windows)

$ErrorActionPreference = "Stop"

Write-Host "-> Uninstalling DataForSEO extension..." -ForegroundColor Yellow

# Remove skill
if (Test-Path "$env:USERPROFILE\.claude\skills\seo-dataforseo") {
    Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\skills\seo-dataforseo"
}

# Remove agent
$agentFile = "$env:USERPROFILE\.claude\agents\seo-dataforseo.md"
if (Test-Path $agentFile) {
    Remove-Item -Force $agentFile
}

# Remove field config
$fieldConfig = "$env:USERPROFILE\.claude\skills\seo\dataforseo-field-config.json"
if (Test-Path $fieldConfig) {
    Remove-Item -Force $fieldConfig
}

# Remove the MCP server entry from ~/.claude.json (where Claude Code reads MCP
# servers). Native PowerShell, same pattern as firecrawl's uninstaller: the
# credential-bearing path is never interpolated into another language's source,
# and the write is atomic. A file that does not parse throws before anything
# is written, so a malformed ~/.claude.json is never replaced.
$McpConfigFile = "$env:USERPROFILE\.claude.json"
if (Test-Path $McpConfigFile) {
    try {
        $settings = Get-Content $McpConfigFile -Raw | ConvertFrom-Json
        if ($settings.mcpServers -and $settings.mcpServers.'dataforseo') {
            $settings.mcpServers.PSObject.Properties.Remove('dataforseo')
            # Write atomically: stage to a temp file in the same directory, then
            # swap it into place, so a crash mid-write never leaves
            # ~/.claude.json truncated or half-written.
            # -Depth 100 so an existing ~/.claude.json with deeply nested config
            # round-trips intact.
            $TempConfigFile = Join-Path (Split-Path -Parent $McpConfigFile) ".claude.json.$([guid]::NewGuid().ToString('N')).tmp"
            $jsonText = $settings | ConvertTo-Json -Depth 100
            # Write without a byte-order mark: Node's JSON.parse rejects a BOM.
            [System.IO.File]::WriteAllText($TempConfigFile, $jsonText, (New-Object System.Text.UTF8Encoding $false))
            Move-Item -Path $TempConfigFile -Destination $McpConfigFile -Force
            Write-Host "  [OK] Removed dataforseo from ~/.claude.json" -ForegroundColor Green
        } else {
            Write-Host "  [OK] No dataforseo entry in ~/.claude.json" -ForegroundColor Green
        }
    } catch {
        Write-Host "  [!]  Could not auto-remove MCP config ($($_.Exception.Message)). Remove 'dataforseo' from ~\.claude.json manually; it was not changed." -ForegroundColor Yellow
    }
}

# Older releases wrote the entry, with the credential, to ~/.claude/settings.json,
# which Claude Code never reads for MCP servers. Remove that stale copy when
# Python is available; the helper never rewrites a file that does not parse.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LegacyCleanup = Join-Path (Split-Path -Parent $ScriptDir) "mcp_config_cleanup.py"
$python = Get-Command -Name python -ErrorAction SilentlyContinue
if ($null -ne $python -and (Test-Path $LegacyCleanup)) {
    & $python.Source $LegacyCleanup dataforseo
} elseif (Test-Path "$env:USERPROFILE\.claude\settings.json") {
    Write-Host "  Note: if ~\.claude\settings.json still has an mcpServers.dataforseo entry, remove it by hand." -ForegroundColor Yellow
}

Write-Host "[OK] DataForSEO extension uninstalled." -ForegroundColor Green
