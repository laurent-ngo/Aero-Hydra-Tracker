#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/utils.sh"

SERVICE_NAME="aero-hydra-api"
SERVICE_FILE="$SCRIPT_DIR/aero-hydra-api.service"
SERVICE_DEST="/etc/systemd/system/$SERVICE_NAME.service"

ELEV_SERVICE_NAME="aero-hydra-elevation"
ELEV_SERVICE_FILE="$SCRIPT_DIR/aero-hydra-elevation.service"
ELEV_SERVICE_DEST="/etc/systemd/system/$ELEV_SERVICE_NAME.service"
PROJECT_HOME="$(dirname "$(dirname "$SCRIPT_DIR")")"

header "Aero-Hydra API — Deploy"

# ── 0. Check api.env exists ───────────────────────────────────
ENV_FILE="$SCRIPT_DIR/api.env"
if [[ ! -f "$ENV_FILE" ]]; then
    error "api.env not found at $ENV_FILE — create it before deploying (see api.env on dev machine)"
    exit 1
fi

# ── 1. Pull latest code ────────────────────────────────────────
info "Pulling latest code..."
git -C "$PROJECT_HOME" pull || { error "git pull failed"; exit 1; }

# ── 2. Python venv + dependencies ────────────────────────────
VENV="$PROJECT_HOME/.venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
if [[ ! -f "$VENV/bin/uvicorn" ]]; then
    info "Creating virtual environment..."
    python3 -m venv "$VENV" || { error "python3 -m venv failed"; exit 1; }
fi
info "Installing/updating Python dependencies..."
"$VENV/bin/pip" install -q -r "$REQUIREMENTS" || { error "pip install failed"; exit 1; }

# ── 3. Install/update systemd service file ────────────────────
info "Installing service file to $SERVICE_DEST (user=$(whoami), project=$PROJECT_HOME)..."
sed \
    -e "s|User=.*|User=$(whoami)|" \
    -e "s|/home/lngo/projects/aero-hydra|$PROJECT_HOME|g" \
    "$SERVICE_FILE" | sudo tee "$SERVICE_DEST" > /dev/null \
    || { error "Failed to install service file"; exit 1; }
sudo systemctl daemon-reload || { error "daemon-reload failed"; exit 1; }

# ── 3. Enable service (idempotent) ────────────────────────────
sudo systemctl enable "$SERVICE_NAME" 2>/dev/null
info "Service enabled."

# ── 4. Restart (or start if not running) ──────────────────────
if systemctl is-active --quiet "$SERVICE_NAME"; then
    info "Restarting $SERVICE_NAME..."
    sudo systemctl restart "$SERVICE_NAME" || { error "Restart failed"; exit 1; }
else
    info "Starting $SERVICE_NAME..."
    sudo systemctl start "$SERVICE_NAME" || { error "Start failed"; exit 1; }
fi

# ── 5. Elevation service ──────────────────────────────────────
info "Installing elevation service..."
sed \
    -e "s|User=.*|User=$(whoami)|" \
    -e "s|/home/lngo/projects/aero-hydra|$PROJECT_HOME|g" \
    "$ELEV_SERVICE_FILE" | sudo tee "$ELEV_SERVICE_DEST" > /dev/null \
    || { error "Failed to install elevation service file"; exit 1; }
sudo systemctl daemon-reload
sudo systemctl enable "$ELEV_SERVICE_NAME" 2>/dev/null
if systemctl is-active --quiet "$ELEV_SERVICE_NAME"; then
    sudo systemctl restart "$ELEV_SERVICE_NAME"
else
    sudo systemctl start "$ELEV_SERVICE_NAME"
fi

# ── 6. Status ─────────────────────────────────────────────────
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    info "$SERVICE_NAME is running on port 8010."
else
    error "$SERVICE_NAME failed to start. Check: sudo journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi
if systemctl is-active --quiet "$ELEV_SERVICE_NAME"; then
    info "$ELEV_SERVICE_NAME is running on port 8011."
else
    error "$ELEV_SERVICE_NAME failed to start. Check: sudo journalctl -u $ELEV_SERVICE_NAME -n 50"
    exit 1
fi
