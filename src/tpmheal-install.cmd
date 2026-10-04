@echo off
REM tpmheal-install - self-elevates, registers the TpmHeal task (boot + resume + daily).
net session >nul 2>&1
if %errorlevel%==0 goto run
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
goto :eof
:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tpmheal-install.ps1"
echo.
pause
