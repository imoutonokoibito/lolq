# tpmfix - heal the TPM now. Thin wrapper over tpmheal.ps1 (the shared, non-destructive path).
#
# -AllowClear opts into the destructive path: it arms a boot-time TPM clear (PPI op-22), which
# wipes the SRK, owner auth and every key sealed to the TPM. That used to be armed
# automatically and is exactly why the fix never lasted - each clear destroyed the state the
# previous run had just provisioned. It is now opt-in, and refuses to run while anything
# depends on those keys.
[CmdletBinding()]
param([switch]$AllowClear)

$ErrorActionPreference = 'SilentlyContinue'
$heal = Join-Path $PSScriptRoot 'tpmheal.ps1'

& $heal
$healed = ($LASTEXITCODE -eq 0)

if ($healed -or -not $AllowClear) {
    if (-not $healed) {
        Write-Host ""
        Write-Host "Run 'tpmfix -AllowClear' only if you accept losing TPM-sealed keys." -ForegroundColor DarkGray
    }
    exit $LASTEXITCODE
}

# Destructive path, explicitly requested. Guard the things a clear would break.
$blockers = @()
$bitlocker = Get-BitLockerVolume | Where-Object { $_.ProtectionStatus -ne 'Off' -or $_.VolumeStatus -ne 'FullyDecrypted' }
if ($bitlocker) { $blockers += "BitLocker is active on: $(($bitlocker.MountPoint) -join ', ')" }
$ngc = Join-Path $env:WINDIR 'ServiceProfiles\LocalService\AppData\Local\Microsoft\Ngc'
if ((Test-Path $ngc) -and (Get-ChildItem $ngc -ErrorAction SilentlyContinue)) {
    $blockers += "Windows Hello (PIN/biometrics) is enrolled and will need re-enrolling"
}

if ($blockers) {
    Write-Host ""
    Write-Host "Refusing to clear the TPM - these depend on its keys:" -ForegroundColor Red
    foreach ($b in $blockers) { Write-Host "   - $b" -ForegroundColor Red }
    Write-Host "Back up your BitLocker recovery key / remove the PIN first, then re-run." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Arming a boot-time TPM clear. Keys sealed to the TPM will be lost." -ForegroundColor Yellow
$answer = Read-Host "Type CLEAR to confirm"
if ($answer -ne 'CLEAR') { Write-Host "Cancelled - nothing armed." -ForegroundColor Green; exit 1 }

$tpm = Get-CimInstance -Namespace 'root/cimv2/Security/MicrosoftTpm' -ClassName Win32_Tpm
try {
    $null = Invoke-CimMethod -InputObject $tpm -MethodName SetPhysicalPresenceRequest -Arguments @{ Request = [uint32]22 }
    # Marker so the TpmHeal task does not cancel a clear that was armed on purpose.
    Set-Content -Path (Join-Path $PSScriptRoot '.clear-armed') -Value (Get-Date -Format s) -Encoding utf8
    Write-Host "Armed. Reboot and accept the firmware prompt; TpmHeal re-provisions after boot." -ForegroundColor Yellow
} catch {
    Write-Host "Could not arm the clear: $($_.Exception.Message)" -ForegroundColor Red
}
exit 1
