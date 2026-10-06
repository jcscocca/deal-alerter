# Run only after reviewing the dry run and obtaining explicit cutover approval.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PreparedDirectory,
    [Parameter(Mandatory)][string]$PythonExe,
    [string]$SecretsFile = '',
    [switch]$ApproveCutover
)
$ErrorActionPreference = 'Stop'
if (-not $ApproveCutover) { throw 'Explicit approval is required: -ApproveCutover' }
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run the approved cutover from an elevated PowerShell session.' }
$release = Get-Content -Raw -LiteralPath (Join-Path $PreparedDirectory 'release.json') | ConvertFrom-Json
$runtime = [IO.Path]::GetFullPath($release.runtime)
if ($runtime -ne 'C:\ProgramData\DealAlerter') { throw 'Review nonstandard runtime path before installation' }
$app = Join-Path $runtime 'app'
$state = Join-Path $runtime 'state'
$secretPath = Join-Path $runtime 'secrets.env'
if ($SecretsFile) {
    if (-not (Test-Path -LiteralPath $SecretsFile -PathType Leaf)) { throw 'Staged credential file is missing' }
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    & icacls.exe $runtime /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Private runtime ACL failed' }
    Copy-Item -LiteralPath $SecretsFile -Destination $secretPath -Force
}
if (-not (Test-Path -LiteralPath $secretPath)) { throw "Populate $secretPath locally first; GitHub secret values cannot be read back." }
$present = @{}
foreach ($line in Get-Content -LiteralPath $secretPath) {
    if ($line -match '^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)$') { $present[$Matches[1]] = -not [string]::IsNullOrWhiteSpace($Matches[2].Trim('"',"'")) }
}
foreach ($key in 'NTFY_TOPIC','EBAY_CLIENT_ID','EBAY_CLIENT_SECRET','SMTP_USER','SMTP_PASSWORD','MAIL_TO') {
    if (-not $present[$key]) { throw "Required local credential missing: $key" }
}
if (Test-Path -LiteralPath (Join-Path $runtime 'owner.json')) { throw 'An owner manifest already exists; use the documented upgrade/rollback procedure.' }
foreach ($property in $release.hashes.PSObject.Properties) {
    $path = Join-Path (Join-Path $PreparedDirectory 'app') $property.Name
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash -ne $property.Value) { throw "Prepared file changed: $($property.Name)" }
}
& git -C $release.checkout fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed' }
$changes = & git -C $release.checkout diff --name-only $release.base origin/main -- . ':!state'
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'origin/main code changed; refresh and retest the prepared release before cutover.' }
$workflow = & git -C $release.checkout show origin/main:.github/workflows/check.yml
if ($LASTEXITCODE -ne 0 -or -not ($workflow -match 'HARDWARE_WRITER')) {
    throw 'Merge the reviewed hardware-owner workflow guard, refresh origin/main, retest and prepare again before enabling.'
}
function Invoke-Gh {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $result = & gh @Arguments
    if ($LASTEXITCODE -ne 0) { throw "GitHub operation failed: $($Arguments[0])" }
    return $result
}
# Save only nonsecret ownership/schedule switches for an exact rollback.
$vars = (Invoke-Gh -Arguments @('api','repos/jcscocca/deal-alerter/actions/variables')) | ConvertFrom-Json
$saved = @{}
foreach ($variable in $vars.variables) {
    if ($variable.name -in 'ENABLE_HARDWARE','ENABLE_HARDWARE_FAST','ENABLE_STEAM','HARDWARE_WRITER') { $saved[$variable.name] = $variable.value }
}
if (-not (Test-Path -LiteralPath (Join-Path $runtime 'prior-switches.json'))) {
    $saved | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $runtime 'prior-switches.json')
}
# Close both hardware schedule gates. Steam's variable and cron are untouched.
Invoke-Gh -Arguments @('variable','set','HARDWARE_WRITER','--repo','jcscocca/deal-alerter','--body','thinkpad') | Out-Null
Invoke-Gh -Arguments @('variable','set','ENABLE_HARDWARE_FAST','--repo','jcscocca/deal-alerter','--body','false') | Out-Null
Invoke-Gh -Arguments @('variable','set','ENABLE_HARDWARE','--repo','jcscocca/deal-alerter','--body','false') | Out-Null
# Never race a pre-cutover workflow or cancel Steam. Fail closed until it drains.
$runs = (Invoke-Gh -Arguments @('run','list','--repo','jcscocca/deal-alerter','--workflow','check.yml','--limit','100','--json','status,databaseId')) | ConvertFrom-Json
if ($runs | Where-Object { $_.status -ne 'completed' }) {
    throw 'Check-deals runs remain active/queued. Hardware gates are closed; let them drain and rerun. Do not restore hardware schedules while a local writer is active.'
}
& git -C $release.checkout fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Final state fetch failed' }
New-Item -ItemType Directory -Force -Path $app,$state | Out-Null
foreach ($property in $release.hashes.PSObject.Properties) {
    $destination = Join-Path $app $property.Name
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath (Join-Path (Join-Path $PreparedDirectory 'app') $property.Name) -Destination $destination -Force
}
$archive = Join-Path $runtime 'hardware-cutover.zip'
& git -C $release.checkout archive --format=zip -o $archive origin/main state/hardware
if ($LASTEXITCODE -ne 0) { throw 'Hardware state snapshot failed' }
Expand-Archive -LiteralPath $archive -DestinationPath $runtime -Force
& $PythonExe -m venv (Join-Path $runtime 'venv')
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
$python = Join-Path $runtime 'venv\Scripts\python.exe'
& $python -m pip install -r (Join-Path $app 'requirements.txt') -r (Join-Path $app 'alerters\hardware\native\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& (Join-Path $PSScriptRoot 'Set-MonitorRuntimePermissions.ps1') -RuntimeDirectory $runtime
@{ hardware_writer='thinkpad'; approved=$true; checkout=$app; state_root=$state; cutover_commit=(& git -C $release.checkout rev-parse origin/main) } |
    ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $runtime 'owner.json')
foreach ($name in 'Hardware','Watchdog') {
    Register-ScheduledTask -TaskName "DealAlerter-$name" -Xml (Get-Content -Raw -LiteralPath (Join-Path $PreparedDirectory "DealAlerter-$name.xml")) | Out-Null
}
Start-ScheduledTask -TaskName 'DealAlerter-Hardware'
Start-ScheduledTask -TaskName 'DealAlerter-Watchdog'
Write-Output 'Local hardware writer enabled. Steam settings were preserved. Inspect health before considering cutover complete.'
