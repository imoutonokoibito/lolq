$ErrorActionPreference = 'Stop'
$installDir = Join-Path $env:LOCALAPPDATA 'Programs\LoLQ'
$env:LOLQ_DATA_DIR = Join-Path $env:RUNNER_TEMP 'lolq-smoke-data'
$setup = (Resolve-Path 'dist/installer/LoLQ-Setup.exe').Path
function Install-LoLQ {
    $p = Start-Process $setup -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/LOG=$env:RUNNER_TEMP\lolq-install.log" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Installer exit $($p.ExitCode)" }
}
function Wait-LoLQ {
    for ($i=0; $i -lt 45; $i++) {
        try { return Invoke-RestMethod 'http://127.0.0.1:17653/api/session' -Headers @{'X-LoLQ-Client'='web'} -TimeoutSec 3 } catch { Start-Sleep -Seconds 1 }
    }
    throw 'Connector failed to start'
}
Write-Host 'Installing'
Install-LoLQ
Write-Host 'Starting connector'
$exe = Join-Path $installDir 'LoLQ.exe'
Start-Process $exe -ArgumentList '--background'
$session = Wait-LoLQ
$headers = @{'X-LoLQ-Client'='web'; Authorization="Bearer $($session.token)"; Origin='https://imoutosuki.com'}
$config = Invoke-RestMethod 'http://127.0.0.1:17653/api/config' -Headers $headers
if ($config.enabled -ne $false) { throw 'New installs must begin paused' }
$config.bans = @('Ahri')
Invoke-RestMethod 'http://127.0.0.1:17653/api/config' -Method Post -ContentType 'application/json' -Body ($config | ConvertTo-Json -Depth 10) -Headers $headers | Out-Null
Start-Sleep -Seconds 3
$status = Invoke-RestMethod 'http://127.0.0.1:17653/api/status' -Headers $headers
if (!$status.worker) { throw 'Picker worker not running' }
if (!(Test-Path 'HKCU:\Software\Classes\lolq\shell\open\command')) { throw 'Open LoLQ link not registered' }
if (!(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run').LoLQ) { throw 'Startup entry missing' }
Write-Host 'Initial install, worker and settings verified'
# Reopening must reuse the first connector, not spawn a competing worker.
Write-Host 'Checking duplicate launch'
Start-Process $exe -ArgumentList '--background' -Wait
Write-Host 'Duplicate launch exited'
$again = Wait-LoLQ
if ($again.token -ne $session.token) { throw 'Duplicate launch replaced the connector' }
Write-Host 'Upgrading'
Install-LoLQ
Write-Host 'Restarting upgraded app'
Start-Process $exe -ArgumentList '--background'
$session = Wait-LoLQ
$headers.Authorization = "Bearer $($session.token)"
$config = Invoke-RestMethod 'http://127.0.0.1:17653/api/config' -Headers $headers
if ($config.bans[0] -ne 'Ahri') { throw 'Upgrade lost configuration' }
Write-Host 'Uninstalling'
$p = Start-Process (Join-Path $installDir 'unins000.exe') -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
if ($p.ExitCode -ne 0) { throw 'Uninstall failed' }
if (Test-Path $exe) { throw 'Uninstall left executable' }
if (Test-Path 'HKCU:\Software\Classes\lolq') { throw 'Uninstall left URL registration' }
try { Invoke-WebRequest 'http://127.0.0.1:17653/api/health' -Headers @{'X-LoLQ-Client'='web'} -TimeoutSec 2 | Out-Null; throw 'Connector survived uninstall' } catch {
    if ($_.Exception.Message -eq 'Connector survived uninstall') { throw }
}
if (!(Test-Path (Join-Path $env:LOLQ_DATA_DIR 'config.json'))) { throw 'Uninstall should preserve personal settings' }
Write-Host 'Install, worker launch, duplicate launch, upgrade persistence and uninstall passed.'
