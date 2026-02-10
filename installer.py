import os
import sys
import shutil
import subprocess

INSTALL_DIR = "/opt/server-guard"
BIN_NAME = "ToolsServer"

def run_cmd(cmd):
    subprocess.run(cmd, shell=True, check=True)

def print_step(msg):
    print(f"\033[1;32m[+] {msg}\033[0m")

def main():
    if os.geteuid() != 0:
        sys.exit("Please run as root: sudo python3 installer.py")

    print("\033[1;36m======================================")
    print("   ServerGuard Installer v1.0   ")
    print("======================================\033[0m")

    # 1. Environment Check
    print_step("Checking environment...")
    if not shutil.which("docker"):
        print("Docker not found! Installing...")
        run_cmd("curl -fsSL https://get.docker.com | sh")
    
    # 2. Structure Creation
    print_step(f"Creating directories in {INSTALL_DIR}...")
    if os.path.exists(INSTALL_DIR):
        shutil.rmtree(INSTALL_DIR)
    
    os.makedirs(os.path.join(INSTALL_DIR, "data"))
    os.makedirs(os.path.join(INSTALL_DIR, "src"))
    
    # 3. File Copy
    print_step("Copying source files...")
    cwd = os.path.dirname(os.path.abspath(__file__))
    
    shutil.copytree(os.path.join(cwd, "src"), os.path.join(INSTALL_DIR, "src"), dirs_exist_ok=True)
    shutil.copy(os.path.join(cwd, "manager.py"), os.path.join(INSTALL_DIR, "manager.py"))
    
    # 4. Host Scripts
    print_step("Installing host scripts...")
    shutil.copy(os.path.join(cwd, "scripts/gatekeeper.sh"), "/usr/local/bin/sg-gatekeeper")
    shutil.copy(os.path.join(cwd, "scripts/logger.sh"), "/usr/local/bin/sg-logger")
    shutil.copy(os.path.join(cwd, "scripts/auth_hook.sh"), "/etc/profile.d/z99-server-guard.sh")
    
    run_cmd("chmod +x /usr/local/bin/sg-gatekeeper")
    run_cmd("chmod +x /usr/local/bin/sg-logger")
    run_cmd("chmod +x /etc/profile.d/z99-server-guard.sh")
    run_cmd(f"chmod +x {INSTALL_DIR}/manager.py")

    # 5. BashRC Hook
    print_step("Patching .bashrc...")
    bashrc_path = os.path.expanduser("~/.bashrc") # Usually /root/.bashrc or users
    # We actually need to patch /etc/bash.bashrc for global effect
    target_rc = "/etc/bash.bashrc"
    
    hook_content = """
# --- SERVERGUARD HOOK ---
sg_monitor_hook() {
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
        with open(target_rc, "r") as f:
            content = f.read()
        if "SERVERGUARD HOOK" not in content:
            with open(target_rc, "a") as f:
                f.write(hook_content)
    except Exception as e:
        print(f"Warning: Could not patch {target_rc}: {e}")

    # 6. Configuration
    print_step("Configuration Setup")
    tg_token = input("Enter Telegram Bot Token: ").strip()
    admin_id = input("Enter Your Telegram Admin ID: ").strip()
    
    with open(os.path.join(INSTALL_DIR, ".env"), "w") as f:
        f.write(f"TG_TOKEN={tg_token}\n")
        f.write(f"ADMIN_ID={admin_id}\n")

    # 7. Symlink
    print_step(f"Creating '{BIN_NAME}' command...")
    symlink_path = f"/usr/local/bin/{BIN_NAME}"
    if os.path.exists(symlink_path):
        os.remove(symlink_path)
    os.symlink(f"{INSTALL_DIR}/manager.py", symlink_path)

    # 8. Launch
    print_step("Starting Docker services...")
    run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml up -d --build")

    print("\n\033[1;32m✅ Installation Complete!\033[0m")
    print(f"Type \033[1;36m{BIN_NAME}\033[0m to manage the server.")

if __name__ == "__main__":
    main()
