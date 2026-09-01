@echo off
setlocal

set "ROOT=%~dp0"
set "ENV_DIR=%ROOT%env"
set "ENV_FILE=%ROOT%environment.yml"
set "CONDA="

if exist "C:\ProgramData\Miniconda3\condabin\conda.bat" set "CONDA=C:\ProgramData\Miniconda3\condabin\conda.bat"
if not defined CONDA if exist "C:\ProgramData\Anaconda3\condabin\conda.bat" set "CONDA=C:\ProgramData\Anaconda3\condabin\conda.bat"
if not defined CONDA if exist "%LocalAppData%\miniconda3\condabin\conda.bat" set "CONDA=%LocalAppData%\miniconda3\condabin\conda.bat"
if not defined CONDA if exist "%UserProfile%\miniconda3\condabin\conda.bat" set "CONDA=%UserProfile%\miniconda3\condabin\conda.bat"
if not defined CONDA for /f "delims=" %%I in ('where conda.bat 2^>nul') do if not defined CONDA set "CONDA=%%I"

if not defined CONDA (
    echo.
    echo Conda was not found on this computer.
    echo Install Miniconda, then run this file again.
    echo https://www.anaconda.com/download
    echo.
    pause
    exit /b 1
)

if not exist "%ENV_FILE%" (
    echo Environment definition was not found: "%ENV_FILE%"
    pause
    exit /b 1
)

if not exist "%ROOT%data" mkdir "%ROOT%data"
if not exist "%ROOT%reports" mkdir "%ROOT%reports"

if exist "%ENV_DIR%\python.exe" (
    echo Updating Jumputils environment...
    call "%CONDA%" env update --prefix "%ENV_DIR%" --file "%ENV_FILE%" --prune
) else (
    echo Creating Jumputils environment...
    call "%CONDA%" env create --prefix "%ENV_DIR%" --file "%ENV_FILE%"
)

if errorlevel 1 (
    echo.
    echo Environment installation failed.
    pause
    exit /b 1
)

"%ENV_DIR%\python.exe" -c "import tkinter,numpy,pandas,scipy,matplotlib,ezc3d; print('Jumputils environment OK')"
if errorlevel 1 (
    echo Environment verification failed.
    pause
    exit /b 1
)

echo.
echo Jumputils is ready.
echo Environment: "%ENV_DIR%"
echo Start the application with run.bat
echo.
pause
endlocal
