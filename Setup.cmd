@echo off
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r setup\requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Open Start exhibit.cmd.
pause
exit /b 0
:failed
echo Setup failed. Check that Python is installed and internet is available.
pause
exit /b 1
