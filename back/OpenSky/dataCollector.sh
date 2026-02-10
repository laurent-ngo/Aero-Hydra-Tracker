#!/bin/bash

# Capture the first argument passed to the shell script
ACTIVE_FLAG=""
if [[ "$1" == "--active" ]]; then
    ACTIVE_FLAG="--active"
fi

# 1. Navigate to the project root so Python can find its imports
cd $PROJECT_HOME/back/OpenSky/src

# 2. Print the date to the log
date

# 3. Load your environment variables (Crucial!)
# Assuming your .env is in the root of the project
export $(grep -v '^#' $PROJECT_HOME/.env | xargs)

# 4. Run the script using the full path to the virtualenv python
. $PROJECT_HOME/back/OpenSky/back_end.sh token 2>&1
$PROJECT_HOME/.venv/bin/python dataCollector.py $ACTIVE_FLAG 2>&1
$PROJECT_HOME/.venv/bin/python dataProcessor.py 2>&1