[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PreparedDirectory,
    [switch]$ApproveUpgrade,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'TechScout-Lifecycle.ps1')
function Invoke-WriterLockProbe([string]$Python,[string]$PackageApp,[string]$LockPath) {
    # Expected contention must not emit stderr: Windows PowerShell 5.1 promotes
    # native stderr to NativeCommandError under ErrorActionPreference=Stop.
    $code = @'
import sys
from pathlib import Path
try:
    sys.path.insert(0,sys.argv[1])
    from dealcore.locking import WriterLock
    with WriterLock(Path(sys.argv[2])):
        pass
except ValueError as exc:
    if str(exc) == 'Another hardware state writer is running':
        sys.exit(75)
    print(type(exc).__name__)
    sys.exit(2)
except Exception as exc:
    print(type(exc).__name__)
    sys.exit(2)
'@
    $diagnostic = & $Python -c $code $PackageApp $LockPath
    return @{exit_code=$LASTEXITCODE;diagnostic=($diagnostic -join ' ')}
}
function Wait-MonitorStopped($TaskNames,[int]$PreviousPid,[string]$Python,[string]$PackageApp,[string]$LockPath,[int]$Attempts=30,[int]$RetrySeconds=2) {
    for ($attempt=0; $attempt -lt $Attempts; $attempt++) {
        $probe = Invoke-WriterLockProbe $Python $PackageApp $LockPath
        if ($probe.exit_code -notin @(0,75)) { throw "Writer lock probe failed: $($probe.diagnostic) (exit $($probe.exit_code))." }
        $active = @(Get-ScheduledTask -TaskName $TaskNames | Where-Object { $_.State -in @('Running','Queued') })
        $oldProcess = Get-Process -Id $PreviousPid -ErrorAction SilentlyContinue
        if ($probe.exit_code -eq 0 -and -not $active -and -not $oldProcess) { return }
        Start-Sleep -Seconds $RetrySeconds
    }
    throw 'Hardware writer/tasks did not stop and release the lock; application was not replaced.'
}
function Start-EnabledMonitorTasks($Tasks,[string]$Runtime,[int]$PreviousPid) {
    $health = $null
    try {
        if ($Tasks['DealAlerter-Hardware'].enabled) {
            Enable-ScheduledTask -TaskName 'DealAlerter-Hardware' | Out-Null
            $healthy=$false
            for ($attempt=0; $attempt -lt 30; $attempt++) {
                $task = Get-ScheduledTask -TaskName 'DealAlerter-Hardware'
                if ($task.State -notin @('Running','Queued')) { Start-ScheduledTask -TaskName 'DealAlerter-Hardware' }
                Start-Sleep -Seconds 2
                $health = Get-Content -Raw -LiteralPath (Join-Path $Runtime 'health.json') | ConvertFrom-Json
                if ($health.pid -ne $PreviousPid -and [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$health.heartbeat -lt 60 -and -not $health.dry_run) {
                    $healthy=$true; break
                }
            }
            if (-not $healthy) { throw 'Enabled hardware task has no new process with a fresh heartbeat.' }
        }
    } finally {
        # Enabling early can itself fire a missed minute trigger. Keep watchdog
        # disabled through startup; restore it on both successful and failed starts.
        if ($Tasks['DealAlerter-Watchdog'].enabled) {
            Enable-ScheduledTask -TaskName 'DealAlerter-Watchdog' | Out-Null
            Start-ScheduledTask -TaskName 'DealAlerter-Watchdog'
        }
    }
    return $health
}
if (-not $ValidateOnly -and -not $ApproveUpgrade) { throw 'Apply requires -ApproveUpgrade.' }
$PreparedDirectory = (Get-Item -LiteralPath $PreparedDirectory).FullName
$release = Get-Content -Raw -LiteralPath (Join-Path $PreparedDirectory 'release.json') | ConvertFrom-Json
$runtime = [IO.Path]::GetFullPath($release.runtime)
if ($runtime -ne 'C:\ProgramData\DealAlerter') { throw 'This upgrade supports the existing DealAlerter runtime only.' }
$app = Join-Path $runtime 'app'
$state = Join-Path $runtime 'state'
$python = Join-Path $runtime 'venv\Scripts\python.exe'
$ownerPath = Join-Path $runtime 'owner.json'
$owner = Get-Content -Raw -LiteralPath $ownerPath | ConvertFrom-Json
if (-not $owner.approved -or $owner.hardware_writer -ne 'thinkpad' -or
    $owner.checkout -ne $app -or $owner.state_root -ne $state) { throw 'Installed owner manifest does not match this runtime.' }
foreach ($root in @($runtime, $PreparedDirectory)) {
    $items = @(Get-Item -LiteralPath $root) + @(Get-ChildItem -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue)
    if ($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Upgrade paths must not contain reparse points.' }
}
& git -C $release.checkout fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify current main.' }
$upstream = & git -C $release.checkout rev-parse origin/main
$pending = & git -C $release.checkout status --porcelain
$changes = & git -C $release.checkout diff --name-only HEAD origin/main -- . ':!state'
if ($LASTEXITCODE -ne 0 -or $pending -or $changes) { throw 'Prepare the clean merged application before upgrading.' }
$packageApp = Join-Path $PreparedDirectory 'app'
foreach ($property in $release.hashes.PSObject.Properties) {
    $source = [IO.Path]::GetFullPath((Join-Path $packageApp $property.Name))
    if (-not $source.StartsWith($packageApp + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Prepared path escapes application package.' }
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $property.Value) { throw "Prepared file changed: $($property.Name)" }
    $checkoutFile = Join-Path $release.checkout $property.Name
    if ((Get-FileHash -LiteralPath $checkoutFile -Algorithm SHA256).Hash -ne $property.Value) { throw "Package differs from merged checkout: $($property.Name)" }
}
# This maintenance release changes no dependencies. Refuse a future dependency
# migration rather than modifying the environment while a service is running.
foreach ($relative in @('requirements.txt','alerters\hardware\native\requirements.txt')) {
    if ((Get-FileHash -LiteralPath (Join-Path $app $relative)).Hash -ne
        (Get-FileHash -LiteralPath (Join-Path $packageApp $relative)).Hash) { throw 'Dependency changes need a separately prepared environment.' }
}
# A read-only token (this repository only, Variables: read) lets the gate check run
# over key-based SSH, where gh cannot read its own credential store. It is scoped
# to this one call and never printed; without the file, gh's own login is used.
$tokenFile = Join-Path $env:USERPROFILE '.deal-alerter\github-variables.token'
$savedToken = Test-Path -LiteralPath $tokenFile
if ($savedToken) { $env:GH_TOKEN = (Get-Content -Raw -LiteralPath $tokenFile).Trim() }
try {
    $variables = & gh api repos/jcscocca/deal-alerter/actions/variables
    $gateStatus = $LASTEXITCODE
} finally {
    if ($savedToken) { Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue }
}
if ($gateStatus -ne 0) {
    if ($savedToken) { throw "Cannot verify hardware writer gates with $tokenFile. If it expired or GitHub returned 401/403, regenerate the token and re-run the save command (jcscocca/deal-alerter only, Variables: read)." }
    throw "Cannot verify hardware writer gates. To deploy over SSH, save a read-only token (jcscocca/deal-alerter only, Variables: read) to $tokenFile."
}
$gates = @{}
foreach ($variable in ($variables | ConvertFrom-Json).variables) { $gates[$variable.name] = $variable.value }
if ($gates.HARDWARE_WRITER -ne 'thinkpad' -or $gates.ENABLE_HARDWARE -ne 'false' -or $gates.ENABLE_HARDWARE_FAST -ne 'false') {
    throw 'GitHub hardware writers must remain gated during maintenance.'
}
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent.' }
$dashboardBackends = @(Get-TechScoutBackends $python $packageApp $app)
if (-not $release.acceptance -or $release.acceptance.watch_schema_version -ne 3) { throw 'Reprepare this release with current deployment acceptance metadata.' }
if ($ValidateOnly) { Write-Output "Merged package, installed runtime and $($dashboardBackends.Count) scoped dashboard processes validated; no live changes."; return }
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Windows administrator elevation is required to update the protected runtime and tasks.' }
$tasks = @{}
foreach ($name in @('DealAlerter-Hardware','DealAlerter-Watchdog')) {
    $task = Get-ScheduledTask -TaskName $name
    $tasks[$name] = @{enabled=[bool]$task.Settings.Enabled;running=($task.State -eq 'Running')}
}
$before = Get-Content -Raw -LiteralPath (Join-Path $runtime 'health.json') | ConvertFrom-Json
$backup = Join-Path $runtime ('backups\upgrade-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N'))
$copied = $false
$controlsBackedUp = $false
$launcherBackups = @()
$maintenance = Join-Path $runtime 'ui\upgrade-in-progress.json'
if (Test-Path -LiteralPath $maintenance) { throw 'A previous dashboard maintenance marker remains. Review its recorded upgrade before proceeding.' }
try {
    New-Item -ItemType Directory -Path $backup | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path $maintenance) | Out-Null
    @{backup=$backup;started_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -Encoding UTF8 $maintenance
    # Replace recognized per-user launchers before stopping backends. New
    # launches now honor the maintenance marker; no elevated dashboard is started.
    New-Item -ItemType Directory -Path (Join-Path $backup 'launchers') | Out-Null
    foreach ($backend in @($dashboardBackends | Sort-Object data_directory -Unique)) {
        $launcher = Join-Path $backend.data_directory 'Start-TechScout.ps1'
        $savedLauncher = Join-Path $backup ('launchers\' + $launcherBackups.Count + '.ps1')
        $present = Test-Path -LiteralPath $launcher
        if ($present) { Copy-Item -LiteralPath $launcher -Destination $savedLauncher }
        $launcherBackups += @{path=$launcher;saved=$savedLauncher;present=$present}
        Copy-Item -LiteralPath (Join-Path $packageApp 'scripts\windows\Start-TechScout.ps1') -Destination $launcher -Force
    }
    $dashboardBackends | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $backup 'dashboard-restart.json')
    Stop-TechScoutBackends $dashboardBackends $python $packageApp $app
    if (@(Get-TechScoutBackends $python $packageApp $app).Count) { throw 'A dashboard backend restarted during maintenance; application was not replaced.' }
    # Stop the watchdog first so it cannot restart hardware midway through copying.
    foreach ($name in @('DealAlerter-Watchdog','DealAlerter-Hardware')) {
        Disable-ScheduledTask -TaskName $name | Out-Null
        Stop-ScheduledTask -TaskName $name
    }
    Wait-MonitorStopped @('DealAlerter-Hardware','DealAlerter-Watchdog') $before.pid $python $packageApp (Join-Path $state 'hardware\.writer.lock')
    Copy-Item -LiteralPath $app -Destination (Join-Path $backup 'app') -Recurse
    Copy-Item -LiteralPath $state -Destination (Join-Path $backup 'state') -Recurse
    Copy-Item -LiteralPath $ownerPath -Destination (Join-Path $backup 'owner.json')
    Backup-TechScoutControls $runtime $backup
    $controlsBackedUp = $true
    foreach ($name in $tasks.Keys) {
        Export-ScheduledTask -TaskName $name | Set-Content -Encoding Unicode (Join-Path $backup ($name+'.xml'))
    }
    $copied=$true
    foreach ($property in $release.hashes.PSObject.Properties) {
        $destination = [IO.Path]::GetFullPath((Join-Path $app $property.Name))
        if (-not $destination.StartsWith($app+'\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Destination escapes installed application.' }
        New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
        Copy-Item -LiteralPath (Join-Path $packageApp $property.Name) -Destination $destination -Force
        if ((Get-FileHash -LiteralPath $destination).Hash -ne $property.Value) { throw "Installed hash mismatch: $($property.Name)" }
    }
    & $python (Join-Path $app 'scripts\repair_hardware_history.py') (Join-Path $state 'hardware\US\prices.jsonl') --quarantine-unlabelled --apply --backup (Join-Path $backup 'prices-before-repair.jsonl') |
        Set-Content -Encoding UTF8 (Join-Path $backup 'repair-result.json')
    if ($LASTEXITCODE -ne 0) { throw 'History repair refused; backup retained.' }
    $owner | Add-Member -NotePropertyName installed_commit -NotePropertyValue $upstream -Force
    $owner | Add-Member -NotePropertyName upgraded_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
    $ownerTemporary = Join-Path $runtime ('.owner-' + [Guid]::NewGuid().ToString('N') + '.json')
    $owner | ConvertTo-Json | Set-Content -Encoding UTF8 $ownerTemporary
    Move-Item -LiteralPath $ownerTemporary -Destination $ownerPath -Force
    $health = Start-EnabledMonitorTasks $tasks $runtime $before.pid
    $acceptance = if ($tasks['DealAlerter-Hardware'].enabled) { Test-MonitorReleaseAcceptance $runtime $python $app -RequiredKinds @($release.acceptance.job_kinds) -Capabilities @($release.acceptance.capabilities) } else { @{status='monitor-was-disabled'} }
    Remove-Item -LiteralPath $maintenance -Force
    $restart = @($dashboardBackends | Sort-Object data_directory -Unique | Select-Object data_directory,owner_sid,session_id)
    $result = @{status='monitor-updated';commit=$upstream;backup=$backup;pid=$health.pid;acceptance=$acceptance;dashboard_restart_required=[bool]$restart.Count;dashboard_restart=$restart}
    $result | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 (Join-Path $PreparedDirectory 'upgrade-result.json')
    Write-Output 'Monitor updated and startup acceptance passed; history and receipts retained. Restart any recorded TechScout dashboard from its normal owning account, then run deployment acceptance.'
} catch {
    $failure = $_.Exception.Message
    $recovery = 'failed'
    $recoveryError = ''
    $failedWriter = $before.pid
    try { $failedWriter = (Get-Content -Raw -LiteralPath (Join-Path $runtime 'health.json') | ConvertFrom-Json).pid } catch {}
    foreach ($name in @('DealAlerter-Watchdog','DealAlerter-Hardware')) {
        Disable-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    }
    try {
        $retryBackends = @(Get-TechScoutBackends $python $packageApp $app)
        Stop-TechScoutBackends $retryBackends $python $packageApp $app
        Wait-MonitorStopped @('DealAlerter-Hardware','DealAlerter-Watchdog') $failedWriter $python $packageApp (Join-Path $state 'hardware\.writer.lock')
        if ($copied) {
            Move-Item -LiteralPath $app -Destination (Join-Path $backup 'failed-app')
            Copy-Item -LiteralPath (Join-Path $backup 'app') -Destination $app -Recurse
            Copy-Item -LiteralPath (Join-Path $backup 'owner.json') -Destination $ownerPath -Force
        }
        if ($controlsBackedUp) { Restore-TechScoutControls $runtime $backup }
        foreach ($launcher in $launcherBackups) {
            if ($launcher.present) { Copy-Item -LiteralPath $launcher.saved -Destination $launcher.path -Force }
            elseif (Test-Path -LiteralPath $launcher.path) { Remove-Item -LiteralPath $launcher.path -Force }
        }
        # Never roll back history/receipts after a task may have sent a real alert.
        $health = Start-EnabledMonitorTasks $tasks $runtime $failedWriter
        $recovery = 'complete'
        if (Test-Path -LiteralPath $maintenance) { Remove-Item -LiteralPath $maintenance -Force }
    } catch {
        $recoveryError = $_.Exception.Message
        foreach ($name in @('DealAlerter-Hardware','DealAlerter-Watchdog')) {
            if ($tasks[$name].enabled) { Enable-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null }
        }
    }
    @{status='failed';reason=$failure;backup=$backup;recovery_status=$recovery;recovery_error=$recoveryError;dashboard_restart_required=[bool]$dashboardBackends.Count;dashboard_restart=@($dashboardBackends | Select-Object data_directory,owner_sid,session_id)} | ConvertTo-Json -Depth 6 |
        Set-Content -Encoding UTF8 (Join-Path $PreparedDirectory 'upgrade-result.json')
    throw "Upgrade failed: $failure Recovery: $recovery $recoveryError"
}
