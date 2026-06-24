@echo off
cd /d "%~dp0"
if not exist "..\logs" mkdir "..\logs"
del /q "..\logs\csv_output.txt" 2>nul
where py >nul 2>nul && (py convert_to_csv.py > "..\logs\csv_output.txt" 2>&1) || (python convert_to_csv.py > "..\logs\csv_output.txt" 2>&1)
echo EXITCODE=%errorlevel% >> "..\logs\csv_output.txt"
echo DONE_SENTINEL >> "..\logs\csv_output.txt"
type "..\logs\csv_output.txt"
echo.
echo Finished. You can close this window.
pause
