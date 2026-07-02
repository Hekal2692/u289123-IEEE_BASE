@echo off
set timestamp=%date:~10,4%-%date:~4,2%-%date:~7,2%_%time:~0,2%-%time:~3,2%-%time:~6,2%
set logdir=logs\job_%timestamp%
mkdir "%logdir%"

echo Running Python job...
python main.py > "%logdir%\stdout_stderr.log" 2>&1
echo Job complete. Output saved to %logdir%

pause
