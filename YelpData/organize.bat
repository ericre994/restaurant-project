@echo off
cd /d "%~dp0"

mkdir source  2>nul
mkdir docs    2>nul
mkdir scripts 2>nul
mkdir output  2>nul
mkdir logs    2>nul

rem --- raw Yelp dataset ---
move /y "yelp_dataset.tar" source\ >nul 2>nul
move /y "yelp_academic_dataset_business.json" source\ >nul 2>nul
move /y "yelp_academic_dataset_checkin.json" source\ >nul 2>nul
move /y "yelp_academic_dataset_review.json" source\ >nul 2>nul
move /y "yelp_academic_dataset_tip.json" source\ >nul 2>nul
move /y "yelp_academic_dataset_user.json" source\ >nul 2>nul

rem --- documentation / license ---
move /y "Yelp Dataset Documentation & ToS copy.pdf" docs\ >nul 2>nul
move /y "Dataset_User_Agreement.pdf" docs\ >nul 2>nul

rem --- pipeline scripts ---
move /y "extract_and_prepare_yelp.py" scripts\ >nul 2>nul
move /y "normalize_to_schema.py" scripts\ >nul 2>nul
move /y "convert_to_csv.py" scripts\ >nul 2>nul
move /y "run_philadelphia.bat" scripts\ >nul 2>nul
move /y "run_normalize.bat" scripts\ >nul 2>nul
move /y "run_csv.bat" scripts\ >nul 2>nul

rem --- generated outputs ---
move /y "restaurants_seed_Philadelphia.json" output\ >nul 2>nul
move /y "restaurants_seed_Philadelphia.sql" output\ >nul 2>nul
move /y "restaurants_Philadelphia_schema.json" output\ >nul 2>nul
move /y "restaurants_Philadelphia_schema.ndjson" output\ >nul 2>nul
move /y "restaurants_Philadelphia_schema.csv" output\ >nul 2>nul

rem --- run logs ---
move /y "run_output.txt" logs\ >nul 2>nul
move /y "normalize_output.txt" logs\ >nul 2>nul
move /y "csv_output.txt" logs\ >nul 2>nul

dir /s /b > organize_listing.txt
echo DONE_SENTINEL >> organize_listing.txt
echo Organized. New structure written to organize_listing.txt
pause
