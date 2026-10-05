[CmdletBinding()]
param([string]$StagingDirectory = '')
$ErrorActionPreference = 'Stop'
if (-not $StagingDirectory) { $StagingDirectory = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path '.local\credentials' }
# AppData may have a different view in packaged apps, UAC and runner services.
$staging = [IO.Path]::GetFullPath($StagingDirectory)
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
$linuxPrepare = @'
import os, sys
from pathlib import Path
root = Path('/home/jacob/.local/share/deal-alerter-provision')
root.mkdir(parents=True, exist_ok=True, mode=0o700)
if root.is_symlink() or root.stat().st_uid != os.getuid():
    raise SystemExit('Unexpected staging owner or symlink')
root.chmod(0o700)
if (root / 'secrets.env').exists():
    raise SystemExit('WSL staging credentials already exist')
(root / 'request-id.txt').write_text(sys.argv[1], encoding='utf-8')
'@
& wsl.exe -d Ubuntu -- python3 -c $linuxPrepare $request
if ($LASTEXITCODE -ne 0) { throw 'Private WSL staging preparation failed' }
Write-Output "Private staging prepared. One-time request ID: $request"
Write-Output 'After approval, dispatch provision-thinkpad.yml on main with this request_id. No credentials requested or written yet.'
