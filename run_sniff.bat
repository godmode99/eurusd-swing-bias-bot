@echo off
set ROOT=C:\Users\iidogpon\Documents\GitHub\eurusd-swing-bias-bot
cd /d %ROOT%
mkdir artifacts\ff 2>nul

echo Running... > artifacts\ff\run.log
python -u .\python\fetch\calendar\02_sniff_network_min.py >> artifacts\ff\run.log 2>&1

echo. >> artifacts\ff\run.log
echo === DONE (see artifacts\ff\run.log) === >> artifacts\ff\run.log
type artifacts\ff\run.log
pause
