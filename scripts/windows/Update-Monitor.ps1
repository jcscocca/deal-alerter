[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PreparedDirectory,
    [switch]$ApproveUpgrade,
    [switch]$ValidateOnly
)
$ErrorActionPreference = 'Stop'
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
$variables = & gh api repos/jcscocca/deal-alerter/actions/variables
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify hardware writer gates.' }
$gates = @{}
foreach ($variable in ($variables | ConvertFrom-Json).variables) { $gates[$variable.name] = $variable.value }
if ($gates.HARDWARE_WRITER -ne 'thinkpad' -or $gates.ENABLE_HARDWARE -ne 'false' -or $gates.ENABLE_HARDWARE_FAST -ne 'false') {
    throw 'GitHub hardware writers must remain gated during maintenance.'
}
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Installed dependencies are inconsistent.' }
if ($ValidateOnly) { Write-Output 'Merged package and installed runtime validated; no live changes.'; return }
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
try {
    # Stop the watchdog first so it cannot restart hardware midway through copying.
    foreach ($name in @('DealAlerter-Watchdog','DealAlerter-Hardware')) {
        Disable-ScheduledTask -TaskName $name | Out-Null
        Stop-ScheduledTask -TaskName $name
    }
    Wait-MonitorStopped @('DealAlerter-Hardware','DealAlerter-Watchdog') $before.pid $python $packageApp (Join-Path $state 'hardware\.writer.lock')
    New-Item -ItemType Directory -Path $backup | Out-Null
    Copy-Item -LiteralPath $app -Destination (Join-Path $backup 'app') -Recurse
    Copy-Item -LiteralPath $state -Destination (Join-Path $backup 'state') -Recurse
    Copy-Item -LiteralPath $ownerPath -Destination (Join-Path $backup 'owner.json')
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
    $result = @{status='complete';commit=$upstream;backup=$backup;pid=$health.pid}
    $result | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $PreparedDirectory 'upgrade-result.json')
    Write-Output 'Monitor updated and restarted; live history repaired, receipts retained and secrets untouched.'
} catch {
    $failure = $_.Exception.Message
    $recovery = 'failed'
    $recoveryError = ''
    $failedWriter = (Get-Content -Raw -LiteralPath (Join-Path $runtime 'health.json') | ConvertFrom-Json).pid
    foreach ($name in @('DealAlerter-Watchdog','DealAlerter-Hardware')) {
        Disable-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null
        Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    }
    try {
        Wait-MonitorStopped @('DealAlerter-Hardware','DealAlerter-Watchdog') $failedWriter $python $packageApp (Join-Path $state 'hardware\.writer.lock')
        if ($copied) {
            Copy-Item -Path (Join-Path $backup 'app\*') -Destination $app -Recurse -Force
            Copy-Item -LiteralPath (Join-Path $backup 'owner.json') -Destination $ownerPath -Force
        }
        # Never roll back history/receipts after a task may have sent a real alert.
        $health = Start-EnabledMonitorTasks $tasks $runtime $failedWriter
        $recovery = 'complete'
    } catch {
        $recoveryError = $_.Exception.Message
        foreach ($name in @('DealAlerter-Hardware','DealAlerter-Watchdog')) {
            if ($tasks[$name].enabled) { Enable-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null }
        }
    }
    @{status='failed';reason=$failure;backup=$backup;recovery_status=$recovery;recovery_error=$recoveryError} | ConvertTo-Json |
        Set-Content -Encoding UTF8 (Join-Path $PreparedDirectory 'upgrade-result.json')
    throw "Upgrade failed: $failure Recovery: $recovery $recoveryError"
}
