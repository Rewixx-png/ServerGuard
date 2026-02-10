#!/bin/bash
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
  "user": "$USER",
  "ip": "$IP",
  "cmd": "$CMD"
}
EOF
)

# Send UDP packet to Bot (Fast, Fire-and-Forget)
echo "$PAYLOAD" | nc -u -w 1 127.0.0.1 9999 > /dev/null 2>&1 &