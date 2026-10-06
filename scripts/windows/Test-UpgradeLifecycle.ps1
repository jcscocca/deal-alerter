[CmdletBinding()]
param([string]$PythonExe = (Get-Command python.exe -ErrorAction Stop).Source)
$ErrorActionPreference='Stop'
$checkout=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$temporaryRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot=Join-Path $temporaryRoot ('monitor upgrade test-'+[Guid]::NewGuid().ToString('N'))
$resolvedTestRoot=[IO.Path]::GetFullPath($testRoot)
if (-not $resolvedTestRoot.StartsWith($temporaryRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Test path escapes temporary directory.' }
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Update-Monitor.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Invoke-WriterLockProbe','Wait-MonitorStopped','Start-EnabledMonitorTasks')) {
    $definition=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if (-not $definition) { throw "Missing updater helper: $name" }
    . ([scriptblock]::Create($definition.Extent.Text))
}
# Stub only scheduled tasks. Contention uses a real OS lock and native Python
# under Windows PowerShell 5.1 with ErrorActionPreference=Stop.
function Get-ScheduledTask($TaskName) {
    foreach($name in $TaskName) { [PSCustomObject]@{TaskName=$name;State='Disabled'} }
}
$holder=$null
try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    $lockPath=Join-Path $testRoot 'writer lock'
    $holderCode="import sys,time; from pathlib import Path; sys.path.insert(0,sys.argv[1]); from dealcore.locking import WriterLock; lock=WriterLock(Path(sys.argv[2])); lock.__enter__(); print('READY',flush=True); time.sleep(4); lock.__exit__()"
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$PythonExe
    $start.Arguments='-c "'+$holderCode+'" "'+$checkout+'" "'+$lockPath+'"'
    $start.UseShellExecute=$false
    $start.CreateNoWindow=$true
    $start.RedirectStandardOutput=$true
    $start.RedirectStandardError=$true
    $holder=[Diagnostics.Process]::Start($start)
    if ($holder.StandardOutput.ReadLine() -ne 'READY') { throw ('Lock holder failed: '+$holder.StandardError.ReadToEnd()) }
    $holderId=$holder.Id
    $probe=Invoke-WriterLockProbe $PythonExe $checkout $lockPath
    if ($probe.exit_code -ne 75 -or $probe.diagnostic) { throw 'Busy lock must be a quiet, retryable exit status.' }
    Wait-MonitorStopped @('DealAlerter-Hardware','DealAlerter-Watchdog') $holderId $PythonExe $checkout $lockPath -Attempts 10 -RetrySeconds 1
    if (-not $holder.HasExited) { throw 'Updater proceeded while the original writer still existed.' }
    $probe=Invoke-WriterLockProbe $PythonExe $checkout $lockPath
    if ($probe.exit_code -ne 0) { throw 'Released OS lock must become available.' }
    function Get-ScheduledTask($TaskName) { [PSCustomObject]@{TaskName=$TaskName;State='Running'} }
    $failed=$false
    try { Wait-MonitorStopped @('DealAlerter-Hardware') $holderId $PythonExe $checkout $lockPath -Attempts 1 -RetrySeconds 0 } catch { $failed=$_.Exception.Message -like 'Hardware writer/tasks did not stop*' }
    if (-not $failed) { throw 'An empty lock cannot authorize replacement while Task Scheduler still reports a running instance.' }
    $probe=Invoke-WriterLockProbe $PythonExe $checkout $testRoot
    if ($probe.exit_code -ne 2 -or -not $probe.diagnostic) { throw 'Unexpected I/O errors must not masquerade as lock contention.' }
    $failed=$false
    try { Wait-MonitorStopped @('DealAlerter-Hardware') $holderId $PythonExe $checkout $testRoot -Attempts 1 -RetrySeconds 0 } catch { $failed=$_.Exception.Message -like 'Writer lock probe failed:*' }
    if (-not $failed) { throw 'Unexpected probe errors must fail closed before replacement.' }
    $script:events=@()
    $script:fixtureRuntime=$testRoot
    $script:fixturePreviousPid=$holderId
    @{pid=$holderId;heartbeat=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();dry_run=$false} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $testRoot 'health.json')
    function Get-ScheduledTask($TaskName) { [PSCustomObject]@{TaskName=$TaskName;State='Ready'} }
    function Enable-ScheduledTask($TaskName) { $script:events+=('enable '+$TaskName) }
    function Start-ScheduledTask($TaskName) {
        $script:events+=('start '+$TaskName)
        if ($TaskName -eq 'DealAlerter-Hardware') {
            @{pid=($script:fixturePreviousPid+1);heartbeat=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();dry_run=$false} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $script:fixtureRuntime 'health.json')
        }
    }
    function Start-Sleep($Seconds) {}
    $tasks=@{'DealAlerter-Hardware'=@{enabled=$true};'DealAlerter-Watchdog'=@{enabled=$true}}
    $health=Start-EnabledMonitorTasks $tasks $testRoot $holderId
    if ($health.pid -eq $holderId -or ($script:events -join '|') -ne 'enable DealAlerter-Hardware|start DealAlerter-Hardware|enable DealAlerter-Watchdog|start DealAlerter-Watchdog') { throw 'Restart must establish a new hardware heartbeat before enabling or starting the watchdog.' }
    @{pid=$holderId;heartbeat=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();dry_run=$false} | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $testRoot 'health.json')
    $script:events=@()
    function Start-ScheduledTask($TaskName) { $script:events+=('start '+$TaskName) }
    $failed=$false
    try { $null=Start-EnabledMonitorTasks $tasks $testRoot $holderId } catch { $failed=$_.Exception.Message -like '*no new process*' }
    if (-not $failed -or 'start DealAlerter-Watchdog' -notin $script:events) { throw 'Old heartbeat cannot mask failed startup; enabled watchdog recovery must remain available.' }
    $script:events=@()
    $tasks['DealAlerter-Hardware'].enabled=$false
    $tasks['DealAlerter-Watchdog'].enabled=$false
    $null=Start-EnabledMonitorTasks $tasks $testRoot $holderId
    if ($script:events.Count) { throw 'Previously disabled tasks must remain disabled.' }
    Write-Output 'Busy lock retries, stopped writer, unexpected I/O and task restart order verified without live mutations.'
} finally {
    if ($holder) { if (-not $holder.HasExited) { $holder.Kill() }; $holder.Dispose() }
    if (Test-Path -LiteralPath $resolvedTestRoot) {
        if ([IO.Path]::GetFullPath($resolvedTestRoot) -ne $testRoot -or -not $resolvedTestRoot.StartsWith($temporaryRoot,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test cleanup path.' }
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
    }
}
# Negative probe cases deliberately leave a nonzero native exit status. GitHub's
# PowerShell wrapper otherwise propagates it after this successful test script.
exit 0
