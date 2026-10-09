@echo off
setlocal
cd /d "%~dp0"

if not exist config.ini copy config.ini.example config.ini >nul

if exist ".venv\Scripts\python.exe" goto venv_ready
echo Creating virtual environment...
py -3 -m venv .venv 2>nul
if exist ".venv\Scripts\python.exe" goto venv_install
python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo Python 3 was not found. Install Python 3.12+ from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH".
  goto fail
)
:venv_install
echo Installing packages...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail

:venv_ready
netstat -ano | findstr ":9222 " | findstr LISTENING >nul
if not errorlevel 1 goto chrome_ready

set "CHROME_EXE="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if defined CHROME_EXE goto chrome_found
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if defined CHROME_EXE goto chrome_found
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if defined CHROME_EXE goto chrome_found
echo chrome.exe was not found. Start Chrome manually with:
echo   chrome.exe --remote-debugging-port=9222 --user-data-dir="%LocalAppData%\iThome30day_Editor\chrome-profile"
goto chrome_ready

:chrome_found
echo Starting Chrome with remote debugging port 9222 (separate profile)...
start "" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%LocalAppData%\iThome30day_Editor\chrome-profile" https://ithelp.ithome.com.tw/

:chrome_ready
rem Open the editor page a few seconds after the server starts.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:5451/ithome/"
".venv\Scripts\python.exe" ithome_editor.py serve
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo Startup failed. See the messages above.
pause
exit /b 1
