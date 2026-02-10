#!/usr/bin/env python3
import os
import sys
import sqlite3
import subprocess
import time

INSTALL_DIR = "/opt/server-guard"
DB_PATH = os.path.join(INSTALL_DIR, "data/guard.db")
COMPOSE_FILE = os.path.join(INSTALL_DIR, "src/docker-compose.yml")

def clear_screen():
    os.system('clear')

def header():
    clear_screen()
    print("\033[1;36m=========================================")
    print("      ServerGuard Management Tool        ")
    print("=========================================\033[0m")

def check_status():
    print("\n\033[1;33m[+] Checking System Status...\033[0m")
    try:
        subprocess.run(["docker", "compose", "-f", COMPOSE_FILE, "ps"], check=True)
    except:
        print("Docker Error or Not Installed.")
    input("\nPress Enter to return...")

def view_history():
    header()
    if not os.path.exists(DB_PATH):
        print("Database not found. Is the service running?")
        input("Press Enter...")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, ip, user, status, timestamp FROM history ORDER BY id DESC LIMIT 50")
        rows = c.fetchall()
        conn.close()

        print(f"{'ID':<6} {'IP Address':<18} {'User':<10} {'Status':<12} {'Time'}")
        print("-" * 65)
        for r in rows:
            ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(r[4]))
            color = "\033[1;32m" if r[3] == "ALLOWED" else "\033[1;31m"
            print(f"{r[0]:<6} {r[1]:<18} {r[2]:<10} {color}{r[3]:<12}\033[0m {ts}")
        
    except Exception as e:
        print(f"Error reading DB: {e}")
    
    input("\nPress Enter to return...")

def service_control(action):
    print(f"\n\033[1;33m[+] {action}ing Service...\033[0m")
    cmd = "up -d --build" if action == "Start" else "down"
    os.system(f"docker compose -f {COMPOSE_FILE} {cmd}")
    input("\nPress Enter...")

def uninstall():
    print("\n\033[1;31m!!! WARNING !!!\033[0m")
    confirm = input("Are you sure you want to remove ServerGuard? (y/N): ")
    if confirm.lower() != 'y': return

    print("Stopping services...")
    os.system(f"docker compose -f {COMPOSE_FILE} down")
    
    print("Removing files...")
    os.system(f"rm -rf {INSTALL_DIR}")
    os.system("rm -f /usr/local/bin/sg-gatekeeper")
    os.system("rm -f /usr/local/bin/sg-logger")
    os.system("rm -f /usr/local/bin/ToolsServer")
    os.system("rm -f /etc/profile.d/z99-server-guard.sh")
    
    print("Cleaning bashrc...")
    # Safe cleanup of bashrc hook
    try:
        with open(os.path.expanduser("~/.bashrc"), "r") as f:
            lines = f.readlines()
        with open(os.path.expanduser("~/.bashrc"), "w") as f:
            skip = False
            for line in lines:
                if "# --- SERVERGUARD HOOK ---" in line:
                    skip = True
                if not skip:
                    f.write(line)
                if "# --- END SERVERGUARD ---" in line:
                    skip = False
    except:
        pass
        
    print("Uninstalled successfully.")
    sys.exit(0)

def main_menu():
    while True:
        header()
        print("1. 📊 System Status")
        print("2. 📜 View Login History")
        print("3. ▶️  Start/Restart Service")
        print("4. ⏹️  Stop Service")
        print("5. ❌ Uninstall")
        print("0. 🚪 Exit")
        
        choice = input("\nSelect option: ")
        
        if choice == '1': check_status()
        elif choice == '2': view_history()
        elif choice == '3': service_control("Start")
        elif choice == '4': service_control("Stop")
        elif choice == '5': uninstall()
        elif choice == '0': sys.exit()

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("This script must be run as root!")
        sys.exit(1)
    main_menu()
