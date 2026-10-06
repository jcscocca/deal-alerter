[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$script = 'C:\ProgramData\DealAlerter\app\scripts\windows\Test-MonitorRecovery.ps1'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Test-MonitorRecovery.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
# Load only the action/settings builders; the operational script is never run.
foreach ($name in @('Task-Action','Task-Settings')) {
    $definition=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if (-not $definition) { throw "Missing task builder: $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
$service=New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder=$service.GetFolder('\')
foreach ($mode in @('AfterBoot','RestoreNetwork')) {
    $trigger=if ($mode -eq 'AfterBoot') { New-ScheduledTaskTrigger -AtStartup } else { New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) }
    if ($mode -eq 'AfterBoot') { $trigger.Delay='PT90S' }
    $task=New-ScheduledTask -Action (Task-Action $mode) -Trigger $trigger -Settings (Task-Settings) -Principal (New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest)
    if (-not $task.Settings.Hidden -or $task.Settings.DisallowStartIfOnBatteries -or $task.Settings.StopIfGoingOnBatteries) { throw 'Acceptance task must remain hidden and permit battery operation.' }
    $xml=$task | Export-ScheduledTask
    # TASK_VALIDATE_ONLY = 1. Do not register or execute an acceptance task.
    $null=$folder.RegisterTask("DealAlerter-Acceptance-Validate-$mode",$xml,1,'SYSTEM',$null,5,$null)
    Write-Output "Validated without registration or network/reboot changes: $mode"
}
