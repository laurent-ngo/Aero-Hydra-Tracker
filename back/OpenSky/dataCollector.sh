#!/bin/bash

# Capture the first argument passed to the shell script
ACTIVE_FLAG=""
if [ "$1" == "--active" ]; then
    ACTIVE_FLAG="--active"
fi

# 1. Navigate to the project root so Python can find its imports
cd /home/lngo/projects/aero-hydra/back/OpenSky/src

# 2. Print the date to the log
date

# 3. Load your environment variables (Crucial!)
# Assuming your .env is in the root of the project
export $(grep -v '^#' /home/lngo/projects/aero-hydra/.env | xargs)

# 4. Run the script using the full path to the virtualenv python
. /home/lngo/projects/aero-hydra/back/OpenSky/back_end.sh token 2>&1
/home/lngo/projects/aero-hydra/.venv/bin/python dataCollector.py $ACTIVE_FLAG 2>&1
/home/lngo/projects/aero-hydra/.venv/bin/python dataProcessor.py 2>&1