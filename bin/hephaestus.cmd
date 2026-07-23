@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\Agentlas\PythonCache") else (set "PYTHONPYCACHEPREFIX=%TEMP%\Agentlas-PythonCache")
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
if defined HEPHAESTUS_PYTHON goto use_env_python
if exist "%~dp0python3.cmd" goto use_python3_shim
where py >nul 2>nul
if not errorlevel 1 goto use_py_launcher
where python >nul 2>nul
if not errorlevel 1 goto use_path_python
echo hephaestus: Python 3.9+ not found. Install Python from python.org and rerun hephaestus doctor. 1>&2
exit /b 127

:use_env_python
"%HEPHAESTUS_PYTHON%" -m agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_python3_shim
call "%~dp0python3.cmd" -m agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_py_launcher
py -3 -m agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_path_python
python -m agentlas_cloud %*
exit /b %ERRORLEVEL%
