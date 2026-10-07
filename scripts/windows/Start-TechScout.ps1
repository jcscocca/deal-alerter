[CmdletBinding()]
param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$app = 'C:\ProgramData\DealAlerter\app'
# Install-TechScout copies this launcher beside the per-user settings and venv.
# Use that physical directory even when installation ran in a packaged desktop app.
$local = $PSScriptRoot
$python = Join-Path $local 'venv\Scripts\pythonw.exe'
$url = 'http://127.0.0.1:8768/'
$mutex = New-Object Threading.Mutex($false, 'Local\TechScout-Launcher')
$locked = $false
function Test-TechScout {
    try { $health = Invoke-RestMethod ($url+'health') -TimeoutSec 2; return $health.service -eq 'TechScout' -and $health.status -eq 'ok' }
    catch { return $false }
}
try {
    $locked = $mutex.WaitOne(15000)
    if (-not $locked) { throw 'TechScout is still starting. Try the shortcut again.' }
    if (-not (Test-TechScout)) {
        if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath (Join-Path $app 'alerters\techscout\dashboard.py'))) { throw 'Deploy the merged monitor package and run Install-TechScout.ps1 before starting TechScout.' }
        $logs = Join-Path $local 'logs'
        New-Item -ItemType Directory -Force -Path $logs | Out-Null
        $arguments = @('-m','alerters.techscout','--serve','--settings',('"'+(Join-Path $local 'settings.json')+'"'),'--output',('"'+(Join-Path $local 'reports')+'"'))
        Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $app -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'techscout.stdout.log') -RedirectStandardError (Join-Path $logs 'techscout.stderr.log') | Out-Null
        $ready = $false
        for ($attempt=0; $attempt -lt 20; $attempt++) {
            if (Test-TechScout) { $ready=$true; break }
            Start-Sleep -Milliseconds 500
        }
        if (-not $ready) { throw 'TechScout could not start. Inspect the TechScout logs in LocalAppData.' }
    }
    if ($OpenBrowser) { Start-Process $url }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
