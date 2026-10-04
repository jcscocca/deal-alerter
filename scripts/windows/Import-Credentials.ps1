[CmdletBinding()]
param([Parameter(Mandatory)][string]$PythonExe)
$ErrorActionPreference = 'Stop'
# Capture credentials entirely inside Python; never send them to PowerShell output.
$importer = @'
from pathlib import Path
import subprocess
source = '/home/jacob/.local/share/deal-alerter-provision/secrets.env'
reader = "from pathlib import Path; import sys; sys.stdout.buffer.write(Path(sys.argv[1]).read_bytes())"
result = subprocess.run(['wsl.exe','-d','Ubuntu','--','python3','-c',reader,source], capture_output=True, timeout=30)
if result.returncode:
    raise SystemExit('WSL credential staging is unavailable')
root = Path(r'C:\Users\jacob\AppData\Local\DealAlerterProvision')
if root.is_symlink() or not (root / 'request-id.txt').is_file():
    raise SystemExit('Prepare the private Windows staging directory first')
with (root / 'secrets.env').open('xb') as stream:
    stream.write(result.stdout)
    stream.flush()
    import os
    os.fsync(stream.fileno())
remove = "from pathlib import Path; import sys; Path(sys.argv[1]).unlink()"
result = subprocess.run(['wsl.exe','-d','Ubuntu','--','python3','-c',remove,source],capture_output=True,timeout=30)
if result.returncode:
    raise SystemExit('Windows import succeeded; remove the private WSL staging copy locally')
(root / 'request-id.txt').unlink()
print('Credentials imported into private Windows staging; values hidden.')
'@
$importer | & $PythonExe -
if ($LASTEXITCODE -ne 0) { throw 'Credential import did not complete' }
