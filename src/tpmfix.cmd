@echo off
REM tpmfix - self-elevates, live-reprovisions the TPM, then re-checks.
net session >nul 2>&1
if %errorlevel%==0 goto run
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
goto :eof
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tpmfix.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tpmcheck.ps1"
echo.
pause
