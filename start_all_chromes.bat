@echo off
REM One Chrome per agent (4 windows). Those already running are left alone.
cd /d "%~dp0"
for %%A in (indeed linkedin wttj hellowork freework) do call start_chrome.bat %%A
