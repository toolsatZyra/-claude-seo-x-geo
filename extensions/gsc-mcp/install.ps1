# Claude SEO x GEO — optional Google Search Console MCP extension installer (Windows).
$ErrorActionPreference = "Stop"

$SkillDir = "$env:USERPROFILE\.claude\skills"
Write-Host "========================================"
Write-Host "  Claude SEO x GEO -- GSC-MCP extension"
Write-Host "========================================"
Write-Host "OAuth-free alternative to the native seo-google GSC integration."

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js required for the MCP server."
    exit 1
}
if (-not (Test-Path "$SkillDir\seo")) {
    Write-Error "claude-seo base not installed."
    exit 1
}
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Error "Claude Code CLI required (for 'claude mcp add')."
    exit 1
}

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GscMcpPackage = Read-Host "Path to your Google Search Console MCP server package (npm package name or local path)"
if ([string]::IsNullOrEmpty($GscMcpPackage)) {
    Write-Error "No package specified."
    exit 1
}

claude mcp add gsc-mcp -- npx -y $GscMcpPackage

New-Item -ItemType Directory -Force -Path "$SkillDir\seo-gsc-mcp" | Out-Null
Copy-Item "$SourceDir\skills\seo-gsc-mcp\SKILL.md" "$SkillDir\seo-gsc-mcp\SKILL.md"

Write-Host "Done. This extension does not replace seo-google's native GSC path."
Write-Host "Try: /seo gsc-mcp sites"
