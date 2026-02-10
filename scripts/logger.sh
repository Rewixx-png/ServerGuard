#!/bin/bash
USER_NAME=$(whoami)
CLIENT_IP=$(echo $SSH_CLIENT | awk '{print $1}')
CMD="$1"

if [ -z "$CLIENT_IP" ]; then CLIENT_IP="Local"; fi
if [ -z "$CMD" ]; then exit 0; fi

JSON_PAYLOAD=$(python3 -c "import json, sys; print(json.dumps({'type': 'cmd', 'user': '$USER_NAME', 'ip': '$CLIENT_IP', 'cmd': sys.argv[1]}))" "$CMD")
echo -n "$JSON_PAYLOAD" > /dev/udp/127.0.0.1/9999 2>/dev/null
