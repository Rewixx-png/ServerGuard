#!/bin/bash

# Arguments:
# $1 = Controller API URL (e.g., http://1.2.3.4:8080)
# $2 = Agent Token
# $3 = UDP Logger Host (e.g., 1.2.3.4)

API_URL="$1"
TOKEN="$2"
LOG_HOST="$3"

if [ -z "$API_URL" ] || [ -z "$TOKEN" ]; then
    echo "Error: Missing arguments."
    exit 1
fi

echo ">>> Installing ServerGuard Agent..."

# 1. Install Dependencies
apt-get update -qq && apt-get install -y curl netcat-openbsd

# 2. Setup Config
mkdir -p /etc/server-guard
cat > /etc/server-guard/agent.env <<EOF
API_URL="${API_URL}/check-access"
API_TOKEN="${TOKEN}"
LOG_HOST="${LOG_HOST}"
EOF
chmod 600 /etc/server-guard/agent.env

# 3. Create Scripts
# We assume the 'check_access.sh' content is passed via scp or created here. 
# For this installer, we will download them or assume they are copied to /tmp by the bot.

mv /tmp/sg-check-access /usr/local/bin/sg-check-access
mv /tmp/sg-sftp-wrapper /usr/local/bin/sg-sftp-wrapper
mv /tmp/sg-logger /usr/local/bin/sg-logger

chmod +x /usr/local/bin/sg-check-access
chmod +x /usr/local/bin/sg-sftp-wrapper
chmod +x /usr/local/bin/sg-logger

# 4. Configure Logger (Point to Remote Controller)
cat > /usr/local/bin/sg-logger <<EOF_LOG
#!/bin/bash
CMD="\$1"
USER=\$(whoami)
if [ -n "\$SSH_CONNECTION" ]; then
    IP=\$(echo "\$SSH_CONNECTION" | awk '{print \$1}')
else
    IP="LOCAL"
fi

# Read config for Log Host
source /etc/server-guard/agent.env

PAYLOAD=\$(cat <<JSON
{
  "type": "cmd",
  "token": "\$API_TOKEN",
  "user": "\$USER",
  "ip": "\$IP",
  "cmd": "\$CMD"
}
JSON
)

echo "\$PAYLOAD" | nc -u -w 1 \$LOG_HOST 9999 > /dev/null 2>&1 &
EOF_LOG
chmod +x /usr/local/bin/sg-logger

# 5. Profile Hook
HOOK_FILE="/etc/profile.d/z99-server-guard.sh"
cat > $HOOK_FILE <<EOF_HOOK
if [ -n "\$SSH_CONNECTION" ]; then
    /usr/local/bin/sg-check-access
    RET=\$?
    if [ \$RET -ne 0 ]; then
        kill -KILL \$\$
    fi
fi
EOF_HOOK
chmod +x $HOOK_FILE

# 6. Patch SSHD
SSHD_CONFIG="/etc/ssh/sshd_config"
cp $SSHD_CONFIG "${SSHD_CONFIG}.bak"
sed -i '/Subsystem sftp/d' $SSHD_CONFIG
echo "Subsystem sftp /usr/local/bin/sg-sftp-wrapper" >> $SSHD_CONFIG

# 7. BashRC Hook
BASHRC="/etc/bash.bashrc"
if ! grep -q "SERVERGUARD HOOK" $BASHRC; then
cat >> $BASHRC <<EOF_RC

# --- SERVERGUARD HOOK ---
sg_monitor_hook() {
    if [ ! -x /usr/local/bin/sg-logger ]; then return; fi
    local LAST_CMD=\$(history 1 | sed "s/^[ ]*[0-9]*[ ]*//")
    if [ -n "\$LAST_CMD" ]; then
        /usr/local/bin/sg-logger "\$LAST_CMD" &
    fi
}
if [ -x /usr/local/bin/sg-logger ]; then
    export PROMPT_COMMAND="history -a; sg_monitor_hook"
fi
# --- END SERVERGUARD ---
EOF_RC
fi

# 8. Restart SSH
service ssh restart || systemctl restart sshd

echo ">>> Agent Installed Successfully."
