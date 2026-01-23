#!/bin/bash

LOCAL_ENVS="./local.sh"

if [ -x "$LOCAL_ENVS" ]; then
    echo "Loading local variables..."
    bash "$LOCAL_ENVS"
fi

source ./local.sh

# Check if env vars are provided
if [[ -z "$OPEN_SKY_CLIENT_ID" ]] ; then
    echo "Missing var : OPEN_SKY_CLIENT_ID"
    exit 1
fi

if [[ -z "$OPEN_SKY_CLIENT_SECRET" ]] ; then
    echo "Missing var : OPEN_SKY_CLIENT_SECRET"
    exit 1
fi

source back/OpenSky/OAuth2ClientCredential.sh $OPEN_SKY_CLIENT_ID $OPEN_SKY_CLIENT_SECRET
