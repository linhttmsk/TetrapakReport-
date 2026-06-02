"""
TetrapakReport.py — Entry point
Launch Streamlit app, auto-open browser
Check version from GitHub Releases, auto download & install if new version
"""
import streamlit.web.cli as stcli
import os
import sys
import json
import requests
import subprocess
import tempfile
import threading
import webbrowser
import socket
import time
import psutil
from configparser import ConfigParser

# ── Config ──
GITHUB_OWNER = "linhttmsk"
GITHUB_REPO  = "TetrapakReport-"
GITHUB_API   = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
PORT         = 8502


def resolve_path(path):
    resolved_path = os.path.abspath(os.path.join(os.getcwd() + r"\\app", path))
    return resolved_path


def get_current_version() -> str:
    try:
        ini = resolve_path(".streamlit/config.ini")
        parser = ConfigParser()
        parser.read(ini)
        return parser.get("APP", "appversion", fallback="0.0.0")
    except:
        return "0.0.0"


def get_latest_version() -> tuple:
    try:
        resp = requests.get(GITHUB_API, timeout=5, headers={"Accept": "application/vnd.github+json"})
        if resp.status_code != 200:
            return "", ""
        data   = resp.json()
        tag    = data.get("tag_name", "").lstrip("v")
        assets = data.get("assets", [])
        for asset in assets:
            if asset.get("name", "").endswith(".exe"):
                return tag, asset.get("browser_download_url", "")
        return tag, ""
    except:
        return "", ""


def compare_version(v1: str, v2: str) -> int:
    try:
        t1 = tuple(int(x) for x in v1.split("."))
        t2 = tuple(int(x) for x in v2.split("."))
        if t1 > t2: return 1
        if t1 < t2: return -1
        return 0
    except:
        return 0


def download_and_install(dl_url: str, new_version: str):
    try:
        print(f"[Update] Downloading v{new_version}...")

        resp = requests.get(dl_url, timeout=60, stream=True, allow_redirects=True)
        print(f"[Update] Status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"[Update] Download failed: {resp.status_code}")
            return

        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".exe",
            prefix="TetrapakReport_Setup_"
        )
        for chunk in resp.iter_content(chunk_size=8192):
            tmp.write(chunk)
        tmp.close()

        print(f"[Update] Triggering installer for v{new_version}...")

        # Installer uses PrivilegesRequired=lowest (installs to %LOCALAPPDATA%),
        # so no admin/UAC is needed. Launch it detached, then exit immediately
        # so the file lock on TetrapakReport.exe is released before the
        # installer's CloseApplications+file-copy phase runs.
        subprocess.Popen(
            [tmp.name, "/SILENT", "/NORESTART"],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        print("[Update] Installer launched. Exiting so files can be replaced...")
        time.sleep(1)
        os._exit(0)

    except Exception as e:
        print(f"[Update] Error: {e}")


def check_and_update():
    current = get_current_version()
    print(f"[Version] Current: {current}")
    latest, dl_url = get_latest_version()
    if not latest:
        print("[Version] Cannot reach GitHub — skipping update check.")
        return
    print(f"[Version] Latest: {latest}")
    if compare_version(latest, current) > 0:
        # Dùng popup thay vì input()
        import ctypes
        result = ctypes.windll.user32.MessageBoxW(
            0,
            f"New version v{latest} available!\nCurrent: v{current}\n\nUpdate now?",
            "TetrapakReport Update",
            4  # MB_YESNO
        )
        # result = 6 là Yes, 7 là No
        if result == 6 and dl_url:
            download_and_install(dl_url, latest)
        else:
            print("[Version] Skipping update.")
    else:
        print("[Version] Already up to date.")


def kill_port(port: int):
    """Kill any process using the port."""
    try:
        for conn in psutil.net_connections():
            if conn.laddr.port == port and conn.pid:
                try:
                    psutil.Process(conn.pid).kill()
                    print(f"[Port] Killed process {conn.pid} on port {port}")
                except:
                    pass
    except:
        pass


def wait_for_server(port=PORT, timeout=120) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("localhost", port), timeout=2):
                time.sleep(1)
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False



if __name__ == "__main__":
    
    # 1. Kill old process on port
    print(f"[Start] Clearing port {PORT}...")
    kill_port(PORT)
    time.sleep(2)

    # 2. Check for updates
    check_and_update()


    # home_path = resolve_path("Home.py")
    # with open(os.path.join(os.path.dirname(sys.executable), "debug.log"), "w") as f:
    #     f.write(f"exe: {sys.executable}\n")
    #     f.write(f"home: {home_path}\n")
    #     f.write(f"exists: {os.path.exists(home_path)}\n")

    # 3. Launch Streamlit
    print("[Start] Launching Streamlit...")
    sys.argv = [
        "streamlit",
        "run",
        resolve_path("Home.py"),
        "--global.developmentMode=false",
        "--client.showSidebarNavigation=False",
        "--client.showErrorDetails=False",
        f"--server.port={PORT}",
        "--server.headless=false",
        "--logger.level=debug",
    ]
    sys.exit(stcli.main())