@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONDONTWRITEBYTECODE=1"
if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\Agentlas\PythonCache") else (set "PYTHONPYCACHEPREFIX=%TEMP%\Agentlas-PythonCache")
if defined PYTHONPATH goto agentlas_pythonpath_join
set "PYTHONPATH=%~dp0.."
goto agentlas_pythonpath_done
:agentlas_pythonpath_join
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"
:agentlas_pythonpath_done
rem The current directory must not be able to supply agentlas_cloud: python -m puts it first on sys.path. Same text as AGENTLAS_SAFE_RUNPY in agentlas-python-cache-boundary (tested).
set "AGENTLAS_SAFE_RUNPY=import os,sys;sys.path[:]=[p for p in sys.path if os.path.isabs(p) and not (os.path.exists(p) and os.path.exists(os.curdir) and os.path.samefile(p,os.curdir))];import runpy;r=sys.argv[1];sys.path.insert(0,r);sys.argv=sys.argv[2:];runpy.run_module(sys.argv[0],run_name='__main__',alter_sys=True)"
if defined HEPHAESTUS_PYTHON goto use_env_python
if exist "%~dp0python3.cmd" goto use_python3_shim
where py >nul 2>nul
if not errorlevel 1 goto use_py_launcher
where python >nul 2>nul
if not errorlevel 1 goto use_path_python
echo hephaestus: Python 3.9+ not found. Install Python from python.org and rerun hephaestus doctor. 1>&2
exit /b 127

:use_env_python
"%HEPHAESTUS_PYTHON%" -c "%AGENTLAS_SAFE_RUNPY%" "%~dp0.." agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_python3_shim
call "%~dp0python3.cmd" -c "%AGENTLAS_SAFE_RUNPY%" "%~dp0.." agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_py_launcher
py -3 -c "%AGENTLAS_SAFE_RUNPY%" "%~dp0.." agentlas_cloud %*
exit /b %ERRORLEVEL%

:use_path_python
python -c "%AGENTLAS_SAFE_RUNPY%" "%~dp0.." agentlas_cloud %*
exit /b %ERRORLEVEL%
