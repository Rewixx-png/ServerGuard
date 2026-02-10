#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import urllib.request
import time

INSTALL_DIR = "/opt/server-guard"
BIN_NAME = "ToolsServer"
SSHD_CONFIG = "/etc/ssh/sshd_config"

# --- SCRIPTS CONTENT (INLINED FOR SAFETY) ---

SCRIPT_CHECK_ACCESS = r"""#!/bin/bash
# ServerGuard Access Checker v2.5
# Force load config
if [ -f "/etc/server-guard/agent.env" ]; then
    source "/etc/server-guard/agent.env"
fi

# Debug Log
LOG_FILE="/tmp/sg-debug.log"

# Defaults if config fails
if [ -z "$API_TOKEN" ]; then
    echo "$(date) [ERROR] API_TOKEN missing in agent.env" >> $LOG_FILE
    API_TOKEN="local-token"
fi
if [ -z "$API_URL" ]; then
    API_URL="http://127.0.0.1:8080/check-access"
fi

# Get IP
if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
else
    IP="127.0.0.1"
fi
USER=$(whoami)

# Bypass Localhost
if [ "$IP" = "127.0.0.1" ] || [ "$IP" = "::1" ]; then
    exit 0
fi

# Execute Request with explicit Header
# We capture stderr to log file for debugging
HTTP_CODE=$(curl -4 -m 3 -s -o /dev/null -w "%{http_code}" \
    -H "X-Guard-Token: $API_TOKEN" \
    "${API_URL}?ip=${IP}&user=${USER}" 2>>$LOG_FILE)

CURL_RET=$?

if [ $CURL_RET -ne 0 ]; then
    echo "$(date) [FAIL] Curl connection failed (Exit: $CURL_RET) to $API_URL" >> $LOG_FILE
    # Fail Closed
    echo "⚠️  ServerGuard Connection Error. See /tmp/sg-debug.log"
    exit 1
fi

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
"""

SCRIPT_LOGGER = r"""#!/bin/bash
# ServerGuard Logger v2.5
if [ -f "/etc/server-guard/agent.env" ]; then
    source "/etc/server-guard/agent.env"
else
    API_TOKEN="local-token"
    LOG_HOST="127.0.0.1"
fi

CMD="$1"
USER=$(whoami)
if [ -n "$SSH_CONNECTION" ]; then
    IP=$(echo "$SSH_CONNECTION" | awk '{print $1}')
else
    IP="LOCAL"
fi

# JSON Payload
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

# Send UDP
echo "$PAYLOAD" | nc -u -w 1 "$LOG_HOST" 9999 > /dev/null 2>&1 &
"""

SCRIPT_SFTP = r"""#!/bin/bash
# ServerGuard SFTP Wrapper
/usr/local/bin/sg-check-access
if [ $? -ne 0 ]; then
    exit 1
fi

if [ -x "/usr/lib/openssh/sftp-server" ]; then
    exec /usr/lib/openssh/sftp-server "$@"
elif [ -x "/usr/libexec/openssh/sftp-server" ]; then
    exec /usr/libexec/openssh/sftp-server "$@"
else
    echo "SFTP Server binary not found."
    exit 1
fi
"""

# --- HELPERS ---

def run_cmd(cmd):
    subprocess.run(cmd, shell=True, check=True)

def print_step(msg):
    print(f"\033[1;32m[+] {msg}\033[0m")

def write_file(path, content, mode=0o755):
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, mode)

def get_public_ip():
    try:
        return urllib.request.urlopen('https://api.ipify.org', timeout=3).read().decode('utf8')
    except:
        return "127.0.0.1"

def patch_sshd_config():
    print_step(f"Patching {SSHD_CONFIG}...")
    if not os.path.exists(SSHD_CONFIG): return

    # Backup
    if not os.path.exists(f"{SSHD_CONFIG}.bak"):
        shutil.copy(SSHD_CONFIG, f"{SSHD_CONFIG}.bak")
    
    with open(SSHD_CONFIG, "r") as f:
        lines = f.readlines()
    
    new_lines = []
    sftp_patched = False
    wrapper = "/usr/local/bin/sg-sftp-wrapper"

    for line in lines:
        if line.strip().startswith("Subsystem") and "sftp" in line:
            if wrapper in line:
                sftp_patched = True
                new_lines.append(line)
            else:
                new_lines.append(f"# {line.strip()} [Disabled by ServerGuard]\n")
                new_lines.append(f"Subsystem sftp {wrapper}\n")
                sftp_patched = True
        else:
            new_lines.append(line)
            
    if not sftp_patched:
        new_lines.append(f"\nSubsystem sftp {wrapper}\n")

    with open(SSHD_CONFIG, "w") as f:
        f.writelines(new_lines)

    try:
        run_cmd("systemctl restart sshd")
    except:
        pass

def main():
    if os.geteuid() != 0:
        sys.exit("Please run as root.")

    print("\033[1;36m======================================")
    print("   ServerGuard Hardcore Installer     ")
    print("======================================\033[0m")

    # 1. Environment
    print_step("Checking dependencies...")
    if not shutil.which("docker"):
        print("Installing Docker...")
        run_cmd("curl -fsSL https://get.docker.com | sh")
    run_cmd("apt-get update -qq && apt-get install -y curl netcat-openbsd")

    # 2. Config
    print_step("Configuring Agent...")
    os.makedirs("/etc/server-guard", exist_ok=True)
    
    # Force overwrite agent.env to ensure valid syntax
    with open("/etc/server-guard/agent.env", "w") as f:
        f.write('API_URL="http://127.0.0.1:8080/check-access"\n')
        f.write('API_TOKEN="local-token"\n')
        f.write('LOG_HOST="127.0.0.1"\n')
    
    os.chmod("/etc/server-guard", 0o755)
    os.chmod("/etc/server-guard/agent.env", 0o644)

    # 3. Write Host Scripts (Direct Write - No Copy)
    print_step("Writing System Binaries...")
    write_file("/usr/local/bin/sg-check-access", SCRIPT_CHECK_ACCESS)
    write_file("/usr/local/bin/sg-logger", SCRIPT_LOGGER)
    write_file("/usr/local/bin/sg-sftp-wrapper", SCRIPT_SFTP)

    # 4. Profile Hook
    hook_file = "/etc/profile.d/z99-server-guard.sh"
    hook_content = """if [ -n "$SSH_CONNECTION" ]; then
    /usr/local/bin/sg-check-access
    if [ $? -ne 0 ]; then kill -KILL $$; fi
fi
"""
    write_file(hook_file, hook_content)

    # 5. BashRC Hook
    bashrc = "/etc/bash.bashrc"
    bashrc_content = """
# --- SERVERGUARD HOOK ---
sg_monitor_hook() {
    if [ ! -x /usr/local/bin/sg-logger ]; then return; fi
    local LAST_CMD=$(history 1 | sed "s/^[ ]*[0-9]*[ ]*//")
    if [ -n "$LAST_CMD" ]; then
        /usr/local/bin/sg-logger "$LAST_CMD" &
    fi
}
if [ -x /usr/local/bin/sg-logger ]; then
    export PROMPT_COMMAND="history -a; sg_monitor_hook"
fi
# --- END SERVERGUARD ---
"""
    # Simple check to append
    try:
        with open(bashrc, "r") as f:
            if "SERVERGUARD HOOK" not in f.read():
                with open(bashrc, "a") as fa:
                    fa.write(bashrc_content)
    except: pass

    # 6. SSHD
    patch_sshd_config()

    # 7. Bot Setup
    print_step("Setting up Docker...")
    # Check .env
    env_path = os.path.join(INSTALL_DIR, ".env")
    if not os.path.exists(env_path):
        os.makedirs(INSTALL_DIR, exist_ok=True)
        tg = input("Telegram Token: ").strip()
        aid = input("Admin ID: ").strip()
        ip = get_public_ip()
        with open(env_path, "w") as f:
            f.write(f"TG_TOKEN={tg}\nADMIN_ID={aid}\nPUBLIC_IP={ip}\n")
    
    # Rebuild
    cwd = os.path.dirname(os.path.abspath(__file__))
    # Copy src
    shutil.rmtree(f"{INSTALL_DIR}/src", ignore_errors=True)
    shutil.copytree(os.path.join(cwd, "src"), f"{INSTALL_DIR}/src")
    shutil.copy(os.path.join(cwd, "manager.py"), f"{INSTALL_DIR}/manager.py")
    os.symlink(f"{INSTALL_DIR}/manager.py", "/usr/local/bin/ToolsServer") if not os.path.exists("/usr/local/bin/ToolsServer") else None

    run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml down")
    run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml up -d --build")

    print("\n✅ \033[1;32mDONE!\033[0m")
    print("Debug log available at: /tmp/sg-debug.log")

if __name__ == "__main__":
    main()
