#!/bin/bash

echo "Installing dev dependencies..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    brew install jq
    
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    sudo apt update && sudo apt install -y jq
fi