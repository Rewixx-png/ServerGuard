#!/bin/bash

CONFIG_FILE="/etc/server-guard/agent.env"

# Load Config
if [ -f "$CONFIG_FILE" ]; then
    set -a # Automatically export all variables
    source "$CONFIG_FILE"
    set +a
fi

# Fallback if source failed
if [ -z "$API_TOKEN" ]; then
    API_TOKEN="local-token"
fi
if [ -z "$API_URL" ]; then
    API_URL="http://127.0.0.1:8080/check-access"
fi

USER=$(whoami)

if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
else
    IP="127.0.0.1"
fi

# Allow localhost bypass
if [ "$IP" = "127.0.0.1" ] || [ "$IP" = "::1" ]; then
    exit 0
fi

# Debug: Print to stderr if token is missing (visible in manual run)
if [ -z "$API_TOKEN" ]; then
    echo "Error: API_TOKEN is empty in check_access.sh" >&2
fi

# Request
HTTP_CODE=$(curl -4 -m 2 -s -o /dev/null -w "%{http_code}" -H "X-Guard-Token: $API_TOKEN" "${API_URL}?ip=${IP}&user=${USER}")

if [ "$HTTP_CODE" = "200" ]; then
    exit 0
elif [ "$HTTP_CODE" = "403" ]; then
    echo "🚨 ACCESS DENIED: IP ${IP} is not authorized."
    exit 1
else
    # Fail safe
    echo "⚠️  ServerGuard System Error (Code: ${HTTP_CODE})"
    exit 1
fi
