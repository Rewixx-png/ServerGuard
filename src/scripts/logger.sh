#!/bin/bash
# ServerGuard Logger v3.0 (Remote Agent)
if [ -f "/etc/server-guard/agent.env" ]; then
    source "/etc/server-guard/agent.env"
fi

API_TOKEN=$(echo "$API_TOKEN" | xargs)
if [ -z "$LOG_HOST" ]; then exit 0; fi

CMD="$1"
USER=$(whoami)
if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
else
    IP="LOCAL"
fi

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

echo "$PAYLOAD" | nc -u -w 1 "$LOG_HOST" 9999 > /dev/null 2>&1 &
