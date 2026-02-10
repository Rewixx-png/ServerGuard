#!/usr/bin/env python3
import os
import sys
import shutil
import subprocess
import urllib.request
import re

INSTALL_DIR = "/opt/server-guard"

def run_cmd(cmd):
    subprocess.run(cmd, shell=True, check=True)

def get_public_ip():
    try:
        urls = ['https://api.ipify.org', 'https://ifconfig.me/ip', 'https://icanhazip.com']
        for url in urls:
            try:
                return urllib.request.urlopen(url, timeout=3).read().decode('utf8').strip()
            except:
                continue
        return "127.0.0.1"
    except:
        return "127.0.0.1"

def update_env_ip(ip):
    env_path = os.path.join(INSTALL_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r") as f:
        lines = f.readlines()
    with open(env_path, "w") as f:
        for line in lines:
            if line.startswith("PUBLIC_IP="):
                f.write(f"PUBLIC_IP={ip}\n")
            else:
                f.write(line)

def main():
    if os.geteuid() != 0:
        sys.exit("Root required.")

    print("\033[1;36m======================================")
    print("   ServerGuard 404 FIX INSTALLER      ")
    print("======================================\033[0m")
    
    current_ip = get_public_ip()
    print(f"\n🌍 Public IP: {current_ip}")
    
    os.makedirs(INSTALL_DIR, exist_ok=True)
    env_path = os.path.join(INSTALL_DIR, ".env")
    if os.path.exists(env_path):
        update_env_ip(current_ip)
    else:
        tg = input("Telegram Token: ").strip()
        aid = input("Admin ID: ").strip()
        with open(env_path, "w") as f:
            f.write(f"TG_TOKEN={tg}\nADMIN_ID={aid}\nPUBLIC_IP={current_ip}\n")

    cwd = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(cwd, "src")
    if os.path.exists(src_dir):
        print(f"[+] Updating source...")
        shutil.rmtree(f"{INSTALL_DIR}/src", ignore_errors=True)
        shutil.copytree(src_dir, f"{INSTALL_DIR}/src")
    
    print("[+] Rebuilding Bot Container...")
    if os.path.exists(f"{INSTALL_DIR}/src/docker-compose.yml"):
        try:
            run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml down")
            run_cmd(f"docker compose -f {INSTALL_DIR}/src/docker-compose.yml up -d --build")
        except Exception as e:
            print(f"Docker Error: {e}")

    print("\n✅ \033[1;32mFIX APPLIED\033[0m")
    print("WARNING: You must RE-ADD the remote server to push the URL fix.")

if __name__ == "__main__":
    main()
