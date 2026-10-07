[CmdletBinding()]
param([Parameter(Mandatory)][string]$UserSid)
$ErrorActionPreference='Stop'
$principal=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this setup as administrator to create the watch-settings folder.' }
$sid=New-Object Security.Principal.SecurityIdentifier($UserSid)
if ($sid.Value -notmatch '^S-1-5-21-') { throw 'An individual Windows account SID is required.' }
$runtime='C:\ProgramData\DealAlerter'
$folder=Join-Path $runtime 'ui'
foreach ($path in @($runtime,$folder)) {
    if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Watch settings cannot use a reparse point.' }
}
New-Item -ItemType Directory -Force -Path $folder | Out-Null
$acl=Get-Acl -LiteralPath $folder
$rule=New-Object Security.AccessControl.FileSystemAccessRule($sid,'Modify','ContainerInherit,ObjectInherit','None','Allow')
$acl.SetAccessRule($rule)
Set-Acl -LiteralPath $folder -AclObject $acl
Write-Output 'Only the non-secret watch-settings folder is now editable by the selected account.'
