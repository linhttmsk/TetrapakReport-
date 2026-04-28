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
from configparser import ConfigParser

# ── Config ──
GITHUB_OWNER  = "linhttmsk"
GITHUB_REPO   = "TetrapakReport-"
GITHUB_API    = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
PORT          = 8502


def resolve_path(path):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "app", path)


def get_current_version() -> str:
    """Read version from config.ini"""
    try:
        ini = resolve_path(".streamlit/config.ini")
        parser = ConfigParser()
        parser.read(ini)
        return parser.get("APP", "appversion", fallback="0.0.0")
    except:
        return "0.0.0"


def get_latest_version() -> tuple:
    """
    Check GitHub Releases API for latest version.
    Returns (version_str, download_url) or ("", "") if unreachable.
    """
    try:
        resp = requests.get(GITHUB_API, timeout=5)
        if resp.status_code != 200:
            return "", ""
        data = resp.json()
        tag     = data.get("tag_name", "").lstrip("v")
        assets  = data.get("assets", [])
        # Find Windows installer
        dl_url  = ""
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith("_Setup.exe") or name.endswith(".exe"):
                dl_url = asset.get("browser_download_url", "")
                break
        return tag, dl_url
    except:
        return "", ""


def compare_version(v1: str, v2: str) -> int:
    """Returns 1 if v1 > v2, -1 if v1 < v2, 0 if equal."""
    try:
        t1 = tuple(int(x) for x in v1.split("."))
        t2 = tuple(int(x) for x in v2.split("."))
        if t1 > t2: return 1
        if t1 < t2: return -1
        return 0
    except:
        return 0


def download_and_install(dl_url: str, new_version: str):
    """Download installer and run silently."""
    try:
        print(f"[Update] Downloading v{new_version}...")
        resp = requests.get(dl_url, timeout=60, stream=True)
        if resp.status_code != 200:
            print(f"[Update] Download failed: {resp.status_code}")
            return

        # Save to temp file
        tmp = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".exe",
            prefix="TetrapakReport_Setup_"
        )
        for chunk in resp.iter_content(chunk_size=8192):
            tmp.write(chunk)
        tmp.close()

        print(f"[Update] Installing v{new_version}...")
        # Run installer silently — /SILENT = no UI, /NORESTART = no restart
        subprocess.Popen([tmp.name, "/SILENT", "/NORESTART"])
        print("[Update] Installer launched — app will close now.")
        sys.exit(0)

    except Exception as e:
        print(f"[Update] Error: {e}")


def check_and_update():
    """Check GitHub for new version and prompt user."""
    current = get_current_version()
    print(f"[Version] Current: {current}")

    latest, dl_url = get_latest_version()
    if not latest:
        print("[Version] Cannot reach GitHub — skipping update check.")
        return

    print(f"[Version] Latest: {latest}")

    if compare_version(latest, current) > 0:
        # Show simple console prompt
        print(f"\n{'='*50}")
        print(f"  New version v{latest} available! (current: v{current})")
        print(f"{'='*50}")
        try:
            ans = input("  Update now? (y/n): ").strip().lower()
        except:
            ans = "n"

        if ans == "y" and dl_url:
            download_and_install(dl_url, latest)
        else:
            print("[Version] Skipping update. Launching current version...")
    else:
        print("[Version] Already up to date.")


def wait_for_server(port=PORT, timeout=30) -> bool:
    """Wait until Streamlit server is ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("localhost", port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def open_browser():
    """Wait for server ready then open browser."""
    if wait_for_server(PORT):
        webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    # 1. Check for updates
    check_and_update()

    # 2. Open browser after server is ready
    threading.Thread(target=open_browser, daemon=True).start()

    # 3. Launch Streamlit
    sys.argv = [
        "streamlit",
        "run",
        resolve_path("Home.py"),
        "--global.developmentMode=false",
        "--client.showSidebarNavigation=False",
        "--client.showErrorDetails=False",
        f"--server.port={PORT}",
        "--server.headless=true",
    ]
    sys.exit(stcli.main())
