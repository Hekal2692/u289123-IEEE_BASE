@echo off
for /f %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm-ss"') do set timestamp=%%a

set logdir=logs\%timestamp%
mkdir "%logdir%"

REM Pass the timestamp to Python
start "" python main.py --timestamp %timestamp%
