@echo off
REM Scheduled scan (Windows Task Scheduler): starts the 4 agent Chromes if needed, then all agents AT THE SAME TIME
REM in WSL (python scan.py). Logs: runs\scan-<agent>.log (+ runs\scan.log summary)   Reports: reports\scan-*-<agent>.md
cd /d "%~dp0"
call start_all_chromes.bat
timeout /t 10 >nul
wsl -d Ubuntu -e bash -lc "cd ~/applying_jobs_agent && mkdir -p runs && ~/.venvs/jobagent/bin/python scan.py >> runs/scan.log 2>&1"
