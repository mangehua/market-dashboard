@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   HUAFUBING - Support/Resisance Dashboard
echo ========================================
echo.
echo Starting server...
echo.
echo Open browser: http://localhost:8000
echo.
echo Press Ctrl+C to stop server
echo ========================================
echo.
start http://localhost:8000
py app.py
