#!/bin/bash

# Load Config
if [ -f "/etc/server-guard/agent.env" ]; then
    source "/etc/server-guard/agent.env"
else
    # Fallback defaults
    LOG_HOST="127.0.0.1"
    API_TOKEN="local-token"
fi

CMD="$1"
USER=$(whoami)

# Get IP safely
if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
else
    IP="LOCAL"
fi

# Create JSON Payload with Token
PAYLOAD=$(cat <<EOF
{
  "type": "cmd",
  "token": "$API_TOKEN",
  "user": "$USER",
  "ip": "$IP",
  "cmd": "$CMD"
}
EOF
)

# Send via UDP to the LOG_HOST defined in env
echo "$PAYLOAD" | nc -u -w 1 "$LOG_HOST" 9999 > /dev/null 2>&1 &
