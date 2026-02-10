#!/bin/bash

# Default Config
CONFIG_FILE="/etc/server-guard/agent.env"
API_URL="http://127.0.0.1:8080/check-access"
API_TOKEN="local-token"

# Load Config if exists
if [ -f "$CONFIG_FILE" ]; then
    source "$CONFIG_FILE"
fi

USER=$(whoami)

# Extract IP from SSH_CONNECTION
if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
else
    IP="127.0.0.1"
fi

# Whitelist Localhost explicitly to prevent lockout if config is bad
if [ "$IP" = "127.0.0.1" ] || [ "$IP" = "::1" ]; then
    exit 0
fi

# Perform check
# Pass Token in header for security
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "X-Guard-Token: $API_TOKEN" "${API_URL}?ip=${IP}&user=${USER}")

if [ "$HTTP_CODE" = "200" ]; then
    exit 0
elif [ "$HTTP_CODE" = "403" ]; then
    echo "🚨 ACCESS DENIED: IP ${IP} is not authorized."
    echo "Request sent to ServerGuard Admin."
    exit 1
else
    # Fail Closed
    echo "⚠️  ServerGuard Verification Failed (Error ${HTTP_CODE})"
    echo "Contact System Administrator."
    exit 1
fi