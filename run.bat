@echo off
title Transparency Mode
echo Starting Transparency Mode...
python app.py
if errorlevel 1 (
    echo.
    echo An error occurred. Installing dependencies...
    pip install -r requirements.txt
    python app.py
)
pause
