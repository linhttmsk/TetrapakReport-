"""
app/Home.py — TetrapakReport Home
"""
import streamlit as st
import getpass
from datetime import datetime
from configparser import ConfigParser
import os, sys

# ── Path ──
current_file = os.path.abspath(__file__)
folder_path0 = os.path.dirname(current_file)
sys.path.insert(0, os.path.join(folder_path0, "src"))

from nav import sidebar as _nav_sidebar  # type: ignore
inifile = os.path.join(folder_path0, ".streamlit", "config.ini")
parser = ConfigParser()
parser.read(inifile)
APP_VERSION = parser.get("APP", "appversion", fallback="1.0.0")
APP_NAME    = parser.get("APP", "appname",    fallback="TetrapakReport")

USERID   = getpass.getuser()
DATETIME = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

# ── Page config ──
st.set_page_config(
    page_title=APP_NAME,
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# _nav_sidebar()

# ═══════════════════════════════════════════════════════════════════════════
# MAIN — Header
# ═══════════════════════════════════════════════════════════════════════════

st.title(f"📦 {APP_NAME}")
st.caption(f"v{APP_VERSION}  |  User: **{USERID}**  |  {DATETIME}")

# st.divider()
st.success(f"Welcome **{USERID}** — Signed in at {DATETIME}", icon="✅")

from db import get_conn
with st.spinner("Connecting to database, if 'please sign in your account' pop up please sign in ..."):
    try:
        get_conn()
        st.toast("Database connected", icon="🟢")
    except Exception as e:
        st.error(f"Database connection failed: {e}")


# st.divider()

# ── Card style ──
st.markdown("""
<style>
.nav-card a {
    display: block;
    text-decoration: none;
    background: #1e2130;
    border: 1px solid #2e3250;
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 10px;
    transition: border-color 0.2s, background 0.2s;
}
.nav-card a:hover {
    background: #262c45;
    border-color: #4e5a8a;
}
.nav-card .card-title {
    font-size: 1.05rem;
    font-weight: 600;
    color: #e0e4f0;
    margin: 0 0 4px 0;
}
.nav-card .card-desc {
    font-size: 0.82rem;
    color: #7a849e;
    margin: 0;
}
</style>
""", unsafe_allow_html=True)


def card(icon: str, title: str, desc: str, url: str):
    st.markdown(f"""
    <div class="nav-card">
        <a href="{url}" target="_blank">
            <p class="card-title">{icon} {title} ↗</p>
            <p class="card-desc">{desc}</p>
        </a>
    </div>""", unsafe_allow_html=True)


# ── Cards ──
with st.expander("Navigate to:", True):
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 📋 Functions")
        card("🚢", "Daily Shipment",      "View, edit and import daily shipment records",  "/Daily_Shipment")
        card("🚛", "OPS Loading",         "Operational loading management",                "/OPS_Loading")
        card("📊", "Loading Performance", "Performance tracking and analytics",            "/Loading_Performance")
        card("🗄️", "Container Inventory", "Container stock and tracking",                  "/Container_Inventory")

    with col2:
        st.markdown("#### 📑 Reports")
        card("📈", "Report", "Generate and export reports", "/Report")

    with col3:
        st.markdown("#### ⚙️ System")
        card("🔧", "Configuration", "App settings and configuration", "/Configuration")
        card("⚙️", "Dev",           "Table admin and dev tools",      "/Dev")


