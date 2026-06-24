@echo off
cd /d "%~dp0"
if not exist "..\logs" mkdir "..\logs"
del /q "..\logs\run_output.txt" 2>nul
where py >nul 2>nul && (py extract_and_prepare_yelp.py > "..\logs\run_output.txt" 2>&1) || (python extract_and_prepare_yelp.py > "..\logs\run_output.txt" 2>&1)
echo EXITCODE=%errorlevel% >> "..\logs\run_output.txt"
echo DONE_SENTINEL >> "..\logs\run_output.txt"
type "..\logs\run_output.txt"
echo.
echo Finished. You can close this window.
pause
