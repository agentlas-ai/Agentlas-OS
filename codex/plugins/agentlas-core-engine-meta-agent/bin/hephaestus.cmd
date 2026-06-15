@echo off
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
if exist "%~dp0python3.cmd" (
  call "%~dp0python3.cmd" -m agentlas_cloud %*
) else (
  py -3 -m agentlas_cloud %* || python -m agentlas_cloud %*
)
