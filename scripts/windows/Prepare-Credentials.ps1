[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$staging = Join-Path $env:LOCALAPPDATA 'DealAlerterProvision'
if ($staging -ne 'C:\Users\jacob\AppData\Local\DealAlerterProvision') {
    throw 'The provisioning workflow is bound to the reviewed ThinkPad account path.'
}
if (Test-Path -LiteralPath (Join-Path $staging 'secrets.env')) {
    throw 'Staged credentials already exist; refusing to replace them.'
}
New-Item -ItemType Directory -Force -Path $staging | Out-Null
if ((Get-Item -LiteralPath $staging).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Staging must be a normal local directory.'
}
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $staging /inheritance:r /grant:r "*$($sid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Private staging ACL failed' }
$request = [guid]::NewGuid().ToString()
$request | Set-Content -Encoding utf8 -LiteralPath (Join-Path $staging 'request-id.txt')
Write-Output "Private staging prepared. One-time request ID: $request"
Write-Output 'After approval, dispatch provision-thinkpad.yml on main with this request_id. No credentials requested or written yet.'
