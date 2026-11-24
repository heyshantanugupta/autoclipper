@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller
python build.py
echo.
echo Done. Your app is dist\AutoClipper.exe
pause
