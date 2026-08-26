@echo off
REM Wrapper around clutch.ps1 for Windows.
REM
REM Use this if PowerShell refuses to run the .ps1 directly ("running scripts
REM is disabled on this system"). It bypasses the execution policy for this one
REM invocation only, without changing any machine setting.
REM
REM   clutch setup
REM   clutch seed
REM   clutch api
REM
REM Anything after the command is passed straight through, so
REM `clutch ingest -Season 2023-24 -Limit 50` works as expected.

setlocal
set "SCRIPT=%~dp0clutch.ps1"

where pwsh >nul 2>&1
if %ERRORLEVEL%==0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
)
exit /b %ERRORLEVEL%
