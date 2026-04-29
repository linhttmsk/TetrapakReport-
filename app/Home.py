"""
app/Home.py — TetrapakReport Home
"""
import streamlit as st
import getpass
from datetime import datetime
from configparser import ConfigParser
import os, sys

# ── Config ──
# Use __file__ to get correct path regardless of how Streamlit was launched
current_file = os.path.abspath(__file__)  # ...app/Home.py
folder_path0 = os.path.dirname(current_file)  # ...app/
inifile = os.path.join(folder_path0, ".streamlit", "config.ini")
parser = ConfigParser()
parser.read(inifile)
APP_VERSION = parser.get("APP", "appversion", fallback="1.0.0")
APP_NAME    = parser.get("APP", "appname", fallback="TetrapakReport")

USERID   = getpass.getuser()
DATETIME = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

# ── Page config ──
st.set_page_config(
    page_title=APP_NAME,
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ── Header ──
st.title(f"📦 {APP_NAME}")
st.caption(f"v{APP_VERSION}  |  User: **{USERID}**  |  {DATETIME}")
st.divider()

# ── Quick links ──
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 📋 Functions")
    st.page_link("pages/1_Daily_Shipment.py",      label="Daily Shipment",       icon="🚢")
    st.page_link("pages/2_OPS_Loading.py",          label="OPS Loading",          icon="🚛")
    st.page_link("pages/3_Loading_Performance.py",  label="Loading Performance",  icon="📊")
    st.page_link("pages/4_Container_Inventory.py",  label="Container Inventory",  icon="🗄️")

with col2:
    st.markdown("### 📑 Reports")
    st.page_link("pages/5_Report.py", label="Report", icon="📈")

with col3:
    st.markdown("### ⚙️ System")
    st.page_link("pages/6_Configuration.py", label="Configuration", icon="🔧")

st.divider()
st.success(f"Welcome **{USERID}** — Signed in at {DATETIME}", icon="✅")
