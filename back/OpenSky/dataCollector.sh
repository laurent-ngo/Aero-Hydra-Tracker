#!/bin/bash

(sleep 180; echo "wahtdog is killing the script"; kill $$) & 
WATCHDOG_PID=$!

# Capture the first argument passed to the shell script
ACTIVE_FLAG=""
if [[ "$1" == "--active" ]]; then
    ACTIVE_FLAG="--active"
fi

# 1. Navigate to the project root so Python can find its imports
cd $PROJECT_HOME/back/OpenSky/src

# 4. Run the script using the full path to the virtualenv python
. $PROJECT_HOME/back/OpenSky/back_end.sh token 2>&1
python dataProcessor.py $1 2>&1

# Kill the watchdog if the script finishes early
kill $WATCHDOG_PID 2>/dev/null