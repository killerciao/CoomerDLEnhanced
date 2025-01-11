@echo off
REM Batch file to run the Telegram Media Downloader with virtual environment setup

REM Set the name of the virtual environment directory
SET VENV_DIR=venv

REM Check if the virtual environment directory exists
IF NOT EXIST "%VENV_DIR%\" (
    ECHO Creating virtual environment...
    python -m venv %VENV_DIR%
)

REM Activate the virtual environment
CALL %VENV_DIR%\Scripts\activate.bat

REM Upgrade pip
ECHO Upgrading pip...
python -m pip install --upgrade pip

REM Install required packages (only if missing or outdated)
ECHO Installing required packages...
python -m pip install -r requirements.txt

REM Check if gallery-dl is already installed
ECHO Checking if gallery-dl is installed...
python -c "import gallery_dl" 2>nul
IF %ERRORLEVEL% NEQ 0 (
    ECHO gallery-dl is not installed. Installing from GitHub...
    python -m pip install --no-deps https://github.com/mikf/gallery-dl/archive/master.tar.gz
) ELSE (
    ECHO gallery-dl is already installed. Skipping installation.
)

REM Run the Telegram Media Downloader script
ECHO Running the CoomerDownloaderEnhanced...
python main.py

REM Deactivate the virtual environment after completion
CALL %VENV_DIR%\Scripts\deactivate.bat

PAUSE