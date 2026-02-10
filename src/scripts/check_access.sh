#!/bin/bash

API_URL="http://127.0.0.1:8080/check-access"
USER=$(whoami)

# Extract IP from SSH_CONNECTION (client_ip client_port server_ip server_port)
if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
else
    # Fallback for non-SSH contexts or local testing
    IP="127.0.0.1"
fi

# Skip check for localhost/docker network if needed, but safer to check everything
# If IP is empty, allow (likely local console)
if [ -z "$IP" ]; then
    exit 0
fi

# Perform check
# -s: Silent
# -o /dev/null: discard body
# -w "%{http_code}": print status code
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}?ip=${IP}&user=${USER}")

if [ "$HTTP_CODE" = "200" ]; then
    exit 0
elif [ "$HTTP_CODE" = "403" ]; then
    echo "🚨 ACCESS DENIED: IP ${IP} is not authorized."
    echo "Check your Telegram for authorization request."
    exit 1
else
    # Fail closed if bot is down (safety first)
    echo "⚠️  ServerGuard System Unavailable (Error ${HTTP_CODE})"
    exit 1
fi