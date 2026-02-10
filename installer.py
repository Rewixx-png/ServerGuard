#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import re

INSTALL_DIR = "/opt/server-guard"
BIN_NAME = "ToolsServer"
SSHD_CONFIG = "/etc/ssh/sshd_config"

def run_cmd(cmd):
    subprocess.run(cmd, shell=True, check=True)

def print_step(msg):
    print(f"\033[1;32m[+] {msg}\033[0m")

def patch_sshd_config():
    print_step(f"Patching {SSHD_CONFIG} for SFTP interception...")
    
    if not os.path.exists(SSHD_CONFIG):
        print(f"Error: {SSHD_CONFIG} not found.")
        return

    # Backup
    shutil.copy(SSHD_CONFIG, f"{SSHD_CONFIG}.bak")
    
    with open(SSHD_CONFIG, "r") as f:
        lines = f.readlines()
    
    new_lines = []
    sftp_patched = False
    
    # Check where sftp-server binary lives for the wrapper to fallback
    sftp_bin = "/usr/lib/openssh/sftp-server"
    if os.path.exists("/usr/libexec/openssh/sftp-server"):
        sftp_bin = "/usr/libexec/openssh/sftp-server"
    
    wrapper_path = "/usr/local/bin/sg-sftp-wrapper"

    for line in lines:
        # Detect existing Subsystem sftp
        if line.strip().startswith("Subsystem") and "sftp" in line:
            if wrapper_path in line:
                sftp_patched = True
                new_lines.append(line)
            else:
                # Comment out old config
                new_lines.append(f"# {line.strip()} [Disabled by ServerGuard]\n")
                new_lines.append(f"Subsystem sftp {wrapper_path}\n")
                sftp_patched = True
        else:
            new_lines.append(line)
            
    if not sftp_patched:
        # If no subsystem defined, append it
        new_lines.append(f"\nSubsystem sftp {wrapper_path}\n")

    with open(SSHD_CONFIG, "w") as f:
        f.writelines(new_lines)

    print_step("Restarting SSH Service...")
    try:
        run_cmd("systemctl restart sshd")
    except:
        try:
            run_cmd("service ssh restart")
        except:
            print("Warning: Could not restart SSH. Please restart manually.")

def clean_bashrc_hook(file_path):
    if not os.path.exists(file_path):
        return
    
    try:
        with open(file_path, "r") as f:
            lines = f.readlines()
        
        with open(file_path, "w") as f:
            skip = False
            for line in lines:
                if "# --- SERVERGUARD HOOK ---" in line:
                    skip = True
                if not skip:
                    f.write(line)
                if "# --- END SERVERGUARD ---" in line:
                    skip = False
    except Exception as e:
        print(f"Warning: Failed to clean {file_path}: {e}")

def main():
    if os.geteuid() != 0:
        sys.exit("Please run as root: sudo python3 installer.py")

    print("\033[1;36m======================================")
    print("   ServerGuard Installer v2.2 (Fix)   ")
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
        # We preserve data if exists
        if not os.path.exists(f"{INSTALL_DIR}/data"):
            shutil.rmtree(INSTALL_DIR)
            os.makedirs(os.path.join(INSTALL_DIR, "data"))
        else:
            # Refresh source only
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
    
    # 4. Host Scripts
    print_step("Installing system hooks...")
    
    # Copy scripts
    shutil.copy(os.path.join(cwd, "src/scripts/check_access.sh"), "/usr/local/bin/sg-check-access")
    shutil.copy(os.path.join(cwd, "src/scripts/sftp_wrapper.sh"), "/usr/local/bin/sg-sftp-wrapper")
    shutil.copy(os.path.join(cwd, "src/scripts/logger.sh"), "/usr/local/bin/sg-logger")
    shutil.copy(os.path.join(cwd, "src/scripts/auth_hook.sh"), "/etc/profile.d/z99-server-guard.sh")
    
    # Permissions
    run_cmd("chmod +x /usr/local/bin/sg-check-access")
    run_cmd("chmod +x /usr/local/bin/sg-sftp-wrapper")
    run_cmd("chmod +x /usr/local/bin/sg-logger")
    run_cmd("chmod +x /etc/profile.d/z99-server-guard.sh")
    run_cmd(f"chmod +x {INSTALL_DIR}/manager.py")

    # 5. Patch SSHD for SFTP
    patch_sshd_config()

    # 6. BashRC Hook (Force Update)
    print_step("Patching .bashrc for logging...")
    target_rc = "/etc/bash.bashrc"
    
    # First, clean old hooks to prevent duplication or legacy broken code
    clean_bashrc_hook(target_rc)
    
    # UPDATED HOOK: Checks for file existence inside the function
    hook_content = """
# --- SERVERGUARD HOOK ---
sg_monitor_hook() {
    # Fail-safe: silently return if logger is gone (uninstalled)
    if [ ! -x /usr/local/bin/sg-logger ]; then
        return
    fi
    local LAST_CMD=$(history 1 | sed "s/^[ ]*[0-9]*[ ]*//")
    if [ -n "$LAST_CMD" ]; then
        /usr/local/bin/sg-logger "$LAST_CMD" &
    fi
}
# Only export if installed, but function remains safe
if [ -x /usr/local/bin/sg-logger ]; then
    export PROMPT_COMMAND="history -a; sg_monitor_hook"
fi
# --- END SERVERGUARD ---
"""
    try:
        with open(target_rc, "a") as f:
            f.write(hook_content)
    except Exception as e:
        print(f"Warning: Could not patch {target_rc}: {e}")

    # 7. Configuration
    print_step("Configuration Setup")
    if not os.path.exists(os.path.join(INSTALL_DIR, ".env")):
        tg_token = input("Enter Telegram Bot Token: ").strip()
        admin_id = input("Enter Your Telegram Admin ID: ").strip()
        
        with open(os.path.join(INSTALL_DIR, ".env"), "w") as f:
            f.write(f"TG_TOKEN={tg_token}\n")
            f.write(f"ADMIN_ID={admin_id}\n")
    else:
        print("Configuration found, skipping...")

    # 8. Symlink
    print_step(f"Creating '{BIN_NAME}' command...")
    symlink_path = f"/usr/local/bin/{BIN_NAME}"
    if os.path.exists(symlink_path):
        os.remove(symlink_path)
    os.symlink(f"{INSTALL_DIR}/manager.py", symlink_path)

    # 9. Launch
    print_step("Starting Docker services...")
    run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml up -d --build")

    print("\n\033[1;32m✅ Installation Complete!\033[0m")
    print(f"Type \033[1;36m{BIN_NAME}\033[0m to manage the server.")

if __name__ == "__main__":
    main()