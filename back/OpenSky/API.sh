#!/bin/bash

# Load the utilities
source ./utils.sh



# Configuration
PROJECT_DIR="/home/lngo/projects/aero-hydra/back/OpenSky"
PID_FILE="$PROJECT_DIR/api.pid"
LOG_FILE="$PROJECT_DIR/logs/api_logs.txt"

LOCAL_ENVS="$PROJECT_DIR/local.sh"

header "Aero-Hydra API Manager"

if [[ -x "$LOCAL_ENVS" ]]; then
    info "Loading local variables..."
    source "$LOCAL_ENVS"
else 
    warn "No local variables loaded, this might cause a few errors."
fi


start() {
    if [[ -f "$PID_FILE" ]]; then
        warn "API is already running (PID: $(cat $PID_FILE))."
    else
        info "Starting Aero-Hydra API..."
        cd "$PROJECT_DIR/src"
        
        # Load environment
        #export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
        
        
        #nohup "$PROJECT_DIR/.venv/bin/uvicorn" API:app --host $API_HOST --port &API_PORT > "$LOG_FILE" 2>&1 &
        nohup "uvicorn" API:app --host $API_HOST --port $API_PORT > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        info "API successfully started on port 8000."
    fi
    return
}

stop() {
    if [[ -f "$PID_FILE" ]]; then
        PID=$(cat "$PID_FILE")
        info "Stopping API (PID: $PID)..."
        kill "$PID"
        rm "$PID_FILE"
        info "API stopped."
    else
        warn "API is not currently running."
    fi
    return 
}

case "$1" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 2; start ;;
    status)
        if [[ -f "$PID_FILE" ]]; then
            info "API is RUNNING (PID: $(cat $PID_FILE))"
        else
            error "API is OFFLINE"
        fi
        ;;
    *) echo "Usage: $0 {start|stop|restart|status}" ;;
esac