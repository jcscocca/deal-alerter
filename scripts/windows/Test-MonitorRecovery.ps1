[CmdletBinding(DefaultParameterSetName='Prepare')]
param(
    [Parameter(ParameterSetName='Prepare')][switch]$ValidateOnly,
    [Parameter(ParameterSetName='Prepare')][switch]$ApproveReboot,
    [Parameter(Mandatory,ParameterSetName='Boot')][switch]$AfterBoot,
    [Parameter(Mandatory,ParameterSetName='Restore')][switch]$RestoreNetwork
)
$ErrorActionPreference = 'Stop'
$runtime = 'C:\ProgramData\DealAlerter'
$acceptance = Join-Path $runtime 'acceptance'
$baselinePath = Join-Path $acceptance 'baseline.json'
$resultPath = Join-Path $acceptance 'recovery-result.json'
$script = Join-Path $runtime 'app\scripts\windows\Test-MonitorRecovery.ps1'
$python = Join-Path $runtime 'venv\Scripts\python.exe'
$bootTask = 'DealAlerter-AcceptanceBoot'
$restoreTask = 'DealAlerter-AcceptanceNetworkRestore'
function Read-Json([string]$Path) { Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json }
function Save-Json($Value,[string]$Path) {
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N')
    $Value | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 $temporary
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}
function Epoch { [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() }
function Boot-Time { (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o') }
function Active-Adapters($Baseline) {
    @(Get-NetAdapter -Physical | Where-Object { [string]$_.InterfaceGuid -in $Baseline.adapter_guids })
}
function Task-Action([string]$Mode) {
    New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $script + '" -' + $Mode)
}
function Task-Settings {
    New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
}
try {
    $owner = Read-Json (Join-Path $runtime 'owner.json')
    if (-not $owner.approved -or $owner.hardware_writer -ne 'thinkpad' -or
        $owner.checkout -ne (Join-Path $runtime 'app') -or $owner.state_root -ne (Join-Path $runtime 'state')) { throw 'Runtime owner does not match.' }
    if (Get-ChildItem -LiteralPath $runtime -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Acceptance must not follow runtime reparse points.' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$identity
    if ($PSCmdlet.ParameterSetName -ne 'Prepare' -and $identity.User.Value -ne 'S-1-5-18') { throw 'Recovery task must run as SYSTEM.' }
    if ($RestoreNetwork) {
        $baseline = Read-Json $baselinePath
        Active-Adapters $baseline | Enable-NetAdapter -Confirm:$false
        Save-Json @{restored_at=(Epoch);status='restore-requested'} (Join-Path $acceptance 'network-restore.json')
        return
    }
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Recovery acceptance needs Windows administrator elevation.' }
    foreach ($name in @('DealAlerter-Hardware','DealAlerter-Watchdog')) {
        $task = Get-ScheduledTask -TaskName $name
        [xml]$xml = Export-ScheduledTask -TaskName $name
        if ($task.Principal.UserId -notin @('SYSTEM','S-1-5-18') -or -not $task.Settings.Enabled -or
            -not $xml.Task.Triggers.BootTrigger -or $xml.Task.Triggers.BootTrigger.Enabled -ne 'true' -or
            $task.Settings.DisallowStartIfOnBatteries -or $task.Settings.StopIfGoingOnBatteries -or
            -not $task.Settings.WakeToRun -or $task.Actions.Execute -notlike '*\pythonw.exe') { throw "Unexpected installed task: $name" }
    }
    if (-not $owner.installed_commit) { throw 'Apply the merged maintenance release first.' }
    $health = Read-Json (Join-Path $runtime 'health.json')
    if ((Epoch)-$health.heartbeat -gt 60 -or $health.dry_run) { throw 'Live monitor heartbeat is unavailable.' }
} catch {
    if ($AfterBoot -and (Test-Path -LiteralPath $acceptance)) {
        Save-Json @{status='failed';stage='preflight';reason=$_.Exception.Message;completed_at=(Epoch)} $resultPath
        Unregister-ScheduledTask -TaskName $bootTask -Confirm:$false -ErrorAction SilentlyContinue
    }
    throw
}
if ($ValidateOnly) { Write-Output 'Installed ownership, SYSTEM boot tasks, battery/wake settings and heartbeat validated; no changes.'; return }
if (-not $AfterBoot) {
    if (-not $ApproveReboot) { throw 'Scheduling the disruptive acceptance requires -ApproveReboot.' }
    if ([IO.Path]::GetFullPath($PSCommandPath) -ne $script) { throw 'Run the installed protected script.' }
    if (Get-ScheduledTask -TaskName $bootTask,$restoreTask -ErrorAction SilentlyContinue) { throw 'An acceptance task already exists; inspect its result first.' }
    $adapters = @(Get-NetAdapter -Physical | Where-Object Status -eq 'Up')
    if (-not $adapters) { throw 'No active physical network adapter to test.' }
    New-Item -ItemType Directory -Force -Path $acceptance | Out-Null
    Copy-Item -LiteralPath (Join-Path $runtime 'state\hardware\US\alerts.json') -Destination (Join-Path $acceptance 'alerts-before-reboot.json') -Force
    $baseline = @{boot=(Boot-Time);pid=$health.pid;commit=$owner.installed_commit;prepared_at=(Epoch);
                  adapter_guids=@($adapters | ForEach-Object { [string]$_.InterfaceGuid })}
    Save-Json $baseline $baselinePath
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT90S'
    Register-ScheduledTask -TaskName $bootTask -Action (Task-Action 'AfterBoot') -Trigger $trigger -Settings (Task-Settings) -User 'SYSTEM' -RunLevel Highest | Out-Null
    Save-Json @{status='awaiting-reboot';commit=$baseline.commit;prepared_at=$baseline.prepared_at} $resultPath
    # A two-minute grace period lets the user save work and cancel with shutdown /a.
    & shutdown.exe /r /t 120 /c 'DealAlerter recovery check: save work. After restart, leave this ThinkPad signed out for two minutes. Networking will be restored automatically after a brief acceptance test.'
    if ($LASTEXITCODE -ne 0) {
        Unregister-ScheduledTask -TaskName $bootTask -Confirm:$false
        Save-Json @{status='failed';reason='Windows rejected the reboot request'} $resultPath
        throw 'Windows rejected the reboot request.'
    }
    Write-Output 'Reboot scheduled in two minutes. Cancel with shutdown /a. Recovery result will be recorded after startup.'
    return
}
$result = @{status='running';started_at=(Epoch);boot=(Boot-Time);commit=$owner.installed_commit}
try {
    $baseline = Read-Json $baselinePath
    if ($result.boot -eq $baseline.boot -or $owner.installed_commit -ne $baseline.commit -or
        $health.pid -eq $baseline.pid -or $health.started -lt ([DateTimeOffset][datetime]$result.boot).ToUnixTimeSeconds()) { throw 'Fresh boot into the expected installed release was not established.' }
    $result.pid = $health.pid
    $result.boot_tasks_verified = $true
    $logons = @(Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TerminalServices-LocalSessionManager/Operational';Id=21;StartTime=[datetime]$result.boot} -ErrorAction SilentlyContinue)
    $result.started_before_interactive_logon = -not @($logons | Where-Object { ([DateTimeOffset]$_.TimeCreated).ToUnixTimeSeconds() -le $health.started }).Count
    Save-Json $result $resultPath
    # Select a previously successful retailer that is about to poll, so the
    # physical outage exercises the actual monitor rather than an unused socket.
    $deadline = (Epoch)+180
    do {
        $health = Read-Json (Join-Path $runtime 'health.json')
        $job = $health.jobs.PSObject.Properties | Where-Object {
            $_.Value.kind -eq 'newegg' -and $_.Value.last_success -gt 0 -and $_.Value.failures -eq 0 -and $_.Value.next -le (Epoch)+10
        } | Select-Object -First 1
        if (-not $job) { Start-Sleep -Seconds 2 }
    } while (-not $job -and (Epoch) -lt $deadline)
    if (-not $job) { throw 'No healthy retailer became due for the network recovery check.' }
    $result.network_job = $job.Name
    $adapters = Active-Adapters $baseline
    if (-not $adapters -or @($adapters | Where-Object Status -ne 'Up').Count) { throw 'The original physical adapters are not available.' }
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(90)
    Register-ScheduledTask -TaskName $restoreTask -Action (Task-Action 'RestoreNetwork') -Trigger $trigger -Settings (Task-Settings) -User 'SYSTEM' -RunLevel Highest | Out-Null
    $result.offline_started_at = Epoch
    Save-Json $result $resultPath
    try {
        $adapters | Disable-NetAdapter -Confirm:$false
        if (@(Active-Adapters $baseline | Where-Object Status -eq 'Up').Count) { throw 'Physical network adapter did not go offline.' }
        for ($i=0; $i -lt 30; $i++) { Start-Sleep -Seconds 2 }
        $offline = Read-Json (Join-Path $runtime 'health.json')
        $result.offline_failure_seen = $offline.jobs.PSObject.Properties[$job.Name].Value.failures -gt $job.Value.failures
        $result.heartbeat_during_outage = (Epoch)-$offline.heartbeat -le 60 -and $offline.pid -eq $result.pid
    } finally {
        # The independent restore task also runs if this verifier is terminated.
        Active-Adapters $baseline | Enable-NetAdapter -Confirm:$false
        $result.network_restored_at = Epoch
        Save-Json $result $resultPath
    }
    $deadline = (Epoch)+600
    do {
        Start-Sleep -Seconds 2
        $health = Read-Json (Join-Path $runtime 'health.json')
        $recovered = $health.jobs.PSObject.Properties[$job.Name].Value.last_success -gt $result.network_restored_at
    } while (-not $recovered -and (Epoch) -lt $deadline)
    $result.network_recovered = $recovered
    $result.pid_preserved_during_network_recovery = $health.pid -eq $result.pid
    $receiptCode = @'
import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from dealcore.state import AlertState
before=AlertState(Path(sys.argv[2]),lambda key:key).records
after=AlertState(Path(sys.argv[3]),lambda key:key).records
missing=sum(1 for key,channels in before.items() for channel,record in channels.items() if key not in after or channel not in after[key] or after[key][channel].alerted_at < record.alerted_at)
print(json.dumps({'prior_receipts':sum(map(len,before.values())),'lost_or_rewound_receipts':missing}))
sys.exit(bool(missing))
'@
    $receiptText = & $python -c $receiptCode $owner.checkout (Join-Path $acceptance 'alerts-before-reboot.json') (Join-Path $runtime 'state\hardware\US\alerts.json')
    $receiptExit = $LASTEXITCODE
    $result.receipts = $receiptText | ConvertFrom-Json
    if ($receiptExit -ne 0 -or -not $recovered -or -not $result.offline_failure_seen -or
        -not $result.heartbeat_during_outage -or -not $result.pid_preserved_during_network_recovery) { throw 'Physical recovery acceptance did not pass all required evidence checks.' }
    $result.status = if ($result.started_before_interactive_logon) { 'complete' } else { 'partial' }
    if ($result.status -eq 'partial') { $result.reason='Boot and network recovery passed; interactive logon preceded monitor startup, so no-login acceptance remains unproven.' }
} catch {
    $result.status='failed'
    $result.reason=$_.Exception.Message
} finally {
    $result.completed_at = Epoch
    Save-Json $result $resultPath
    if ($baseline -and @(Active-Adapters $baseline | Where-Object Status -eq 'Up').Count -eq $baseline.adapter_guids.Count) {
        Unregister-ScheduledTask -TaskName $restoreTask -Confirm:$false -ErrorAction SilentlyContinue
    }
    Unregister-ScheduledTask -TaskName $bootTask -Confirm:$false -ErrorAction SilentlyContinue
}
