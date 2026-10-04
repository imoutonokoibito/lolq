# tpmheal - non-destructive TPM heal. Safe to run unattended, as often as you like.
#
# Why this exists: the old tpmfix armed a boot-time TPM clear (PPI op-22) whenever the live
# heal did not finish in 48s. That clear wipes the SRK and owner auth at the next boot, so
# every "fix" destroyed the state it had just created (System log: 1793 "scheduled to be
# cleared" -> 519 "cleared, Reason: ByPPI" -> 1027 -> 1025, on 2026-09-28 and 2026-09-29/30).
# This script never clears the TPM. It also disarms a pending clear, so an op-22 left over
# from the old script cannot fire on the next boot.
#
# Exit codes: 0 = TPM ready, 1 = not ready and needs firmware/BIOS attention.
[CmdletBinding()]
param([switch]$Quiet)

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

Say "TPM not ready - healing in place (no reboot, no clear)..." 'Cyan'
Enable-TpmAutoProvisioning | Out-Null
Start-ScheduledTask -TaskPath '\Microsoft\Windows\TPM\' -TaskName 'Tpm-Maintenance'
Initialize-Tpm | Out-Null

$ok = $false
for ($i = 0; $i -lt 12; $i++) {
    if (Ready) { $ok = $true; break }
    Start-Sleep -Seconds 4
}

if ($ok) {
    Say "TPM is READY now." 'Green'
    Log 'TPM healed in place (auto-provisioning + Tpm-Maintenance + Initialize-Tpm).'
    exit 0
}

# Everything Windows can do from the OS side has been tried. What is left is firmware, and
# no script can set it: the TPM/PTT switch and Secure Boot live in the BIOS.
Say "TPM still not ready. This is a firmware-side problem, not something Windows can fix:" 'Yellow'
Say "   - BIOS > Security: Intel PTT (or fTPM) must be Enabled" 'Yellow'
Say "   - BIOS > Boot: Secure Boot must be Enabled (needs a Supervisor Password first)" 'Yellow'
Say "   - Then re-run tpmcheck." 'Yellow'
Say "Not arming a boot-time clear: it wipes TPM keys and is what made the old fix" 'DarkGray'
Say "undo itself every boot. If you truly want a clear, do it deliberately: tpmfix -AllowClear" 'DarkGray'
Log 'TPM not ready after in-place heal; firmware/BIOS attention needed. No clear armed.'
exit 1
