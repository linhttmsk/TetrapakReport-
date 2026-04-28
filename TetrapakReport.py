"""
TetrapakReport.py — Entry point
Launch Streamlit app, auto-open browser
"""
import streamlit.web.cli as stcli
import os
import sys


def resolve_path(path):
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "app", path)


if __name__ == "__main__":
    sys.argv = [
        "streamlit",
        "run",
        resolve_path("Home.py"),
        "--global.developmentMode=false",
        "--client.showSidebarNavigation=False",
        "--client.showErrorDetails=False",
        "--server.port=8501",
        "--server.headless=false",
    ]
    sys.exit(stcli.main())
