@echo off
REM =============================================================================
REM Build Windows EXE for Math Modeling Assistant
REM
REM Prerequisites:
REM   1. Python 3.10+ installed (with pip)
REM   2. Run: pip install pyinstaller -r requirements.txt
REM
REM Usage:  win_build.bat
REM Output: dist\MathModelingAssistant\  (folder with .exe)
REM =============================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

set APP_NAME=MathModelingAssistant
set VERSION=1.0.0
set DIST_DIR=dist
set BUILD_DIR=build

echo === Math Modeling Assistant — Windows EXE Builder ===
echo.

REM Step 1: Clean previous builds
echo [1/3] Cleaning previous builds...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\%APP_NAME%" rmdir /s /q "%DIST_DIR%\%APP_NAME%"

REM Step 2: Build with PyInstaller
echo [2/3] Building .exe with PyInstaller...
pyinstaller --clean --noconfirm --distpath "%DIST_DIR%" --workpath "%BUILD_DIR%" win_build.spec
if %ERRORLEVEL% neq 0 (
    echo ERROR: PyInstaller build failed
    exit /b 1
)
echo   OK %DIST_DIR%\%APP_NAME%\%APP_NAME%.exe created

REM Step 3: Create ZIP archive
echo [3/3] Creating ZIP archive...
if exist "%DIST_DIR%\%APP_NAME%-win64.zip" del "%DIST_DIR%\%APP_NAME%-win64.zip"
powershell -Command "Compress-Archive -Path '%DIST_DIR%\%APP_NAME%' -DestinationPath '%DIST_DIR%\%APP_NAME%-win64.zip'"
if %ERRORLEVEL% neq 0 (
    echo WARNING: ZIP creation failed, but .exe is ready
)

echo.
echo === Done ===
echo Folder: %DIST_DIR%\%APP_NAME%\
echo ZIP:    %DIST_DIR%\%APP_NAME%-win64.zip
echo.
echo To distribute: send the ZIP file. User unzips and runs %APP_NAME%.exe
echo NOTE: First launch may take 5-10 seconds to start.
endlocal
