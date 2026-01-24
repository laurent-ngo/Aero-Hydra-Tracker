#!/bin/bash

LOCAL_ENVS="./local.sh"

# Define Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color (Reset)

# Helper functions for clean output
info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

export -f info
export -f warn
export -f error


if [[ -x "$LOCAL_ENVS" ]]; then
    info "Loading local variables..."
    bash "$LOCAL_ENVS"
fi

source ./local.sh

# Check if env vars are provided
if [[ -z "$OPEN_SKY_CLIENT_ID" ]] ; then
    error "Missing var : OPEN_SKY_CLIENT_ID"
    exit 1
fi

if [[ -z "$OPEN_SKY_CLIENT_SECRET" ]] ; then
    error "Missing var : OPEN_SKY_CLIENT_SECRET"
    exit 1
fi


source ./OAuth2ClientCredential.sh $OPEN_SKY_CLIENT_ID $OPEN_SKY_CLIENT_SECRET
