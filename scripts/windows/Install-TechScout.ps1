[CmdletBinding()]
param([switch]$NoStartup)
$ErrorActionPreference='Stop'
$local=Join-Path $env:LOCALAPPDATA 'TechScout'
New-Item -ItemType Directory -Force -Path $local | Out-Null
$app='C:\ProgramData\DealAlerter\app'
$basePython='C:\ProgramData\DealAlerter\venv\Scripts\python.exe'
# Resolve MSIX/AppData redirection before writing shortcuts used outside the app.
$local = & $basePython -c 'import pathlib,sys; print(pathlib.Path(sys.argv[1]).resolve())' $local
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $local)) { throw 'Cannot resolve the TechScout data directory.' }
$venv=Join-Path $local 'venv'
$python=Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath (Join-Path $app 'alerters\techscout\web\workspace.js'))) { throw 'Deploy the merged monitor integration before installing shortcuts.' }
if (-not (Test-Path -LiteralPath $python)) {
    & $basePython -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare the per-user TechScout environment.' }
}
# Keep optional shopping dependencies out of the protected monitor environment.
& $python -m pip install --disable-pip-version-check -r (Join-Path $app 'requirements-techscout.txt')
if ($LASTEXITCODE -ne 0) { throw 'TechScout dependencies could not be installed.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'TechScout dependencies are inconsistent.' }
$launcher=Join-Path $local 'Start-TechScout.ps1'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Start-TechScout.ps1') -Destination $launcher -Force
$shell=New-Object -ComObject WScript.Shell
$powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
function New-TechScoutShortcut([string]$Folder,[bool]$OpenBrowser) {
    $shortcut=$shell.CreateShortcut((Join-Path $Folder 'TechScout.lnk'))
    $shortcut.TargetPath=$powershell
    $shortcut.Arguments='-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+$launcher+'"'+$(if ($OpenBrowser) {' -OpenBrowser'} else {''})
    $shortcut.WorkingDirectory=$local
    $shortcut.WindowStyle=7
    $shortcut.Description='TechScout deals, watches and alerts'
    $shortcut.Save()
}
New-TechScoutShortcut ([Environment]::GetFolderPath('Desktop')) $true
New-TechScoutShortcut ([Environment]::GetFolderPath('Programs')) $true
if (-not $NoStartup) { New-TechScoutShortcut ([Environment]::GetFolderPath('Startup')) $false }
Write-Output 'TechScout desktop and Start menu shortcuts installed.'
if (-not $NoStartup) { Write-Output 'The dashboard also starts hidden at sign-in.' }
