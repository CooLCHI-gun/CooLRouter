# CooLRouter — one-command local install (Windows / PowerShell).
#
#   ./deploy/install.ps1                  install into .\coolrouter-run and start it
#   ./deploy/install.ps1 -Startup         also register it to start at logon
#
# Idempotent: an existing .env is reused and a healthy instance is left alone.
param([switch]$Startup)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$run  = if ($env:COOLROUTER_HOME) { $env:COOLROUTER_HOME } else { Join-Path $root "coolrouter-run" }
$port = if ($env:COOLROUTER_PORT) { $env:COOLROUTER_PORT } else { 8000 }

$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "python not found on PATH — install Python 3.9+ first" }
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.9+ required" }

New-Item -ItemType Directory -Force -Path (Join-Path $run "logs") | Out-Null
Copy-Item (Join-Path $root "router\router-proxy.py") (Join-Path $run "router-proxy.py") -Force
$envFile = Join-Path $run ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root "deploy\.env.example") $envFile
    Write-Host "wrote $envFile — add your keys there"
}

$healthy = $false
try { $healthy = (Invoke-WebRequest "http://127.0.0.1:$port/healthz" -TimeoutSec 3).StatusCode -eq 200 } catch {}
if ($healthy) {
    Write-Host "already healthy on :$port"
} else {
    $p = Start-Process -FilePath $py -ArgumentList "-u", "router-proxy.py", "$port" `
         -WorkingDirectory $run -WindowStyle Hidden -PassThru `
         -RedirectStandardOutput (Join-Path $run "logs\router.out.log") `
         -RedirectStandardError  (Join-Path $run "logs\router.err.log")
    $p.Id | Set-Content (Join-Path $run "router.pid")
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        try { if ((Invoke-WebRequest "http://127.0.0.1:$port/healthz" -TimeoutSec 3).StatusCode -eq 200) { break } } catch {}
    }
    try { Invoke-WebRequest "http://127.0.0.1:$port/healthz" -TimeoutSec 3 | Out-Null }
    catch { throw "router did not come up — see $run\logs\router.err.log" }
    Write-Host "router listening on :$port (pid $($p.Id))"
}

(Invoke-RestMethod "http://127.0.0.1:$port/healthz") |
    Select-Object ok, ollama_up, local_gpu_ok, tiers | Format-List

if ($Startup) {
    $lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "coolrouter.lnk"
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = $py
    $s.Arguments = "-u router-proxy.py $port"
    $s.WorkingDirectory = $run
    $s.WindowStyle = 7
    $s.Save()
    Write-Host "registered at logon: $lnk"
}

Write-Host @"

Next: point any OpenAI-compatible client at it.

  Invoke-RestMethod http://127.0.0.1:$port/v1/chat/completions -Method Post ``
    -ContentType 'application/json' -Body '{"messages":[{"role":"user","content":"what is 2+2"}]}'
"@
