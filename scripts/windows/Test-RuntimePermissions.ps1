# Regression for the access-denied startup failure, without touching live state.
$ErrorActionPreference = 'Stop'
$fixture = Join-Path $env:TEMP ('deal-alerter-acl-' + [guid]::NewGuid())
$nested = Join-Path $fixture 'venv\Scripts'
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
New-Item -ItemType Directory -Path $nested -Force | Out-Null
$leaf = Join-Path $nested 'runtime.txt'
$secret = Join-Path $fixture 'secrets.env'
'fixture' | Set-Content -LiteralPath $leaf
'not-a-real-secret' | Set-Content -LiteralPath $secret
try {
    $broken = [Security.AccessControl.FileSecurity]::new()
    $broken.SetAccessRuleProtection($true, $false)
    Set-Acl -LiteralPath $leaf -AclObject $broken
    if ((Get-Acl -LiteralPath $leaf).Access.Count -ne 0) { throw 'Fixture did not reproduce the empty DACL' }
    & (Join-Path $PSScriptRoot 'Set-MonitorRuntimePermissions.ps1') -RuntimeDirectory $fixture -ReadOnlyOwnerSid $sid
    if ((Get-Content -LiteralPath $leaf).Trim() -ne 'fixture') { throw 'Owner cannot read the repaired file' }
    $access = (Get-Acl -LiteralPath $leaf).GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
    if (-not ($access | Where-Object { $_.IdentityReference.Value -eq 'S-1-5-18' -and $_.IsInherited -and ($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq [Security.AccessControl.FileSystemRights]::FullControl })) { throw 'SYSTEM did not inherit full access' }
    $secretAcl = Get-Acl -LiteralPath $secret
    $privateRules = $secretAcl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
    if (-not $secretAcl.AreAccessRulesProtected -or $privateRules.Count -ne 2 -or ($privateRules | Where-Object { $_.IdentityReference.Value -notin 'S-1-5-18','S-1-5-32-544' })) { throw 'Secret ACL is not private' }
    Write-Output 'Empty file DACL repaired; nested SYSTEM access and private secrets verified.'
} finally {
    # Let the normal temporary-directory cleanup reclaim this nonsecret fixture.
    & icacls.exe $fixture /grant:r "*$($sid):F" /T /Q | Out-Null
}
