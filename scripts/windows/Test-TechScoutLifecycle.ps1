# Scoped process identity, preference rollback and acceptance without live changes.
[CmdletBinding()]
param([string]$PythonExe=(Get-Command python.exe -ErrorAction Stop).Source)
$ErrorActionPreference='Stop'
foreach ($script in Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1') {
    $tokens=$null; $errors=$null
    $null=[Management.Automation.Language.Parser]::ParseFile($script.FullName,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
}
. (Join-Path $PSScriptRoot 'TechScout-Lifecycle.ps1')
$root=Join-Path ([IO.Path]::GetTempPath()) ('techscout lifecycle-'+[Guid]::NewGuid().ToString('N'))
$holder=$null
$childId=0
try {
    $runtime=Join-Path $root 'runtime'
    $backup=Join-Path $root 'backup'
    New-Item -ItemType Directory -Force -Path (Join-Path $runtime 'ui'),$backup | Out-Null
    $controls=Join-Path $runtime 'ui\watches.json'
    $old='{"version":1,"mode":"all","watches":[]}'
    [IO.File]::WriteAllText($controls,$old)
    Backup-TechScoutControls $runtime $backup
    [IO.File]::WriteAllText($controls,'{"version":3,"mode":"paused","include_target_notices":false,"watches":[]}')
    Restore-TechScoutControls $runtime $backup
    if ([IO.File]::ReadAllText($controls) -ne $old) { throw 'Rollback must restore the original preference schema/content exactly.' }
    Remove-Item -LiteralPath $controls
    $absentBackup=Join-Path $root 'absent-backup'
    Backup-TechScoutControls $runtime $absentBackup
    [IO.File]::WriteAllText($controls,'{"version":3}')
    Restore-TechScoutControls $runtime $absentBackup
    if (Test-Path -LiteralPath $controls) { throw 'Rollback must restore preference absence, not leave a new-schema file behind.' }

    $script:fixtureProcesses=@(
        [PSCustomObject]@{ProcessId=100;CommandLine='pythonw -m alerters.techscout --serve --settings settings.json';SessionId=1},
        [PSCustomObject]@{ProcessId=200;CommandLine='pythonw -m http.server 8768';SessionId=1})
    $script:fixtureRecognized=$true
    $script:stopped=@()
    function Get-CimInstance { $script:fixtureProcesses }
    function Get-Process($Id) { $script:fixtureProcesses | Where-Object { $_.ProcessId -eq $Id } }
    function Invoke-CimMethod { [PSCustomObject]@{ReturnValue=0;Sid='S-1-5-21-1-2-3-1001'} }
    function Invoke-TestInspection {
        $global:LASTEXITCODE=0
        if ($args[0] -eq '-c') { return '{"error":null,"version":3,"mode":"all"}' }
        return (@{recognized=$script:fixtureRecognized;is_techscout=$true;app_scope=$true;pid=100;data_directory='C:\Users\shopper\TechScout';executable='C:\Users\shopper\TechScout\venv\Scripts\pythonw.exe'} | ConvertTo-Json -Compress)
    }
    function Stop-Process($Id) { $script:stopped+=([int]$Id); $script:fixtureProcesses=@($script:fixtureProcesses | Where-Object { $_.ProcessId -ne $Id }) }
    $backends=@(Get-TechScoutBackends 'Invoke-TestInspection' $root $root)
    if ($backends.Count -ne 1 -or $backends[0].pid -ne 100) { throw 'An unrelated port-8768 process cannot be recognized as TechScout.' }
    $direct=[PSCustomObject]@{pid=100;owner_sid='S-1-5-21-1-2-3-1001';data_directory='C:\Users\shopper\TechScout';session_id=1}
    $child=[PSCustomObject]@{pid=101;venv_wrapper_pid=100;owner_sid=$direct.owner_sid;data_directory=$direct.data_directory;session_id=1}
    if (-not (Test-TechScoutBackendOwner @($direct) $direct.owner_sid $direct.data_directory -StartedPid 100)) { throw 'Direct startup PID proof was rejected.' }
    if (-not (Test-TechScoutBackendOwner @($child) $direct.owner_sid $direct.data_directory -StartedPid 100)) { throw 'Venv base-child startup proof was rejected.' }
    if (Test-TechScoutBackendOwner @($child) $direct.owner_sid $direct.data_directory -StartedPid 999) { throw 'Another process cannot satisfy startup readiness.' }
    if (Test-TechScoutBackendOwner @($child) 'S-1-5-18' $direct.data_directory) { throw 'SYSTEM cannot satisfy normal-account acceptance.' }
    Stop-TechScoutBackends $backends 'Invoke-TestInspection' $root $root
    if (($script:stopped -join ',') -ne '100' -or -not (Get-Process -Id 200)) { throw 'Only the independently scoped backend may be stopped.' }
    $script:fixtureProcesses+=([PSCustomObject]@{ProcessId=100;CommandLine='pythonw -m alerters.techscout --serve';SessionId=1})
    $script:fixtureRecognized=$false
    $failed=$false
    try { $null=@(Get-TechScoutBackends 'Invoke-TestInspection' $root $root) } catch { $failed=$_.Exception.Message -like '*unrecognized executable*' }
    if (-not $failed) { throw 'Unknown backend identity must fail closed before process stop.' }

    $now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $health=@{pid=300;heartbeat=$now;started=$now-10;dry_run=$false;jobs=@{
        reddit=@{kind='reddit';last_success=$now};slickdeals=@{kind='slickdeals';last_success=$now};ebay=@{kind='legacy';url='ebay';last_success=$now}}}
    $health | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $runtime 'health.json')
    @{capabilities=@('watches-v3')} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $runtime 'shopping-sources.json')
    $accepted=Test-MonitorReleaseAcceptance $runtime 'Invoke-TestInspection' $root -RequireSourceCycle
    if ($accepted.source_cycle_status -ne 'verified' -or $accepted.controls_version -ne 3) { throw 'Acceptance lost source-cycle/control proof.' }
    $health.jobs.retired=@{kind='newegg';last_success=$now}
    $health | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $runtime 'health.json')
    $failed=$false
    try { $null=Test-MonitorReleaseAcceptance $runtime 'Invoke-TestInspection' $root } catch { $failed=$_.Exception.Message -like '*Retired or unexpected*' }
    if (-not $failed) { throw 'A heartbeat must not hide retired active jobs.' }
    $health.jobs.Remove('retired')
    $health | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $runtime 'health.json')
    @{capabilities=@('watches-v2')} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $runtime 'shopping-sources.json')
    $failed=$false
    try { $null=Test-MonitorReleaseAcceptance $runtime 'Invoke-TestInspection' $root } catch { $failed=$_.Exception.Message -like '*capability missing*' }
    if (-not $failed) { throw 'Old watch capability must not pass current acceptance.' }

    # Real same-architecture wrapper/base-child inspection against a temporary
    # no-network fixture module. No live backend, port or protected runtime used.
    Remove-Item Function:Get-CimInstance,Function:Get-Process,Function:Invoke-CimMethod,Function:Stop-Process -ErrorAction SilentlyContinue
    $fixtureApp=Join-Path $root 'app'
    $local=Join-Path $root 'local'
    New-Item -ItemType Directory -Force -Path (Join-Path $fixtureApp 'alerters\techscout'),$local | Out-Null
    [IO.File]::WriteAllText((Join-Path $fixtureApp 'alerters\__init__.py'),'')
    [IO.File]::WriteAllText((Join-Path $fixtureApp 'alerters\techscout\__init__.py'),'')
    [IO.File]::WriteAllText((Join-Path $fixtureApp 'alerters\techscout\__main__.py'),"import os,sys; print(os.getpid(),flush=True); sys.stdin.readline()")
    & $PythonExe -m venv --without-pip (Join-Path $local 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Fixture venv could not be created.' }
    $venvPython=Join-Path $local 'venv\Scripts\python.exe'
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$venvPython
    $start.Arguments='-m alerters.techscout --serve --settings "'+(Join-Path $local 'settings.json')+'" --output "'+(Join-Path $local 'reports')+'"'
    $start.WorkingDirectory=$fixtureApp
    $start.UseShellExecute=$false
    $start.CreateNoWindow=$true
    $start.RedirectStandardInput=$true
    $start.RedirectStandardOutput=$true
    $start.RedirectStandardError=$true
    $holder=[Diagnostics.Process]::Start($start)
    $childId=[int]$holder.StandardOutput.ReadLine()
    if (-not $childId) { throw 'Fixture process did not start.' }
    $helper=Join-Path $PSScriptRoot 'techscout_process.py'
    $raw=& $PythonExe $helper --pid $childId --app $fixtureApp
    if ($LASTEXITCODE -ne 0 -or -not (($raw -join '') | ConvertFrom-Json).recognized) { throw 'Native process cwd/executable/venv identity was not recognized.' }
    $raw=& $PythonExe $helper --pid $childId --app (Join-Path $root 'different-app')
    if ($LASTEXITCODE -ne 0 -or (($raw -join '') | ConvertFrom-Json).recognized) { throw 'A different actual cwd cannot authorize process stop.' }
    $holder.StandardInput.WriteLine('release')
    $holder.StandardInput.Flush()
    if (-not $holder.WaitForExit(10000)) { throw 'Fixture process did not exit.' }
    Write-Output 'TechScout process scoping, real Windows cwd/venv inspection, preference rollback, parser and monitor acceptance regressions passed; no live mutations.'
} finally {
    if ($holder) {
        if (-not $holder.HasExited) {
            try { $holder.StandardInput.WriteLine('release');$holder.StandardInput.Flush();$null=$holder.WaitForExit(2000) } catch {}
            if (-not $holder.HasExited) { $holder.Kill() }
        }
        $holder.Dispose()
    }
    if ($childId -and (Get-Process -Id $childId -ErrorAction SilentlyContinue)) { Stop-Process -Id $childId -Force }
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
exit 0
