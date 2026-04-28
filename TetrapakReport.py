"""
TetrapakReport.py — Entry point
Launch Streamlit app, wait for server ready, then open browser
"""
import subprocess
import sys
import os
import time
import threading
import webbrowser
import socket


def resolve_path(path):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "app", path)


def wait_for_server(port=8501, timeout=30):
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
    """Wait for server then open browser."""
    if wait_for_server(8501):
        webbrowser.open("http://localhost:8501")


if __name__ == "__main__":
    # Start browser opener in background thread
    threading.Thread(target=open_browser, daemon=True).start()

    # Launch Streamlit
    home_path = resolve_path("Home.py")
    sys.argv = [
        "streamlit",
        "run",
        home_path,
        "--global.developmentMode=false",
        "--client.showSidebarNavigation=False",
        "--client.showErrorDetails=False",
        "--server.port=8501",
        "--server.headless=true",   # headless=true, browser opened manually above
    ]

    import streamlit.web.cli as stcli
    sys.exit(stcli.main())
