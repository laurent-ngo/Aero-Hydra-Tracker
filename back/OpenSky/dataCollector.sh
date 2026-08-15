#!/bin/bash

# Watchdog disabled — re-enable for scheduled polling runs
# (sleep 1800; echo "watchdog is killing the script"; kill $$ 2>/dev/null) &
WATCHDOG_PID=$!

# 1. Navigate to the project root so Python can find its imports
cd $PROJECT_HOME/back/OpenSky/src

# 4. Run the script using the full path to the virtualenv python
. $PROJECT_HOME/back/OpenSky/back_end.sh token 2>&1
python dataProcessor.py "$@" 2>&1

# Kill the watchdog if the script finishes early

kill $WATCHDOG_PID 2>/dev/null
wait $WATCHDOG_PID 2>/dev/null
kill 0 2>/dev/null
