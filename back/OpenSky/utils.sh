#!/bin/bash

# Define Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color (Reset)

# Helper functions for clean output
info() {
    local message="$1"
    echo -e "${GREEN}[INFO]${NC} ${message}">&2; 
    return 0
}

warn() { 
    local message="$1"
    echo -e "${YELLOW}[WARN]${NC} ${message}">&2; 
    return 0
}

error() { 
    local message="$1"
    echo -e "${RED}[ERROR]${NC} ${message}">&2; 
    return 0
}

header() { 
    local message="$1"
    echo -e "${BLUE}=== ${message} ===${NC}">&2; 
    return 0
}

export -f info
export -f warn
export -f error