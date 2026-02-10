#!/bin/bash
# ServerGuard Access Checker v3.0 (Remote Agent)

# 1. Load Config
if [ -f "/etc/server-guard/agent.env" ]; then
    source "/etc/server-guard/agent.env"
fi

# 2. Debug Log
LOG_FILE="/tmp/sg-debug.log"

# 3. ULTIMATE TOKEN SANITIZATION
# Trim whitespace
API_TOKEN=$(echo "$API_TOKEN" | xargs)

# Check for bad values
if [ "$API_TOKEN" = "None" ] || [ "$API_TOKEN" = "null" ] || [ -z "$API_TOKEN" ]; then
    # On remote agents, we cannot default to 'local-token' blindly, 
    # but if the config is broken, we have no choice but to try or fail.
    # We will log this critical error.
    echo "$(date) [CRITICAL] Token is missing or None on Agent!" >> $LOG_FILE
fi

# 4. URL Default
if [ -z "$API_URL" ]; then
    echo "$(date) [CRITICAL] API_URL missing!" >> $LOG_FILE
    exit 1
fi

# 5. Get Connection Info
if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
else
    IP="127.0.0.1"
fi
USER=$(whoami)

# 6. Bypass Localhost
if [ "$IP" = "127.0.0.1" ] || [ "$IP" = "::1" ]; then
    exit 0
fi

# 7. Execute Request
HTTP_CODE=$(curl -4 -m 3 -s -o /dev/null -w "%{http_code}" \
    -H "X-Guard-Token: $API_TOKEN" \
    "${API_URL}?ip=${IP}&user=${USER}" 2>>$LOG_FILE)

CURL_RET=$?

# 8. Handle Curl Errors
if [ $CURL_RET -ne 0 ]; then
    echo "$(date) [FAIL] Curl failed (Exit: $CURL_RET) to $API_URL" >> $LOG_FILE
    # Fail Closed
    echo "⚠️  ServerGuard Connection Error. See /tmp/sg-debug.log"
    exit 1
fi

# 9. Handle Response
if [ "$HTTP_CODE" = "200" ]; then
    echo "$(date) [OK] Access Granted for $IP" >> $LOG_FILE
    exit 0
elif [ "$HTTP_CODE" = "403" ]; then
    echo "$(date) [BLOCK] Access Denied for $IP" >> $LOG_FILE
    echo "🚨 ACCESS DENIED: Authorization required."
    exit 1
else
    echo "$(date) [ERROR] API returned $HTTP_CODE" >> $LOG_FILE
    echo "⚠️  ServerGuard API Error ($HTTP_CODE)"
    exit 1
fi
