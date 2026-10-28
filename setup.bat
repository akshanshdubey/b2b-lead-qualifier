@echo off
setlocal
cd /d "%~dp0"
echo === Setting up Lead Qualifier ===
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist .venv (
  py -3 -m venv .venv
  if errorlevel 1 ( echo Could not create virtual environment. & pause & exit /b 1 )
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 ( echo Dependency install failed. & pause & exit /b 1 )
if not exist .env (
  copy .env.example .env >nul
  echo Created .env - open it in Notepad and paste your ANTHROPIC_API_KEY.
)
echo.
echo Setup complete. Next: double-click run_app.bat
pause
