[CmdletBinding()]
param(
    [string]$RuntimeDirectory='C:\ProgramData\DealAlerter',
    [Parameter(Mandatory)][string]$DataDirectory,
    [Parameter(Mandatory)][string]$ExpectedUserSid,
    [switch]$RequireSourceCycle
)
$ErrorActionPreference='Stop'
$app=Join-Path $RuntimeDirectory 'app'
$python=Join-Path $RuntimeDirectory 'venv\Scripts\python.exe'
. (Join-Path $PSScriptRoot 'TechScout-Lifecycle.ps1')
if (Test-Path -LiteralPath (Join-Path $RuntimeDirectory 'ui\upgrade-in-progress.json')) { throw 'Application maintenance is still in progress.' }
$monitor=Test-MonitorReleaseAcceptance $RuntimeDirectory $python $app -RequireSourceCycle:$RequireSourceCycle
$expected=Get-TechScoutExpectedVersion $python $app
$health=Invoke-RestMethod 'http://127.0.0.1:8768/health' -TimeoutSec 3
if ($health.service -ne 'TechScout' -or $health.status -ne 'ok' -or $health.version -ne $expected -or $health.watch_schema_version -ne 3 -or -not $health.instance_id -or -not $health.pid) { throw 'Dashboard is stale or does not expose the expected application/schema identity.' }
$backends=@(Get-TechScoutBackends $python $app $app -ProcessIds @([int]$health.pid))
if (-not (Test-TechScoutBackendOwner $backends $ExpectedUserSid $DataDirectory)) { throw 'Dashboard is not running from the expected normal interactive account and data directory.' }
$workspace=Invoke-RestMethod 'http://127.0.0.1:8768/api/workspace' -TimeoutSec 3
if (-not $workspace.supported -or $workspace.error -or $workspace.settings.version -ne 3) { throw 'Dashboard watch controls are unavailable or incompatible.' }
@{status='accepted';version=$health.version;instance_id=$health.instance_id;dashboard_pid=$health.pid;dashboard_user_sid=$ExpectedUserSid;dashboard_session_id=$backends[0].session_id;monitor=$monitor} | ConvertTo-Json -Depth 6
