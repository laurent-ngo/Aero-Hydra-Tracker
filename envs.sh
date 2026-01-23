#!/bin/bash
# Check if argument is provided
if [ -z "$1" ] ; then
    echo "Usage: $0 <client_secret>"
    exit 1
fi

source back/OpenSky/OAuth2ClientCredential.sh laurent.ngo-api-client $1
