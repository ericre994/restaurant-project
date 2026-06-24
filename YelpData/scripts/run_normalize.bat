@echo off
cd /d "%~dp0"
if not exist "..\logs" mkdir "..\logs"
del /q "..\logs\normalize_output.txt" 2>nul
where py >nul 2>nul && (py normalize_to_schema.py > "..\logs\normalize_output.txt" 2>&1) || (python normalize_to_schema.py > "..\logs\normalize_output.txt" 2>&1)
echo EXITCODE=%errorlevel% >> "..\logs\normalize_output.txt"
echo DONE_SENTINEL >> "..\logs\normalize_output.txt"
type "..\logs\normalize_output.txt"
echo.
echo Finished. You can close this window.
pause
