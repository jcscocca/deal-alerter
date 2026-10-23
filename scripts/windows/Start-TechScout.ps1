[CmdletBinding()]
param([switch]$OpenBrowser,[string]$DataDirectory='')
$ErrorActionPreference = 'Stop'
$app = 'C:\ProgramData\DealAlerter\app'
$runtime = Split-Path $app
$maintenance = Join-Path $runtime 'ui\upgrade-in-progress.json'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($identity.User.Value -eq 'S-1-5-18' -or $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or [Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0) { throw 'Start TechScout from the normal signed-in account, without administrator elevation or SYSTEM.' }
# Install-TechScout copies this launcher beside the per-user settings and venv.
$local = if ($DataDirectory) { [IO.Path]::GetFullPath($DataDirectory) } else { $PSScriptRoot }
$python = Join-Path $local 'venv\Scripts\pythonw.exe'
$consolePython = Join-Path $local 'venv\Scripts\python.exe'
$url = 'http://127.0.0.1:8768/'
if (Test-Path -LiteralPath $maintenance) { throw 'TechScout is paused for application maintenance. Restart it from this account after maintenance completes.' }
. (Join-Path $app 'scripts\windows\TechScout-Lifecycle.ps1')
$expected = Get-TechScoutExpectedVersion $consolePython $app
$mutex = New-Object Threading.Mutex($false, 'Local\TechScout-Launcher')
$locked = $false
function Get-TechScoutHealth {
    try { return Invoke-RestMethod ($url+'health') -TimeoutSec 2 } catch { return $null }
}
function Test-TechScoutHealth($Health) {
    return ($Health -and $Health.service -eq 'TechScout' -and $Health.status -eq 'ok' -and $Health.version -eq $expected -and $Health.watch_schema_version -eq 3 -and $Health.instance_id -and $Health.pid)
}
try {
    $locked = $mutex.WaitOne(15000)
    if (-not $locked) { throw 'TechScout is still starting. Try the shortcut again.' }
    if (Test-Path -LiteralPath $maintenance) { throw 'TechScout is paused for application maintenance.' }
    $health = Get-TechScoutHealth
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8768 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($listeners.Count) {
        $backends = @(Get-TechScoutBackends $consolePython $app $app -ProcessIds $listeners)
        $owned = @($backends | Where-Object { $_.owner_sid -eq $identity.User.Value -and $_.data_directory -eq $local })
        if ($owned.Count -ne 1 -or $backends.Count -ne 1 -or $listeners.Count -ne 1) { throw 'Port 8768 belongs to another or unrecognized process. No process was stopped; close the conflicting application from its owner account.' }
        if (-not (Test-TechScoutHealth $health) -or $health.pid -ne $owned[0].pid) {
            Stop-TechScoutBackends $owned $consolePython $app $app
            $health = $null
        }
    } else {
        $health = $null
    }
    if (-not (Test-TechScoutHealth $health)) {
        if (-not (Test-Path -LiteralPath $python)) { throw 'Run Install-TechScout.ps1 from this account before starting TechScout.' }
        if (Test-Path -LiteralPath $maintenance) { throw 'TechScout is paused for application maintenance.' }
        $logs = Join-Path $local 'logs'
        New-Item -ItemType Directory -Force -Path $logs | Out-Null
        $arguments = @('-m','alerters.techscout','--serve','--settings',('"'+(Join-Path $local 'settings.json')+'"'),'--output',('"'+(Join-Path $local 'reports')+'"'))
        $started = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $app -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'techscout.stdout.log') -RedirectStandardError (Join-Path $logs 'techscout.stderr.log') -PassThru
        $ready = $false
        for ($attempt=0; $attempt -lt 20; $attempt++) {
            $health = Get-TechScoutHealth
            if (Test-TechScoutHealth $health) {
                $proof = @(Get-TechScoutBackends $consolePython $app $app -ProcessIds @([int]$health.pid))
                if (Test-TechScoutBackendOwner $proof $identity.User.Value $local -StartedPid $started.Id) { $ready=$true; break }
            }
            Start-Sleep -Milliseconds 500
        }
        if (-not $ready) { throw 'The expected TechScout version could not start. Inspect the per-user TechScout logs.' }
    }
    if ($OpenBrowser) { Start-Process $url }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
