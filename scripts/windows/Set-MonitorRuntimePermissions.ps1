[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RuntimeDirectory,
    [string]$ReadOnlyOwnerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
)
$ErrorActionPreference = 'Stop'
$root = (Get-Item -LiteralPath $RuntimeDirectory).FullName
$items = @(Get-Item -LiteralPath $root) + @(Get-ChildItem -LiteralPath $root -Recurse -Force)
if ($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Runtime permissions must not follow reparse points' }
$owner = [Security.Principal.SecurityIdentifier]::new($ReadOnlyOwnerSid)
$system = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
$admins = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in @($system, $admins)) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', $inherit, 'None', 'Allow'))
}
$acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($owner, 'ReadAndExecute', $inherit, 'None', 'Allow'))

# Protect secrets before changing the inheritable parent ACL.
$secret = Join-Path $root 'secrets.env'
if (Test-Path -LiteralPath $secret) {
    $private = [Security.AccessControl.FileSecurity]::new()
    $private.SetAccessRuleProtection($true, $false)
    foreach ($sid in @($system, $admins)) {
        $private.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'Allow'))
    }
    Set-Acl -LiteralPath $secret -AclObject $private
}
Set-Acl -LiteralPath $root -AclObject $acl
# Apply inheritance to files as well as directories. Never recursively remove it:
# directory-only (OI)(CI) grants can leave leaf files with an empty protected DACL.
foreach ($child in Get-ChildItem -LiteralPath $root -Force | Where-Object { $_.Name -ne 'secrets.env' }) {
    & icacls.exe $child.FullName /inheritance:e /T /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Runtime inheritance repair failed' }
}
Write-Output 'Runtime files inherit SYSTEM access; secrets retain a separate private ACL.'
