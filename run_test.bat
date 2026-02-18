@echo off
setlocal EnableDelayedExpansion

:: ============================================================
:: HWG Test Runner — Automated headless test pipeline
:: ============================================================
::
:: Usage:
::   run_test.bat                  Test all models with all their hairlines
::   run_test.bat head.obj         Test specific model with all its hairlines
::   run_test.bat --skip-render    Test all models, skip rendering
::
:: The pipeline per (model, hairline) pair:
::   1. Run full wig base generation
::   2. Validate mesh metrics
::   3. Render multi-angle previews
::
:: Hairline fixtures are auto-saved by the Draw Hairline operator:
::   tests/fixtures/hairline_<ModelName>_1.json
::   tests/fixtures/hairline_<ModelName>_2.json
::   tests/fixtures/hairline_<ModelName>_3.json
::
:: Outputs per test:
::   renders/<model>_<hairline>\*.png   Multi-angle renders
::   output/<model>_<hairline>\         Mesh + metrics
::   blender_output.log                 Full log
:: ============================================================

set BLENDER="C:\Program Files\Blender Foundation\Blender 4.0\blender.exe"
set REPO=%~dp0
set HARNESS=%REPO%test_harness.py
set FIXTURES=%REPO%tests\fixtures
set SKIP_RENDER=

:: Parse args
set SPECIFIC_MODEL=
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
echo  HWG Test Runner — Multi-Model Multi-Hairline
echo ============================================================

:: Find all head models (OBJ and STL files in fixtures)
set TOTAL_TESTS=0
set PASSED=0
set FAILED=0

:: Iterate model files
for %%M in ("%FIXTURES%\*.obj" "%FIXTURES%\*.stl") do (
    if exist "%%M" (
        :: Get model base name without extension
        set "MODEL_FILE=%%M"
        set "MODEL_NAME=%%~nM"

        :: Skip if specific model requested and this isn't it
        if defined SPECIFIC_MODEL (
            echo !MODEL_NAME! | findstr /i "!SPECIFIC_MODEL!" >nul 2>&1
            if errorlevel 1 (
                goto :skip_model
            )
        )

        echo.
        echo ============================================================
        echo  Model: !MODEL_NAME!
        echo ============================================================

        :: Find all hairline fixtures for this model
        set FOUND_HAIRLINES=0
        for %%H in ("%FIXTURES%\hairline_!MODEL_NAME!_*.json") do (
            if exist "%%H" (
                set /a FOUND_HAIRLINES+=1
                set /a TOTAL_TESTS+=1
                set "HAIRLINE_FILE=%%H"
                set "HAIRLINE_NAME=%%~nH"

                :: Create output dirs for this test
                set "TEST_OUTPUT=%REPO%output\!HAIRLINE_NAME!"
                set "TEST_RENDERS=%REPO%renders\!HAIRLINE_NAME!"
                if exist "!TEST_OUTPUT!" rmdir /s /q "!TEST_OUTPUT!"
                if exist "!TEST_RENDERS!" rmdir /s /q "!TEST_RENDERS!"
                mkdir "!TEST_OUTPUT!"
                mkdir "!TEST_RENDERS!"

                echo.
                echo --- Test: !HAIRLINE_NAME! ---
                echo   Model:    !MODEL_FILE!
                echo   Hairline: !HAIRLINE_FILE!

                %BLENDER% --background --python "%HARNESS%" -- ^
                    --head-model "!MODEL_FILE!" ^
                    --hairline-config "!HAIRLINE_FILE!" ^
                    --output-dir "!TEST_OUTPUT!" ^
                    --render-dir "!TEST_RENDERS!" ^
                    !SKIP_RENDER! ^
                    2>&1 >> "%REPO%blender_output.log"

                if !ERRORLEVEL! equ 0 (
                    if exist "!TEST_OUTPUT!\metrics.json" (
                        echo   RESULT: PASS
                        set /a PASSED+=1
                    ) else (
                        echo   RESULT: FAIL (no metrics.json)
                        set /a FAILED+=1
                    )
                ) else (
                    echo   RESULT: FAIL (exit code !ERRORLEVEL!)
                    set /a FAILED+=1
                )
            )
        )

        if !FOUND_HAIRLINES! equ 0 (
            echo   WARNING: No hairline fixtures found for !MODEL_NAME!
            echo   Expected: %FIXTURES%\hairline_!MODEL_NAME!_*.json
            echo   Draw hairlines in Blender — they auto-save on confirm.
        )
    )
    :skip_model
)

:: Summary
echo.
echo ============================================================
echo  Test Summary
echo ============================================================
echo  Total tests: %TOTAL_TESTS%
echo  Passed:      %PASSED%
echo  Failed:      %FAILED%
echo.
echo  Log: %REPO%blender_output.log
echo  Renders: %REPO%renders\
echo  Output:  %REPO%output\
echo ============================================================

if %TOTAL_TESTS% equ 0 (
    echo.
    echo  No tests were run! You need to:
    echo    1. Place head models (.obj/.stl) in tests\fixtures\
    echo    2. Open each model in Blender and draw 3 hairlines
    echo       (they auto-save to tests\fixtures\ on confirm)
    echo    3. Run this script again
)

if %FAILED% gtr 0 exit /b 1
endlocal
