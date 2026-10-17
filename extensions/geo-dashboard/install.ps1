# Claude SEO x GEO - optional CRM/report dashboard extension installer (Windows).
$ErrorActionPreference = "Stop"

$SkillDir = "$env:USERPROFILE\.claude\skills"
Write-Host "========================================"
Write-Host "  Claude SEO x GEO -- Dashboard extension"
Write-Host "========================================"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3 required."
    exit 1
}
if (-not (Test-Path "$SkillDir\seo")) {
    Write-Error "claude-seo base not installed."
    exit 1
}

$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# flask>=3.1.3 matches requirements.txt's security floor.
python -m pip install "flask>=3.1.3,<4.0.0" "rich>=13.0.0,<14.0.0"
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)." }

New-Item -ItemType Directory -Force -Path "$SkillDir\geo-dashboard" | Out-Null
Copy-Item "$SourceDir\skills\geo-dashboard\SKILL.md" "$SkillDir\geo-dashboard\SKILL.md"
# Copy directory contents (not the directory itself) so a reinstall updates
# files in place instead of nesting scripts\scripts.
New-Item -ItemType Directory -Force -Path "$SkillDir\geo-dashboard\scripts", "$SkillDir\geo-dashboard\templates" | Out-Null
Copy-Item -Recurse -Force "$SourceDir\scripts\*" "$SkillDir\geo-dashboard\scripts"
Copy-Item -Recurse -Force "$SourceDir\templates\*" "$SkillDir\geo-dashboard\templates"

Write-Host "Done. Try: python $SkillDir\geo-dashboard\scripts\crm_dashboard.py"
