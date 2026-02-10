#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import urllib.request

INSTALL_DIR = "/opt/server-guard"
BIN_NAME = "ToolsServer"
SSHD_CONFIG = "/etc/ssh/sshd_config"

def run_cmd(cmd):
    subprocess.run(cmd, shell=True, check=True)

def print_step(msg):
    print(f"\033[1;32m[+] {msg}\033[0m")

def get_public_ip():
    try:
        return urllib.request.urlopen('https://api.ipify.org').read().decode('utf8')
    except:
        return "127.0.0.1"

def patch_sshd_config():
    print_step(f"Patching {SSHD_CONFIG} for SFTP interception...")
    
    if not os.path.exists(SSHD_CONFIG):
        print(f"Error: {SSHD_CONFIG} not found.")
        return

    shutil.copy(SSHD_CONFIG, f"{SSHD_CONFIG}.bak")
    
    with open(SSHD_CONFIG, "r") as f:
        lines = f.readlines()
    
    new_lines = []
    sftp_patched = False
    wrapper_path = "/usr/local/bin/sg-sftp-wrapper"

    for line in lines:
        if line.strip().startswith("Subsystem") and "sftp" in line:
            if wrapper_path in line:
                sftp_patched = True
                new_lines.append(line)
            else:
                new_lines.append(f"# {line.strip()} [Disabled by ServerGuard]\n")
                new_lines.append(f"Subsystem sftp {wrapper_path}\n")
                sftp_patched = True
        else:
            new_lines.append(line)
            
    if not sftp_patched:
        new_lines.append(f"\nSubsystem sftp {wrapper_path}\n")

    with open(SSHD_CONFIG, "w") as f:
        f.writelines(new_lines)

    try:
        run_cmd("systemctl restart sshd")
    except:
        pass

def clean_bashrc_hook(file_path):
    if not os.path.exists(file_path): return
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
        with open(file_path, "w") as f:
            skip = False
            for line in lines:
                if "# --- SERVERGUARD HOOK ---" in line: skip = True
                if not skip: f.write(line)
                if "# --- END SERVERGUARD ---" in line: skip = False
    except:
        pass

def main():
    if os.geteuid() != 0:
        sys.exit("Please run as root: sudo python3 installer.py")

    print("\033[1;36m======================================")
    print("   ServerGuard Controller Installer   ")
    print("======================================\033[0m")

    # 1. Environment Check
    print_step("Checking environment...")
    if not shutil.which("docker"):
        print("Docker not found! Installing...")
        run_cmd("curl -fsSL https://get.docker.com | sh")
    
    if not shutil.which("curl"):
        run_cmd("apt-get update && apt-get install -y curl")
        
    if not shutil.which("nc"):
        run_cmd("apt-get install -y netcat")

    # 2. Structure Creation
    print_step(f"Creating directories in {INSTALL_DIR}...")
    if os.path.exists(INSTALL_DIR):
        if not os.path.exists(f"{INSTALL_DIR}/data"):
            shutil.rmtree(INSTALL_DIR)
            os.makedirs(os.path.join(INSTALL_DIR, "data"))
        else:
            if os.path.exists(f"{INSTALL_DIR}/src"):
                shutil.rmtree(f"{INSTALL_DIR}/src")
    else:
        os.makedirs(os.path.join(INSTALL_DIR, "data"))

    os.makedirs(os.path.join(INSTALL_DIR, "src"))
    
    # 3. File Copy
    print_step("Copying source files...")
    cwd = os.path.dirname(os.path.abspath(__file__))
    
    shutil.copytree(os.path.join(cwd, "src"), os.path.join(INSTALL_DIR, "src"), dirs_exist_ok=True)
    shutil.copy(os.path.join(cwd, "manager.py"), os.path.join(INSTALL_DIR, "manager.py"))
    
    # 4. Host Scripts (Local Master Node)
    print_step("Installing local master node scripts...")
    
    # We install the scripts locally so this server is also protected
    shutil.copy(os.path.join(cwd, "src/scripts/check_access.sh"), "/usr/local/bin/sg-check-access")
    shutil.copy(os.path.join(cwd, "src/scripts/sftp_wrapper.sh"), "/usr/local/bin/sg-sftp-wrapper")
    shutil.copy(os.path.join(cwd, "src/scripts/logger.sh"), "/usr/local/bin/sg-logger")
    shutil.copy(os.path.join(cwd, "src/scripts/auth_hook.sh"), "/etc/profile.d/z99-server-guard.sh")
    
    run_cmd("chmod +x /usr/local/bin/sg-check-access")
    run_cmd("chmod +x /usr/local/bin/sg-sftp-wrapper")
    run_cmd("chmod +x /usr/local/bin/sg-logger")
    run_cmd("chmod +x /etc/profile.d/z99-server-guard.sh")
    run_cmd(f"chmod +x {INSTALL_DIR}/manager.py")

    # Create local config for master node
    os.makedirs("/etc/server-guard", exist_ok=True)
    with open("/etc/server-guard/agent.env", "w") as f:
        f.write("API_URL=http://127.0.0.1:8080/check-access\n")
        f.write("API_TOKEN=local-token\n")
        f.write("LOG_HOST=127.0.0.1\n")

    # 5. Patch SSHD
    patch_sshd_config()

    # 6. BashRC Hook
    print_step("Patching .bashrc for logging...")
    target_rc = "/etc/bash.bashrc"
    clean_bashrc_hook(target_rc)
    
    hook_content = """
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
    try:
        with open(target_rc, "a") as f:
            f.write(hook_content)
    except:
        pass

    # 7. Configuration
    print_step("Configuration Setup")
    if not os.path.exists(os.path.join(INSTALL_DIR, ".env")):
        tg_token = input("Enter Telegram Bot Token: ").strip()
        admin_id = input("Enter Your Telegram Admin ID: ").strip()
        
        # Detect Public IP
        detected_ip = get_public_ip()
        pub_ip = input(f"Enter Public IP of this server [{detected_ip}]: ").strip() or detected_ip
        
        with open(os.path.join(INSTALL_DIR, ".env"), "w") as f:
            f.write(f"TG_TOKEN={tg_token}\n")
            f.write(f"ADMIN_ID={admin_id}\n")
            f.write(f"PUBLIC_IP={pub_ip}\n")
    else:
        print("Configuration found, skipping...")

    # 8. Symlink
    symlink_path = f"/usr/local/bin/{BIN_NAME}"
    if os.path.exists(symlink_path): os.remove(symlink_path)
    os.symlink(f"{INSTALL_DIR}/manager.py", symlink_path)

    # 9. Launch
    print_step("Starting Controller...")
    run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml up -d --build")

    print("\n\033[1;32m✅ Installation Complete!\033[0m")

if __name__ == "__main__":
    main()