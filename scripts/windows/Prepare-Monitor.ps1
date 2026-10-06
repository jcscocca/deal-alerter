[CmdletBinding()]
param(
    [string]$Checkout = '',
    [string]$OutputDirectory = '',
    [string]$RuntimeDirectory = 'C:\ProgramData\DealAlerter'
)
$ErrorActionPreference = 'Stop'
if (-not $Checkout) { $Checkout = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path }
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $Checkout '.local\windows' }
$Checkout = [IO.Path]::GetFullPath($Checkout)
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$RuntimeDirectory = [IO.Path]::GetFullPath($RuntimeDirectory)
$packageApp = Join-Path $OutputDirectory 'app'
New-Item -ItemType Directory -Force -Path $packageApp | Out-Null
$files = & git -C $Checkout ls-files --cached --others --exclude-standard
if ($LASTEXITCODE -ne 0) { throw 'Cannot enumerate the checkout' }
$hashes = @{}
foreach ($relative in $files) {
    if ($relative -notmatch '^(alerters/|dealcore/|config/|scripts/windows/|requirements.*\.txt$)') { continue }
    $source = Join-Path $Checkout $relative
    $destination = Join-Path $packageApp $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Force
    $hashes[$relative] = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash
}
$base = & git -C $Checkout rev-parse origin/main
if ($LASTEXITCODE -ne 0) { throw 'origin/main is unavailable' }
$manifest = @{ version = 1; checkout = $Checkout; base = $base; runtime = $RuntimeDirectory; hashes = $hashes }
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 (Join-Path $OutputDirectory 'release.json')
$pythonw = [Security.SecurityElement]::Escape((Join-Path $RuntimeDirectory 'venv\Scripts\pythonw.exe'))
$app = [Security.SecurityElement]::Escape((Join-Path $RuntimeDirectory 'app'))
$runtime = [Security.SecurityElement]::Escape($RuntimeDirectory)
foreach ($name in 'Hardware','Watchdog') {
    $extra = if ($name -eq 'Watchdog') { '--watchdog' } else { '' }
    $repeat = if ($name -eq 'Watchdog') { '<TimeTrigger><Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition><StartBoundary>2026-01-01T00:00:00</StartBoundary><Enabled>true</Enabled></TimeTrigger>' } else { '' }
    $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>DealAlerter $name; prepared only until approved cutover.</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled><Delay>PT45S</Delay></BootTrigger>$repeat</Triggers>
  <Principals><Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><Enabled>true</Enabled><Hidden>true</Hidden>
    <WakeToRun>true</WakeToRun><ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="System"><Exec><Command>$pythonw</Command>
    <Arguments>-m alerters.hardware.monitor --state-dir &quot;$runtime\state&quot; --runtime &quot;$runtime&quot; --env-file &quot;$runtime\secrets.env&quot; $extra</Arguments>
    <WorkingDirectory>$app</WorkingDirectory>
  </Exec></Actions>
</Task>
"@
    $xml | Set-Content -Encoding Unicode (Join-Path $OutputDirectory "DealAlerter-$name.xml")
    [xml]$validated = $xml
}
@'
# Populate locally before cutover. Never commit this file or print its values.
NTFY_TOPIC=
NTFY_SERVER=https://ntfy.sh
NTFY_TOKEN=
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
SMTP_USER=
SMTP_PASSWORD=
MAIL_TO=
MAIL_FROM=
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
DESKTOP_NOTIFY=0
'@ | Set-Content -Encoding utf8 (Join-Path $OutputDirectory 'secrets.env.template')
Write-Output "Prepared release, secret-name template and two task XML files in $OutputDirectory"
Write-Output 'No tasks registered; no schedules changed; no notifications sent.'
