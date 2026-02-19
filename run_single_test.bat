@echo off
setlocal EnableDelayedExpansion

:: Quick single-test runner for fast iteration
:: Usage: run_single_test.bat [hairline_number]
::   e.g. run_single_test.bat 1

set BLENDER="C:\Program Files\Blender Foundation\Blender 4.0\blender.exe"
set REPO=%~dp0
set HARNESS=%REPO%test_harness.py
set FIXTURES=%REPO%tests\fixtures
set NUM=%1
if "%NUM%"=="" set NUM=1

set "MODEL=%FIXTURES%\BaldGuy-LP_head.obj"
set "HAIRLINE=%FIXTURES%\hairline_BaldGuy-LP_head_%NUM%.json"
set "OUTPUT=%REPO%output\hairline_BaldGuy-LP_head_%NUM%"
set "RENDERS=%REPO%renders\hairline_BaldGuy-LP_head_%NUM%"
set "TILES=%REPO%renders\_tiles"

if exist "%OUTPUT%" rmdir /s /q "%OUTPUT%"
if exist "%RENDERS%" rmdir /s /q "%RENDERS%"
mkdir "%OUTPUT%"
mkdir "%RENDERS%"
if not exist "%TILES%" mkdir "%TILES%"

echo Running single test: hairline %NUM%
echo   Model: %MODEL%
echo   Hairline: %HAIRLINE%

if exist "%REPO%blender_output.log" del "%REPO%blender_output.log"

%BLENDER% --background --python "%HARNESS%" -- --head-model "%MODEL%" --hairline-config "%HAIRLINE%" --output-dir "%OUTPUT%" --render-dir "%RENDERS%" --scan-units cm --test-label "Test %NUM% - hairline_BaldGuy-LP_head_%NUM%" --tile-output "%TILES%\test_%NUM%_hairline_BaldGuy-LP_head_%NUM%.png" 2>&1 >> "%REPO%blender_output.log"

if !ERRORLEVEL! equ 0 (
    if exist "%OUTPUT%\metrics.json" (
        echo RESULT: PASS
    ) else (
        echo RESULT: FAIL - no metrics.json
    )
) else (
    echo RESULT: FAIL - exit code !ERRORLEVEL!
)

echo.
echo Log: %REPO%blender_output.log
echo Tile: %TILES%\test_%NUM%_hairline_BaldGuy-LP_head_%NUM%.png
endlocal
