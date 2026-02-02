#!/bin/bash


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/utils.sh"

LOCAL_ENVS="$SCRIPT_DIR/local.sh"


usage() {
    echo "Usage: $0 {start|stop|status|migrate|load|token|clean}"
    return 1
}


if [[ -x "$LOCAL_ENVS" ]]; then
    info "Loading local variables..."
    source "$LOCAL_ENVS"
else 
    warn "No local variables loaded, this might cause a few errors."
fi

case "$1" in
    start)
        info "Starting Aero-Hydra infrastructure..."
        info "Spinning up Docker containers..."
        docker-compose up -d
        info "Waiting for database health check..."
        until docker exec ${DB_CONTAINER_NAME} pg_isready -U ${DB_USER} > /dev/null 2>&1; do
            echo -n "."
            sleep 1
        done
        echo "" # New line

        info "Infrastructure is UP."
        ;;

    stop)
        warn "Stopping Aero-Hydra infrastructure..."
        docker-compose stop
        info "Infrastructure is STOPPED."
        ;;

    status)
        info "Checking system status..."
        docker ps --filter "name=${DB_CONTAINER_NAME}"
        ;;

    migrate)
        info "Running database migrations..."
        python3 "$SCRIPT_DIR/src/migrate.py"

        if [[ $? -eq 0 ]]; then
            info "Deployment successful! System is ready."
        else
            error "Deployment failed during migration."
        fi

        info "Querying database for table list..."
        docker exec -i aero-hydra-db psql -U ${DB_USER} -d ${DB_NAME} -c "\dt"
        ;;
    load)
        if [[ -f "$AIRCRAFT_FLEET_CSV" && -f "$AIRFIELDS_CSV" ]]; then
            info "Loading aircrafts from ${AIRCRAFT_FLEET_CSV}..."
            info "Loading airfields from ${AIRFIELDS_CSV}..."
            python3 "$SCRIPT_DIR/src/loadCSV.py" "${SCRIPT_DIR}/${AIRCRAFT_FLEET_CSV}" "${SCRIPT_DIR}/${AIRFIELDS_CSV}"
        else
            error "${AIRCRAFT_FLEET_CSV} not found!"
            error "${AIRFIELDS_CSV} not found!"
        fi
        ;;
    token)
        info "Generating OpenSky Token..."
        # Check if env vars are provided
        if [[ -z "$OPEN_SKY_CLIENT_ID" ]] ; then
            error "Missing var : OPEN_SKY_CLIENT_ID"
            exit 1
        fi

        if [[ -z "$OPEN_SKY_CLIENT_SECRET" ]] ; then
            error "Missing var : OPEN_SKY_CLIENT_SECRET"
            exit 1
        fi

        source $SCRIPT_DIR/OAuth2ClientCredential.sh $OPEN_SKY_CLIENT_ID $OPEN_SKY_CLIENT_SECRET
        ;;

    clean)
        warn "This will remove containers and ALL stored data. Are you sure? (y/N)"
        read -r confirm
        if [[ "$confirm" =~ ^[Yy]$ ]]; then
            docker-compose down -v
            info "Environment wiped."
        else
            info "Cleanup aborted."
        fi
        ;;

    *)
        usage
        ;;
esac

