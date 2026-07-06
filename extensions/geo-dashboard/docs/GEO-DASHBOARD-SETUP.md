# GEO Dashboard extension setup

Optional. Installs a Rich-based terminal dashboard for viewing
`geo-prospect`/`geo-proposal` CRM data and GEO audit reports.

## Install (macOS/Linux)

```bash
bash extensions/geo-dashboard/install.sh
```

## Install (Windows)

```powershell
extensions\geo-dashboard\install.ps1
```

## Uninstall

```bash
bash extensions/geo-dashboard/uninstall.sh
```

This extension is never required by any core skill — `flask` and `rich` are
only imported by files under `extensions/geo-dashboard/`.
