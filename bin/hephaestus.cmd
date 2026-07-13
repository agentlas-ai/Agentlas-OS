@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
if defined HEPHAESTUS_PYTHON (
  "%HEPHAESTUS_PYTHON%" -m agentlas_cloud %*
  exit /b %ERRORLEVEL%
)
if exist "%~dp0python3.cmd" (
  call "%~dp0python3.cmd" -m agentlas_cloud %*
  exit /b %ERRORLEVEL%
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -m agentlas_cloud %*
  exit /b %ERRORLEVEL%
)
where python >nul 2>nul
if not errorlevel 1 (
  python -m agentlas_cloud %*
  exit /b %ERRORLEVEL%
)
echo hephaestus: Python 3.9+ not found. Install Python from python.org and rerun hephaestus doctor. 1>&2
exit /b 127
