# tpmheal-install - register the TpmHeal scheduled task so nothing has to be run by hand.
#
# The old tpmfix claimed "the TpmHeal task also fixes it on boot/resume", but no such task was
# ever registered (Get-ScheduledTask showed only Microsoft's own Tpm-Maintenance and
# Tpm-HASCertRetr). That is the other half of why the fix "did not last": after a reboot
# nothing healed anything, so it always needed re-invoking.
#
# Triggers: at startup (1 min delay, after the TPM stack is up), on resume from
# sleep/hibernate, and daily as a backstop. Runs as SYSTEM, non-destructive, idempotent.
[CmdletBinding()]
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$taskName = 'TpmHeal'
$heal = Join-Path $PSScriptRoot 'tpmheal.ps1'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Needs admin. Re-run from an elevated prompt." -ForegroundColor Red
    exit 1
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed the existing $taskName task." -ForegroundColor DarkGray
}

if ($Uninstall) { Write-Host "$taskName uninstalled." -ForegroundColor Green; exit 0 }

if (-not (Test-Path $heal)) { Write-Host "Missing $heal" -ForegroundColor Red; exit 1 }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$heal`" -Quiet"

$atStartup = New-ScheduledTaskTrigger -AtStartup
$atStartup.Delay = 'PT1M'
$daily = New-ScheduledTaskTrigger -Daily -At '12:00'

# Resume from sleep/hibernate: Power-Troubleshooter 1 is logged on every wake.
$onResume = New-CimInstance -CimClass (Get-CimClass -ClassName MSFT_TaskEventTrigger `
        -Namespace Root/Microsoft/Windows/TaskScheduler) -ClientOnly
$onResume.Enabled = $true
$onResume.Subscription = @'
<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]</Select></Query></QueryList>
'@

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $taskName -Action $action `
    -Trigger @($atStartup, $onResume, $daily) -Principal $principal -Settings $settings `
    -Description 'Heals the TPM in place (never clears it) at boot, on resume, and daily.' | Out-Null

Write-Host "Registered $taskName (boot + resume + daily, runs as SYSTEM)." -ForegroundColor Green
Write-Host "It runs tpmheal.ps1 -Quiet; results land in the Application log, source TpmHeal." -ForegroundColor DarkGray
