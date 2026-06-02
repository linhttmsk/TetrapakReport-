import streamlit as st
from configparser import ConfigParser
import os, getpass

def _config():
    current_file = os.path.abspath(__file__)
    app_folder = os.path.dirname(os.path.dirname(current_file))
    inifile = os.path.join(app_folder, ".streamlit", "config.ini")
    parser = ConfigParser()
    parser.read(inifile)
    return {
        "version": parser.get("APP", "appversion", fallback="1.0.0"),
        "name":    parser.get("APP", "appname",    fallback="TetrapakReport"),
    }

def sidebar():
    """Call once per page right after set_page_config."""

    # Hide Streamlit's auto-generated page nav in sidebar
    st.markdown("""
    <style>
    [data-testid="stSidebarNav"] { display: none !important; }
    </style>""", unsafe_allow_html=True)

    cfg  = _config()
    user = getpass.getuser()
    
    with st.sidebar:
        with st.expander("Page Navigation",False):
            st.markdown(f"### 📦 {cfg['name']}")
            st.caption(f"v{cfg['version']} · {user}")
            st.divider()

            st.caption("FUNCTIONS")
            st.page_link("pages/1_Daily_Shipment.py",     label="Daily Shipment",      icon="🚢")
            st.page_link("pages/2_OPS_Loading.py",         label="OPS Loading",         icon="🚛")
            st.page_link("pages/3_Loading_Performance.py", label="Loading Performance", icon="📊")
            st.page_link("pages/4_Container_Inventory.py", label="Container Inventory", icon="🗄️")

            st.divider()
            st.caption("REPORTS")
            st.page_link("pages/5_Report.py", label="Report", icon="📈")

            st.divider()
            st.caption("SYSTEM")
            st.page_link("pages/6_Configuration.py", label="Configuration", icon="🔧")
            st.page_link("pages/0_Dev.py",           label="Dev",           icon="⚙️")

            st.divider()
            st.page_link("Home.py", label="🏠 Home")
