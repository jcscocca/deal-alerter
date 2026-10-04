# Exercise the actual helper under Windows PowerShell 5.1 without live mutations.
$ErrorActionPreference = 'Stop'
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Enable-Monitor.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw 'Installer syntax errors' }
$helper = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Invoke-Gh' }, $true)
Invoke-Expression $helper.Extent.Text
function gh {
    $script:received = @($args)
    $global:LASTEXITCODE = 0
    return '{"ok":true}'
}
$calls = $ast.FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Invoke-Gh' }, $true)
foreach ($call in $calls) {
    $script:received = @()
    $result = Invoke-Expression $call.Extent.Text
    if ($script:received.Count -lt 2 -or $script:received[0] -notin 'api','variable','run') {
        throw 'GitHub CLI arguments were collapsed or omitted'
    }
    if (-not ($result | ConvertFrom-Json).ok) { throw 'GitHub CLI result lost' }
}
if ($calls.Count -ne 5) { throw 'Update this regression check for the installer calls' }
Write-Output 'All five installer CLI calls preserve separate arguments; no live operations performed.'
