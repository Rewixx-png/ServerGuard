#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import urllib.request

INSTALL_DIR = "/opt/server-guard"
BIN_NAME = "ToolsServer"

def run_cmd(cmd):
    subprocess.run(cmd, shell=True, check=True)

def print_step(msg):
    print(f"\033[1;32m[+] {msg}\033[0m")

def get_public_ip():
    try: return urllib.request.urlopen('https://api.ipify.org').read().decode('utf8')
    except: return "127.0.0.1"

def main():
    if os.geteuid() != 0: sys.exit("Run as root.")

    print_step("Updating Components...")
    
    # Ensure Docker
    if not shutil.which("docker"): run_cmd("curl -fsSL https://get.docker.com | sh")
    run_cmd("apt-get install -y curl netcat-openbsd")

    # Paths
    cwd = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Update Scripts
    print_step("Updating local scripts...")
    shutil.copy(os.path.join(cwd, "src/scripts/check_access.sh"), "/usr/local/bin/sg-check-access")
    shutil.copy(os.path.join(cwd, "src/scripts/sftp_wrapper.sh"), "/usr/local/bin/sg-sftp-wrapper")
    shutil.copy(os.path.join(cwd, "src/scripts/logger.sh"), "/usr/local/bin/sg-logger")
    run_cmd("chmod +x /usr/local/bin/sg-*")

    # 2. Update Config Permissions
    print_step("Fixing config permissions...")
    os.makedirs("/etc/server-guard", exist_ok=True)
    conf_file = "/etc/server-guard/agent.env"
    
    # Write config if missing
    if not os.path.exists(conf_file):
        with open(conf_file, "w") as f:
            f.write('API_URL="http://127.0.0.1:8080/check-access"\n')
            f.write('API_TOKEN="local-token"\n')
            f.write('LOG_HOST="127.0.0.1"\n')
    
    # CRITICAL: Make config readable by all users (so 'ls' by non-root can be logged)
    run_cmd("chmod 755 /etc/server-guard")
    run_cmd("chmod 644 /etc/server-guard/agent.env")

    # 3. Rebuild Bot
    print_step("Rebuilding Docker...")
    shutil.copytree(os.path.join(cwd, "src"), os.path.join(INSTALL_DIR, "src"), dirs_exist_ok=True)
    run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml down")
    run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml up -d --build")

    print("\n\033[1;32m✅ Update Complete!\033[0m")
    print("Please execute a command (ls/pwd) and check docker logs.")

if __name__ == "__main__":
    main()
