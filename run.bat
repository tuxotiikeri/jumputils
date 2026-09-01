@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%env\python.exe"
set "MAIN=%ROOT%app\main.py"

if not exist "%PYTHON%" (
    echo Jumputils environment is missing. Starting setup...
    call "%ROOT%SETUP_jumputils.bat"
    if errorlevel 1 exit /b 1
)

if not exist "%MAIN%" (
    echo Jumputils application was not found: "%MAIN%"
    pause
    exit /b 1
)

pushd "%ROOT%"
"%PYTHON%" -m app.main
set "APP_EXIT=%ERRORLEVEL%"
popd

if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%
