#!/bin/bash
# Check if both arguments are provided
if [ -z "$1" ] ; then
    echo "Usage: $0 <client_secret>"
    exit 1
fi

back/OpenSky/OAuth2ClientCredential.sh laurent.ngo-api-client $1
