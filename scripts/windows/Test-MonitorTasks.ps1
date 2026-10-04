[CmdletBinding()]
param([Parameter(Mandatory)][string]$PreparedDirectory)
$ErrorActionPreference = 'Stop'
$service = New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder = $service.GetFolder('\')
foreach ($name in 'Hardware','Watchdog') {
    $xml = Get-Content -Raw -LiteralPath (Join-Path $PreparedDirectory "DealAlerter-$name.xml")
    # TASK_VALIDATE_ONLY = 1; never combine with CREATE/UPDATE.
    # https://learn.microsoft.com/en-us/windows/win32/taskschd/taskfolder-registertask
    $null = $folder.RegisterTask("DealAlerter-$name", $xml, 1, 'SYSTEM', $null, 5, $null)
    Write-Output "Validated without registration: DealAlerter-$name"
}
