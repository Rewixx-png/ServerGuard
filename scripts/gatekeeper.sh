#!/bin/bash
API_URL="http://127.0.0.1:8080/check-access"
CLIENT_IP=$(echo $SSH_CLIENT | awk '{print $1}')
USER_NAME=$(whoami)

if [ -z "$CLIENT_IP" ] || [ "$CLIENT_IP" == "127.0.0.1" ] || [[ "$CLIENT_IP" == "172."* ]]; then
    exit 0
fi

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${API_URL}?ip=${CLIENT_IP}&user=${USER_NAME}")

if [ "$HTTP_STATUS" != "200" ]; then
    echo "==================================================="
    echo " ⛔ ACCESS DENIED "
    echo "==================================================="
    echo " IP: $CLIENT_IP"
    echo " Status: Unauthorized"
    echo " Request sent to Administrator."
    echo "==================================================="
    exit 1
fi
exit 0
