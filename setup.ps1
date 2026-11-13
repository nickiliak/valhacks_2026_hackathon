# Run from repo root:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + "$env:USERPROFILE\.local\bin"
}

Refresh-Path
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing uv...'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    } else {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
    Refresh-Path
}

uv sync
if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }
uv run python --version
Write-Host 'Done. Use "uv run python ..." or select .venv as the interpreter in VS Code.'
