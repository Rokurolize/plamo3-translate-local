@echo off
rem THE single entry point for PLaMo 3 Translate: starts manager.py (WebUI + API).
rem Args: %~1 = model size (0.8b default | 2b | 8b), %~2 = port (8000 default).
rem From PowerShell:  ^& "%~dp0start-plamo.bat"
rem The Task Scheduler task runs this file via run-at-logon.bat.
rem Keep this file pure ASCII: non-ASCII bytes break cmd.exe under other codepages.
setlocal
set "ROOT=%~dp0"
set "SIZE=%~1"
if "%SIZE%"=="" set "SIZE=0.8b"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8000"
echo Checking PLaMo 3 Translate on http://127.0.0.1:%PORT%
curl.exe -s -o NUL -m 2 http://127.0.0.1:%PORT%/api/status
if not errorlevel 1 (
  echo Manager is already running; restarting the loaded model...
  curl.exe -s -o NUL -m 120 -X POST http://127.0.0.1:%PORT%/api/restart
  if errorlevel 1 (
    echo Could not restart the model.
    exit /b 1
  )
  echo Model restarted. Open http://127.0.0.1:%PORT%/ to use it.
  exit /b 0
)
echo Starting PLaMo 3 Translate manager (model %SIZE%) on http://127.0.0.1:%PORT% ^(Ctrl+C to stop^)
where uv >nul 2>nul
if not errorlevel 1 (
  uv run --no-project "%ROOT%manager.py" --model %SIZE% --port %PORT%
  exit /b %errorlevel%
)
where python >nul 2>nul
if errorlevel 1 (
  echo Neither 'uv' nor 'python' was found on PATH.
  exit /b 1
)
python "%ROOT%manager.py" --model %SIZE% --port %PORT%
