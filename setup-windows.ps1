# Windows setup for PLaMo 3 Translate.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -All
#   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Model 0.8b -RegisterTask
param(
    [string[]]$Model = @(),
    [switch]$All,
    [switch]$RegisterTask
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

Write-Host "PLaMo 3 Translate - Windows setup" -ForegroundColor Cyan
Write-Host "Repo: $root"

# 1. Python runtime: uv is preferred, plain python works too.
$uv = Get-Command uv -ErrorAction SilentlyContinue
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $uv -and -not $py) {
    throw "Neither 'uv' nor 'python' is on PATH. Install uv from https://docs.astral.sh/uv/ or Python 3.10+."
}
if ($uv) { Write-Host "[ok] uv: $($uv.Source)" } else { Write-Host "[ok] python: $($py.Source)" }

# 2. llama.cpp backend. Builds older than b12182 do not know the plamo3 tokenizer.
$llama = Get-Command llama-server -ErrorAction SilentlyContinue
if (-not $llama) {
    $wingetDirs = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages\ggml.llamacpp_*\llama-server.exe'
    $llama = Get-ChildItem $wingetDirs -ErrorAction SilentlyContinue | Select-Object -First 1
}
if ($llama) {
    Write-Host "[ok] llama-server: $($llama.Source)"
} else {
    Write-Warning "llama-server not found. Install it with: winget install --id ggml.llamacpp -e"
    Write-Warning "Or set PLAMO_LLAMA_SERVER / pass --llama-server to manager.py."
}

# 3. Model weights (never committed to git).
$modelArgs = if ($All -or $Model.Count -eq 0) { @('--all', '--verify') } else { @($Model) + @('--verify') }
$fetchScript = Join-Path $root 'fetch-models.py'
if ($uv) {
    & uv run --no-project python $fetchScript @modelArgs
} else {
    & python $fetchScript @modelArgs
}
if ($LASTEXITCODE -ne 0) { throw "Model download failed." }

# 4. Optional persistence at logon.
if ($RegisterTask) {
    $wrap = Join-Path $root 'run-at-logon.bat'
    $action = New-ScheduledTaskAction -Execute $wrap
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName 'PLaMo 3 Translate' -Action $action -Trigger $trigger `
        -Principal $principal -Description 'Starts PLaMo 3 Translate (WebUI + API) at logon' -Force | Out-Null
    Start-ScheduledTask -TaskName 'PLaMo 3 Translate'
    Write-Host "[ok] Scheduled task 'PLaMo 3 Translate' registered and started." -ForegroundColor Green
}

Write-Host ""
Write-Host "Start manually:  & '$root\start-plamo.bat'" -ForegroundColor Green
Write-Host "Then open:       http://127.0.0.1:8000/" -ForegroundColor Green
