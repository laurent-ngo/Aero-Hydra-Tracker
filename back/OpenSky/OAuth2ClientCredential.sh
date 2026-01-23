#!/bin/bash

# Check if both arguments are provided
if [[ -z "$1" ]] || [[ -z "$2" ]]; then
    echo "Usage: $0 <client_id> <client_secret>"
    exit 1
fi

# configuration
CLIENT_ID="$1"
CLIENT_SECRET="$2"
AUTH_URL="https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"

# Fetch Token
TOKEN=$(curl -s -X POST "$AUTH_URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=$CLIENT_ID" \
  -d "client_secret=$CLIENT_SECRET" | jq -r .access_token)
  
# Output result (Fixed variable name from $TOKE to $TOKEN)
echo "Access Token saved under OPENSKY_CLIENT_TOKEN"
export OPENSKY_CLIENT_TOKEN="$TOKEN"

