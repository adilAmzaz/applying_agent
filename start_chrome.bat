@echo off
REM Starts the Windows Chrome of ONE agent, with its own profile (own logins) and its own debugging port.
REM   start_chrome.bat              -> indeed agent
REM   start_chrome.bat linkedin     -> linkedin agent      (wttj, hellowork, freework: same)
REM Ports must match config.toml [agents]. Already running -> nothing done.
REM First time for each agent: log in BY HAND in its window (Indeed / LinkedIn / WTTJ / HelloWork / Free-Work). Remembered.
REM These profiles are separate from your own Chrome: Chrome refuses remote debugging on your main profile.
setlocal
set "AGENT=%~1"
if "%AGENT%"=="" set "AGENT=indeed"
if /I "%AGENT%"=="indeed"    ( set "PORT=9222" & set "PROFILE=.jobagent-chrome"           & set "URL=https://fr.indeed.com/" )
if /I "%AGENT%"=="linkedin"  ( set "PORT=9223" & set "PROFILE=.jobagent-chrome-linkedin"  & set "URL=https://www.linkedin.com/jobs/" )
if /I "%AGENT%"=="wttj"      ( set "PORT=9224" & set "PROFILE=.jobagent-chrome-wttj"      & set "URL=https://www.welcometothejungle.com/fr" )
if /I "%AGENT%"=="hellowork" ( set "PORT=9225" & set "PROFILE=.jobagent-chrome-hellowork" & set "URL=https://www.hellowork.com/fr-fr/" )
if /I "%AGENT%"=="freework"  ( set "PORT=9226" & set "PROFILE=.jobagent-chrome-freework"  & set "URL=https://www.free-work.com/fr/login" )
if not defined PORT ( echo unknown agent %AGENT% & exit /b 1 )

curl -s http://localhost:%PORT%/json/version >nul 2>&1 && ( echo Chrome of agent %AGENT% already running on port %PORT% & exit /b 0 )

set CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

echo Starting Chrome of agent %AGENT% (port %PORT%, profile %USERPROFILE%\%PROFILE%)
start "" %CHROME% --remote-debugging-port=%PORT% --user-data-dir="%USERPROFILE%\%PROFILE%" --disable-background-timer-throttling --disable-renderer-backgrounding --disable-backgrounding-occluded-windows --disable-features=HighEfficiencyMode %URL%
endlocal
