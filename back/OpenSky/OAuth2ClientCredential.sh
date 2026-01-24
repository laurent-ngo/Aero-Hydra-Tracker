#!/bin/bash

# Check if both arguments are provided
if [[ -z "$1" ]] || [[ -z "$2" ]]; then
    error "Usage: $0 <client_id> <client_secret>"
    exit 1
fi

# configuration
CLIENT_ID="$1"
CLIENT_SECRET="$2"
AUTH_URL="https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

info "Attempting to fetch token..."

# Fetch Token with timeout and error checking
# --max-time 15: kills the request if it takes longer than 15s
# --fail: makes curl return an error code for HTTP 4xx/5xx errors
RESPONSE=$(curl -s --max-time 15 --fail -X POST "$AUTH_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET")

# Check if curl succeeded
if [[ $? -ne 0 ]]; then
    error "Connection timed out or backend is down. Check your WSL2 network/Docker bridge."
    exit 1
fi

# Extract token using jq
TOKEN=$(echo "$RESPONSE" | jq -r .access_token)

# Verify the token is not null or empty
if [[ "$TOKEN" == "null" ]] || [[ -z "$TOKEN" ]]; then
    error "Response received, but token is empty. Check your credentials."
    exit 1
fi

# Output result (Fixed variable name from $TOKE to $TOKEN)
info "Successfully retrieved token."
info "Access Token saved under OPENSKY_CLIENT_TOKEN"
export OPENSKY_CLIENT_TOKEN="$TOKEN"

