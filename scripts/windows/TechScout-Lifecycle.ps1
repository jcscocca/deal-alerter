# Shared maintenance helpers. Dot-sourcing defines functions and changes nothing.
function Get-TechScoutExpectedVersion([string]$Python,[string]$App) {
    $code = 'import sys; sys.path.insert(0,sys.argv[1]); from alerters.techscout.version import app_version; print(app_version())'
    $value = & $Python -c $code $App
    if ($LASTEXITCODE -ne 0 -or ($value -join '') -notmatch '^standout-v3-[a-f0-9]{20}$') { throw 'Installed TechScout version cannot be established; deploy the current package before launching.' }
    return ($value -join '').Trim()
}
function Get-TechScoutBackends([string]$Python,[string]$PackageApp,[string]$InstalledApp,[int[]]$ProcessIds=@()) {
    $helper = Join-Path $PackageApp 'scripts\windows\techscout_process.py'
    foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'")) {
        if ($ProcessIds.Count -and $process.ProcessId -notin $ProcessIds) { continue }
        if ($process.CommandLine -notmatch '(?i)(?:^|\s)-m\s+"?alerters\.techscout"?(?:\s|$)' -or $process.CommandLine -notmatch '(?:^|\s)--serve(?:\s|$)') { continue }
        $raw = & $Python $helper --pid $process.ProcessId --app $InstalledApp
        if ($LASTEXITCODE -ne 0) {
            if (-not (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) { continue }
            throw 'A TechScout process could not be scoped safely. Close it from its owning account before maintenance.'
        }
        $identity = ($raw -join '') | ConvertFrom-Json
        if (-not $identity.app_scope) { continue }
        if (-not $identity.recognized) { throw 'An installed-app TechScout process has an unrecognized executable or data path. Close it from its owning account.' }
        $owner = Invoke-CimMethod -InputObject $process -MethodName GetOwnerSid
        if ($owner.ReturnValue -ne 0 -or -not $owner.Sid) { throw 'TechScout process owner could not be established.' }
        $identity | Add-Member -NotePropertyName owner_sid -NotePropertyValue $owner.Sid
        $identity | Add-Member -NotePropertyName session_id -NotePropertyValue $process.SessionId
        $identity
    }
}
function Test-TechScoutBackendOwner($Backends,[string]$ExpectedUserSid,[string]$DataDirectory,[int]$StartedPid=0) {
    $proof = @($Backends)
    return ($proof.Count -eq 1 -and $ExpectedUserSid -ne 'S-1-5-18' -and $proof[0].owner_sid -eq $ExpectedUserSid -and $proof[0].data_directory -eq $DataDirectory -and $proof[0].session_id -ne 0 -and (-not $StartedPid -or $proof[0].pid -eq $StartedPid -or $proof[0].venv_wrapper_pid -eq $StartedPid))
}
function Stop-TechScoutBackends($Backends,[string]$Python,[string]$PackageApp,[string]$InstalledApp) {
    foreach ($backend in @($Backends | Sort-Object @{Expression={if ($_.venv_wrapper_pid) {0} else {1}}})) {
        $current = @(Get-TechScoutBackends $Python $PackageApp $InstalledApp -ProcessIds @([int]$backend.pid))
        if (-not $current.Count) { continue }
        if ($current.Count -ne 1 -or $current[0].owner_sid -ne $backend.owner_sid -or $current[0].data_directory -ne $backend.data_directory -or $current[0].executable -ne $backend.executable) { throw 'TechScout identity changed before stop; no process was terminated.' }
        Stop-Process -Id $backend.pid -Force
        for ($attempt=0; $attempt -lt 20; $attempt++) {
            if (-not (Get-Process -Id $backend.pid -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-Process -Id $backend.pid -ErrorAction SilentlyContinue) { throw 'Scoped TechScout backend did not stop.' }
    }
}
function Backup-TechScoutControls([string]$Runtime,[string]$Backup) {
    $destination = Join-Path $Backup 'ui'
    New-Item -ItemType Directory -Force -Path $destination | Out-Null
    $controls = Join-Path $Runtime 'ui\watches.json'
    if (Test-Path -LiteralPath $controls) {
        Copy-Item -LiteralPath $controls -Destination (Join-Path $destination 'watches.json')
    } else {
        [IO.File]::WriteAllText((Join-Path $destination 'watches.absent'), 'No preferences file existed before this upgrade.')
    }
}
function Restore-TechScoutControls([string]$Runtime,[string]$Backup) {
    $saved = Join-Path $Backup 'ui\watches.json'
    $absent = Join-Path $Backup 'ui\watches.absent'
    if ((Test-Path -LiteralPath $saved) -eq (Test-Path -LiteralPath $absent)) { throw 'Watch-preference backup is ambiguous or missing; rollback cannot proceed safely.' }
    $controls = Join-Path $Runtime 'ui\watches.json'
    if (Test-Path -LiteralPath $saved) {
        New-Item -ItemType Directory -Force -Path (Split-Path $controls) | Out-Null
        $temporary = $controls + '.restore-' + [Guid]::NewGuid().ToString('N')
        Copy-Item -LiteralPath $saved -Destination $temporary
        Move-Item -LiteralPath $temporary -Destination $controls -Force
    } elseif (Test-Path -LiteralPath $controls) {
        Remove-Item -LiteralPath $controls -Force
    }
}
function Test-MonitorReleaseAcceptance([string]$Runtime,[string]$Python,[string]$App,[string[]]$RequiredKinds=@('reddit','slickdeals','legacy'),[string[]]$Capabilities=@('watches-v3'),[switch]$RequireSourceCycle) {
    $health = Get-Content -Raw -LiteralPath (Join-Path $Runtime 'health.json') | ConvertFrom-Json
    if ($health.dry_run -or [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$health.heartbeat -ge 60) { throw 'Monitor acceptance requires a fresh non-preview heartbeat.' }
    $jobs = @($health.jobs.PSObject.Properties | ForEach-Object { $_.Value })
    $kinds = @($jobs | ForEach-Object { $_.kind } | Sort-Object -Unique)
    foreach ($kind in $RequiredKinds) { if ($kind -notin $kinds) { throw "Required monitor job is missing: $kind" } }
    if (@($kinds | Where-Object { $_ -notin @('reddit','slickdeals','legacy') }).Count) { throw 'Retired or unexpected monitor jobs remain active.' }
    if (@($jobs | Where-Object { $_.kind -eq 'legacy' -and $_.url -ne 'ebay' }).Count) { throw 'Unexpected legacy monitor source remains active.' }
    $shopping = Get-Content -Raw -LiteralPath (Join-Path $Runtime 'shopping-sources.json') | ConvertFrom-Json
    foreach ($capability in $Capabilities) { if ($capability -notin @($shopping.capabilities)) { throw "Shopping integration capability missing: $capability" } }
    $code = @'
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from alerters.hardware.shopping_controls import read_controls
settings,error=read_controls(Path(sys.argv[2])/'ui'/'watches.json')
print(json.dumps({'error':error,'version':settings['version'],'mode':settings['mode']}))
'@
    $raw = & $Python -c $code $App $Runtime
    if ($LASTEXITCODE -ne 0) { throw 'Watch-preference acceptance could not run.' }
    $controls = ($raw -join '') | ConvertFrom-Json
    if ($controls.error -or $controls.version -ne 3) { throw 'Watch preferences are invalid or incompatible with the installed application.' }
    $cycles = @($jobs | Where-Object { $_.last_success -ge $health.started -and $_.last_success -gt 0 }).Count
    if ($RequireSourceCycle -and -not $cycles) { throw 'No source has completed a real cycle in the current monitor process yet.' }
    return @{pid=$health.pid;job_kinds=$kinds;capabilities=@($shopping.capabilities);controls_version=$controls.version;controls_mode=$controls.mode;source_cycles=$cycles;source_cycle_status=$(if ($cycles) {'verified'} else {'pending'})}
}
