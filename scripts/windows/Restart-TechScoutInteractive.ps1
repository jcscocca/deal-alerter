# Run only as part of an approved update. No stored password or elevated backend.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$UpgradeResult,
    [Parameter(Mandatory)][string]$DataDirectory,
    [Parameter(Mandatory)][string]$ExpectedUserSid,
    [switch]$ApproveRestart
)
$ErrorActionPreference='Stop'
if (-not $ApproveRestart) { throw 'Use -ApproveRestart only for the approved normal-account dashboard restart.' }
$result=Get-Content -Raw -LiteralPath $UpgradeResult | ConvertFrom-Json
if ($result.status -ne 'monitor-updated') { throw 'This restart requires a successful monitor update result.' }
$record=@($result.dashboard_restart | Where-Object { $_.owner_sid -eq $ExpectedUserSid -and $_.data_directory -eq $DataDirectory })
if ($record.Count -ne 1 -or $ExpectedUserSid -eq 'S-1-5-18' -or $record[0].session_id -eq 0) { throw 'The requested interactive account/data path was not the dashboard stopped by this update.' }
$launcher=Join-Path $DataDirectory 'Start-TechScout.ps1'
if (-not (Test-Path -LiteralPath $launcher)) { throw 'Recorded per-user launcher is missing.' }
$name='DealAlerter-TechScout-Restart-'+[Guid]::NewGuid().ToString('N')
$executable=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments='-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$launcher+'"'
$action=New-ScheduledTaskAction -Execute $executable -Argument $arguments -WorkingDirectory $DataDirectory
$principal=New-ScheduledTaskPrincipal -UserId $ExpectedUserSid -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
try {
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings | Out-Null
    Start-ScheduledTask -TaskName $name
    $accepted=$false
    $lastError='The expected signed-in account may not have an active interactive session.'
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        try {
            $acceptance=& (Join-Path $PSScriptRoot 'Test-DeploymentAcceptance.ps1') -DataDirectory $DataDirectory -ExpectedUserSid $ExpectedUserSid
            $accepted=$true
            break
        } catch { $lastError=$_.Exception.Message }
    }
    if (-not $accepted) { throw "Normal-account dashboard restart did not pass acceptance: $lastError" }
    $acceptance
} finally {
    # On-demand, no-trigger task exists only for this already-signed-in account.
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}
