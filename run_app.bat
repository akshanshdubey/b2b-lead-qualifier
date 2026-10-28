@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat ( echo Run setup.bat first. & pause & exit /b 1 )
call .venv\Scripts\activate.bat
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
  echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"
)
streamlit run app.py
