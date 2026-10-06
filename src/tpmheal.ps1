# tpmheal - get the TPM back to ready, unattended, however it broke.
#
# The actual fault chain on this machine (diagnosed 2026-10-06 from the live event log
# and TPM state), root cause first:
#   1. Intel PTT intermittently CHANGES/LOSES the SRK across S3 resume (System 519
#      "SRK has changed or is not present"; ~9 of 107 resumes). This is a PTT firmware
#      bug. Acer's latest BIOS for the PT516-52s is V1.08 (2022) - already installed -
#      and ships no fix, so the SRK loss itself cannot be eliminated on this hardware.
#   2. When the SRK changes, the auth values Windows holds no longer match, so auth
#      attempts fail and the TPM enters DICTIONARY-ATTACK LOCKOUT (PTT policy: MaxTries
#      31, recovers 1 try / 600s, full recovery 86400s). GetDictionaryAttackParameters
#      confirms this.
#   3. A locked-out TPM refuses Clear-Tpm ("The TPM is currently locked out"), so the
#      OLD version of this script escalated to a PPI op-22 BOOT CLEAR - a destructive
#      wipe that, on reboot, loses the SRK again and re-arms itself. That is the exact
#      1793 -> 519 ByPPI -> 1027 -> 1025 loop the original tpmfix had. It was NOT gone:
#      an op-22 was found armed on 2026-10-06 15:45.
#
# Correct, non-destructive recovery (this version), and nothing here ever reboots:
#   1. heal in place     - Enable auto-provisioning + Tpm-Maintenance + Initialize-Tpm.
#                          When not locked out, Windows re-provisions silently in ~2s
#                          (observed 2026-10-05 23:45: 519 -> 1025 "ready", no clear).
#   2. reset the lockout - ResetAuthLockOut with the stored owner auth, then re-provision.
#                          This is the canonical fix for DA lockout: no clear, no reboot.
#   3. runtime clear     - Clear-Tpm (re-provision in place, no reboot) ONLY as a last
#                          resort and ONLY when nothing is sealed to the TPM.
# This script NEVER arms a PPI boot clear (op-22). A genuinely stuck PTT lockout also
# clears on its own power-cycle, so a plain reboot is a safe fallback the user can take.
# Any leftover op-22 from an older run or by hand is CANCELLED on every run.
#
# Exit codes: 0 = TPM ready, 1 = still not ready (lockout still decaying, or a reboot /
# firmware attention needed). Never leaves a destructive action armed.
[CmdletBinding()]
param([switch]$Quiet, [switch]$NoClear)

$ErrorActionPreference = 'SilentlyContinue'

function Say($text, $color) {
    if (-not $Quiet) {
        if ($color) { Write-Host $text -ForegroundColor $color } else { Write-Host $text }
    }
}

function Log($text) {
    # One line per run in the event log, so unattended runs stay auditable.
    $null = New-EventLog -LogName Application -Source 'TpmHeal' -ErrorAction SilentlyContinue
    Write-EventLog -LogName Application -Source 'TpmHeal' -EntryType Information `
        -EventId 1000 -Message $text -ErrorAction SilentlyContinue
}

function Ready() {
    $info = tpmtool getdeviceinformation 2>$null
    $storage = [bool]($info -match 'Ready For Storage:\s*True')
    $clear = [bool]($info -match 'Clear Needed To Recover:\s*True')
    return ($storage -and (-not $clear))
}

# A clear armed by the old tpmfix (or by hand) fires at the next boot and undoes everything.
# Request 0 cancels any pending physical-presence request. Only leftovers get cancelled: a
# clear the user armed on purpose via "tpmfix -AllowClear" drops a marker, and that marker is
# respected until the boot that consumes it.
function DisarmPendingClear() {
    $marker = Join-Path $PSScriptRoot '.clear-armed'
    if (Test-Path $marker) {
        $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
        if ((Get-Item $marker).LastWriteTime -gt $boot) {
            Say "   A deliberate clear is armed (tpmfix -AllowClear); leaving it alone." 'DarkGray'
            return
        }
        Remove-Item $marker -Force   # survived a boot, so it has already fired
    }
    $tpm = Get-CimInstance -Namespace 'root/cimv2/Security/MicrosoftTpm' -ClassName Win32_Tpm
    if (-not $tpm) { return }
    try {
        $null = Invoke-CimMethod -InputObject $tpm -MethodName SetPhysicalPresenceRequest `
            -Arguments @{ Request = [uint32]0 }
        Say "   Cancelled any leftover boot-time TPM clear request." 'DarkGray'
    } catch {}
}

if (Ready) {
    DisarmPendingClear
    Say "TPM is READY - nothing to do." 'Green'
    Log 'TPM already ready; leftover clear requests cancelled.'
    exit 0
}

# Anything whose keys live in the TPM must not be surprised by a clear.
function SealedDependencies() {
    $found = @()
    $protected = Get-BitLockerVolume | Where-Object {
        $_.ProtectionStatus -ne 'Off' -or $_.VolumeStatus -ne 'FullyDecrypted' -or
        ($_.KeyProtector | Where-Object { $_.KeyProtectorType -like '*Tpm*' })
    }
    if ($protected) { $found += "BitLocker on $(($protected.MountPoint) -join ', ')" }
    $ngc = Join-Path $env:WINDIR 'ServiceProfiles\LocalService\AppData\Local\Microsoft\Ngc'
    if ((Get-ChildItem $ngc -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0) {
        $found += 'Windows Hello enrollment'
    }
    return $found
}

function Provision() {
    Enable-TpmAutoProvisioning | Out-Null
    Start-ScheduledTask -TaskPath '\Microsoft\Windows\TPM\' -TaskName 'Tpm-Maintenance'
    Initialize-Tpm | Out-Null
    for ($i = 0; $i -lt 12; $i++) {
        if (Ready) { return $true }
        Start-Sleep -Seconds 4
    }
    return (Ready)
}

# Canonical dictionary-attack-lockout recovery: reset the lockout with the OS-retained
# owner auth, then let auto-provisioning finish. No clear, no reboot. After an SRK change
# the stored owner auth can be stale, so this may legitimately fail - in which case the
# caller falls through to the (still non-destructive) options, never a boot clear.
function ResetLockout() {
    $own = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\TPM\WMI\Admin' `
        -ErrorAction SilentlyContinue).OwnerAuthFull
    if (-not $own) { return $false }
    $tpm = Get-CimInstance -Namespace 'root/cimv2/Security/MicrosoftTpm' -ClassName Win32_Tpm
    if (-not $tpm) { return $false }
    try {
        $r = Invoke-CimMethod -InputObject $tpm -MethodName 'ResetAuthLockOut' `
            -Arguments @{ OwnerAuth = [string]$own }
        if ($r.ReturnValue -eq 0) {
            Say "   Reset the TPM dictionary-attack lockout with the stored owner auth." 'DarkGray'
            return (Provision)
        }
        Say ("   ResetAuthLockOut returned 0x{0:X8} (owner auth likely stale after the SRK change)." -f $r.ReturnValue) 'DarkGray'
    } catch {
        Say "   ResetAuthLockOut failed: $($_.Exception.Message)" 'DarkGray'
    }
    return $false
}

Say "TPM not ready - healing in place..." 'Cyan'
if (Provision) {
    Say "TPM is READY now." 'Green'
    Log 'TPM healed in place (auto-provisioning + Tpm-Maintenance + Initialize-Tpm).'
    exit 0
}

# The usual reason in-place provisioning fails here is a dictionary-attack lockout that
# followed the SRK change. Try the non-destructive lockout reset before anything else.
if (ResetLockout) {
    Say "TPM is READY now (lockout reset + re-provision)." 'Green'
    Log 'TPM recovered by resetting the DA lockout with owner auth and re-provisioning. No clear.'
    exit 0
}

$info = tpmtool getdeviceinformation 2>$null
$clearNeeded = [bool]($info -match 'Clear Needed To Recover:\s*True')

if (-not $clearNeeded) {
    # In-place heal failed but Windows is not asking for a clear, so a clear would not help.
    Say "TPM still not ready and Windows is not asking for a clear. Check firmware:" 'Yellow'
    Say "   - BIOS > Security: Intel PTT (or fTPM) Enabled" 'Yellow'
    Say "   - BIOS: update it (an SRK that vanishes across sleep is a known PTT firmware bug)" 'Yellow'
    Log 'TPM not ready after in-place heal; no clear requested by Windows. Firmware attention needed.'
    exit 1
}

# A clear is recovery, not a routine. If the TPM keeps falling back into "clear needed", the
# fault is firmware and clearing it on a loop helps nobody - say so and stop.
function RecentClears() {
    $log = Join-Path $PSScriptRoot '.clear-log'
    if (-not (Test-Path $log)) { return @() }
    $cutoff = (Get-Date).AddHours(-24)
    return @(Get-Content $log | Where-Object {
        $parsed = $null
        if ([datetime]::TryParse($_, [ref]$parsed)) { $parsed -gt $cutoff } else { $false }
    })
}

$recent = RecentClears
if ($recent.Count -ge 3) {
    Say "The TPM has needed $($recent.Count) runtime clears in 24h. The SRK-loss-on-resume is a" 'Red'
    Say "PTT firmware bug with no fix (Acer PT516-52s tops out at BIOS V1.08, already installed)," 'Red'
    Say "so clearing again just churns. Letting the lockout decay / rebooting is the safe path." 'Red'
    Log "TPM needed a clear but $($recent.Count) runtime clears already happened in 24h; refusing to churn. No clear."
    exit 1
}

$blockers = SealedDependencies
if ($NoClear -or $blockers) {
    Say "Windows reports the TPM needs a clear to recover, but not clearing it:" 'Yellow'
    if ($NoClear) { Say "   - called with -NoClear" 'Yellow' }
    foreach ($b in $blockers) { Say "   - $b depends on TPM-sealed keys" 'Red' }
    Say "   Back those up / remove them, then run tpmfix." 'Yellow'
    Log "TPM needs a clear; skipped. Blockers: $($blockers -join '; ') NoClear=$NoClear"
    exit 1
}

# Nothing is sealed to this TPM, and Windows says a clear is the recovery path. Do it at
# runtime with the stored owner auth: no reboot, no firmware prompt.
Say "Windows reports the TPM needs a clear to recover. Clearing it now (nothing is sealed to it)..." 'Cyan'
Add-Content -Path (Join-Path $PSScriptRoot '.clear-log') -Value (Get-Date -Format s) -Encoding utf8
$cleared = $false
try {
    Clear-Tpm -ErrorAction Stop | Out-Null
    $cleared = $true
} catch {
    Say "   Runtime clear refused: $($_.Exception.Message)" 'DarkGray'
}

if ($cleared -and (Provision)) {
    Say "TPM cleared and re-provisioned - READY." 'Green'
    Log 'TPM was in "clear needed" state; cleared at runtime and re-provisioned. Now ready.'
    exit 0
}

# Runtime clear was refused too (the TPM is locked out and the stored owner auth is stale).
# We do NOT arm a PPI boot clear (op-22): that wipe is exactly the self-perpetuating loop
# that was the original bug. A PTT dictionary-attack lockout is volatile - it decays on its
# own (1 try / 600s, full recovery within 24h) and clears completely on a power cycle - so
# the safe recovery is simply time or a normal reboot, with nothing destructive armed.
# Make doubly sure no boot clear is left queued, then stop and report.
$tpm = Get-CimInstance -Namespace 'root/cimv2/Security/MicrosoftTpm' -ClassName Win32_Tpm
if ($tpm) {
    try { $null = Invoke-CimMethod -InputObject $tpm -MethodName SetPhysicalPresenceRequest `
        -Arguments @{ Request = [uint32]0 } } catch {}
}
Remove-Item (Join-Path $PSScriptRoot '.clear-armed') -Force -ErrorAction SilentlyContinue
Say "TPM is locked out and cannot be recovered without a wipe right now. NOT wiping." 'Yellow'
Say "   It will recover as the lockout decays, or immediately after a normal reboot" 'Yellow'
Say "   (a power cycle clears the PTT lockout). Nothing destructive has been armed." 'Yellow'
Log 'TPM locked out; runtime clear refused. Left to decay/reboot; no boot clear armed (non-destructive).'
exit 1
