@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: HWG Test Runner - Automated headless test pipeline
:: ============================================================

set BLENDER="C:\Program Files\Blender Foundation\Blender 4.0\blender.exe"
set REPO=%~dp0
set HARNESS=%REPO%test_harness.py
set FIXTURES=%REPO%tests\fixtures
set SKIP_RENDER=
set SPECIFIC_MODEL=

:: Parse args
:parse_args
if "%~1"=="" goto :done_args
if "%~1"=="--skip-render" (
    set SKIP_RENDER=--skip-render
    shift
    goto :parse_args
)
set SPECIFIC_MODEL=%~1
shift
goto :parse_args
:done_args

echo ============================================================
echo  HWG Test Runner
echo ============================================================

set TOTAL_TESTS=0
set PASSED=0
set FAILED=0

:: Iterate model files
for %%M in ("%FIXTURES%\*.obj" "%FIXTURES%\*.stl") do (
    if exist "%%M" call :process_model "%%M" "%%~nM"
)

goto :print_summary

:: ============================================================
:process_model
:: ============================================================
set "MODEL_FILE=%~1"
set "MODEL_NAME=%~2"

:: Skip if specific model requested and this isn't it
if defined SPECIFIC_MODEL (
    echo !MODEL_NAME! | findstr /i "!SPECIFIC_MODEL!" >nul 2>&1
    if errorlevel 1 goto :eof
)

echo.
echo ============================================================
echo  Model: !MODEL_NAME!
echo ============================================================

:: Build the hairline glob pattern into a variable FIRST,
:: then use it in the for loop via call.
set "HAIRLINE_PATTERN=%FIXTURES%\hairline_!MODEL_NAME!_*.json"
set FOUND_HAIRLINES=0

:: Use dir to list matching files, pipe to for /f to avoid
:: delayed expansion issues inside for-in patterns.
for /f "delims=" %%H in ('dir /b "!HAIRLINE_PATTERN!" 2^>nul') do (
    call :process_hairline "%FIXTURES%\%%H" "%%~nH"
)

if !FOUND_HAIRLINES! equ 0 (
    echo   WARNING: No hairline fixtures found for !MODEL_NAME!
    echo   Expected: !HAIRLINE_PATTERN!
    echo   Draw hairlines in Blender - they auto-save on confirm.
)
goto :eof

:: ============================================================
:process_hairline
:: ============================================================
set "HAIRLINE_FILE=%~1"
set "HAIRLINE_NAME=%~2"
set /a FOUND_HAIRLINES+=1
set /a TOTAL_TESTS+=1

set "TEST_OUTPUT=%REPO%output\!HAIRLINE_NAME!"
set "TEST_RENDERS=%REPO%renders\!HAIRLINE_NAME!"
set "TILES_DIR=%REPO%renders\_tiles"
if exist "!TEST_OUTPUT!" rmdir /s /q "!TEST_OUTPUT!"
if exist "!TEST_RENDERS!" rmdir /s /q "!TEST_RENDERS!"
mkdir "!TEST_OUTPUT!"
mkdir "!TEST_RENDERS!"
if not exist "!TILES_DIR!" mkdir "!TILES_DIR!"

echo.
echo --- Test: !HAIRLINE_NAME! ---
echo   Model:    !MODEL_FILE!
echo   Hairline: !HAIRLINE_FILE!

%BLENDER% --background --python "%HARNESS%" -- --head-model "!MODEL_FILE!" --hairline-config "!HAIRLINE_FILE!" --output-dir "!TEST_OUTPUT!" --render-dir "!TEST_RENDERS!" --scan-units cm --test-label "Test !TOTAL_TESTS! - !HAIRLINE_NAME!" --tile-output "!TILES_DIR!\test_!TOTAL_TESTS!_!HAIRLINE_NAME!.png" !SKIP_RENDER! 2>&1 >> "%REPO%blender_output.log"

if !ERRORLEVEL! equ 0 (
    if exist "!TEST_OUTPUT!\metrics.json" (
        echo   RESULT: PASS
        set /a PASSED+=1
    ) else (
        echo   RESULT: FAIL - no metrics.json
        set /a FAILED+=1
    )
) else (
    echo   RESULT: FAIL - exit code !ERRORLEVEL!
    set /a FAILED+=1
)
goto :eof

:: ============================================================
:print_summary
:: ============================================================
echo.
echo ============================================================
echo  Test Summary
echo ============================================================
echo  Total tests: !TOTAL_TESTS!
echo  Passed:      !PASSED!
echo  Failed:      !FAILED!
echo.
echo  Log: %REPO%blender_output.log
echo  Renders: %REPO%renders\
echo  Tiles:   %REPO%renders\_tiles\
echo  Output:  %REPO%output\
echo ============================================================

if !TOTAL_TESTS! equ 0 (
    echo.
    echo  No tests were run. You need to:
    echo    1. Place head models in tests\fixtures\
    echo    2. Open each model in Blender and draw hairlines
    echo    3. Run this script again
)

if !FAILED! gtr 0 exit /b 1
endlocal
