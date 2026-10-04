# tpmcheck - fast, read-only "is this machine in a state Vanguard is happy with" check.
# Read-only: it never provisions, clears or changes anything.
$ErrorActionPreference = 'SilentlyContinue'

$info     = tpmtool getdeviceinformation 2>$null
$storage  = [bool]($info -match 'Ready For Storage:\s*True')
$attest   = [bool]($info -match 'Ready For Attestation:\s*True')
$clear    = [bool]($info -match 'Clear Needed To Recover:\s*True')
$fisready = [bool](((certutil -tpminfo 2>&1) -join "`n") -match 'fIsReady = 1')

$secure   = $false
try { $secure = [bool](Confirm-SecureBootUEFI) } catch {}
$build    = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
$win11    = ($build -ge 22000)
$healTask = [bool](Get-ScheduledTask -TaskName 'TpmHeal' -ErrorAction SilentlyContinue)

# Windows 11 is where Vanguard hard-requires TPM 2.0 + Secure Boot. On Windows 10 it does not,
# so a ready TPM there is hygiene, not a gate - a VAN error on Win10 is some other cause.
$ok = $storage -and (-not $clear)
if ($win11) { $ok = $ok -and $secure }

Write-Host ""
if ($ok) {
  Write-Host "  ==================================================" -ForegroundColor Green
  Write-Host "        TPM READY   ->   SAFE TO QUEUE" -ForegroundColor Green
  Write-Host "  ==================================================" -ForegroundColor Green
} else {
  Write-Host "  ==================================================" -ForegroundColor Red
  Write-Host "        NOT READY   ->   DO NOT QUEUE" -ForegroundColor Red
  Write-Host "        Fix it now:   tpmfix    (then re-check)" -ForegroundColor Yellow
  Write-Host "  ==================================================" -ForegroundColor Red
}
Write-Host ""
Write-Host ("   Ready For Storage     : {0}" -f $(if ($storage) { 'True' } else { 'False' })) -ForegroundColor $(if ($storage) { 'Green' } else { 'Red' })
Write-Host ("   Ready For Attestation : {0}" -f $(if ($attest)  { 'True' } else { 'False' })) -ForegroundColor $(if ($attest)  { 'Green' } else { 'Red' })
Write-Host ("   Clear Needed          : {0}" -f $(if ($clear)   { 'True  (bad)' } else { 'False (good)' })) -ForegroundColor $(if ($clear) { 'Red' } else { 'Green' })
Write-Host ("   certutil fIsReady     : {0}" -f $(if ($fisready){ '1 (good)' } else { '0 (bad)' })) -ForegroundColor $(if ($fisready) { 'Green' } else { 'Red' })
Write-Host ("   Secure Boot           : {0}" -f $(if ($secure)  { 'Enabled' } else { 'DISABLED (BIOS setting)' })) -ForegroundColor $(if ($secure) { 'Green' } else { 'Yellow' })
Write-Host ("   Windows               : build {0} ({1})" -f $build, $(if ($win11) { 'Win11 - Vanguard requires TPM 2.0 + Secure Boot' } else { 'Win10 - Vanguard does not gate on TPM/Secure Boot' })) -ForegroundColor DarkGray
Write-Host ("   TpmHeal task          : {0}" -f $(if ($healTask) { 'Installed (boot + resume + daily)' } else { 'NOT installed - run tpmheal-install.ps1' })) -ForegroundColor $(if ($healTask) { 'Green' } else { 'Yellow' })
Write-Host ""

if (-not $secure) {
  Write-Host "   Secure Boot is off, so Windows logs TPM-WMI 1796 at every boot and PCR7 stays" -ForegroundColor DarkGray
  Write-Host "   unbound. No script can change it: BIOS > set Supervisor Password, then enable" -ForegroundColor DarkGray
  Write-Host "   Secure Boot. Needed for Vanguard only on Windows 11." -ForegroundColor DarkGray
  Write-Host ""
}

if ($ok) { exit 0 } else { exit 1 }
