#!/bin/bash
# ServerGuard Remote Installer v3.1
# Args: API_URL TOKEN LOG_HOST

API_URL="$1"
API_TOKEN="$2"
LOG_HOST="$3"

LOG_FILE="/tmp/sg_install_debug.log"
echo "Starting Install: $(date)" > $LOG_FILE
echo "Params: URL=$API_URL HOST=$LOG_HOST" >> $LOG_FILE

# 0. Self-Check Connectivity
echo "Checking connectivity to Master ($LOG_HOST)..."
if command -v nc &> /dev/null; then
    nc -z -w 3 "$LOG_HOST" 8080
    if [ $? -eq 0 ]; then
        echo "Connection OK" >> $LOG_FILE
    else
        echo "WARNING: Cannot reach Master on port 8080. Firewall?" >> $LOG_FILE
    fi
fi

# 1. Install Dependencies
if command -v apt-get &> /dev/null; then
    apt-get update -qq && apt-get install -y curl netcat-openbsd
elif command -v yum &> /dev/null; then
    yum install -y curl nc
fi

# 2. Configure
mkdir -p /etc/server-guard
# Force overwrite
cat > /etc/server-guard/agent.env <<EOF
API_URL="$API_URL"
API_TOKEN="$API_TOKEN"
LOG_HOST="$LOG_HOST"
EOF
chmod 644 /etc/server-guard/agent.env

# 3. Install Binaries
mv /tmp/sg-check-access /usr/local/bin/sg-check-access
mv /tmp/sg-logger /usr/local/bin/sg-logger
mv /tmp/sg-sftp-wrapper /usr/local/bin/sg-sftp-wrapper

chmod +x /usr/local/bin/sg-check-access
chmod +x /usr/local/bin/sg-logger
chmod +x /usr/local/bin/sg-sftp-wrapper

# 4. Hooks
cat > /etc/profile.d/z99-server-guard.sh <<EOF
if [ -n "\$SSH_CONNECTION" ]; then
    /usr/local/bin/sg-check-access
    if [ \$? -ne 0 ]; then kill -KILL \$\$; fi
fi
EOF

# BashRC Global
BASHRC="/etc/bash.bashrc"
# Clear old hooks first to prevent duplicates
sed -i '/# --- SERVERGUARD HOOK ---/,/# --- END SERVERGUARD ---/d' "$BASHRC"

cat >> "$BASHRC" <<EOF

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
EOF

# 5. SSHD Config
SSHD_CONFIG="/etc/ssh/sshd_config"
cp $SSHD_CONFIG ${SSHD_CONFIG}.bak
sed -i 's/^Subsystem[[:space:]]\+sftp/# &/' $SSHD_CONFIG
if ! grep -q "sg-sftp-wrapper" $SSHD_CONFIG; then
    echo "Subsystem sftp /usr/local/bin/sg-sftp-wrapper" >> $SSHD_CONFIG
fi
service sshd reload || systemctl reload sshd

echo ">>> Agent Installed Successfully." >> $LOG_FILE